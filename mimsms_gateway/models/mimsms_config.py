from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import requests
import logging

_logger = logging.getLogger(__name__)


class MimsmsConfig(models.Model):
    _name = 'mimsms.config'
    _description = 'MiMSMS Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # ADD THIS LINE
    _rec_name = 'username'

    username = fields.Char(string='Username (Email)', required=True, tracking=True)
    apikey = fields.Char(string='API Key', required=True, groups='mimsms_gateway.group_sms_gateway_manager')
    sender_id = fields.Char(string='Sender ID', required=True, tracking=True)
    base_url = fields.Char(
        string='Base URL',
        default='https://api.mimsms.com',
        required=True
    )
    active = fields.Boolean(string='Active', default=True, tracking=True)
    balance = fields.Float(string='Current Balance', readonly=True)
    last_balance_check = fields.Datetime(string='Last Balance Check', readonly=True)
    company_ids = fields.Many2many(
        'res.company',
        'mimsms_config_company_rel',
        'config_id',
        'company_id',
        string='Companies',
        help='Leave empty to use this configuration as the global fallback.'
    )

    @api.constrains('active', 'company_ids')
    def _check_active_company_scope(self):
        """Allow one active global fallback and one active config per company."""
        for config in self.filtered('active'):
            other_active = self.search([
                ('id', '!=', config.id),
                ('active', '=', True),
            ])
            if not config.company_ids:
                if any(not other.company_ids for other in other_active):
                    raise ValidationError(_('Only one global SMS configuration can be active.'))
                continue

            overlapping = config.company_ids & other_active.mapped('company_ids')
            if overlapping:
                raise ValidationError(_(
                    'An active SMS configuration already exists for: %s'
                ) % ', '.join(overlapping.mapped('display_name')))
    
    @api.model
    @api.private
    def get_active_config(self, company=None, raise_if_missing=True):
        """Resolve a company-specific configuration, then the global fallback.

        Automatic integrations should pass ``raise_if_missing=False`` and skip
        sending when the returned recordset is empty.
        """
        company = company or self.env.company
        configs = self.sudo()
        config = configs.search([
            ('active', '=', True),
            ('company_ids', 'in', [company.id]),
        ], limit=1)
        if not config:
            config = configs.search([
                ('active', '=', True),
                ('company_ids', '=', False),
            ], limit=1)
        if not config and raise_if_missing:
            raise UserError(_(
                'No active SMS Gateway configuration was found for %s. '
                'Please contact your SMS Gateway administrator.'
            ) % company.display_name)
        return config
    
    def action_check_balance(self):
        """Check SMS balance"""
        self.ensure_one()
        
        payload = {
            "UserName": self.username,
            "Apikey": self.apikey
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/SmsSending/balanceCheck",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            result = response.json()
            
            if result.get('statusCode') == "200":
                self.balance = float(result.get('responseResult', 0))
                self.last_balance_check = fields.Datetime.now()
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Balance Check'),
                        'message': _('Current Balance: ৳%s') % self.balance,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_('Failed to check balance: %s') % result.get('statusMessage'))
                
        except requests.exceptions.RequestException as e:
            _logger.error(f"Balance check failed: {str(e)}")
            raise UserError(_('Failed to connect to MiMSMS API: %s') % str(e))
    
    @api.private
    def send_sms(self, mobile, message, transaction_type='T'):
        """Send single SMS"""
        self.ensure_one()
        
        payload = {
            "UserName": self.username,
            "Apikey": self.apikey,
            "MobileNumber": mobile,
            "CampaignId": "null",
            "SenderName": self.sender_id,
            "TransactionType": transaction_type,
            "Message": message
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/SmsSending/SMS",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"SMS sending failed: {str(e)}")
            raise UserError(_('Failed to send SMS: %s') % str(e))
    
    @api.private
    def send_bulk_sms(self, mobiles, message):
        """Send same message to multiple numbers"""
        self.ensure_one()
        
        mobile_numbers = ','.join(mobiles)
        
        payload = {
            "UserName": self.username,
            "Apikey": self.apikey,
            "MobileNumber": mobile_numbers,
            "CampaignId": "null",
            "SenderName": self.sender_id,
            "TransactionType": "T",
            "Message": message
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/SmsSending/OneToMany",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"Bulk SMS sending failed: {str(e)}")
            raise UserError(_('Failed to send bulk SMS: %s') % str(e))
    
    @api.private
    def send_dynamic_sms(self, sms_data):
        """Send different messages to different numbers"""
        self.ensure_one()
        
        payload = {
            "UserName": self.username,
            "Apikey": self.apikey,
            "SenderName": self.sender_id,
            "TransactionType": "D",
            "SmsData": sms_data
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/SmsSending/DSMS",
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"Dynamic SMS sending failed: {str(e)}")
            raise UserError(_('Failed to send dynamic SMS: %s') % str(e))
