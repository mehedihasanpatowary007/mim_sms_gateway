# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class ContactChatterController(http.Controller):
    
    @http.route('/chatter_custom/send_sms', type='json', auth='user')
    def send_sms_action(self, model, res_id):
        """Function to open SMS composer for contact or CRM lead"""
        try:
            record = request.env[model].browse(int(res_id))
            
            if not record.exists():
                return {"error": True, "message": "Record not found"}
            
            # Get phone number based on model
            phone_number = False
            number_field_name = 'phone'
            
            if model == 'res.partner':
                # For contacts/partners - check if mobile field exists
                if hasattr(record, 'mobile') and record.mobile:
                    phone_number = record.mobile
                    number_field_name = 'mobile'
                elif record.phone:
                    phone_number = record.phone
                    number_field_name = 'phone'
                
            elif model == 'crm.lead':
                # For CRM leads - check phone field
                if record.phone:
                    phone_number = record.phone
                    number_field_name = 'phone'
                # If lead doesn't have phone, check the linked partner
                elif record.partner_id:
                    if hasattr(record.partner_id, 'mobile') and record.partner_id.mobile:
                        phone_number = record.partner_id.mobile
                        number_field_name = 'mobile'
                    elif record.partner_id.phone:
                        phone_number = record.partner_id.phone
                        number_field_name = 'phone'
            
            if not phone_number:
                return {
                    "error": True,
                    "message": "No phone number found for this record"
                }
            
            # Prepare SMS composer action
            action = {
                "type": "ir.actions.act_window",
                "name": "Send SMS",
                "res_model": "sms.composer",
                "view_mode": "form",
                "views": [[False, "form"]],
                "target": "new",
                "context": {
                    "default_composition_mode": "comment",
                    "default_res_model": model,
                    "default_res_id": int(res_id),
                    "default_number_field_name": number_field_name,
                    "active_model": model,
                    "active_id": int(res_id),
                    "active_ids": [int(res_id)],
                }
            }
            
            return {"success": True, "action": action}
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(f"Error opening SMS composer: {str(e)}")
            return {"error": True, "message": f"Error: {str(e)}"}