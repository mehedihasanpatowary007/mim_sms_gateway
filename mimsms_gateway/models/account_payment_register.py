from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        """Keep the standard payment flow.

        Payment SMS is triggered from account.payment.action_post so it works
        for both invoice Register Payment and direct Payments entry.
        """
        return super()._create_payments()
