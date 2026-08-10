from odoo import models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_send_delivery_sms(self):
        self.ensure_one()
        if not self.env.user.has_group('mimsms_gateway.group_sms_gateway_user'):
            raise UserError(_('You do not have permission to send SMS messages.'))
        if self.picking_type_code != 'outgoing':
            raise UserError(_('SMS is only available for customer deliveries.'))

        template = self.env.ref('mimsms_gateway.sms_template_delivery')
        message = template._render_template(template.body, self)
        return {
            'name': _('Send Delivery SMS'),
            'type': 'ir.actions.act_window',
            'res_model': 'mimsms.composer',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_ids': str(self.ids),
                'default_composition_mode1': 'single',
                'default_message': message,
            },
        }
