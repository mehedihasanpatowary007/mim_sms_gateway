# models/res_partner.py
from odoo import models

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    def action_send_sms(self):
        """Open SMS composer from contact"""
        # Log a message in the chatter
        self.message_post(
            body="SMS composer opened for this contact.",
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send SMS',
            'res_model': 'sms.composer',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'res.partner',
                'default_res_ids': str([self.id]),
                'default_composition_mode': 'single',
            }
        }