from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_send_invoice_sms(self):
        self.ensure_one()
        if not self.env.user.has_group('mimsms_gateway.group_sms_gateway_user'):
            raise UserError(_('You do not have permission to send SMS messages.'))
        if self.move_type != 'out_invoice' or self.state != 'posted':
            raise UserError(_('SMS can only be sent for a posted customer invoice.'))

        template = self.env.ref('mimsms_gateway.sms_template_invoice_generated')
        message = template._render_template(template.body, self)
        return {
            'name': _('Send Invoice SMS'),
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

    @classmethod
    def _sms_money(cls, amount):
        return f'{amount:,.2f}'

    @api.model
    @api.private
    def _cron_send_overdue_sms(self):
        today = fields.Date.context_today(self)
        invoices = self.sudo().search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date_due', '<', today),
            ('amount_residual', '>', 0),
        ])
        template = self.env.ref('mimsms_gateway.sms_template_invoice_overdue')
        service = self.env['sms.automation']
        for invoice in invoices:
            message = template._render_template(template.body, invoice)
            service._send(
                partner=invoice.partner_id,
                message=message,
                event_key=f'overdue:account.move:{invoice.id}',
                event_type='overdue',
                company=invoice.company_id,
                source=invoice,
                template=template,
            )
