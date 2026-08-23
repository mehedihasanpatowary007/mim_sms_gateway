from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
import re
import ast
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class SmsComposer(models.TransientModel):
    _name = 'mimsms.composer'
    _description = 'SMS Composer'

    def _check_sms_user(self):
        if not self.env.user.has_group('mimsms_gateway.group_sms_gateway_user'):
            raise UserError(_('You do not have permission to send SMS messages.'))

    def _get_recipient_records(self):
        """Safely parse recipient IDs and enforce normal Odoo read access."""
        if not self.res_model or self.res_model not in self.env:
            raise UserError(_('The recipient model is invalid.'))
        try:
            record_ids = ast.literal_eval(self.res_ids or '[]')
        except (ValueError, SyntaxError):
            raise UserError(_('The recipient list is invalid.'))
        if isinstance(record_ids, int):
            record_ids = [record_ids]
        if not isinstance(record_ids, (list, tuple)) or any(
            not isinstance(record_id, int) or isinstance(record_id, bool)
            for record_id in record_ids
        ):
            raise UserError(_('The recipient list is invalid.'))
        records = self.env[self.res_model].browse(list(dict.fromkeys(record_ids))).exists()
        records.check_access('read')
        return records

    # Basic fields
    composition_mode1 = fields.Selection([
        ('single', 'Single SMS'),
        ('bulk', 'Bulk SMS'),
        ('template', 'Use Template')
    ], string='Composition Mode', default='single', required=True)
    is_chatter_single = fields.Boolean(
        string='Single Recipient Flow',
        default=False,
        readonly=True,
    )
    
    res_model = fields.Char(string='Document Model')
    res_ids = fields.Char(string='Document IDs')
    company_id = fields.Many2one('res.company', compute='_compute_company_id')
    
    # Message fields
    message = fields.Text(string='Message', required=True)
    template_id = fields.Many2one('mimsms.template', string='SMS Template', 
                                 domain="[('model', '=', res_model)]")
    
    # Recipients info
    recipient_count = fields.Integer(string='Recipients', compute='_compute_recipient_info')
    recipient_info = fields.Text(string='Recipient Details', compute='_compute_recipient_info')
    is_single_partner = fields.Boolean(compute='_compute_recipient_options')
    send_to_partner = fields.Boolean(string='Send to Partner', default=True)
    send_to_manager = fields.Boolean(string='Send to Manager', default=False)
    partner_recipient_name = fields.Char(
        string='Partner Name', compute='_compute_recipient_options'
    )
    partner_recipient_mobile = fields.Char(
        string='Partner Mobile', compute='_compute_recipient_options'
    )
    manager_recipient_name = fields.Char(
        string='Manager Name', compute='_compute_recipient_options'
    )
    manager_recipient_mobile = fields.Char(
        string='Manager Mobile', compute='_compute_recipient_options'
    )
    manager_recipient_available = fields.Boolean(
        compute='_compute_recipient_options'
    )
    
    # Preview
    preview_mobile = fields.Char(string='Preview Mobile', compute='_compute_preview')
    preview_message = fields.Text(string='Preview Message', compute='_compute_preview')

    # SMS length / segment calculation
    character_count = fields.Integer(string='Characters', compute='_compute_sms_metrics')
    sms_parts = fields.Integer(string='SMS Parts', compute='_compute_sms_metrics')
    sms_encoding = fields.Char(string='Encoding', compute='_compute_sms_metrics')
    
    # ADDED: Helper fields to control visibility
    show_template = fields.Boolean(compute='_compute_visibility')
    show_bulk_info = fields.Boolean(compute='_compute_visibility')
    show_single_info = fields.Boolean(compute='_compute_visibility')

    @api.depends('res_model', 'res_ids')
    def _compute_company_id(self):
        for wizard in self:
            company = self.env.company
            try:
                records = wizard._get_recipient_records()
                if records:
                    company = getattr(records[0], 'company_id', False) or self.env.company
            except UserError:
                pass
            wizard.company_id = company

    @api.depends('res_model', 'res_ids')
    def _compute_recipient_options(self):
        for wizard in self:
            partner = False
            if wizard.res_model == 'res.partner' and wizard.res_ids:
                try:
                    records = wizard._get_recipient_records()
                    partner = records if len(records) == 1 else False
                except UserError:
                    partner = False

            wizard.is_single_partner = bool(partner)
            wizard.partner_recipient_name = partner.display_name if partner else ''
            wizard.partner_recipient_mobile = (
                (partner.mobile or partner.phone or '') if partner else ''
            )
            wizard.manager_recipient_name = (
                partner.sms_manager_name or '' if partner else ''
            )
            wizard.manager_recipient_mobile = (
                partner.sms_manager_mobile or '' if partner else ''
            )
            wizard.manager_recipient_available = bool(
                partner
                and partner.sms_manager_name
                and wizard._normalize_phone_number(partner.sms_manager_mobile)
            )
    
    @api.model
    def _sms_metrics(self, text):
        """Return (visible chars, SMS parts, encoding).

        GSM-7 extension characters consume two septets. Any non-GSM
        character (including Bangla) uses Unicode SMS limits.
        """
        text = self.env['mimsms.template']._coerce_body_text(text or '')
        char_count = len(text)
        if not text:
            return 0, 0, 'GSM-7'

        gsm_basic = set(
            "@\u00a3$\u00a5\u00e8\u00e9\u00f9\u00ec\u00f2\u00c7\n"
            "\u00d8\u00f8\r\u00c5\u00e5\u0394_\u03a6\u0393\u039b\u03a9"
            "\u03a0\u03a8\u03a3\u0398\u039e !\"#\u00a4%&'()*+,-./"
            "0123456789:;<=>?\u00a1ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "\u00c4\u00d6\u00d1\u00dc\u00a7\u00bfabcdefghijklmnopqrstuvwxyz"
            "\u00e4\u00f6\u00f1\u00fc\u00e0"
        )
        gsm_ext = set('^{}\\[~]|\u20ac')

        if all(ch in gsm_basic or ch in gsm_ext for ch in text):
            units = sum(2 if ch in gsm_ext else 1 for ch in text)
            parts = 1 if units <= 160 else (units + 152) // 153
            return char_count, parts, 'GSM-7'

        # UCS-2/UTF-16 units are the practical limit for Unicode SMS.
        units = len(text.encode('utf-16-be')) // 2
        parts = 1 if units <= 70 else (units + 66) // 67
        return char_count, parts, 'Unicode'

    @api.depends('message', 'preview_message', 'composition_mode1', 'template_id')
    def _compute_sms_metrics(self):
        for wizard in self:
            text = wizard.preview_message if wizard.composition_mode1 == 'template' and wizard.preview_message else wizard.message
            count, parts, encoding = wizard._sms_metrics(text)
            wizard.character_count = count
            wizard.sms_parts = parts
            wizard.sms_encoding = encoding

    @api.depends('composition_mode1')
    def _compute_visibility(self):
        """Control which UI elements to show based on composition mode"""
        for wizard in self:
            wizard.show_template = wizard.composition_mode1 == 'template'
            wizard.show_bulk_info = wizard.composition_mode1 == 'bulk'
            wizard.show_single_info = wizard.composition_mode1 == 'single'
    
    @api.model
    def default_get(self, fields_list):
        """Override to handle context values"""
        defaults = super(SmsComposer, self).default_get(fields_list)
        
        # Get active model and IDs from context
        ctx = self.env.context
        
        _logger.info(f"=== SMS Composer default_get ===")
        _logger.info(f"Context keys: {list(ctx.keys())}")
        
        # Set res_model from context
        if 'default_res_model' in ctx:
            defaults['res_model'] = ctx['default_res_model']
        elif 'active_model' in ctx:
            defaults['res_model'] = ctx['active_model']
        
        # Set res_ids from context - must be string format
        if 'default_res_ids' in ctx:
            res_ids = ctx['default_res_ids']
            if isinstance(res_ids, list):
                defaults['res_ids'] = str(res_ids)
            elif isinstance(res_ids, str):
                defaults['res_ids'] = res_ids
            else:
                defaults['res_ids'] = str([res_ids])
        elif 'active_ids' in ctx:
            defaults['res_ids'] = str(ctx['active_ids'])
        elif 'active_id' in ctx:
            defaults['res_ids'] = str([ctx['active_id']])
        
        # Handle composition_mode - map invalid values to valid ones
        composition_mode = None
        if 'default_composition_mode' in ctx:
            composition_mode = ctx['default_composition_mode']
        elif 'default_composition_mode1' in ctx:
            composition_mode = ctx['default_composition_mode1']
        elif 'composition_mode1' in defaults:
            composition_mode = defaults['composition_mode1']
        
        # Map various composition modes to valid values
        mode_mapping = {
            'comment': 'single',
            'mass': 'bulk',
            'mass_mail': 'bulk',
            'numbers': 'bulk',
        }
        
        if composition_mode:
            if composition_mode in mode_mapping:
                defaults['composition_mode1'] = mode_mapping[composition_mode]
                _logger.info(f"Mapped composition_mode '{composition_mode}' to '{defaults['composition_mode1']}'")
            elif composition_mode in ['single', 'bulk', 'template']:
                defaults['composition_mode1'] = composition_mode
            else:
                _logger.warning(f"Unknown composition_mode '{composition_mode}', using 'single'")
                defaults['composition_mode1'] = 'single'
        
        # Multiple selected records always use bulk mode, regardless of the
        # field-level default returned by super().
        if 'active_ids' in ctx and len(ctx.get('active_ids', [])) > 1:
            defaults['composition_mode1'] = 'bulk'
        
        # Ensure composition_mode1 is always set
        if 'composition_mode1' not in defaults:
            defaults['composition_mode1'] = 'single'
        
        _logger.info(f"Final defaults - res_model: {defaults.get('res_model')}, res_ids: {defaults.get('res_ids')}, composition_mode1: {defaults.get('composition_mode1')}")
        
        return defaults
    
    def _normalize_phone_number(self, phone):
        """Return a validated Bangladesh mobile number in 8801XXXXXXXXX form."""
        return self.env['res.partner']._normalize_sms_mobile(phone)

    def _validate_outbound_message(self, message, company):
        message = self.env['mimsms.template']._coerce_body_text(message).strip()
        if not message:
            raise UserError(_('The SMS message cannot be empty.'))
        if re.search(r'\{\{|\}\}|\$\{', message):
            raise UserError(_(
                'The message contains an unresolved or malformed template placeholder.'
            ))
        config = self.env['mimsms.config'].get_active_config(company=company)
        _count, parts, _encoding = self._sms_metrics(message)
        if parts > config.max_sms_parts:
            raise UserError(_(
                'This message uses %d SMS parts. The configured maximum for %s is %d.'
            ) % (parts, company.display_name, config.max_sms_parts))
        return message
    
    def _get_mobile_number(self, record):
        """Get mobile number from record, trying different field names"""
        # Try common field names for mobile/phone
        for field_name in ['mobile', 'phone', 'mobile_phone', 'cell_phone']:
            if hasattr(record, field_name):
                try:
                    value = getattr(record, field_name, False)
                    if value:
                        # Normalize the phone number
                        normalized = self._normalize_phone_number(value)
                        _logger.info(f"Original: {value} -> Normalized: {normalized}")
                        return normalized
                except Exception:
                    continue
        if hasattr(record, 'partner_id') and record.partner_id:
            partner = record.partner_id.commercial_partner_id
            mobile = (
                partner['mobile']
                if 'mobile' in partner._fields else False
            )
            phone = (
                partner['phone']
                if 'phone' in partner._fields else False
            )
            return self._normalize_phone_number(mobile or phone)
        return False

    def _get_history_links(self, record):
        partner = record if record._name == 'res.partner' else getattr(record, 'partner_id', False)
        return {
            'partner_id': partner.commercial_partner_id.id if partner else False,
            'res_model': record._name,
            'res_id': record.id,
            'event_type': 'manual',
            'company_id': (
                getattr(record, 'company_id', False).id
                if getattr(record, 'company_id', False)
                else self.env.company.id
            ),
        }
    
    @api.depends('res_model', 'res_ids', 'send_to_partner', 'send_to_manager')
    def _compute_recipient_info(self):
        for wizard in self:
            if wizard.res_model and wizard.res_ids:
                try:
                    records = wizard._get_recipient_records()
                    if wizard.res_model == 'res.partner' and len(records) == 1:
                        partner = records
                        recipients = []
                        if wizard.send_to_partner:
                            recipients.append(
                                f"{partner.display_name}: "
                                f"{partner.mobile or partner.phone or ''}"
                            )
                        if wizard.send_to_manager:
                            recipients.append(
                                f"{partner.sms_manager_name or _('Manager')}: "
                                f"{partner.sms_manager_mobile or ''}"
                            )
                        wizard.recipient_count = len(recipients)
                        wizard.recipient_info = '\n'.join(recipients)
                        continue

                    wizard.recipient_count = len(records)
                    mobiles = []
                    for rec in records:
                        mobile = wizard._get_mobile_number(rec)
                        
                        if mobile:
                            name = rec.name if hasattr(rec, 'name') else str(rec.id)
                            mobiles.append(f"{name}: {mobile}")
                    
                    wizard.recipient_info = '\n'.join(mobiles) if mobiles else 'No mobile numbers found'
                except Exception as e:
                    _logger.error(f"Error computing recipient info: {str(e)}")
                    wizard.recipient_count = 0
                    wizard.recipient_info = f'Error: {str(e)}'
            else:
                wizard.recipient_count = 0
                wizard.recipient_info = ''
    
    @api.depends(
        'message', 'template_id', 'res_model', 'res_ids', 'composition_mode1',
        'send_to_partner', 'send_to_manager',
    )
    def _compute_preview(self):
        for wizard in self:
            if wizard.res_model and wizard.res_ids:
                try:
                    records = wizard._get_recipient_records()
                    first_record = records[0] if records else False
                    
                    if first_record:
                        if wizard.res_model == 'res.partner' and len(records) == 1:
                            preview_mobiles = []
                            if wizard.send_to_partner:
                                partner_mobile = wizard._get_mobile_number(first_record)
                                if partner_mobile:
                                    preview_mobiles.append(partner_mobile)
                            if wizard.send_to_manager:
                                manager_mobile = wizard._normalize_phone_number(
                                    first_record.sms_manager_mobile
                                )
                                if manager_mobile:
                                    preview_mobiles.append(manager_mobile)
                            wizard.preview_mobile = ', '.join(preview_mobiles)
                        else:
                            mobile = wizard._get_mobile_number(first_record)
                            wizard.preview_mobile = mobile or ''
                        
                        if wizard.template_id and wizard.composition_mode1 == 'template':
                            wizard.preview_message = wizard.template_id._render_template(
                                wizard.template_id.body, first_record
                            )
                        else:
                            wizard.preview_message = wizard.message or ''
                    else:
                        wizard.preview_mobile = ''
                        wizard.preview_message = ''
                except Exception as e:
                    _logger.error(f"Error computing preview: {str(e)}")
                    wizard.preview_mobile = ''
                    wizard.preview_message = ''
            else:
                wizard.preview_mobile = ''
                wizard.preview_message = ''
    
    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.message = self.template_id._coerce_body_text(self.template_id.body)
            self.composition_mode1 = 'template'
        elif self.is_chatter_single:
            self.composition_mode1 = 'single'
    
    @api.onchange('composition_mode1')
    def _onchange_composition_mode(self):
        """Handle composition mode changes"""
        if self.is_chatter_single:
            # Chatter always has one recipient, but a template may still be
            # selected to personalize that recipient's message.
            self.composition_mode1 = (
                'template' if self.template_id else 'single'
            )
            return

        # Map invalid modes
        mode_mapping = {
            'comment': 'single',
            'mass': 'bulk',
            'mass_mail': 'bulk',
        }
        
        self.composition_mode1 = mode_mapping.get(
            self.composition_mode1, self.composition_mode1
        )
        
        # Clear template if not in template mode
        if self.composition_mode1 != 'template':
            self.template_id = False

    def _get_single_partner_targets(self, partner):
        """Validate and return the explicitly selected contact destinations."""
        self.ensure_one()
        if not self.send_to_partner and not self.send_to_manager:
            raise UserError(_('Select Partner, Manager, or both as SMS recipients.'))

        targets = []
        if self.send_to_partner:
            partner_mobile = self._get_mobile_number(partner)
            if not partner_mobile:
                raise UserError(_(
                    'The selected partner has no valid Bangladesh mobile number.'
                ))
            targets.append({
                'recipient_type': 'partner',
                'recipient_name': partner.display_name,
                'mobile': partner_mobile,
            })

        if self.send_to_manager:
            manager_name = (partner.sms_manager_name or '').strip()
            manager_mobile = self._normalize_phone_number(
                partner.sms_manager_mobile
            )
            if not manager_name or not manager_mobile:
                raise UserError(_(
                    'Configure a valid Manager Name and Manager Mobile on the '
                    'partner profile before selecting Manager.'
                ))
            if targets and manager_mobile == targets[0]['mobile']:
                raise UserError(_(
                    'Partner and Manager mobile numbers must be different.'
                ))
            targets.append({
                'recipient_type': 'manager',
                'recipient_name': manager_name,
                'mobile': manager_mobile,
            })
        return targets
    
    def _log_sms_success(self, mode, recipient_count, mobiles, message_preview, response):
        """Log SMS success with highlighted format"""
        _logger.info("\n" + "=" * 100)
        _logger.info("SMS SENT SUCCESSFULLY")
        _logger.info("=" * 100)
        _logger.info(f"Mode: {mode.upper()}")
        _logger.info(f"Total Recipients: {recipient_count}")
        _logger.info(f"Mobile Numbers: {', '.join(mobiles)}")
        _logger.info(f"Message Preview: {message_preview[:150]}..." if len(message_preview) > 150 else f"Message: {message_preview}")
        _logger.info(f"Status Code: {response.get('statusCode')}")
        _logger.info(f"Status Message: {response.get('statusMessage')}")
        _logger.info(f"Response: {response}")
        _logger.info("=" * 100 + "\n")
    
    def _log_sms_failure(self, mode, recipient_count, mobiles, message_preview, response):
        """Log SMS failure with highlighted format"""
        _logger.error("\n" + "=" * 100)
        _logger.error("SMS SENDING FAILED")
        _logger.error("=" * 100)
        _logger.error(f"Mode: {mode.upper()}")
        _logger.error(f"Total Recipients: {recipient_count}")
        _logger.error(f"Mobile Numbers: {', '.join(mobiles)}")
        _logger.error(f"Message Preview: {message_preview[:150]}..." if len(message_preview) > 150 else f"Message: {message_preview}")
        _logger.error(f"Status Code: {response.get('statusCode')}")
        _logger.error(f"Status Message: {response.get('statusMessage')}")
        _logger.error(f"Error Response: {response}")
        _logger.error("=" * 100 + "\n")
    
    def _post_chatter_message(self, record, success, mobile, message_preview, response):
        """Post SMS log message in record's chatter"""
        if not hasattr(record, 'message_post'):
            return
        
        try:
            # Escape message content to prevent HTML injection
            mobile_safe = Markup.escape(mobile)
            message_safe = Markup.escape(message_preview)
            
            if success:
                body = Markup("""
                <div style="background: #ffffff; border: 1px solid #d9e2dc; border-left: 4px solid #28a745; border-radius: 8px; overflow: hidden; margin: 8px 0;">
                    <table role="presentation" style="width: 100%%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 11px 12px; border-bottom: 1px solid #edf1ee;">
                                <span title="Sent" style="display: inline-block; color: #176b2c; font-size: 20px; line-height: 1; font-weight: 800; margin-right: 7px; vertical-align: middle;">&#10003;</span>
                                <strong style="color: #26382d;">SMS</strong>
                            </td>
                            <td style="padding: 11px 12px; border-bottom: 1px solid #edf1ee; text-align: right;">
                                <span style="display: inline-block; padding: 3px 9px; color: #176b2c; background: #e4f4e8; border-radius: 12px; font-size: 11px; font-weight: 700; letter-spacing: .4px;">SENT</span>
                            </td>
                        </tr>
                        <tr>
                            <td colspan="2" style="padding: 10px 12px 12px;">
                                <table role="presentation" style="width: 100%%; border-collapse: collapse;">
                                    <tr>
                                        <td style="width: 64px; padding: 3px 8px 3px 0; color: #6b746e; vertical-align: top;">Mobile</td>
                                        <td style="padding: 3px 0; color: #26382d; vertical-align: top;">%s</td>
                                    </tr>
                                    <tr>
                                        <td style="width: 64px; padding: 3px 8px 3px 0; color: #6b746e; vertical-align: top;">Message</td>
                                        <td style="padding: 3px 0; color: #26382d; vertical-align: top; white-space: pre-wrap; overflow-wrap: anywhere;">%s</td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                    </table>
                </div>
                """) % (mobile_safe, message_safe)
                
                record.sudo().with_context(mail_create_nosubscribe=True).message_post(
                    body=body,
                    subject=False,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
            else:
                error_safe = Markup.escape(
                    response.get('statusMessage')
                    or response.get('message')
                    or _('Unknown error')
                )
                body = Markup("""
                <div style="background: #ffffff; border: 1px solid #ead9db; border-left: 4px solid #dc3545; border-radius: 8px; overflow: hidden; margin: 8px 0;">
                    <table role="presentation" style="width: 100%%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 11px 12px; border-bottom: 1px solid #f3e9ea;">
                                <span title="Failed" style="display: inline-block; color: #a61e2c; font-size: 20px; line-height: 1; font-weight: 800; margin-right: 7px; vertical-align: middle;">!</span>
                                <strong style="color: #49292c;">SMS</strong>
                            </td>
                            <td style="padding: 11px 12px; border-bottom: 1px solid #f3e9ea; text-align: right;">
                                <span style="display: inline-block; padding: 3px 9px; color: #8c2430; background: #fae7e9; border-radius: 12px; font-size: 11px; font-weight: 700; letter-spacing: .4px;">FAILED</span>
                            </td>
                        </tr>
                        <tr>
                            <td colspan="2" style="padding: 10px 12px 12px;">
                                <table role="presentation" style="width: 100%%; border-collapse: collapse;">
                                    <tr><td style="width: 64px; padding: 3px 8px 3px 0; color: #78696b; vertical-align: top;">Mobile</td><td style="padding: 3px 0; color: #49292c; vertical-align: top;">%s</td></tr>
                                    <tr><td style="width: 64px; padding: 3px 8px 3px 0; color: #78696b; vertical-align: top;">Message</td><td style="padding: 3px 0; color: #49292c; vertical-align: top; white-space: pre-wrap; overflow-wrap: anywhere;">%s</td></tr>
                                    <tr><td style="width: 64px; padding: 3px 8px 3px 0; color: #78696b; vertical-align: top;">Error</td><td style="padding: 3px 0; color: #8c2430; vertical-align: top;">%s</td></tr>
                                </table>
                            </td>
                        </tr>
                    </table>
                </div>
                """) % (mobile_safe, message_safe, error_safe)
                
                record.sudo().with_context(mail_create_nosubscribe=True).message_post(
                    body=body,
                    subject=False,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
        except Exception as e:
            _logger.exception(
                'Failed to post the styled SMS status to %s,%s',
                record._name,
                record.id,
            )
            # A chatter audit entry is more important than the styled card.
            # Retry with minimal HTML in case the original content is rejected
            # by a sanitizer or a model-specific mail override.
            try:
                fallback_status = _('Sent') if success else _('Failed')
                fallback_body = Markup(
                    '<p><strong>SMS:</strong> %s</p>'
                    '<p><strong>Mobile:</strong> %s</p>'
                    '<p><strong>Message:</strong> %s</p>'
                ) % (
                    Markup.escape(fallback_status),
                    mobile_safe,
                    message_safe,
                )
                record.sudo().with_context(
                    mail_create_nosubscribe=True
                ).message_post(
                    body=fallback_body,
                    subject=False,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
            except Exception:
                _logger.exception(
                    'Could not create the fallback SMS chatter entry for %s,%s',
                    record._name,
                    record.id,
                )
    
    def action_send_sms(self):
        """Send a single SMS immediately; queue bulk/personalized sends."""
        self.ensure_one()
        self._check_sms_user()

        if not self.res_model:
            raise UserError(_('Document Model is required'))
        if not self.res_ids:
            raise UserError(_('No recipients selected'))

        try:
            records = self._get_recipient_records()
        except Exception as error:
            _logger.error('Failed to parse SMS recipient records: %s', error)
            raise UserError(_('Failed to parse recipient records: %s') % str(error))

        if self.composition_mode1 == 'single' and len(records) != 1:
            raise UserError(_(
                'Single SMS mode requires exactly one source record.'
            ))

        single_partner = self.res_model == 'res.partner' and len(records) == 1

        sms_data = []
        skipped_count = 0
        for record in records:
            if self.composition_mode1 == 'template' and self.template_id:
                record_company = getattr(record, 'company_id', False) or self.env.company
                if self.template_id.company_id != record_company:
                    raise UserError(_(
                        'Template %s belongs to %s, but recipient %s belongs to %s.'
                    ) % (
                        self.template_id.display_name,
                        self.template_id.company_id.display_name,
                        record.display_name,
                        record_company.display_name,
                    ))
                self.template_id._validate_placeholders()
                message = self.template_id._render_template(self.template_id.body, record)
            else:
                message = self.env['mimsms.template']._coerce_body_text(self.message)

            if single_partner:
                targets = self._get_single_partner_targets(record)
            else:
                mobile = self._get_mobile_number(record)
                targets = [{
                    'recipient_type': 'partner',
                    'recipient_name': record.display_name,
                    'mobile': mobile,
                }] if mobile else []

            if not targets:
                links = self._get_history_links(record)
                self.env['sms.history'].create_history(
                    mobile='N/A',
                    message=message,
                    template_id=self.template_id.id if self.template_id else False,
                    status='skipped',
                    error_message=_('Customer has no valid Bangladesh mobile number.'),
                    **links,
                )
                skipped_count += 1
                continue

            validated_message = self._validate_outbound_message(
                message,
                getattr(record, 'company_id', False) or self.env.company,
            )
            for target in targets:
                sms_data.append({
                    'record': record,
                    'mobile': target['mobile'],
                    'message': validated_message,
                    'recipient_type': target['recipient_type'],
                    'recipient_name': target['recipient_name'],
                })

        if not sms_data:
            raise UserError(_('No valid mobile numbers found in selected records'))

        send_mode = (
            'dynamic' if single_partner
            else ('bulk' if self.composition_mode1 == 'bulk' else 'dynamic')
        )
        Queue = self.env['sms.queue']
        for data in sms_data:
            Queue.enqueue(
                mobile=data['mobile'],
                message=data['message'],
                record=data['record'],
                send_mode=send_mode,
                template=self.template_id,
                recipient_type=data['recipient_type'],
                recipient_name=data['recipient_name'],
            )

        notification = _('%d SMS added to the queue') % len(sms_data)
        if skipped_count:
            notification += _(', %d skipped because no valid mobile number was found') % skipped_count
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('SMS Queued'),
                'message': notification,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
