from odoo import fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sms_history_count = fields.Integer(
        string='SMS History',
        compute='_compute_sms_history_count',
    )

    def _compute_sms_history_count(self):
        History = self.env['sms.history']
        for partner in self:
            commercial_partner = partner.commercial_partner_id
            partner.sms_history_count = History.search_count([
                ('partner_id', '=', commercial_partner.id),
            ])

    def action_view_sms_history(self):
        self.ensure_one()
        commercial_partner = self.commercial_partner_id
        action = self.env['ir.actions.actions']._for_xml_id(
            'mimsms_gateway.action_sms_history'
        )
        action.update({
            'name': _('SMS History - %s') % commercial_partner.display_name,
            'domain': [('partner_id', '=', commercial_partner.id)],
            'context': {
                'default_partner_id': commercial_partner.id,
                'create': False,
            },
        })
        return action
