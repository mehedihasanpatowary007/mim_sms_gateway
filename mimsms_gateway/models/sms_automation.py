import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


_logger = logging.getLogger(__name__)


class SmsAutomation(models.AbstractModel):
    _name = 'sms.automation'
    _description = 'SMS Automation Service'

    @api.model
    def _normalize_phone(self, phone):
        return self.env['mimsms.composer']._normalize_phone_number(phone)

    @api.model
    def _partner_mobile(self, partner):
        partner = partner.commercial_partner_id
        mobile = partner['mobile'] if 'mobile' in partner._fields else False
        phone = partner['phone'] if 'phone' in partner._fields else False
        return self._normalize_phone(mobile or phone)

    @api.model
    def _send(self, *, partner, message, event_key, event_type, company,
              source=None, template=None):
        """Send one duplicate-safe automatic SMS without blocking business flows."""
        History = self.env['sms.history'].sudo()
        if History.search_count([('event_key', '=', event_key)]):
            return False

        mobile = self._partner_mobile(partner)
        history = History.create_history(
            mobile=mobile or 'N/A',
            message=message,
            partner_id=partner.commercial_partner_id.id,
            template_id=template.id if template else False,
            status='draft',
            company_id=company.id,
            res_model=source._name if source else False,
            res_id=source.id if source else False,
            event_type=event_type,
            event_key=event_key,
        )
        if not mobile:
            history.write({'status': 'skipped', 'error_message': _('Customer has no mobile or phone number.')})
            return False

        config = self.env['mimsms.config'].get_active_config(company=company, raise_if_missing=False)
        if not config:
            history.write({
                'status': 'skipped',
                'error_message': _('No active SMS Gateway configuration was found for %s.') % company.display_name,
            })
            return False

        try:
            response = config.send_sms(mobile, message)
            success = str(response.get('statusCode')) == '200'
            history.write({
                'status': 'sent' if success else 'failed',
                'response_code': response.get('statusCode'),
                'response_message': response.get('statusMessage'),
                'api_response': str(response),
                'sent_date': fields.Datetime.now() if success else False,
                'error_message': False if success else response.get('statusMessage'),
            })
            return success
        except Exception as error:
            history.write({'status': 'failed', 'error_message': str(error)})
            _logger.exception('Automatic SMS failed for event %s', event_key)
            return False

    @api.model
    @api.private
    def _cron_send_monthly_closing(self):
        today = fields.Date.context_today(self)
        if today.day != 1:
            return

        month_start = today - relativedelta(months=1)
        month_end = today - relativedelta(days=1)
        month_label = month_start.strftime('%B %Y')
        template = self.env.ref('mimsms_gateway.sms_template_monthly_closing')

        for company in self.env['res.company'].sudo().search([]):
            self.env.cr.execute("""
                SELECT partner.commercial_partner_id,
                       COALESCE(SUM(CASE WHEN line.date < %s THEN line.balance ELSE 0 END), 0) AS opening,
                       COALESCE(SUM(line.balance), 0) AS closing
                  FROM account_move_line line
                  JOIN account_move move ON move.id = line.move_id
                  JOIN account_account account ON account.id = line.account_id
                  JOIN res_partner partner ON partner.id = line.partner_id
                 WHERE move.state = 'posted'
                   AND account.account_type = 'asset_receivable'
                   AND line.company_id = %s
                   AND line.date <= %s
                 GROUP BY partner.commercial_partner_id
            """, [month_start, company.id, month_end])
            balances = {
                partner_id: {'opening': float(opening), 'closing': float(closing)}
                for partner_id, opening, closing in self.env.cr.fetchall()
            }

            invoices = self.env['account.move'].sudo().search([
                ('company_id', '=', company.id),
                ('state', '=', 'posted'),
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('invoice_date', '>=', month_start),
                ('invoice_date', '<=', month_end),
            ])
            invoice_totals = {}
            for invoice in invoices:
                partner_id = invoice.partner_id.commercial_partner_id.id
                sign = -1 if invoice.move_type == 'out_refund' else 1
                invoice_totals[partner_id] = invoice_totals.get(partner_id, 0.0) + sign * abs(invoice.amount_total_signed)

            partner_ids = set(balances) | set(invoice_totals)
            for partner in self.env['res.partner'].sudo().browse(partner_ids).exists():
                values = balances.get(partner.id, {'opening': 0.0, 'closing': 0.0})
                opening = values['opening']
                invoiced = invoice_totals.get(partner.id, 0.0)
                closing = values['closing']
                paid = opening + invoiced - closing
                if not any(abs(value) >= 0.005 for value in (opening, invoiced, paid, closing)):
                    continue
                replacements = {
                    '{{partner_name}}': partner.name or '',
                    '{{month_name}}': month_label,
                    '{{opening_outstanding}}': f'{opening:,.2f}',
                    '{{monthly_invoice_amount}}': f'{invoiced:,.2f}',
                    '{{monthly_payment}}': f'{paid:,.2f}',
                    '{{closing_outstanding}}': f'{closing:,.2f}',
                }
                message = template.body
                for token, value in replacements.items():
                    message = message.replace(token, value)
                self._send(
                    partner=partner,
                    message=message,
                    event_key=f'monthly:{company.id}:{partner.id}:{month_start:%Y-%m}',
                    event_type='monthly',
                    company=company,
                    source=partner,
                    template=template,
                )
