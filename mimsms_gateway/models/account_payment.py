import logging

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        """Send payment receipt SMS for both invoice and direct payments.

        The standard Register Payment wizard ultimately posts account.payment
        records, so using the payment posting event covers both entry points.
        The automation event key prevents duplicate SMS for the same payment.
        """
        result = super().action_post()

        service = self.env['sms.automation']
        for payment in self.filtered(
            lambda p: p.partner_type == 'customer'
            and p.payment_type == 'inbound'
            and p.partner_id
        ):
            config = self.env['mimsms.config'].get_active_config(
                company=payment.company_id, raise_if_missing=False
            )
            if not config or not config.payment_sms_enabled:
                continue
            try:
                template = self.env['mimsms.template'].get_for_company(
                    payment.company_id, 'payment',
                    'mimsms_gateway.sms_template_payment_received',
                )
            except UserError:
                _logger.exception('No payment SMS template for %s', payment.company_id.display_name)
                continue
            message = template._render_template(template.body, payment)
            service._send(
                partner=payment.partner_id,
                message=message,
                event_key=f'payment:account.payment:{payment.id}',
                event_type='payment',
                company=payment.company_id,
                source=payment,
                template=template,
            )
        return result
