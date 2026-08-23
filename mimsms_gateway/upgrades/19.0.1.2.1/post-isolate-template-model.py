import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT res_id
          FROM ir_model_data
         WHERE module = 'base' AND name = 'main_company'
         LIMIT 1
    """)
    row = cr.fetchone()
    main_company_id = row[0] if row else None
    if main_company_id:
        cr.execute(
            'UPDATE mimsms_template SET company_id = %s WHERE company_id IS NULL',
            [main_company_id],
        )

    template_types = {
        'sms_template_invoice_generated': 'invoice',
        'sms_template_payment_received': 'payment',
        'sms_template_delivery': 'delivery',
        'sms_template_invoice_overdue': 'overdue',
        'sms_template_monthly_closing': 'monthly',
    }
    for xml_name, template_type in template_types.items():
        cr.execute("""
            UPDATE mimsms_template
               SET template_type = %s
             WHERE id = (
                SELECT res_id
                  FROM ir_model_data
                 WHERE module = 'mimsms_gateway' AND name = %s
                 LIMIT 1
             )
        """, [template_type, xml_name])

    cr.execute("SELECT pg_get_serial_sequence('mimsms_template', 'id')")
    sequence = cr.fetchone()[0]
    if sequence:
        cr.execute(
            "SELECT setval(%s, GREATEST(COALESCE((SELECT MAX(id) FROM mimsms_template), 1), 1))",
            [sequence],
        )

    cr.execute("""
        DELETE FROM ir_model_access
         WHERE id IN (
            SELECT res_id
              FROM ir_model_data
             WHERE module = 'mimsms_gateway'
               AND name = 'access_sms_template_user'
               AND model = 'ir.model.access'
         )
    """)
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'mimsms_gateway'
           AND name = 'access_sms_template_user'
           AND model = 'ir.model.access'
    """)
    _logger.info('Completed MiMSMS template model isolation')
