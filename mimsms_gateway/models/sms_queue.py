import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class SmsQueue(models.Model):
    _name = 'sms.queue'
    _description = 'SMS Queue'
    _order = 'create_date asc, id asc'
    _rec_name = 'mobile'
    MAX_ATTEMPTS = 3

    mobile = fields.Char(string='Mobile Number', required=True, index=True)
    message = fields.Text(string='Message', required=True)
    state = fields.Selection([
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ], string='Status', default='queued', required=True, index=True)
    send_mode = fields.Selection([
        ('bulk', 'Bulk'),
        ('dynamic', 'Dynamic'),
    ], string='Queue Mode', required=True, default='bulk', index=True)
    recipient_type = fields.Selection([
        ('partner', 'Partner'),
        ('manager', 'Manager'),
    ], string='Recipient Type', default='partner', required=True, index=True)
    recipient_name = fields.Char(string='Recipient Name', index=True)

    partner_id = fields.Many2one('res.partner', string='Contact', ondelete='set null')
    template_id = fields.Many2one('mimsms.template', string='Template', ondelete='set null')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    user_id = fields.Many2one(
        'res.users', string='Queued By', required=True,
        default=lambda self: self.env.user,
    )
    history_id = fields.Many2one('sms.history', string='SMS History', ondelete='set null')
    res_model = fields.Char(string='Source Model', index=True)
    res_id = fields.Integer(string='Source Record ID', index=True)

    attempts = fields.Integer(string='Attempts', default=0, readonly=True)
    last_attempt = fields.Datetime(string='Last Attempt', readonly=True)
    next_attempt_at = fields.Datetime(string='Next Attempt', readonly=True, index=True)
    response_code = fields.Char(string='Response Code', readonly=True)
    response_message = fields.Char(string='Response Message', readonly=True)
    api_response = fields.Text(string='Full API Response', readonly=True)
    error_message = fields.Text(string='Error Message', readonly=True)
    sent_date = fields.Datetime(string='Sent Date', readonly=True)

    @api.model
    def enqueue(self, *, mobile, message, record, send_mode='bulk', template=None,
                event_type='manual', event_key=False, recipient_type='partner',
                recipient_name=False):
        """Create a visible queue item and a matching queued history row."""
        partner = record if record._name == 'res.partner' else getattr(record, 'partner_id', False)
        partner = partner.commercial_partner_id if partner else False
        company = getattr(record, 'company_id', False) or self.env.company
        recipient_name = recipient_name or (
            partner.display_name if partner else record.display_name
        )
        message = self.env['mimsms.template']._coerce_body_text(message)
        message = self.env['mimsms.composer']._validate_outbound_message(message, company)
        if template:
            if company not in template.company_ids:
                raise UserError(_(
                    'Template %s is not assigned to %s.'
                ) % (template.display_name, company.display_name))
            template._validate_placeholders()

        queue = self.sudo().create({
            'mobile': mobile,
            'message': message,
            'send_mode': send_mode,
            'recipient_type': recipient_type,
            'recipient_name': recipient_name,
            'partner_id': partner.id if partner else False,
            'template_id': template.id if template else False,
            'company_id': company.id,
            'user_id': self.env.user.id,
            'res_model': record._name,
            'res_id': record.id,
        })
        history = self.env['sms.history'].create_history(
            mobile=mobile,
            message=message,
            partner_id=partner.id if partner else False,
            template_id=template.id if template else False,
            status='queued',
            recipient_type=recipient_type,
            recipient_name=recipient_name,
            company_id=company.id,
            user_id=self.env.user.id,
            res_model=record._name,
            res_id=record.id,
            event_type=event_type,
            event_key=event_key,
        )
        queue.history_id = history.id
        return queue

    def _source_record(self):
        self.ensure_one()
        if not self.res_model or self.res_model not in self.env or not self.res_id:
            return False
        return self.env[self.res_model].sudo().browse(self.res_id).exists()

    def _apply_response(self, response, retry_delay_minutes=5):
        """Apply a provider response and schedule at most two retries."""
        success = str(response.get('statusCode')) == '200'
        now = fields.Datetime.now()
        for item in self:
            attempts = item.attempts + 1
            exhausted = attempts >= self.MAX_ATTEMPTS
            state = 'sent' if success else ('failed' if exhausted else 'queued')
            vals = {
                'state': state,
                'attempts': attempts,
                'last_attempt': now,
                'next_attempt_at': (
                    False if success or exhausted else
                    now + relativedelta(minutes=retry_delay_minutes)
                ),
                'response_code': response.get('statusCode'),
                'response_message': response.get('statusMessage') or response.get('message'),
                'api_response': str(response),
                'error_message': False if success else (
                    response.get('statusMessage') or response.get('message') or _('Provider rejected the SMS.')
                ),
                'sent_date': now if success else False,
            }
            item.write(vals)
            if item.history_id:
                item.history_id.sudo().write({
                    'status': state,
                    'response_code': response.get('statusCode'),
                    'response_message': vals['response_message'],
                    'api_response': str(response),
                    'sent_date': now if success else False,
                    'error_message': vals['error_message'],
                })
            if success and item.template_id:
                item.template_id._register_usage()
            source = item._source_record()
            if source and (success or exhausted):
                self.env['mimsms.composer']._post_chatter_message(
                    record=source,
                    success=success,
                    mobile=item.mobile,
                    message_preview=item.message,
                    response=response,
                )

    def _apply_batch_response(self, response, retry_delay_minutes):
        """Use recipient-level results when MiMSMS provides them."""
        results = response.get('responseResult')
        if not isinstance(results, list) or not results:
            self._apply_response(response, retry_delay_minutes)
            return

        remaining = list(self)
        for result in results:
            if not isinstance(result, dict):
                continue
            mobile = str(
                result.get('MobileNumber') or result.get('MobNumber')
                or result.get('mobile') or ''
            ).lstrip('+')
            item = next((candidate for candidate in remaining if candidate.mobile == mobile), False)
            if not item and remaining:
                item = remaining[0]
            if not item:
                continue
            item_response = dict(response)
            item_response.update(result)
            item_response['statusCode'] = result.get(
                'statusCode', result.get('status_code', response.get('statusCode'))
            )
            item_response['statusMessage'] = result.get(
                'statusMessage', result.get('message', response.get('statusMessage'))
            )
            item._apply_response(item_response, retry_delay_minutes)
            remaining.remove(item)
        if remaining:
            self.browse([item.id for item in remaining])._apply_response({
                'statusCode': 'PARTIAL_RESPONSE',
                'statusMessage': _('MiMSMS did not return a result for this recipient.'),
                'responseResult': results,
            }, retry_delay_minutes)

    def _mark_skipped(self, reason):
        now = fields.Datetime.now()
        for item in self:
            item.write({
                'state': 'skipped',
                'attempts': item.attempts + 1,
                'last_attempt': now,
                'next_attempt_at': False,
                'error_message': reason,
            })
            if item.history_id:
                item.history_id.sudo().write({
                    'status': 'skipped',
                    'error_message': reason,
                })

    def _mark_exception(self, error, retry_delay_minutes=5):
        self._apply_response({
            'statusCode': 'EXCEPTION',
            'statusMessage': str(error),
        }, retry_delay_minutes)

    @api.model
    @api.private
    def _cron_process_queue(self, batch_size=100):
        """Process queued bulk SMS asynchronously in provider-friendly batches."""
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(hashtext('mimsms_gateway.queue'))"
        )
        if not self.env.cr.fetchone()[0]:
            return
        self.env.cr.execute("""
            SELECT id, (next_attempt_at IS NULL OR next_attempt_at <= NOW()) AS ready
              FROM sms_queue
             WHERE state = 'queued'
             ORDER BY create_date ASC, id ASC
             FOR UPDATE SKIP LOCKED
             LIMIT %s
        """, [batch_size])
        ready_ids = []
        for queue_id, ready in self.env.cr.fetchall():
            if not ready:
                break
            ready_ids.append(queue_id)
        queue = self.sudo().browse(ready_ids)
        if not queue:
            return

        pending = list(queue)
        while pending:
            first = pending.pop(0)
            items = first
            while pending:
                candidate = pending[0]
                same_run = (
                    candidate.company_id == first.company_id
                    and candidate.send_mode == first.send_mode
                    and (
                        first.send_mode == 'dynamic'
                        or candidate.message == first.message
                    )
                )
                if not same_run:
                    break
                items |= pending.pop(0)

            company = first.company_id
            config = self.env['mimsms.config'].get_active_config(company=company, raise_if_missing=False)
            if not config:
                items._mark_skipped(_('No active SMS Gateway configuration was found for %s.') % company.display_name)
                continue
            try:
                if first.send_mode == 'bulk':
                    response = config.send_bulk_sms(items.mapped('mobile'), first.message)
                else:
                    response = config.send_dynamic_sms([
                        {'MobNumber': item.mobile, 'Message': item.message}
                        for item in items
                    ])
                items._apply_batch_response(response, config.retry_delay_minutes)
            except Exception as error:
                _logger.exception('Queued SMS failed for queue IDs %s', items.ids)
                items._mark_exception(error, config.retry_delay_minutes)
