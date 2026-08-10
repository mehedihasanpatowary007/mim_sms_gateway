from odoo import models


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    def _get_bindings(self, model_name):
        """Hide Odoo/IAP SMS composer entries from contextual Action menus."""
        bindings = super()._get_bindings(model_name)
        return {
            binding_type: tuple(
                action for action in actions
                if action.get('res_model') != 'sms.composer'
            )
            for binding_type, actions in bindings.items()
        }
