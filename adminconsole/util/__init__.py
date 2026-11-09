import ast
import secrets
import string

import psutil


def generate_password():
    return ''.join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(20)
    )


def generate_secret_key():
    choice = string.ascii_letters
    choice = choice + string.digits
    choice = choice + string.punctuation
    return ''.join(secrets.choice(choice) for _ in range(50))


def pid_finished(pid):
    """
    True if the process has ended. Processes not started by the console (same user, `-m manage`) also count as
    ended, so the answer reveals nothing about other processes on the server.
    """
    try:
        process = psutil.Process(int(pid))
        if process.status() == psutil.STATUS_ZOMBIE:
            return True
        return (
            process.username() != psutil.Process().username()
            or 'manage' not in process.cmdline()
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True


def _is_sensitive_key(key):
    """Check if a key name contains sensitive patterns."""
    sensitive_patterns = {'SECRET', 'PASSWORD'}
    return any(pattern in str(key).upper() for pattern in sensitive_patterns)


def _mask_value(value, secret_values=None):
    """Return a masked representation of a value, recursively handling nested structures.

    Args:
        value: The value to mask.
        secret_values: A set of string values that should be masked if found as substrings.
    """
    if secret_values is None:
        secret_values = set()
    if isinstance(value, dict):
        masked = {}
        for k, v in value.items():
            if _is_sensitive_key(k):
                masked[k] = '****'
            else:
                masked[k] = _mask_value(v, secret_values)
        return masked
    elif isinstance(value, (list, tuple)):
        masked = [_mask_value(item, secret_values) for item in value]
        return type(value)(masked)
    elif isinstance(value, str):
        masked = value
        for secret in secret_values:
            masked = masked.replace(secret, '****')
        return masked
    else:
        return value


def parse_log_file(app):
    """Parse the log file of an app into sections with summaries."""
    from adminconsole.util.log_summary import build_summary, build_header_summary

    sections = {'Log': {'text': '', 'result': 1}}
    current = sections['Log']  # capture error output before the first section
    with open(app.log_file, 'r') as file:
        while line := file.readline():
            line = line.strip()
            if line.startswith('# '):
                line = line[2:]
                if line not in sections:
                    sections[line] = {'text': '', 'result': 1}
                current = sections[line]
            elif line.startswith('Return '):
                try:
                    current['result'] = int(line[7:])
                except ValueError:
                    pass
            else:
                if line[:2] in ['b"', "b'"]:
                    current['text'] += str(ast.literal_eval(line), 'utf-8')
                else:
                    current['text'] += line
                current['text'] += '\n'
    if not sections['Log']['text']:
        del sections['Log']

    # Build summaries for each section
    for section_name, section in sections.items():
        section['summary'] = build_summary(
            section['text'], section['result'], section_name
        )
        section['header_summary'] = build_header_summary(
            section['text'], section['result'], section_name
        )

    return sections
