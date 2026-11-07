import unittest

from adminconsole.util.log_parsing import (
    parse_log_line,
    format_timestamp,
)


# =============================================================================
# format_timestamp
# =============================================================================


class TestFormatTimestamp(unittest.TestCase):
    """Test timestamp formatting for compact display."""

    def test_iso_with_t_separator(self):
        self.assertEqual(
            format_timestamp('2026-11-07T12:47:37.895945+01:00'), '7 Nov 12:47:37'
        )

    def test_iso_with_z_utc(self):
        self.assertEqual(
            format_timestamp('2026-11-07T15:03:23.887196000Z'), '7 Nov 15:03:23'
        )

    def test_iso_with_space_separator(self):
        self.assertEqual(format_timestamp('2026-11-03 10:07:37.854'), '3 Nov 10:07:37')

    def test_single_digit_day(self):
        self.assertEqual(
            format_timestamp('2026-01-03T08:51:05+00:00'), '3 Jan 08:51:05'
        )

    def test_double_digit_day(self):
        self.assertEqual(format_timestamp('2026-12-25T00:00:00Z'), '25 Dez 00:00:00')

    def test_all_months(self):
        months = {
            '01': 'Jan',
            '02': 'Feb',
            '03': 'Mär',
            '04': 'Apr',
            '05': 'Mai',
            '06': 'Jun',
            '07': 'Jul',
            '08': 'Aug',
            '09': 'Sep',
            '10': 'Okt',
            '11': 'Nov',
            '12': 'Dez',
        }
        for month_num, expected in months.items():
            ts = f'2026-{month_num}-15T10:30:00Z'
            result = format_timestamp(ts)
            self.assertIn(expected, result, f'Month {month_num} should be {expected}')

    def test_empty_string(self):
        self.assertEqual(format_timestamp(''), '')

    def test_none(self):
        self.assertEqual(format_timestamp(None), '')

    def test_unrecognized_format_fallback(self):
        self.assertEqual(format_timestamp('yesterday'), 'yesterday')


# =============================================================================
# parse_log_line
# =============================================================================


class TestParseLogLineGunicorn(unittest.TestCase):
    """Test parsing of Gunicorn-format log lines with Docker timestamps."""

    def test_gunicorn_with_offset_timestamp(self):
        line = '2026-11-07T12:47:37.895945+01:00 [2026-11-07 12:47:37 +0000] [1] [INFO] Starting gunicorn 25.1.0'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T12:47:37.895945+01:00')
        self.assertEqual(result['level'], 'INFO')
        self.assertEqual(result['pid'], '1')
        self.assertEqual(result['message'], 'Starting gunicorn 25.1.0')
        self.assertFalse(result['is_continuation'])

    def test_gunicorn_with_z_utc_timestamp(self):
        line = '2026-11-07T15:03:23.887196000Z [2026-11-07 14:03:23 +0000] [7] [ERROR] Connection refused'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T15:03:23.887196000Z')
        self.assertEqual(result['level'], 'ERROR')
        self.assertEqual(result['pid'], '7')
        self.assertEqual(result['message'], 'Connection refused')

    def test_gunicorn_warning(self):
        line = '2026-11-07T12:00:00.000000+01:00 [2026-11-07 12:00:00 +0000] [3] [WARNING] Retrying in 1 second'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'WARNING')
        self.assertEqual(result['pid'], '3')
        self.assertEqual(result['message'], 'Retrying in 1 second')

    def test_gunicorn_critical(self):
        line = '2026-11-07T12:00:00+01:00 [2026-11-07 12:00:00 +0000] [1] [CRITICAL] Server crash'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'CRITICAL')

    def test_gunicorn_debug(self):
        line = '2026-11-07T12:00:00.123+01:00 [2026-11-07 12:00:00 +0000] [2] [DEBUG] Debug message'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'DEBUG')

    def test_gunicorn_without_docker_timestamp(self):
        line = '[2026-11-07 12:00:00 +0000] [5] [INFO] Worker ready'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '')
        self.assertEqual(result['level'], 'INFO')
        self.assertEqual(result['pid'], '5')
        self.assertEqual(result['message'], 'Worker ready')


class TestParseLogLineDjango(unittest.TestCase):
    """Test parsing of Django-format log lines."""

    def test_django_warning(self):
        line = '2026-11-07T10:07:37.123456+01:00 [2026-11-07 10:07:37,854] WARNING Not Found: /test'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T10:07:37.123456+01:00')
        self.assertEqual(result['level'], 'WARNING')
        self.assertEqual(result['message'], 'Not Found: /test')

    def test_django_info(self):
        line = '2026-11-07T10:07:37.123456+01:00 [2026-11-07 10:07:37,854] INFO Request completed'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'INFO')
        self.assertEqual(result['message'], 'Request completed')

    def test_django_error(self):
        line = '2026-11-07T10:07:37.123456+01:00 [2026-11-07 10:07:37,854] ERROR Database connection failed'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'ERROR')
        self.assertEqual(result['message'], 'Database connection failed')

    def test_django_without_docker_timestamp(self):
        line = '[2026-11-07 10:07:37,854] WARNING Not Found: /path'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'WARNING')
        self.assertEqual(result['message'], 'Not Found: /path')


class TestParseLogLineBareMessage(unittest.TestCase):
    """Test parsing of bare messages without standard log prefixes."""

    def test_bare_exception_message(self):
        line = "2026-11-07T15:03:23.887196000Z django.core.exceptions.DisallowedHost: Invalid HTTP_HOST header: 'svn.juntagrico.app'"
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T15:03:23.887196000Z')
        self.assertEqual(result['level'], 'UNKNOWN')
        self.assertEqual(result['pid'], '')
        self.assertIn('DisallowedHost', result['message'])
        self.assertFalse(result['is_continuation'])

    def test_bare_message_without_timestamp(self):
        line = 'Some random output'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '')
        self.assertEqual(result['level'], 'UNKNOWN')
        self.assertEqual(result['message'], 'Some random output')


class TestParseLogLineStackTraces(unittest.TestCase):
    """Test parsing of stack trace and continuation lines."""

    def test_traceback_with_docker_timestamp(self):
        line = '2026-11-07T15:03:23.887196000Z Traceback (most recent call last)'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T15:03:23.887196000Z')
        self.assertEqual(result['level'], 'TRACE')
        self.assertTrue(result['is_continuation'])

    def test_indented_continuation(self):
        line = '2026-11-07T15:03:23.887196000Z     File "/code/app/views.py", line 10'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'TRACE')
        self.assertTrue(result['is_continuation'])

    def test_file_quote_continuation(self):
        line = '2026-11-07T15:03:23.887196000Z File "/code/app/views.py", line 10'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'TRACE')
        self.assertTrue(result['is_continuation'])

    def test_tab_continuation(self):
        # Tab after Docker timestamp is consumed by the regex's \s anchor,
        # so the message starts with 'IndentationError' and is treated as UNKNOWN
        line = '2026-11-07T15:03:23.887196000Z\tIndentationError: expected indent'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T15:03:23.887196000Z')
        self.assertEqual(result['level'], 'UNKNOWN')
        self.assertFalse(result['is_continuation'])

    def test_traceback_without_docker_timestamp(self):
        line = 'Traceback (most recent call last)'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '')
        self.assertEqual(result['level'], 'TRACE')
        self.assertTrue(result['is_continuation'])

    def test_double_space_continuation(self):
        line = '  KeyError: "missing_key"'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'TRACE')
        self.assertTrue(result['is_continuation'])


class TestParseLogLineHeartbeat(unittest.TestCase):
    """Test parsing of timestamp-only heartbeat lines."""

    def test_heartbeat_with_docker_timestamp(self):
        line = '2026-11-07T12:47:37.895945+01:00 2026-11-03 12:47:37.895945+01:00'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T12:47:37.895945+01:00')
        self.assertEqual(result['level'], 'HEARTBEAT')
        self.assertEqual(result['message'], '')
        self.assertFalse(result['is_continuation'])

    def test_heartbeat_without_docker_timestamp(self):
        line = '2026-11-03 12:47:37.895945+01:00'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '')
        self.assertEqual(result['level'], 'HEARTBEAT')
        self.assertEqual(result['message'], '')


class TestParseLogLineEdgeCases(unittest.TestCase):
    """Test edge cases and special scenarios."""

    def test_empty_line(self):
        self.assertIsNone(parse_log_line(''))

    def test_whitespace_only_line(self):
        # A line with only spaces is treated as a continuation line (starts with space)
        result = parse_log_line('   ')
        self.assertEqual(result['level'], 'TRACE')
        self.assertTrue(result['is_continuation'])

    def test_newline_stripping(self):
        line = (
            '2026-11-07T12:00:00+01:00 [2026-11-07 12:00:00 +0000] [1] [INFO] Test\r\n'
        )
        result = parse_log_line(line)
        self.assertEqual(result['message'], 'Test')

    def test_docker_timestamp_without_microseconds(self):
        line = '2026-11-07T12:00:00+01:00 [2026-11-07 12:00:00 +0000] [1] [INFO] No microseconds'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T12:00:00+01:00')
        self.assertEqual(result['level'], 'INFO')

    def test_docker_timestamp_with_z_no_microseconds(self):
        line = '2026-11-07T12:00:00Z [2026-11-07 12:00:00 +0000] [1] [INFO] UTC no microseconds'
        result = parse_log_line(line)
        self.assertEqual(result['timestamp'], '2026-11-07T12:00:00Z')
        self.assertEqual(result['level'], 'INFO')

    def test_pid_only_no_level(self):
        line = '2026-11-07T12:00:00+01:00 [1] Some message without level'
        result = parse_log_line(line)
        self.assertEqual(result['pid'], '1')
        self.assertEqual(result['level'], 'UNKNOWN')
        self.assertEqual(result['message'], 'Some message without level')

    def test_level_only_no_pid(self):
        line = '2026-11-07T12:00:00+01:00 [WARNING] Message without pid'
        result = parse_log_line(line)
        self.assertEqual(result['pid'], '')
        self.assertEqual(result['level'], 'WARNING')
        self.assertEqual(result['message'], 'Message without pid')

    def test_neither_pid_nor_level(self):
        line = '2026-11-07T12:00:00+01:00 Just a plain message'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'UNKNOWN')
        self.assertEqual(result['pid'], '')
        self.assertEqual(result['message'], 'Just a plain message')

    def test_django_level_case_insensitive(self):
        line = '2026-11-07T12:00:00+01:00 warning lowercase level'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'WARNING')
        self.assertEqual(result['message'], 'lowercase level')

    def test_message_with_special_characters(self):
        line = '2026-11-07T12:00:00+01:00 [2026-11-07 12:00:00 +0000] [1] [ERROR] Failed: \'value\' & "other"'
        result = parse_log_line(line)
        self.assertEqual(result['level'], 'ERROR')
        self.assertIn('Failed', result['message'])
        self.assertIn('value', result['message'])


class TestParseLogLineIntegration(unittest.TestCase):
    """Integration tests: parse and format timestamps together."""

    def test_gunicorn_full_pipeline(self):
        line = '2026-11-07T12:47:37.895945+01:00 [2026-11-07 12:47:37 +0000] [1] [INFO] Starting gunicorn 25.1.0'
        result = parse_log_line(line)
        display = format_timestamp(result['timestamp'])
        self.assertEqual(display, '7 Nov 12:47:37')
        self.assertEqual(result['level'], 'INFO')

    def test_utc_z_full_pipeline(self):
        line = "2026-11-07T15:03:23.887196000Z django.core.exceptions.DisallowedHost: Invalid HTTP_HOST header: 'svn.juntagrico.app'"
        result = parse_log_line(line)
        display = format_timestamp(result['timestamp'])
        self.assertEqual(display, '7 Nov 15:03:23')
        self.assertEqual(result['level'], 'UNKNOWN')

    def test_continuation_timestamp_inherited(self):
        line = '2026-11-07T15:03:23.887196000Z     File "/code/app/views.py", line 10'
        result = parse_log_line(line)
        display = format_timestamp(result['timestamp'])
        self.assertEqual(display, '7 Nov 15:03:23')
        self.assertEqual(result['level'], 'TRACE')


if __name__ == '__main__':
    unittest.main()
