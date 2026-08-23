import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Copy the accidentally shared core table before foreign keys are rebuilt."""
    cr.execute("SELECT to_regclass('sms_template')")
    if not cr.fetchone()[0]:
        return

    cr.execute("""
        CREATE TABLE IF NOT EXISTS mimsms_template
        (LIKE sms_template INCLUDING ALL)
    """)
    cr.execute("CREATE SEQUENCE IF NOT EXISTS mimsms_template_id_seq")
    cr.execute("ALTER SEQUENCE mimsms_template_id_seq OWNED BY mimsms_template.id")
    cr.execute("""
        ALTER TABLE mimsms_template
        ALTER COLUMN id SET DEFAULT nextval('mimsms_template_id_seq')
    """)
    cr.execute("""
        SELECT source.column_name
          FROM information_schema.columns source
          JOIN information_schema.columns target
            ON target.table_schema = source.table_schema
           AND target.table_name = 'mimsms_template'
           AND target.column_name = source.column_name
         WHERE source.table_schema = current_schema()
           AND source.table_name = 'sms_template'
         ORDER BY source.ordinal_position
    """)
    columns = [row[0] for row in cr.fetchall()]
    if columns:
        quoted = ', '.join('"%s"' % column.replace('"', '""') for column in columns)
        selected = ', '.join(
            'source."%s"' % column.replace('"', '""') for column in columns
        )
        reference_filters = []
        for table in ('sms_history', 'sms_queue'):
            cr.execute('SELECT to_regclass(%s)', [table])
            if cr.fetchone()[0]:
                reference_filters.append(
                    ' OR EXISTS (SELECT 1 FROM %s linked '
                    'WHERE linked.template_id = source.id)' % table
                )
        cr.execute(
            'INSERT INTO mimsms_template (%s) '
            'SELECT %s FROM sms_template source '
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM ir_model_data data "
            "WHERE data.model = 'sms.template' "
            "AND data.res_id = source.id "
            "AND data.module <> 'mimsms_gateway'"
            ')%s ON CONFLICT (id) DO NOTHING'
            % (quoted, selected, ''.join(reference_filters))
        )

    xml_names = (
        'sms_template_invoice_generated',
        'sms_template_payment_received',
        'sms_template_delivery',
        'sms_template_invoice_overdue',
        'sms_template_monthly_closing',
    )
    cr.execute("""
        UPDATE ir_model_data
           SET model = 'mimsms.template'
         WHERE module = 'mimsms_gateway'
           AND name IN %s
    """, [xml_names])
    _logger.info('Copied legacy MiMSMS templates into the isolated model table')
