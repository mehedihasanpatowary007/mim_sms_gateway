# ============================================================================
# FILE: models/sms_history.py
# ============================================================================
from odoo import api, fields, models, _


class SmsHistory(models.Model):
    _name = 'sms.history'
    _description = 'SMS History'
    _order = 'create_date desc'
    _rec_name = 'mobile'

    mobile = fields.Char(string='Mobile Number', required=True)
    message = fields.Text(string='Message', required=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('failed', 'Failed')
    ], string='Status', default='draft', required=True)
    
    response_code = fields.Char(string='Response Code')
    response_message = fields.Char(string='Response Message')
    api_response = fields.Text(string='Full API Response')
    
    partner_id = fields.Many2one('res.partner', string='Contact', ondelete='set null')
    lead_id = fields.Many2one('crm.lead', string='Lead/Opportunity', ondelete='set null')
    template_id = fields.Many2one('sms.template', string='Template Used', ondelete='set null')
    user_id = fields.Many2one('res.users', string='Sent By', default=lambda self: self.env.user)
    
    sent_date = fields.Datetime(string='Sent Date')
    error_message = fields.Text(string='Error Message')
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    
    def name_get(self):
        result = []
        for record in self:
            name = f"{record.mobile} - {record.create_date.strftime('%Y-%m-%d %H:%M')}"
            result.append((record.id, name))
        return result
    
    @api.model
    def create_history(self, mobile, message, partner_id=None, lead_id=None, 
                      template_id=None, status='draft', response=None):
        """Create SMS history record"""
        vals = {
            'mobile': mobile,
            'message': message,
            'partner_id': partner_id,
            'lead_id': lead_id,
            'template_id': template_id,
            'status': status,
        }
        
        if response:
            vals.update({
                'response_code': response.get('statusCode'),
                'response_message': response.get('statusMessage'),
                'api_response': str(response),
                'sent_date': fields.Datetime.now() if response.get('statusCode') == '200' else False,
            })
            
            if response.get('statusCode') == '200':
                vals['status'] = 'sent'
            else:
                vals['status'] = 'failed'
                vals['error_message'] = response.get('statusMessage')
        
        return self.create(vals)
    
    def action_resend(self):
        """Resend failed SMS"""
        self.ensure_one()
        
        config = self.env['mimsms.config'].get_active_config()
        
        try:
            response = config.send_sms(self.mobile, self.message)
            
            self.write({
                'status': 'sent' if response.get('statusCode') == '200' else 'failed',
                'response_code': response.get('statusCode'),
                'response_message': response.get('statusMessage'),
                'api_response': str(response),
                'sent_date': fields.Datetime.now() if response.get('statusCode') == '200' else False,
                'error_message': response.get('statusMessage') if response.get('statusCode') != '200' else False,
            })
            
            if response.get('statusCode') == '200':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('SMS resent successfully'),
                        'type': 'success',
                    }
                }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': str(e),
                    'type': 'danger',
                }
            }
