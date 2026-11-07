import re


# Timestamp-only lines (ISO 8601 with microseconds and timezone offset)
# e.g. 2026-11-03 12:47:37.895945+01:00
TIMESTAMP_ONLY_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2}$'
)

# Docker log timestamp prefix: 2026-11-07T12:47:37.895945+01:00 <message>
# Docker may also use 'Z' for UTC: 2026-11-07T15:03:23.887196000Z <message>
# When timestamps=True, each log line starts with this prefix followed by a space
DOCKER_TIMESTAMP_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z))\s'
)

# Application-level timestamp prefixes to strip from messages
# Gunicorn: [2026-11-03 08:51:05 +0000] ...
# Django: [2026-11-03 10:07:37,854] ...
APP_TIMESTAMP_RE = re.compile(r'^\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[^\]]*\]\s*')

# After the application timestamp is stripped, the remaining message may start with
# optional PID and level brackets, e.g. "[1] [INFO] Starting gunicorn" or "[INFO] message"
MSG_LINE_RE = re.compile(
    r'(?:\[(?P<pid>\d+)\]\s+)?'
    r'(?:\[(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG)\]\s+)?'
    r'(?P<message>.*)',
    re.IGNORECASE,
)

# Date and time extraction for display
# Matches YYYY-MM-DD HH:MM:SS from various timestamp formats (including ISO 8601 with T separator)
DATETIME_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})[T\s]+(\d{2}:\d{2}:\d{2})')

MONTH_ABBR = {
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


def format_timestamp(raw):
    """Format a raw timestamp string for compact display.
    Returns a shortened version showing date and time, e.g. '03 Nov 08:51:05'.
    """
    if not raw:
        return ''
    match = DATETIME_RE.search(raw)
    if match:
        _, month, day, time = match.groups()
        month_str = MONTH_ABBR.get(month, month)
        # Strip trailing zeros from day for compactness
        day_int = int(day)
        return f'{day_int} {month_str} {time}'
    # Fallback: return raw
    return raw


def parse_log_line(line):
    """Parse a single Docker log line into structured data.

    Expects a raw line from Docker logs with timestamps=True, i.e. prefixed with
    Docker's ISO 8601 timestamp. Extracts the Docker timestamp, strips any
    application-level timestamp, and parses the remaining message for level, PID, etc.

    Returns a dict with timestamp, level, pid, message, and is_continuation fields.
    """
    line = line.rstrip('\r\n')
    if not line:
        return None

    # Extract Docker's internal timestamp from the beginning of the line
    docker_ts_match = DOCKER_TIMESTAMP_RE.match(line)
    docker_timestamp = ''
    message_part = line
    if docker_ts_match:
        docker_timestamp = docker_ts_match.group(1)
        message_part = line[docker_ts_match.end() :]

    # Strip application-level timestamp from the message
    message_part = APP_TIMESTAMP_RE.sub('', message_part)

    # Check if it's a stack trace / continuation line (starts with whitespace or traceback pattern)
    if message_part.startswith((' ', '\t', 'Traceback', 'File "', '  ')):
        return {
            'timestamp': docker_timestamp,
            'level': 'TRACE',
            'pid': '',
            'message': message_part,
            'is_continuation': True,
        }

    # Check if it's a timestamp-only line (health check, log flush, keep-alive)
    if TIMESTAMP_ONLY_RE.match(message_part):
        return {
            'timestamp': docker_timestamp,
            'level': 'HEARTBEAT',
            'pid': '',
            'message': '',
            'is_continuation': False,
        }

    # Try the message-level regex for PID and level (after timestamp stripped)
    match = MSG_LINE_RE.match(message_part)
    if match and (match.group('level') or match.group('pid')):
        level = match.group('level')
        return {
            'timestamp': docker_timestamp,
            'level': level.upper() if level else 'UNKNOWN',
            'pid': match.group('pid') or '',
            'message': match.group('message') or '',
            'is_continuation': False,
        }

    # Try Django format (level without brackets, e.g. "WARNING Not Found: /path")
    match = re.match(
        r'(?P<level>INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+(?P<message>.*)',
        message_part,
        re.IGNORECASE,
    )
    if match:
        return {
            'timestamp': docker_timestamp,
            'level': match.group('level').upper(),
            'pid': '',
            'message': match.group('message') or '',
            'is_continuation': False,
        }

    # Fallback: treat as unknown level
    return {
        'timestamp': docker_timestamp,
        'level': 'UNKNOWN',
        'pid': '',
        'message': message_part,
        'is_continuation': False,
    }
