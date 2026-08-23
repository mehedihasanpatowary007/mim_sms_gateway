import ast
import json
import logging

_logger = logging.getLogger(__name__)


def _parse_legacy(value):
    if value in (None, False):
        return value
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return str(value)

    stripped = value.strip()
    if not stripped:
        return value

    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(stripped)
        except (ValueError, TypeError, SyntaxError, json.JSONDecodeError):
            continue
        if isinstance(parsed, (dict, str)) and parsed != value:
            return parsed
    return value


def _plain_text(value):
    value = _parse_legacy(value)
    if isinstance(value, dict):
        for key in ('en_US', 'en_GB'):
            if value.get(key) not in (None, False):
                return _plain_text(value[key])
        for item in value.values():
            if item not in (None, False):
                return _plain_text(item)
        return ''
    if value in (None, False):
        return ''
    return str(value)


def _translation_payload(value):
    value = _parse_legacy(value)
    if isinstance(value, dict):
        result = {}
        for lang, text in value.items():
            result[str(lang)] = _plain_text(text)
        if 'en_US' not in result and result:
            result['en_US'] = next(iter(result.values()))
        return result or {'en_US': ''}
    return {'en_US': _plain_text(value)}


def migrate(cr, version):
    # Normalize template body after the field has been aligned with Odoo's
    # translated JSONB storage. This also repairs text values that previously
    # contained a Python/JSON dict representation.
    cr.execute("""
        SELECT data_type
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'sms_template'
           AND column_name = 'body'
    """)
    row = cr.fetchone()
    body_type = row[0] if row else None

    if body_type:
        cr.execute('SELECT id, body FROM sms_template')
        templates = cr.fetchall()
        for template_id, body in templates:
            payload = _translation_payload(body)
            if body_type == 'jsonb':
                cr.execute(
                    'UPDATE sms_template SET body = %s::jsonb WHERE id = %s',
                    [json.dumps(payload), template_id],
                )
            else:
                cr.execute(
                    'UPDATE sms_template SET body = %s WHERE id = %s',
                    [_plain_text(payload), template_id],
                )
        _logger.info('Normalized %s SMS template bodies', len(templates))

    # Existing history entries may already contain "{'en_US': '...'}".
    cr.execute('SELECT id, message FROM sms_history')
    histories = cr.fetchall()
    fixed = 0
    for history_id, message in histories:
        normalized = _plain_text(message)
        if normalized != (message or ''):
            cr.execute(
                'UPDATE sms_history SET message = %s WHERE id = %s',
                [normalized, history_id],
            )
            fixed += 1
    _logger.info('Normalized %s SMS history messages', fixed)
