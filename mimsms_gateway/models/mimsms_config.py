from odoo import api, fields, models, _
from odoo.exceptions import UserError
import requests
import logging

_logger = logging.getLogger(__name__)


class MimsmsConfig(models.Model):
    _name = 'mimsms.config'
    _description = 'MiMSMS Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # ADD THIS LINE
    _rec_name = 'username'

    username = fields.Char(string='Username (Email)', required=True, 
                          default='ayesha.chowdhury5670@gmail.com',
                          tracking=True)  # Optional: add tracking=True to track changes
    apikey = fields.Char(string='API Key', required=True,
                        default='3ZCPH1U8ZAI2RPT')
    sender_id = fields.Char(string='Sender ID', required=True,
                           default='8809617632488',
                           tracking=True)
    base_url = fields.Char(
        string='Base URL',
        default='https://api.mimsms.com',
        required=True
    )
    active = fields.Boolean(string='Active', default=True, tracking=True)
    balance = fields.Float(string='Current Balance', readonly=True)
    last_balance_check = fields.Datetime(string='Last Balance Check', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    
    @api.model
    def get_active_config(self):
        """Get the active MiMSMS configuration"""
        config = self.search([('active', '=', True)], limit=1)
        if not config:
            raise UserError(_('No active MiMSMS configuration found. Please configure MiMSMS settings first.'))
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