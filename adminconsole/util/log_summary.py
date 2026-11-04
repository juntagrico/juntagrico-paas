import re


# Word-boundary-aware error patterns: match "error" as a standalone word, not inside package names like "liberror-perl"
# These use \b for word boundaries to avoid false positives on package/library names
ERROR_WORD_RE = re.compile(r'\berror\b', re.IGNORECASE)
# Catch compound error names like "OperationalError", "TypeError" — but only after a dot (module path) or at line start
# to avoid false positives on package names like "liberror-perl"
ERROR_COMPOUND_RE = re.compile(r'(?:^|\.)([A-Z]\w*Error)\b')
FAILED_WORD_RE = re.compile(r'\bfailed\b', re.IGNORECASE)
FAILURE_WORD_RE = re.compile(r'\bfailure\b', re.IGNORECASE)
EXCEPTION_WORD_RE = re.compile(r'\bexception\b', re.IGNORECASE)
# Same for compound exception names like "ValueError", "KeyError"
EXCEPTION_COMPOUND_RE = re.compile(r'(?:^|\.)([A-Z]\w*Exception)\b')
TRACEBACK_WORD_RE = re.compile(r'\btraceback\b', re.IGNORECASE)
FATAL_WORD_RE = re.compile(r'\bfatal\b', re.IGNORECASE)
CRITICAL_WORD_RE = re.compile(r'\bcritical\b', re.IGNORECASE)
WARNING_WORD_RE = re.compile(r'\bwarning\b', re.IGNORECASE)
WARN_COLON_RE = re.compile(r'\bwarn:', re.IGNORECASE)
COULD_NOT_RE = re.compile(r'\bcould not\b', re.IGNORECASE)
REFUSED_WORD_RE = re.compile(r'\brefused\b', re.IGNORECASE)
DENIED_WORD_RE = re.compile(r'\bdenied\b', re.IGNORECASE)
TIMEOUT_WORD_RE = re.compile(r'\btimeout\b', re.IGNORECASE)
PERMISSION_DENIED_RE = re.compile(r'\bpermission denied\b', re.IGNORECASE)


def _is_error_line(line):
    """Check if a log line is a genuine error/warning, avoiding false positives on package names like 'liberror-perl'."""
    # Skip lines that look like apt/package manager output (e.g. "Get:29 ... liberror-perl ...")
    if re.match(r'^Get:\d+\s+', line):
        return False
    # Skip lines that look like package installation output
    if re.match(r'^(Selecting|Preparing to unpack|Unpacking|Setting up)\s+', line):
        return False
    # Skip lines that are just package lists (common in apt output, space-separated package names)
    stripped = line.strip()
    if stripped and not stripped[0].isupper() and ':' not in stripped and '(' not in stripped and '=' not in stripped:
        # Likely a package list line like "  git git-man libbrotli1 liberror-perl ..."
        parts = stripped.split()
        if len(parts) > 3 and all('.' not in p and '/' not in p for p in parts):
            return False

    return bool(
        ERROR_WORD_RE.search(line)
        or ERROR_COMPOUND_RE.search(line)
        or FAILED_WORD_RE.search(line)
        or FAILURE_WORD_RE.search(line)
        or EXCEPTION_WORD_RE.search(line)
        or EXCEPTION_COMPOUND_RE.search(line)
        or TRACEBACK_WORD_RE.search(line)
        or FATAL_WORD_RE.search(line)
        or CRITICAL_WORD_RE.search(line)
        or WARNING_WORD_RE.search(line)
        or WARN_COLON_RE.search(line)
        or COULD_NOT_RE.search(line)
        or REFUSED_WORD_RE.search(line)
        or DENIED_WORD_RE.search(line)
        or TIMEOUT_WORD_RE.search(line)
        or PERMISSION_DENIED_RE.search(line)
    )


# Regex patterns for known log formats

# Docker BuildKit: "[+] Building 1.2s (14/18) docker:default" or "[+] Building 0.0s (0/0)"
BUILDKIT_BUILDING_RE = re.compile(r'^\[\+\] Building\s+')

# Docker BuildKit step: "> [builder 5/6] RUN pip install" or "> [stage-1 2/3] COPY ."
BUILDKIT_STEP_RE = re.compile(r'^>\s+\[')

# Docker BuildKit completed step: " => [builder 5/6] RUN pip install" or " => [stage-1 2/3] COPY ."
BUILDKIT_DONE_STEP_RE = re.compile(r'^ =>\s+\[')

# Docker BuildKit export: "[exporting layers", "[exporting manifest", "[writing image"
BUILDKIT_EXPORT_RE = re.compile(r'^\[(exporting|writing|importing|naming)')

# Docker BuildKit error: "ERROR: process \"/bin/sh -c ...\" did not complete successfully"
BUILDKIT_ERROR_RE = re.compile(r'^ERROR:', re.IGNORECASE)

# Docker BuildKit completed line: "successfully built" or "exported to image"
BUILDKIT_SUCCESS_RE = re.compile(r'(successfully built|exported to image|named as)', re.IGNORECASE)

# Docker build with #N prefix: "#0 building with ..." or "#1 [internal] load build definition"
HASH_STEP_RE = re.compile(r'^#(\d+)\s+')

# Docker build #N status: "#1 DONE 0.0s" or "#3 CACHED"
HASH_STATUS_RE = re.compile(r'^#\d+\s+(DONE|CACHED|ERROR)\b', re.IGNORECASE)

# Docker build #N sub-step: "#1 transferring dockerfile: 1.59kB done"
HASH_SUBSTEP_RE = re.compile(r'^#\d+\s+\w', re.IGNORECASE)

# Legacy Docker build: "Step 1/7: FROM ubuntu"
LEGACY_STEP_RE = re.compile(r'^Step\s+\d+/\d+:')

# Legacy Docker success: "Successfully built abc123" or "Successfully tagged"
LEGACY_SUCCESS_RE = re.compile(r'^Successfully\s+(built|tagged)', re.IGNORECASE)

# Legacy Docker error: "The command '...' returned a non-zero code: 1"
LEGACY_ERROR_RE = re.compile(r'^The command.*returned a non-zero code', re.IGNORECASE)

# Django migration headers: "Operations to perform:", "Running migrations:"
DJANGO_MIGRATE_HEADER_RE = re.compile(r'^(Operations to perform:|Running migrations:)')

# Django migration: "Apply all migrations: admin, auth, contenttypes"
DJANGO_MIGRATE_APPLY_ALL_RE = re.compile(r'^Apply all migrations:\s*(.*)', re.IGNORECASE)

# Django migration: "Applying admin.0001_initial..." or " OK" or " FAKED"
# Note: log parser strips leading whitespace, so no \s+ prefix needed
DJANGO_MIGRATE_APPLYING_RE = re.compile(r'^Applying\s+(\S+)\.\.(\.\s*(OK|FAKED))?')

# Django migration: "Creating table auth_user"
DJANGO_MIGRATE_CREATING_RE = re.compile(r'^Creating table\s+')

# Django migration: "No migrations to apply"
DJANGO_MIGRATE_NONE_RE = re.compile(r'^No migrations to apply', re.IGNORECASE)

# Django collectstatic: "123 static files copied to '...'"
# MULTILINE needed because this line may not be the first line of the log
COLLECTSTATIC_COPIED_RE = re.compile(r'^(\d+)\s+static files?\s+(copied|found)', re.IGNORECASE | re.MULTILINE)

# Django collectstatic: "456 post-processed" (standalone line)
COLLECTSTATIC_POST_RE = re.compile(r'^(\d+)\s+post-processed', re.IGNORECASE | re.MULTILINE)

# Django collectstatic: "123 static files copied to '...', 456 post-processed."
COLLECTSTATIC_COMBINED_RE = re.compile(
    r'^(\d+)\s+static files?\s+(copied|found).*?,\s*(\d+)\s+post-processed', re.IGNORECASE | re.MULTILINE
)

# Django collectstatic: "Copying ..."
COLLECTSTATIC_COPYING_RE = re.compile(r'^\s+Copying\s+')

# PostgreSQL psql output when restoring a pg_dump SQL script:
# "CREATE TABLE", "COPY 1234", "ALTER TABLE", "SET", "GRANT", etc.
# MULTILINE needed because these lines may not be the first line of the log
PSQL_CREATE_TABLE_RE = re.compile(r'^CREATE\s+TABLE', re.IGNORECASE | re.MULTILINE)
PSQL_COPY_RE = re.compile(r'^COPY\s+(\d+)', re.IGNORECASE | re.MULTILINE)
PSQL_ERROR_RE = re.compile(r'^(ERROR:|psql:\s*error)', re.IGNORECASE | re.MULTILINE)


def _summarize_psql(text, result):
    """Summarize psql output (e.g., pg_dump restore) — return only error lines and return code."""
    errors = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and _is_error_line(stripped):
            errors.append(stripped)

    parts = []
    for err in errors:
        parts.append(f'⚠ {err}')
    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _count_psql_tables(text):
    """Count the number of tables created."""
    count = 0
    for line in text.split('\n'):
        if PSQL_CREATE_TABLE_RE.match(line.strip()):
            count += 1
    return count


def _count_psql_rows(text):
    """Count the total number of rows copied from COPY N lines."""
    total = 0
    for line in text.split('\n'):
        m = PSQL_COPY_RE.match(line.strip())
        if m:
            total += int(m.group(1))
    return total


def _summarize_docker_build(text, result):
    """Summarize a Docker build log — return only error lines and return code."""
    errors = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and _is_error_line(stripped):
            errors.append(stripped)

    parts = []
    for err in errors:
        parts.append(f'⚠ {err}')
    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _summarize_django_migrate(text, result):
    """Summarize Django migration output — return only error lines and return code."""
    errors = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and _is_error_line(stripped):
            errors.append(stripped)

    parts = []
    for err in errors:
        parts.append(f'⚠ {err}')
    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _summarize_django_collectstatic(text, result):
    """Summarize Django collectstatic output — return only error lines and return code."""
    errors = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and _is_error_line(stripped):
            errors.append(stripped)

    parts = []
    for err in errors:
        parts.append(f'⚠ {err}')
    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _summarize_generic(text, result):
    """Generic summary for unknown log formats — return only error lines and return code."""
    errors = []
    seen = set()
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and _is_error_line(stripped) and stripped not in seen:
            seen.add(stripped)
            errors.append(stripped)

    parts = []
    for err in errors:
        parts.append(f'⚠ {err}')
    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _extract_duration(text):
    """Extract duration from log text (e.g., '4.2s', '12s', '0.6s')."""
    # BuildKit: "[+] Building 4.2s (14/18)"
    m = re.search(r'Building\s+([\d.]+)s', text)
    if m:
        return m.group(1)
    # Hash format: "#1 DONE 0.0s" — sum all DONE durations for total build time
    durations = re.findall(r'DONE\s+([\d.]+)s', text)
    if durations:
        total = sum(float(d) for d in durations)
        # Format: show integer if whole number, otherwise one decimal place
        if total == int(total):
            return str(int(total))
        else:
            return f'{total:.1f}'
    return None


def _count_docker_steps(text):
    """Count the number of Docker build steps."""
    # BuildKit: "[+] Building 1.2s (14/18)"
    m = re.search(r'\((\d+)/(\d+)\)', text)
    if m:
        return int(m.group(2))
    # Hash format: use the highest step number #N as the step count
    max_step = 0
    for line in text.split('\n'):
        stripped = line.strip()
        m = HASH_STEP_RE.match(stripped)
        if m:
            step_num = int(m.group(1))
            if step_num > max_step:
                max_step = step_num
    if max_step > 0:
        return max_step
    # Legacy: "Step 1/7" — extract total from the last step line
    legacy = re.findall(r'^Step\s+\d+/(\d+):', text, re.MULTILINE)
    if legacy:
        return int(legacy[-1])
    return None


def _count_migrations(text):
    """Count the number of migrations applied."""
    count = 0
    for line in text.split('\n'):
        if DJANGO_MIGRATE_APPLYING_RE.match(line.strip()):
            count += 1
    return count


def _count_collectstatic_files(text):
    """Count the number of static files copied."""
    # Combined format: "123 static files copied to '...', 456 post-processed."
    m = COLLECTSTATIC_COMBINED_RE.search(text)
    if m:
        return int(m.group(1))
    # Standalone format
    m = COLLECTSTATIC_COPIED_RE.search(text)
    if m:
        return int(m.group(1))
    return 0


def _get_first_error(text):
    """Extract the first error line from log text."""
    for line in text.split('\n'):
        if _is_error_line(line):
            return line.strip()
    return None


def _detect_format(text):
    """Detect the log format from content. Returns 'buildkit', 'hash', 'legacy', 'migrate', 'collectstatic', 'psql', or None."""
    first_lines = text[:500]
    if BUILDKIT_BUILDING_RE.search(first_lines):
        return 'buildkit'
    if HASH_STEP_RE.search(first_lines):
        return 'hash'
    if LEGACY_STEP_RE.search(first_lines):
        return 'legacy'
    if (DJANGO_MIGRATE_APPLYING_RE.search(first_lines)
        or DJANGO_MIGRATE_CREATING_RE.search(first_lines)
        or DJANGO_MIGRATE_HEADER_RE.search(first_lines)
        or DJANGO_MIGRATE_APPLY_ALL_RE.search(first_lines)):
        return 'migrate'
    if COLLECTSTATIC_COPIED_RE.search(first_lines):
        return 'collectstatic'
    # psql: look for CREATE TABLE and COPY N lines (characteristic of pg_dump restore)
    if PSQL_CREATE_TABLE_RE.search(first_lines) and PSQL_COPY_RE.search(first_lines):
        return 'psql'
    return None


def build_header_summary(text, result, section_name=''):
    """Build a single-line summary for display in the card header next to the step name.
    
    Returns a short string like '8 steps, 12s' or '3 migrations applied' or '' if nothing useful.
    """
    stripped = text.strip()
    if not stripped:
        return ''
    
    # If there's an error, show the first error line (truncated if too long)
    if result != 0:
        first_error = _get_first_error(text)
        if first_error:
            # Truncate long error lines
            if len(first_error) > 80:
                return first_error[:77] + '...'
            return first_error
    
    # Determine format
    section_lower = section_name.lower() if section_name else ''
    fmt = None
    
    # Dispatch by section name first
    if 'docker rebuild' in section_lower or 'docker build' in section_lower:
        fmt = 'docker'
    elif 'django migrate' in section_lower:
        fmt = 'migrate'
    elif 'django collectstatic' in section_lower or 'collectstatic' in section_lower:
        fmt = 'collectstatic'
    else:
        # Auto-detect from content
        detected = _detect_format(text)
        if detected in ('buildkit', 'hash', 'legacy'):
            fmt = 'docker'
        elif detected == 'migrate':
            fmt = 'migrate'
        elif detected == 'collectstatic':
            fmt = 'collectstatic'
        elif detected == 'psql':
            fmt = 'psql'
    
    if fmt == 'docker':
        duration = _extract_duration(text)
        steps = _count_docker_steps(text)
        parts = []
        if steps:
            parts.append(f'{steps} steps')
        if duration:
            parts.append(f'{duration}s')
        return ', '.join(parts) if parts else ''
    
    elif fmt == 'migrate':
        count = _count_migrations(text)
        if count:
            return f'{count} migration(s) applied'
        # Check for "no migrations" case (need MULTILINE for ^ anchor)
        if re.search(DJANGO_MIGRATE_NONE_RE.pattern, text, re.MULTILINE):
            return 'No migrations to apply'
        return ''
    
    elif fmt == 'collectstatic':
        count = _count_collectstatic_files(text)
        if count:
            return f'{count} files copied'
        return ''
    
    elif fmt == 'psql':
        tables = _count_psql_tables(text)
        rows = _count_psql_rows(text)
        parts = []
        if tables:
            parts.append(f'{tables} table(s)')
        if rows:
            parts.append(f'{rows} rows')
        return ', '.join(parts) if parts else ''
    
    return ''


def build_summary(text, result, section_name=''):
    """Build a concise summary from log text, using format-specific summarizers when possible."""

    # Skip empty text
    stripped = text.strip()
    if not stripped:
        return ''

    # Dispatch to format-specific summarizers based on section name
    section_lower = section_name.lower() if section_name else ''

    if 'docker rebuild' in section_lower or 'docker build' in section_lower:
        summary = _summarize_docker_build(text, result)

    if 'django migrate' in section_lower:
        summary = _summarize_django_migrate(text, result)

    if 'django collectstatic' in section_lower or 'collectstatic' in section_lower:
        summary = _summarize_django_collectstatic(text, result)

    if 'clone database' in section_lower or 'clone_db' in section_lower or 'psql' in section_lower:
        summary = _summarize_psql(text, result)

    # Auto-detect format from content when section name is not specific enough
    first_lines = text[:500]
    if BUILDKIT_BUILDING_RE.search(first_lines) or LEGACY_STEP_RE.search(first_lines) or HASH_STEP_RE.search(first_lines):
        summary = _summarize_docker_build(text, result)
    elif (DJANGO_MIGRATE_APPLYING_RE.search(first_lines)
          or DJANGO_MIGRATE_CREATING_RE.search(first_lines)
          or DJANGO_MIGRATE_HEADER_RE.search(first_lines)
          or DJANGO_MIGRATE_APPLY_ALL_RE.search(first_lines)):
        summary = _summarize_django_migrate(text, result)
    elif COLLECTSTATIC_COPIED_RE.search(first_lines):
        summary = _summarize_django_collectstatic(text, result)
    elif PSQL_CREATE_TABLE_RE.search(first_lines) and PSQL_COPY_RE.search(first_lines):
        summary = _summarize_psql(text, result)
    else:
        summary = _summarize_generic(text, result)

    # If the summary is identical to the full content, there's no point in showing it
    if summary.strip() == stripped:
        return ''

    return summary
