from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        payments = super()._create_payments()
        template = self.env.ref('mimsms_gateway.sms_template_payment_received')
        service = self.env['sms.automation']
        for payment in payments.filtered(
            lambda p: p.partner_type == 'customer' and p.payment_type == 'inbound'
        ):
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
        return payments
