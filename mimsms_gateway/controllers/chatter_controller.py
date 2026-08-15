import logging

from odoo import http, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request


_logger = logging.getLogger(__name__)


class MimsmsChatterController(http.Controller):

    @staticmethod
    def _supports_sms(model_name):
        if model_name not in request.env:
            return False
        if model_name == 'res.partner':
            return True
        partner_field = request.env[model_name]._fields.get('partner_id')
        return bool(partner_field and partner_field.type == 'many2one' and partner_field.comodel_name == 'res.partner')

    @http.route('/mimsms_gateway/chatter/availability', type='json', auth='user')
    def sms_availability(self, model, res_id=None):
        available = (
            request.env.user.has_group('mimsms_gateway.group_sms_gateway_user')
            and self._supports_sms(model)
            and bool(res_id)
        )
        if available:
            try:
                record = request.env[model].browse(int(res_id)).exists()
                record.check_access('read')
                available = bool(record)
            except (AccessError, ValueError, TypeError):
                available = False
        return {'available': available}

    @http.route('/mimsms_gateway/chatter/send', type='json', auth='user')
    def send_sms_action(self, model, res_id):
        try:
            if not request.env.user.has_group('mimsms_gateway.group_sms_gateway_user'):
                raise AccessError(_('You do not have permission to send SMS messages.'))
            if not self._supports_sms(model):
                raise UserError(_('This document does not have a related customer.'))

            record = request.env[model].browse(int(res_id)).exists()
            if not record:
                raise UserError(_('The document was not found.'))
            record.check_access('read')

            if model == 'account.move' and record.move_type == 'out_invoice':
                action = record.action_send_invoice_sms()
            elif model == 'stock.picking' and record.picking_type_code == 'outgoing':
                action = record.action_send_delivery_sms()
            else:
                composer_view = request.env.ref(
                    'mimsms_gateway.view_sms_composer_form'
                )
                action = {
                    'name': _('Send SMS'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'mimsms.composer',
                    'view_mode': 'form',
                    'view_id': composer_view.id,
                    'views': [[composer_view.id, 'form']],
                    'target': 'new',
                    'context': {
                        'default_res_model': model,
                        'default_res_ids': str(record.ids),
                        'default_composition_mode1': 'single',
                    },
                }
            return {'success': True, 'action': action}
        except (AccessError, UserError) as error:
            return {'error': True, 'message': str(error)}
        except Exception:
            _logger.exception('Could not open MiMSMS composer from chatter')
            return {'error': True, 'message': _('Could not open the SMS composer.')}
