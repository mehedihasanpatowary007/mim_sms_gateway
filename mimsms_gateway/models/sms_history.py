# ============================================================================
# FILE: models/sms_history.py
# ============================================================================
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SmsHistory(models.Model):
    _name = 'sms.history'
    _description = 'SMS History'
    _order = 'create_date desc'
    _rec_name = 'mobile'

    mobile = fields.Char(string='Mobile Number', required=True)
    message = fields.Text(string='Message', required=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ], string='Status', default='draft', required=True)
    recipient_type = fields.Selection([
        ('partner', 'Partner'),
        ('manager', 'Manager'),
    ], string='Recipient Type', default='partner', required=True, index=True)
    recipient_name = fields.Char(string='Recipient Name', index=True)
    
    response_code = fields.Char(string='Response Code')
    response_message = fields.Char(string='Response Message')
    api_response = fields.Text(string='Full API Response')
    
    partner_id = fields.Many2one('res.partner', string='Contact', ondelete='set null')
    template_id = fields.Many2one('mimsms.template', string='Template Used', ondelete='set null')
    user_id = fields.Many2one('res.users', string='Sent By', default=lambda self: self.env.user)
    
    sent_date = fields.Datetime(string='Sent Date')
    error_message = fields.Text(string='Error Message')
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    res_model = fields.Char(string='Source Model', index=True)
    res_id = fields.Integer(string='Source Record ID', index=True)
    event_type = fields.Selection([
        ('manual', 'Manual'),
        ('payment', 'Payment Received'),
        ('overdue', 'Invoice Overdue'),
        ('monthly', 'Monthly Closing'),
    ], default='manual', required=True, index=True)
    event_key = fields.Char(string='Event Key', index=True, copy=False)
    
    def name_get(self):
        result = []
        for record in self:
            created = (
                record.create_date.strftime('%Y-%m-%d %H:%M')
                if record.create_date else _('New')
            )
            name = f"{record.mobile} - {created}"
            result.append((record.id, name))
        return result
    
    @api.model
    def create_history(self, mobile, message, partner_id=None,
                      template_id=None, status='draft', response=None, **extra_vals):
        """Create SMS history record"""
        message = self.env['mimsms.template']._coerce_body_text(message)
        extra_vals.setdefault('recipient_type', 'partner')
        if not extra_vals.get('recipient_name') and partner_id:
            extra_vals['recipient_name'] = self.env['res.partner'].browse(
                partner_id
            ).display_name
        vals = {
            'mobile': mobile,
            'message': message,
            'partner_id': partner_id,
            'template_id': template_id,
            'status': status,
            **extra_vals,
        }
        
        if response:
            vals.update({
                'response_code': response.get('statusCode'),
                'response_message': response.get('statusMessage'),
                'api_response': str(response),
                'sent_date': fields.Datetime.now() if str(response.get('statusCode')) == '200' else False,
            })
            
            if str(response.get('statusCode')) == '200':
                vals['status'] = 'sent'
            else:
                vals['status'] = 'failed'
                vals['error_message'] = response.get('statusMessage')
        
        return self.create(vals)
    
    def action_resend(self):
        """Queue a failed SMS again so the normal retry policy applies."""
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('mimsms_gateway.group_sms_gateway_user'):
            raise UserError(_('You do not have permission to send SMS messages.'))
        source = False
        if self.res_model and self.res_model in self.env and self.res_id:
            source = self.env[self.res_model].browse(self.res_id).exists()
        source = source or self.partner_id
        if not source:
            raise UserError(_('The original SMS recipient is no longer available.'))
        mobile = self.env['mimsms.composer']._normalize_phone_number(self.mobile)
        if not mobile:
            raise UserError(_('The stored phone number is not a valid Bangladesh mobile number.'))
        self.env['sms.queue'].enqueue(
            mobile=mobile,
            message=self.message,
            record=source,
            send_mode='dynamic',
            template=self.template_id,
            recipient_type=self.recipient_type,
            recipient_name=self.recipient_name,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('SMS Queued'),
                'message': _('The SMS was added to the queue for resend.'),
                'type': 'success',
            },
        }
