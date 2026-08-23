from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMimsmsGateway(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env['mimsms.config'].sudo().search([]).write({'active': False})
        cls.config = cls.env['mimsms.config'].create({
            'username': 'test@example.com',
            'apikey': 'test-secret',
            'sender_id': 'TEST',
            'company_ids': [(6, 0, cls.company.ids)],
            'retry_delay_minutes': 1,
            'max_sms_parts': 2,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'SMS Test Customer',
            'mobile': '01712-345678',
            'company_id': cls.company.id,
        })

    def test_bangladesh_phone_validation(self):
        composer = self.env['mimsms.composer']
        valid_numbers = {
            '01712345678': '8801712345678',
            '+8801712345678': '8801712345678',
            '008801712345678': '8801712345678',
            '1712345678': '8801712345678',
            '(017) 1234-5678': '8801712345678',
        }
        for value, expected in valid_numbers.items():
            self.assertEqual(composer._normalize_phone_number(value), expected)
        for value in ('017123', '01212345678', '8801212345678', 'abc01712345678'):
            self.assertFalse(composer._normalize_phone_number(value))

    def test_message_parts_and_unresolved_placeholder_validation(self):
        composer = self.env['mimsms.composer']
        self.assertEqual(composer._sms_metrics('a' * 160)[1], 1)
        self.assertEqual(composer._sms_metrics('a' * 161)[1], 2)
        self.assertEqual(composer._sms_metrics('\u09ac' * 71)[1], 2)
        with self.assertRaises(UserError):
            composer._validate_outbound_message('Hello {{name}}', self.company)
        with self.assertRaises(UserError):
            composer._validate_outbound_message('a' * 307, self.company)

    def test_template_field_validation_and_company_resolution(self):
        partner_model = self.env['ir.model']._get('res.partner')
        template = self.env['mimsms.template'].create({
            'name': 'Company greeting',
            'company_id': self.company.id,
            'template_type': 'general',
            'model_id': partner_model.id,
            'body': 'Dear {{name}}, welcome.',
        })
        self.assertEqual(template._render_template(template.body, self.partner),
                         'Dear SMS Test Customer, welcome.')
        with self.assertRaises(ValidationError):
            self.env['mimsms.template'].create({
                'name': 'Invalid template',
                'company_id': self.company.id,
                'template_type': 'general',
                'model_id': partner_model.id,
                'body': 'Dear {{unknown_field}}, welcome.',
            })

    def test_retry_stops_after_two_retries(self):
        queue = self.env['sms.queue'].enqueue(
            mobile='8801712345678', message='Retry test',
            record=self.partner, send_mode='dynamic',
        )
        failure = {'statusCode': '500', 'statusMessage': 'Temporary failure'}
        queue._apply_response(failure, retry_delay_minutes=1)
        self.assertEqual((queue.state, queue.attempts), ('queued', 1))
        queue._apply_response(failure, retry_delay_minutes=1)
        self.assertEqual((queue.state, queue.attempts), ('queued', 2))
        queue._apply_response(failure, retry_delay_minutes=1)
        self.assertEqual((queue.state, queue.attempts), ('failed', 3))
        self.assertFalse(queue.next_attempt_at)
        self.assertEqual(queue.history_id.status, 'failed')

    def test_duplicate_recipients_keep_separate_results(self):
        first = self.env['sms.queue'].enqueue(
            mobile='8801712345678', message='Duplicate test',
            record=self.partner, send_mode='bulk',
        )
        second = self.env['sms.queue'].enqueue(
            mobile='8801712345678', message='Duplicate test',
            record=self.partner, send_mode='bulk',
        )
        (first | second)._apply_batch_response({
            'statusCode': '200',
            'statusMessage': 'Accepted',
            'responseResult': [
                {'MobNumber': '8801712345678', 'statusCode': '200'},
                {'MobNumber': '8801712345678', 'statusCode': '500',
                 'statusMessage': 'Rejected'},
            ],
        }, retry_delay_minutes=1)
        self.assertEqual(first.state, 'sent')
        self.assertEqual(second.state, 'queued')
        self.assertEqual(second.attempts, 1)

    def test_contacts_list_action_is_bound(self):
        action = self.env.ref('mimsms_gateway.action_contacts_send_mimsms')
        self.assertEqual(action.binding_model_id.model, 'res.partner')
        self.assertEqual(action.binding_view_types, 'list')
        self.assertIn(
            self.env.ref('mimsms_gateway.group_sms_gateway_user'),
            action.group_ids,
        )

    def test_odoo_core_sms_template_renderer_is_not_overridden(self):
        rendered = self.env['sms.template']._render_template(
            'Core SMS body', 'res.partner', self.partner.ids
        )
        self.assertEqual(rendered[self.partner.id], 'Core SMS body')

    def test_monthly_template_supports_object_syntax(self):
        partner_model = self.env['ir.model']._get('res.partner')
        template = self.env['mimsms.template'].create({
            'name': 'Monthly syntax test',
            'company_id': self.company.id,
            'template_type': 'general',
            'model_id': partner_model.id,
            'body': (
                'Dear ${object.partner_name}, ${object.month_name}: '
                '${object.closing_outstanding}'
            ),
        })
        rendered = template._replace_custom_placeholders(template.body, {
            'partner_name': 'Customer A',
            'month_name': 'July 2026',
            'closing_outstanding': '1,250.00',
        })
        self.assertEqual(rendered, 'Dear Customer A, July 2026: 1,250.00')
        self.assertNotIn('${object.', rendered)

    def test_five_templates_are_created_for_each_target_company(self):
        companies = self.env['res.company'].sudo().create([
            {'name': 'Bridge Chemie Test'},
            {'name': 'Bridge Industrial Technology Test'},
        ])
        self.env['mimsms.template'].ensure_company_templates()
        for company, footer in zip(
            companies, ('Bridge Chemie', 'Bridge Industrial Technology')
        ):
            templates = self.env['mimsms.template'].sudo().search([
                ('company_id', '=', company.id),
                ('active', '=', True),
                ('template_type', '!=', 'general'),
            ])
            self.assertEqual(len(templates), 5)
            self.assertEqual(
                set(templates.mapped('template_type')),
                {'invoice', 'payment', 'delivery', 'overdue', 'monthly'},
            )
            self.assertTrue(all(template.body.endswith(footer) for template in templates))
