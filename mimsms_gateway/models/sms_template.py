from odoo import api, fields, models, _
import ast
import json
import re
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class SmsTemplate(models.Model):
    _name = 'mimsms.template'
    _description = 'MiMSMS Template'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True, translate=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    template_type = fields.Selection([
        ('general', 'General'),
        ('invoice', 'Invoice Generated'),
        ('payment', 'Payment Received'),
        ('delivery', 'Customer Delivery'),
        ('overdue', 'Invoice Overdue'),
        ('monthly', 'Monthly Closing'),
    ], string='Purpose', required=True, default='general', index=True)
    model_id = fields.Many2one(
        'ir.model',
        string='Applies to',
        required=True,
        ondelete='cascade',
        domain=[('transient', '=', False)],
        help='The type of document this template can be used with'
    )
    model = fields.Char(
        string='Model',
        related='model_id.model',
        store=True,
        readonly=True,
        help='Technical name of the model'
    )
    body = fields.Text(
        string='Message Body',
        required=True,
        translate=True,
        help='Use {{field_name}} for dynamic content. Example: Hello {{name}}!'
    )
    active = fields.Boolean(string='Active', default=True)
    usage_count = fields.Integer(string='Times Used', default=0, readonly=True)
    last_used = fields.Datetime(string='Last Used', readonly=True)

    _CUSTOM_PLACEHOLDERS = {
        'partner_name', 'month_name', 'opening_outstanding',
        'monthly_invoice_amount', 'monthly_payment', 'closing_outstanding',
    }
    
    sample_preview = fields.Text(
        string='Sample Preview',
        compute='_compute_sample_preview',
        store=False,
        help='Preview of the template with sample data'
    )

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.setdefault('name', _('%s (Copy)') % self.name)
        default.setdefault('active', False)
        return super().copy(default)
    
    @api.depends('model_id', 'body')
    def _compute_sample_preview(self):
        """Generate a sample preview of the template"""
        for template in self:
            template.sample_preview = ''  # Initialize with empty string
            
            if not template.model or not template.body:
                continue
                
            try:
                # Check if model exists in registry
                if template.model not in self.env:
                    template.sample_preview = 'Model not found in system.'
                    continue
                    
                # Search for a sample record
                sample_record = self.env[template.model].search([], limit=1)
                
                if not sample_record:
                    template.sample_preview = 'No sample data available for preview.'
                    continue
                
                # Render the template
                rendered = template._render_preview(sample_record)
                template.sample_preview = rendered or 'Preview generated successfully'
                
            except Exception as e:
                _logger.error(f"Failed to compute sample preview for template {template.id}: {str(e)}")
                template.sample_preview = f'Error generating preview: {str(e)}'
    
    @api.model
    def _coerce_body_text(self, value):
        """Return a plain SMS string from translated/legacy template values.

        Older deployments may contain a translated JSON value (or its string
        representation) while the Python field is read as a normal Text field.
        That leaks values such as ``{'en_US': 'Dear ...'}`` to the web client and
        API. Keep this method defensive so rendering/sending always receives text.
        """
        if value in (None, False):
            return ''

        if isinstance(value, dict):
            lang = self.env.lang or 'en_US'
            for key in (lang, 'en_US'):
                text = value.get(key)
                if text not in (None, False):
                    return self._coerce_body_text(text)
            for text in value.values():
                if text not in (None, False):
                    return self._coerce_body_text(text)
            return ''

        if isinstance(value, str):
            stripped = value.strip()
            if stripped and stripped[0] in '{[\"\'':
                for loader in (json.loads, ast.literal_eval):
                    try:
                        parsed = loader(stripped)
                    except (ValueError, TypeError, SyntaxError, json.JSONDecodeError):
                        continue
                    if parsed != value:
                        if isinstance(parsed, (dict, str)):
                            return self._coerce_body_text(parsed)
            return value

        return str(value)

    @api.constrains('body', 'model_id')
    def _check_body_placeholders(self):
        for template in self:
            template._validate_placeholders()

    @api.constrains('active', 'company_id', 'template_type')
    def _check_unique_automation_template(self):
        for template in self.filtered(lambda item: item.active and item.template_type != 'general'):
            if self.search_count([
                ('id', '!=', template.id),
                ('active', '=', True),
                ('company_id', '=', template.company_id.id),
                ('template_type', '=', template.template_type),
            ]):
                raise ValidationError(_(
                    'Only one active %s template is allowed for %s.'
                ) % (
                    dict(self._fields['template_type'].selection)[template.template_type],
                    template.company_id.display_name,
                ))

    @api.constrains('template_type', 'model_id')
    def _check_template_model(self):
        expected_models = {
            'invoice': 'account.move',
            'payment': 'account.payment',
            'delivery': 'stock.picking',
            'overdue': 'account.move',
            'monthly': 'res.partner',
        }
        for template in self:
            expected = expected_models.get(template.template_type)
            if expected and template.model != expected:
                raise ValidationError(_(
                    'The %s template must apply to model %s.'
                ) % (template.template_type, expected))

    def _validate_placeholders(self):
        """Reject malformed or unknown field paths before they reach customers."""
        self.ensure_one()
        body = self._coerce_body_text(self.body)
        token_pattern = re.compile(
            r'\{\{\s*(?:object\.)?([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}'
            r'|\$\{(?:object\.)?([a-zA-Z_][a-zA-Z0-9_.]*)\}'
        )
        matches = list(token_pattern.finditer(body))
        remainder = token_pattern.sub('', body)
        if '{{' in remainder or '}}' in remainder or '${' in remainder:
            raise ValidationError(_('The template contains a malformed placeholder.'))

        if not self.model or self.model not in self.env:
            return True
        invalid = []
        for match in matches:
            path = match.group(1) or match.group(2)
            if path in self._CUSTOM_PLACEHOLDERS:
                continue
            model = self.env[self.model]
            for index, part in enumerate(path.split('.')):
                field = model._fields.get(part)
                if not field:
                    invalid.append(path)
                    break
                if index < len(path.split('.')) - 1:
                    if field.type not in ('many2one', 'one2many', 'many2many'):
                        invalid.append(path)
                        break
                    model = self.env[field.comodel_name]
        if invalid:
            raise ValidationError(_(
                'Unknown template field(s): %s'
            ) % ', '.join(sorted(set(invalid))))
        return True

    @api.model
    def get_for_company(self, company, template_type, fallback_xmlid=None):
        template = self.search([
            ('company_id', '=', company.id),
            ('template_type', '=', template_type),
            ('active', '=', True),
        ], order='id', limit=1)
        if not template and fallback_xmlid:
            fallback = self.env.ref(fallback_xmlid, raise_if_not_found=False)
            if fallback and fallback.active and fallback.company_id == company:
                template = fallback
        if not template:
            raise UserError(_(
                'No active %s SMS template is configured for %s.'
            ) % (dict(self._fields['template_type'].selection).get(template_type), company.display_name))
        return template

    def _register_usage(self, count=1):
        """Update counters atomically because queue workers may finish together."""
        if not self or count <= 0:
            return
        self.env.cr.execute(
            'UPDATE mimsms_template '
            'SET usage_count = usage_count + %s, last_used = %s '
            'WHERE id IN %s',
            [count, fields.Datetime.now(), tuple(self.ids)],
        )
        self.invalidate_recordset(['usage_count', 'last_used'])

    def _replace_custom_placeholders(self, body, values):
        """Render custom monthly fields in both supported placeholder syntaxes."""
        rendered = self._coerce_body_text(body)
        for name, value in values.items():
            pattern = (
                r'\{\{\s*(?:object\.)?%s\s*\}\}'
                r'|\$\{(?:object\.)?%s\}'
            ) % (re.escape(name), re.escape(name))
            rendered = re.sub(pattern, str(value or ''), rendered)
        return rendered

    def _render_preview(self, record):
        self.ensure_one()
        if self.template_type != 'monthly':
            return self._render_template(self.body, record)
        return self._replace_custom_placeholders(self.body, {
            'partner_name': record.display_name,
            'month_name': fields.Date.context_today(self).strftime('%B %Y'),
            'opening_outstanding': '0.00',
            'monthly_invoice_amount': '0.00',
            'monthly_payment': '0.00',
            'closing_outstanding': '0.00',
        })

    @api.model
    def ensure_company_templates(self):
        """Keep the five client-approved templates for each target company."""
        company_templates = (
            ('Bridge Chemie', 'Bridge Chemie'),
            ('Bridge Industrial Technology', 'Bridge Industrial Technology'),
        )
        for company_match, footer in company_templates:
            companies = self.env['res.company'].sudo().search([
                ('name', 'ilike', company_match),
            ])
            for company in companies:
                definitions = (
                    (
                        'Invoice Generated', 'invoice', 'account.move',
                        'Dear ${object.partner_id.name}, your Invoice ${object.name} '
                        'for BDT ${object.amount_total} has been generated. Due Date: '
                        '${object.invoice_date_due}.\n%s' % footer,
                    ),
                    (
                        'Payment Received', 'payment', 'account.payment',
                        'Dear ${object.partner_id.name}, we have received your payment '
                        'of BDT ${object.amount} successfully. Ref: ${object.name}.\n%s' % footer,
                    ),
                    (
                        'Customer Delivery', 'delivery', 'stock.picking',
                        'Dear ${object.partner_id.name}, your Delivery ${object.name} '
                        'against Order ${object.origin} is ready for dispatch.\n%s' % footer,
                    ),
                    (
                        'Invoice Overdue', 'overdue', 'account.move',
                        'Dear ${object.partner_id.name}, payment of BDT '
                        '${object.amount_residual} for Invoice ${object.name} was due on '
                        '${object.invoice_date_due} and is now overdue. Please arrange '
                        'payment at your earliest convenience.\n%s' % footer,
                    ),
                    (
                        'Monthly Due', 'monthly', 'res.partner',
                        'Dear ${object.partner_name}, your account summary for '
                        '${object.month_name}: Opening Outstanding: BDT '
                        '${object.opening_outstanding}, Invoice Amount: BDT '
                        '${object.monthly_invoice_amount}, Payment Received: BDT '
                        '${object.monthly_payment}, Closing Outstanding: BDT '
                        '${object.closing_outstanding}.\n%s' % footer,
                    ),
                )
                for name, template_type, model_name, body in definitions:
                    template = self.sudo().search([
                        ('company_id', '=', company.id),
                        ('template_type', '=', template_type),
                    ], order='active desc, id', limit=1)
                    values = {
                        'name': name,
                        'company_id': company.id,
                        'template_type': template_type,
                        'model_id': self.env['ir.model']._get(model_name).id,
                        'body': body,
                        'active': True,
                    }
                    if template:
                        template.write(values)
                    else:
                        self.sudo().create(values)
        return True

    def _render_template(self, body, record):
        """Render template with record values using safe field substitution."""
        body = self._coerce_body_text(body)
        if not body or not record:
            return ''
            
        try:
            # Accept the user-friendly {{field}} syntax and normalize it to
            # Odoo's ${object.field} syntax before using the render engine.
            body = re.sub(
                r'\{\{\s*(?:object\.)?([a-zA-Z0-9_.]+)\s*\}\}',
                lambda match: '${object.%s}' % match.group(1),
                body,
            )
            # SMS templates deliberately support field substitution only. This
            # keeps rendering predictable and avoids executing expressions.
            rendered = self._simple_render(body, record)
            return rendered.strip() if rendered else ''
            
        except Exception as e:
            _logger.error(f"Failed to render template: {str(e)}")
            # Fallback to simple rendering
            return self._simple_render(body, record)
    
    def _simple_render(self, body, record):
        """Simple fallback rendering without QWeb"""
        try:
            rendered = self._coerce_body_text(body)
            
            # Match ${object.field_name} or ${field_name}
            pattern = r'\$\{(object\.)?([a-zA-Z0-9_.]+)\}'
            
            def replace_field(match):
                field_name = match.group(2)
                return self._get_field_value(record, field_name)
            
            return re.sub(pattern, replace_field, rendered)
            
        except Exception as e:
            _logger.error(f"Simple render failed: {str(e)}")
            return body
    
    def _get_field_value(self, record, field_name):
        """Get field value from record"""
        try:
            # Handle dot notation for related fields
            if '.' in field_name:
                parts = field_name.split('.')
                value = record
                for part in parts:
                    if not value:
                        return ''
                    if hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        return f"${{object.{field_name}}}"
            else:
                if not hasattr(record, field_name):
                    return f"${{object.{field_name}}}"
                value = getattr(record, field_name)
            
            # Handle False/None values
            if value is False or value is None:
                return ''
            
            # Format value based on type
            if hasattr(value, 'name'):
                return str(value.name)
            elif hasattr(value, 'strftime'):
                return value.strftime('%d/%m/%Y')
            elif isinstance(value, bool):
                return 'Yes' if value else 'No'
            elif isinstance(value, float):
                return f"{value:.2f}"
            elif isinstance(value, (int, str)):
                return str(value)
            else:
                return str(value)
                
        except Exception as e:
            _logger.warning(f"Failed to get field value for {field_name}: {str(e)}")
            return f"${{object.{field_name}}}"
    
    def action_test_template(self):
        """Test the template with a sample record"""
        self.ensure_one()
        
        if not self.model:
            raise UserError(_('Please select a model first'))
        
        try:
            # Check if model exists
            if self.model not in self.env:
                raise UserError(_('The selected model does not exist in the system.'))
            
            # Get a sample record
            sample_record = self.env[self.model].search([], limit=1)
            
            if not sample_record:
                raise UserError(_('No sample data available for this model.'))
            
            # Render the template
            rendered = self._render_preview(sample_record)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Template Preview'),
                    'message': rendered,
                    'type': 'info',
                    'sticky': True,
                }
            }
            
        except UserError:
            raise
        except Exception as e:
            _logger.error(f"Template test failed: {str(e)}")
            raise UserError(_('Template test failed: %s') % str(e))
