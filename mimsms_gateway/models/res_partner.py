import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sms_manager_name = fields.Char(string='Manager Name')
    sms_manager_mobile = fields.Char(string='Manager Mobile')

    sms_history_count = fields.Integer(
        string='SMS History',
        compute='_compute_sms_history_count',
    )

    @api.model
    def _normalize_sms_mobile(self, phone):
        """Return a Bangladesh mobile number in 8801XXXXXXXXX format."""
        if not phone:
            return False
        phone = str(phone).strip()
        if not re.fullmatch(r'[+0-9\s().-]+', phone):
            return False
        phone = re.sub(r'[\s().-]', '', phone)
        if phone.startswith('+'):
            phone = phone[1:]
        elif phone.startswith('00'):
            phone = phone[2:]

        if re.fullmatch(r'01[3-9][0-9]{8}', phone):
            phone = '880' + phone[1:]
        elif re.fullmatch(r'1[3-9][0-9]{8}', phone):
            phone = '880' + phone
        return phone if re.fullmatch(r'8801[3-9][0-9]{8}', phone) else False

    @api.constrains('sms_manager_name', 'sms_manager_mobile', 'mobile', 'phone')
    def _check_sms_manager(self):
        for partner in self:
            manager_name = (partner.sms_manager_name or '').strip()
            manager_mobile_value = (partner.sms_manager_mobile or '').strip()
            if bool(manager_name) != bool(manager_mobile_value):
                raise ValidationError(_(
                    'Manager Name and Manager Mobile must be provided together.'
                ))
            if not manager_mobile_value:
                continue

            manager_mobile = partner._normalize_sms_mobile(manager_mobile_value)
            if not manager_mobile:
                raise ValidationError(_(
                    'Manager Mobile must be a valid Bangladesh mobile number.'
                ))
            partner_mobile = partner._normalize_sms_mobile(
                partner.mobile or partner.phone
            )
            if partner_mobile and manager_mobile == partner_mobile:
                raise ValidationError(_(
                    'Partner and Manager mobile numbers must be different.'
                ))

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
