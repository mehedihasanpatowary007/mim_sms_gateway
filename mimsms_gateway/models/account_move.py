import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_send_invoice_sms(self):
        self.ensure_one()
        if not self.env.user.has_group('mimsms_gateway.group_sms_gateway_user'):
            raise UserError(_('You do not have permission to send SMS messages.'))
        if self.move_type != 'out_invoice' or self.state != 'posted':
            raise UserError(_('SMS can only be sent for a posted customer invoice.'))

        template = self.env['mimsms.template'].get_for_company(
            self.company_id, 'invoice', 'mimsms_gateway.sms_template_invoice_generated'
        )
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
                'default_is_chatter_single': True,
                'default_template_id': template.id,
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
        service = self.env['sms.automation']
        for invoice in invoices:
            config = self.env['mimsms.config'].get_active_config(
                company=invoice.company_id, raise_if_missing=False
            )
            if not config or not config.overdue_sms_enabled:
                continue
            try:
                template = self.env['mimsms.template'].get_for_company(
                    invoice.company_id, 'overdue',
                    'mimsms_gateway.sms_template_invoice_overdue',
                )
            except UserError:
                _logger.exception('No overdue SMS template for %s', invoice.company_id.display_name)
                continue
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
