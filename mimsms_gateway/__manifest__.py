{
    'name': 'MiMSMS Gateway',
    'version': '19.0.1.0.0',
    'category': 'Bridge Chemie',
    'summary': 'Send SMS via MiMSMS API - Single, Bulk & Template Support',
    'description': """
        MiMSMS SMS Gateway Integration
        ================================
        * Manual invoice and delivery SMS with preview
        * Automatic payment, overdue, and monthly closing SMS
        * Company-specific and global gateway configuration
        * SMS templates management
        * Check SMS balance
        * SMS history tracking
    """,
    'author': 'Zencore Solutions Ltd',
    'website': 'https://www.zencoreltd.com',
    'images': ['static/description/icon.png'],
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'mail',
        'account',
        'stock',
    ],
    'data': [
        'security/sms_gateway_security.xml',
        'security/ir.model.access.csv',
        'data/sms_automation_data.xml',
        'views/mimsms_config_views.xml',
        'views/sms_template_views.xml',
        'views/sms_history_views.xml',
        'views/account_move_views.xml',
        'views/stock_picking_views.xml',
        'views/res_partner_views.xml',
        'wizard/sms_composer_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mimsms_gateway/static/src/scss/mimsms_backend.scss',
            'mimsms_gateway/static/src/xml/chatter_sms_template.xml',
            'mimsms_gateway/static/src/js/chatter_sms.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
