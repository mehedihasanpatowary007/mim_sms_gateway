{
    'name': 'MiMSMS Gateway',
    'version': '19.0.1.0.0',
    'category': 'Marketing/SMS Marketing',
    'summary': 'Send SMS via MiMSMS API - Single, Bulk & Template Support',
    'description': """
        MiMSMS SMS Gateway Integration
        ================================
        * Send single SMS to contacts
        * Send bulk SMS to multiple contacts
        * SMS templates management
        * Integration with CRM and Contacts
        * Check SMS balance
        * SMS history tracking
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'crm',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sms_template_data.xml',
        'views/mimsms_config_views.xml',
        'views/sms_template_views.xml',
        'views/sms_history_views.xml',
        # 'views/res_partner_views.xml',
        # 'views/crm_lead_views.xml',
        'wizard/sms_composer_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mimsms_gateway/static/src/xml/chatter_sms_template.xml',
            'mimsms_gateway/static/src/js/chatter_sms.js',
        ],
    },  # <-- This closing brace and comma were missing!
    'installable': True,
    'application': True,
    'auto_install': False,
}