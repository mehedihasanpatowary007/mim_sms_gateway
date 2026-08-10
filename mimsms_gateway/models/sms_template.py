from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html2plaintext
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class SmsTemplate(models.Model):
    _name = 'sms.template'
    _description = 'SMS Template'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True)
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
        help='Use ${object.field_name} for dynamic content. Example: Hello ${object.name}!'
    )
    active = fields.Boolean(string='Active', default=True)
    usage_count = fields.Integer(string='Times Used', default=0, readonly=True)
    last_used = fields.Datetime(string='Last Used', readonly=True)
    
    sample_preview = fields.Text(
        string='Sample Preview',
        compute='_compute_sample_preview',
        store=False,
        help='Preview of the template with sample data'
    )
    
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
                rendered = template._render_template(template.body, sample_record)
                template.sample_preview = rendered or 'Preview generated successfully'
                
            except Exception as e:
                _logger.error(f"Failed to compute sample preview for template {template.id}: {str(e)}")
                template.sample_preview = f'Error generating preview: {str(e)}'
    
    def _render_template(self, body, record):
        """Render template with record values using Odoo's rendering engine"""
        if not body or not record:
            return ''
            
        try:
            # Use Odoo's standard template rendering with 'object' variable
            # This supports ${object.field_name} syntax
            rendered = self.env['mail.render.mixin']._render_template(
                body,
                record._name,
                record.ids,
                post_process=True
            )[record.id]
            
            # Convert to plain text if HTML
            if rendered and '<' in rendered:
                rendered = html2plaintext(rendered)
            
            return rendered.strip() if rendered else ''
            
        except Exception as e:
            _logger.error(f"Failed to render template: {str(e)}")
            # Fallback to simple rendering
            return self._simple_render(body, record)
    
    def _simple_render(self, body, record):
        """Simple fallback rendering without QWeb"""
        try:
            import re
            rendered = body
            
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
            rendered = self._render_template(self.body, sample_record)
            
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