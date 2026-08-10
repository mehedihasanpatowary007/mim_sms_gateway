from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html_sanitize
import logging
import re

_logger = logging.getLogger(__name__)


class SmsComposer(models.TransientModel):
    _name = 'sms.composer'
    _description = 'SMS Composer'

    # Basic fields
    composition_mode1 = fields.Selection([
        ('single', 'Single SMS'),
        ('bulk', 'Bulk SMS'),
        ('template', 'Use Template')
    ], string='Composition Mode', default='single', required=True)
    
    res_model = fields.Char(string='Document Model')
    res_ids = fields.Char(string='Document IDs')
    
    # Message fields
    message = fields.Text(string='Message', required=True)
    template_id = fields.Many2one('sms.template', string='SMS Template', 
                                 domain="[('model', '=', res_model)]")
    
    # Recipients info
    recipient_count = fields.Integer(string='Recipients', compute='_compute_recipient_info')
    recipient_info = fields.Text(string='Recipient Details', compute='_compute_recipient_info')
    
    # Preview
    preview_mobile = fields.Char(string='Preview Mobile', compute='_compute_preview')
    preview_message = fields.Text(string='Preview Message', compute='_compute_preview')
    
    # ADDED: Helper fields to control visibility
    show_template = fields.Boolean(compute='_compute_visibility')
    show_bulk_info = fields.Boolean(compute='_compute_visibility')
    show_single_info = fields.Boolean(compute='_compute_visibility')
    
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
        
        # If multiple records selected, default to 'bulk' mode
        if 'active_ids' in ctx and len(ctx.get('active_ids', [])) > 1:
            if 'composition_mode1' not in defaults:
                defaults['composition_mode1'] = 'bulk'
        
        # Ensure composition_mode1 is always set
        if 'composition_mode1' not in defaults:
            defaults['composition_mode1'] = 'single'
        
        _logger.info(f"Final defaults - res_model: {defaults.get('res_model')}, res_ids: {defaults.get('res_ids')}, composition_mode1: {defaults.get('composition_mode1')}")
        
        return defaults
    
    def _normalize_phone_number(self, phone):
        """
        Normalize phone number to standard format without + prefix
        Handles formats like:
        - +8801911324774 -> 8801911324774
        - 8801911324774 -> 8801911324774
        - 01911324774 -> 8801911324774 (adds country code if missing)
        """
        if not phone:
            return False
        
        # Remove all non-digit characters except +
        phone = str(phone).strip()
        
        # Remove spaces, dashes, parentheses
        phone = re.sub(r'[\s\-\(\)]', '', phone)
        
        # If starts with +, remove it
        if phone.startswith('+'):
            phone = phone[1:]
        
        # If number starts with 0 and is 11 digits (Bangladesh local format)
        # Add country code 880
        if phone.startswith('0') and len(phone) == 11:
            phone = '880' + phone[1:]
            _logger.info(f"Normalized local number to: {phone}")
        
        # If number doesn't start with 880 and is 10 digits, add 880
        elif not phone.startswith('880') and len(phone) == 10:
            phone = '880' + phone
            _logger.info(f"Added country code: {phone}")
        
        return phone if phone else False
    
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
                except:
                    continue
        return False
    
    @api.depends('res_model', 'res_ids')
    def _compute_recipient_info(self):
        for wizard in self:
            if wizard.res_model and wizard.res_ids:
                try:
                    record_ids = eval(wizard.res_ids)
                    records = self.env[wizard.res_model].browse(record_ids)
                    wizard.recipient_count = len(records)
                    
                    # Get mobile numbers
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
    
    @api.depends('message', 'template_id', 'res_model', 'res_ids', 'composition_mode1')
    def _compute_preview(self):
        for wizard in self:
            if wizard.res_model and wizard.res_ids:
                try:
                    record_ids = eval(wizard.res_ids)
                    records = self.env[wizard.res_model].browse(record_ids)
                    first_record = records[0] if records else False
                    
                    if first_record:
                        # Get mobile number (normalized)
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
            self.message = self.template_id.body
            self.composition_mode1 = 'template'
    
    @api.onchange('composition_mode1')
    def _onchange_composition_mode(self):
        """Handle composition mode changes"""
        # Map invalid modes
        mode_mapping = {
            'comment': 'single',
            'mass': 'bulk',
            'mass_mail': 'bulk',
        }
        
        if self.composition_mode1 in mode_mapping:
            self.composition_mode1 = mode_mapping[self.composition_mode1]
        
        # Clear template if not in template mode
        if self.composition_mode1 != 'template':
            self.template_id = False
    
    def _log_sms_success(self, mode, recipient_count, mobiles, message_preview, response):
        """Log SMS success with highlighted format"""
        _logger.info("\n" + "=" * 100)
        _logger.info("🎉 SMS SENT SUCCESSFULLY! 🎉")
        _logger.info("=" * 100)
        _logger.info(f"📋 Mode: {mode.upper()}")
        _logger.info(f"👥 Total Recipients: {recipient_count}")
        _logger.info(f"📱 Mobile Numbers: {', '.join(mobiles)}")
        _logger.info(f"💬 Message Preview: {message_preview[:150]}..." if len(message_preview) > 150 else f"💬 Message: {message_preview}")
        _logger.info(f"✅ Status Code: {response.get('statusCode')}")
        _logger.info(f"📝 Status Message: {response.get('statusMessage')}")
        _logger.info(f"📊 Response: {response}")
        _logger.info("=" * 100 + "\n")
    
    def _log_sms_failure(self, mode, recipient_count, mobiles, message_preview, response):
        """Log SMS failure with highlighted format"""
        _logger.error("\n" + "=" * 100)
        _logger.error("❌ SMS SENDING FAILED! ❌")
        _logger.error("=" * 100)
        _logger.error(f"📋 Mode: {mode.upper()}")
        _logger.error(f"👥 Total Recipients: {recipient_count}")
        _logger.error(f"📱 Mobile Numbers: {', '.join(mobiles)}")
        _logger.error(f"💬 Message Preview: {message_preview[:150]}..." if len(message_preview) > 150 else f"💬 Message: {message_preview}")
        _logger.error(f"⛔ Status Code: {response.get('statusCode')}")
        _logger.error(f"📝 Status Message: {response.get('statusMessage')}")
        _logger.error(f"📊 Error Response: {response}")
        _logger.error("=" * 100 + "\n")
    
    def _post_chatter_message(self, record, success, mobile, message_preview, response):
        """Post SMS log message in record's chatter"""
        if not hasattr(record, 'message_post'):
            return
        
        try:
            # Escape message content to prevent HTML injection
            from markupsafe import Markup
            mobile_safe = Markup.escape(mobile)
            message_safe = Markup.escape(message_preview[:100] + ('...' if len(message_preview) > 100 else ''))
            
            if success:
                status_safe = Markup.escape(response.get('statusMessage', 'Success'))
                body = Markup("""
                <div style="padding: 10px; background-color: #d4edda; border-left: 4px solid #28a745; margin: 10px 0;">
                    <h4 style="color: #155724; margin: 0 0 10px 0;">🎉 SMS Sent Successfully</h4>
                    <p style="margin: 5px 0;"><strong>📱 Mobile:</strong> %s</p>
                    <p style="margin: 5px 0;"><strong>💬 Message:</strong> %s</p>
                    <p style="margin: 5px 0;"><strong>✅ Status:</strong> %s</p>
                </div>
                """) % (mobile_safe, message_safe, status_safe)
                
                record.message_post(
                    body=body,
                    subject='SMS Sent Successfully',
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
            else:
                error_safe = Markup.escape(response.get('statusMessage', 'Unknown error'))
                body = Markup("""
                <div style="padding: 10px; background-color: #f8d7da; border-left: 4px solid #dc3545; margin: 10px 0;">
                    <h4 style="color: #721c24; margin: 0 0 10px 0;">❌ SMS Sending Failed</h4>
                    <p style="margin: 5px 0;"><strong>📱 Mobile:</strong> %s</p>
                    <p style="margin: 5px 0;"><strong>💬 Message:</strong> %s</p>
                    <p style="margin: 5px 0;"><strong>⛔ Error:</strong> %s</p>
                </div>
                """) % (mobile_safe, message_safe, error_safe)
                
                record.message_post(
                    body=body,
                    subject='SMS Sending Failed',
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
        except Exception as e:
            _logger.error(f"Failed to post chatter message: {str(e)}")
    
    def action_send_sms(self):
        """Send SMS to recipients"""
        self.ensure_one()
        
        _logger.info("=== Starting SMS Send Process ===")
        _logger.info(f"res_model: {self.res_model}")
        _logger.info(f"res_ids: {self.res_ids}")
        _logger.info(f"composition_mode: {self.composition_mode1}")
        
        # Validate required fields
        if not self.res_model:
            raise UserError(_('Document Model is required'))
        
        if not self.res_ids:
            raise UserError(_('No recipients selected'))
        
        # Get configuration
        try:
            config = self.env['mimsms.config'].get_active_config()
            _logger.info(f"SMS Config found: {config.username}")
        except Exception as e:
            _logger.error(f"Failed to get SMS configuration: {str(e)}")
            raise UserError(_(
                'SMS configuration not found.\n\n'
                'Please go to: SMS → Configuration → SMS Configuration\n'
                'and create an active SMS configuration with your MiMSMS credentials.'
            ))
        
        # Get records
        try:
            record_ids = eval(self.res_ids)
            _logger.info(f"Parsed record IDs: {record_ids}")
            records = self.env[self.res_model].browse(record_ids)
            _logger.info(f"Found {len(records)} records")
        except Exception as e:
            _logger.error(f"Failed to parse records: {str(e)}")
            raise UserError(_('Failed to parse recipient records: %s') % str(e))
        
        # Prepare SMS data
        sms_data = []
        for record in records:
            mobile = self._get_mobile_number(record)
            _logger.info(f"Record {record.id} - mobile: {mobile}")
            
            if not mobile:
                _logger.warning(f"Record {record.id} has no mobile number")
                continue
            
            # Get message for this record
            if self.composition_mode1 == 'template' and self.template_id:
                message = self.template_id._render_template(self.template_id.body, record)
            else:
                message = self.message
            
            sms_data.append({
                'record': record,
                'mobile': mobile,
                'message': message
            })
        
        _logger.info(f"Prepared SMS data for {len(sms_data)} recipients")
        
        if not sms_data:
            raise UserError(_('No valid mobile numbers found in selected records'))
        
        # Send SMS
        success_count = 0
        failed_count = 0
        
        try:
            # Determine sending mode
            # 'single' = send to one recipient (supports dynamic content)
            # 'bulk' = send same message to all at once
            # 'template' = use template with dynamic content
            
            if self.composition_mode1 == 'single':
                # Single SMS to one recipient
                data = sms_data[0]
                _logger.info(f"Sending single SMS to {data['mobile']}")
                response = config.send_sms(data['mobile'], data['message'])
                
                # Create history
                partner_id = data['record'].id if self.res_model == 'res.partner' else False
                lead_id = data['record'].id if self.res_model == 'crm.lead' else False
                
                self.env['sms.history'].create_history(
                    mobile=data['mobile'],
                    message=data['message'],
                    partner_id=partner_id,
                    lead_id=lead_id,
                    template_id=self.template_id.id if self.template_id else False,
                    response=response
                )
                
                if response.get('statusCode') == '200':
                    success_count = 1
                    # Log success with highlight
                    self._log_sms_success(
                        mode='SINGLE',
                        recipient_count=1,
                        mobiles=[data['mobile']],
                        message_preview=data['message'],
                        response=response
                    )
                    # Post to chatter
                    self._post_chatter_message(
                        record=data['record'],
                        success=True,
                        mobile=data['mobile'],
                        message_preview=data['message'],
                        response=response
                    )
                else:
                    failed_count = 1
                    # Log failure with highlight
                    self._log_sms_failure(
                        mode='SINGLE',
                        recipient_count=1,
                        mobiles=[data['mobile']],
                        message_preview=data['message'],
                        response=response
                    )
                    # Post to chatter
                    self._post_chatter_message(
                        record=data['record'],
                        success=False,
                        mobile=data['mobile'],
                        message_preview=data['message'],
                        response=response
                    )
                    
            elif self.composition_mode1 == 'bulk':
                # Bulk SMS (same message to all) - uses OneToMany API
                mobiles = [d['mobile'] for d in sms_data]
                _logger.info(f"Sending bulk SMS to {len(mobiles)} recipients")
                response = config.send_bulk_sms(mobiles, self.message)
                
                # Create history for each
                for data in sms_data:
                    partner_id = data['record'].id if self.res_model == 'res.partner' else False
                    lead_id = data['record'].id if self.res_model == 'crm.lead' else False
                    
                    self.env['sms.history'].create_history(
                        mobile=data['mobile'],
                        message=data['message'],
                        partner_id=partner_id,
                        lead_id=lead_id,
                        template_id=self.template_id.id if self.template_id else False,
                        response=response
                    )
                
                if response.get('statusCode') == '200':
                    success_count = len(sms_data)
                    # Log success with highlight
                    self._log_sms_success(
                        mode='BULK',
                        recipient_count=len(sms_data),
                        mobiles=mobiles,
                        message_preview=self.message,
                        response=response
                    )
                    # Post to chatter for each record
                    for data in sms_data:
                        self._post_chatter_message(
                            record=data['record'],
                            success=True,
                            mobile=data['mobile'],
                            message_preview=data['message'],
                            response=response
                        )
                else:
                    failed_count = len(sms_data)
                    # Log failure with highlight
                    self._log_sms_failure(
                        mode='BULK',
                        recipient_count=len(sms_data),
                        mobiles=mobiles,
                        message_preview=self.message,
                        response=response
                    )
                    # Post to chatter for each record
                    for data in sms_data:
                        self._post_chatter_message(
                            record=data['record'],
                            success=False,
                            mobile=data['mobile'],
                            message_preview=data['message'],
                            response=response
                        )
                    
            elif self.composition_mode1 == 'template':
                # Template mode with dynamic content - uses DSMS API for personalization
                api_sms_data = [{'MobNumber': d['mobile'], 'Message': d['message']} 
                               for d in sms_data]
                mobiles = [d['mobile'] for d in sms_data]
                _logger.info(f"Sending template SMS to {len(api_sms_data)} recipients")
                response = config.send_dynamic_sms(api_sms_data)
                
                # Create history for each
                for data in sms_data:
                    partner_id = data['record'].id if self.res_model == 'res.partner' else False
                    lead_id = data['record'].id if self.res_model == 'crm.lead' else False
                    
                    self.env['sms.history'].create_history(
                        mobile=data['mobile'],
                        message=data['message'],
                        partner_id=partner_id,
                        lead_id=lead_id,
                        template_id=self.template_id.id if self.template_id else False,
                        response=response
                    )
                
                if response.get('statusCode') == '200':
                    success_count = len(sms_data)
                    # Log success with highlight
                    self._log_sms_success(
                        mode='TEMPLATE',
                        recipient_count=len(sms_data),
                        mobiles=mobiles,
                        message_preview=sms_data[0]['message'] if sms_data else '',
                        response=response
                    )
                    # Post to chatter for each record
                    for data in sms_data:
                        self._post_chatter_message(
                            record=data['record'],
                            success=True,
                            mobile=data['mobile'],
                            message_preview=data['message'],
                            response=response
                        )
                else:
                    failed_count = len(sms_data)
                    # Log failure with highlight
                    self._log_sms_failure(
                        mode='TEMPLATE',
                        recipient_count=len(sms_data),
                        mobiles=mobiles,
                        message_preview=sms_data[0]['message'] if sms_data else '',
                        response=response
                    )
                    # Post to chatter for each record
                    for data in sms_data:
                        self._post_chatter_message(
                            record=data['record'],
                            success=False,
                            mobile=data['mobile'],
                            message_preview=data['message'],
                            response=response
                        )
            
            # Show notification
            if success_count > 0:
                message = _('%d SMS sent successfully') % success_count
                if failed_count > 0:
                    message += _(', %d failed') % failed_count
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('SMS Sent'),
                        'message': message,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                error_msg = response.get('statusMessage', 'Unknown error') if response else 'No response'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Failed'),
                        'message': _('Failed to send SMS: %s') % error_msg,
                        'type': 'danger',
                        'sticky': True,
                    }
                }
                
        except Exception as e:
            _logger.error(f"SMS sending failed: {str(e)}", exc_info=True)
            raise UserError(_('Failed to send SMS: %s') % str(e))
