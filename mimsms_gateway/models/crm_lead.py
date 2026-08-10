# ============================================================================
# FILE: models/crm_lead.py
# ============================================================================
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CrmLead(models.Model):
    _inherit = 'crm.lead'
    
    sms_count = fields.Integer(string='SMS Count', compute='_compute_sms_count')
    
    def _compute_sms_count(self):
        for lead in self:
            lead.sms_count = self.env['sms.history'].search_count([
                ('lead_id', '=', lead.id)
            ])
    
    def action_send_sms(self):
        """Open SMS composer wizard"""
        self.ensure_one()
        
        if not self.mobile:
            raise UserError(_('This lead/opportunity does not have a mobile number.'))
        
        return {
            'name': _('Send SMS'),
            'type': 'ir.actions.act_window',
            'res_model': 'sms.composer',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'crm.lead',
                'default_res_ids': self.ids,
                'default_composition_mode': 'single' if len(self.ids) == 1 else 'bulk',
            }
        }
    
    def action_view_sms_history(self):
        """View SMS history for this lead"""
        self.ensure_one()
        return {
            'name': _('SMS History'),
            'type': 'ir.actions.act_window',
            'res_model': 'sms.history',
            'view_mode': 'tree,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'create': False}
        }