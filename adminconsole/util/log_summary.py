import re


# Regex patterns for known log formats

# Docker BuildKit: "[+] Building 1.2s (14/18) docker:default" or "[+] Building 0.0s (0/0)"
BUILDKIT_BUILDING_RE = re.compile(r'^\[\+\] Building\s+')

# Docker BuildKit step: "> [builder 5/6] RUN pip install" or "> [stage-1 2/3] COPY ."
BUILDKIT_STEP_RE = re.compile(r'^>\s+\[')

# Docker BuildKit export: "[exporting layers", "[exporting manifest", "[writing image"
BUILDKIT_EXPORT_RE = re.compile(r'^\[(exporting|writing|importing|naming)')

# Docker BuildKit error: "ERROR: process \"/bin/sh -c ...\" did not complete successfully"
BUILDKIT_ERROR_RE = re.compile(r'^ERROR:', re.IGNORECASE)

# Docker BuildKit completed line: "successfully built" or "exported to image"
BUILDKIT_SUCCESS_RE = re.compile(r'(successfully built|exported to image|named as)', re.IGNORECASE)

# Legacy Docker build: "Step 1/7: FROM ubuntu"
LEGACY_STEP_RE = re.compile(r'^Step\s+\d+/\d+:')

# Legacy Docker success: "Successfully built abc123" or "Successfully tagged"
LEGACY_SUCCESS_RE = re.compile(r'^Successfully\s+(built|tagged)', re.IGNORECASE)

# Legacy Docker error: "The command '...' returned a non-zero code: 1"
LEGACY_ERROR_RE = re.compile(r'^The command.*returned a non-zero code', re.IGNORECASE)

# Django migration: " Applying admin.0001_initial..." or " OK" or " FAKED"
DJANGO_MIGRATE_APPLYING_RE = re.compile(r'^\s+Applying\s+(\S+)\.\.(\.\s*(OK|FAKED))?')

# Django migration: " Creating table auth_user"
DJANGO_MIGRATE_CREATING_RE = re.compile(r'^\s+Creating table\s+')

# Django migration: " No migrations to apply"
DJANGO_MIGRATE_NONE_RE = re.compile(r'^\s+No migrations to apply', re.IGNORECASE)

# Django collectstatic: "123 static files copied to '...'"
COLLECTSTATIC_COPIED_RE = re.compile(r'^(\d+)\s+static files?\s+(copied|found)', re.IGNORECASE)

# Django collectstatic: "456 post-processed"
COLLECTSTATIC_POST_RE = re.compile(r'^(\d+)\s+post-processed', re.IGNORECASE)

# Django collectstatic: "Copying ..."
COLLECTSTATIC_COPYING_RE = re.compile(r'^\s+Copying\s+')


def _summarize_docker_build(text, result):
    """Summarize a Docker build log (BuildKit or legacy format)."""
    lines = text.rstrip('\n').split('\n')
    if not lines or (len(lines) == 1 and not lines[0]):
        return ''

    summary_parts = []
    is_buildkit = False
    steps = []
    errors = []
    total_steps = None
    final_line = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect BuildKit format
        if BUILDKIT_BUILDING_RE.match(stripped):
            is_buildkit = True
            # Extract progress: "(14/18)"
            m = re.search(r'\((\d+)/(\d+)\)', stripped)
            if m:
                total_steps = int(m.group(2))
            # Check for final status
            if 'DONE' in stripped.upper() or 'ERROR' in stripped.upper():
                final_line = stripped
            summary_parts.append(stripped)
            continue

        if is_buildkit:
            # BuildKit step lines
            if BUILDKIT_STEP_RE.match(stripped):
                steps.append(stripped)
            elif BUILDKIT_EXPORT_RE.match(stripped):
                # Export lines are less interesting, skip in summary
                pass
            elif BUILDKIT_ERROR_RE.match(stripped):
                errors.append(stripped)
            elif BUILDKIT_SUCCESS_RE.search(stripped):
                final_line = stripped
        else:
            # Legacy format
            if LEGACY_STEP_RE.match(stripped):
                steps.append(stripped)
            elif LEGACY_SUCCESS_RE.match(stripped):
                final_line = stripped
            elif LEGACY_ERROR_RE.match(stripped):
                errors.append(stripped)

    # Build the summary
    parts = []

    if is_buildkit:
        # For BuildKit, show the final building line and key steps
        building_lines = [l for l in lines if BUILDKIT_BUILDING_RE.match(l.strip())]
        if building_lines:
            parts.append(building_lines[-1].strip())
        # Show error steps
        for err in errors:
            parts.append(f'⚠ {err}')
        # Show the last few steps (up to 5)
        if steps and not errors:
            parts.extend(steps[-5:])
        if final_line and final_line not in parts:
            parts.append(final_line)
    else:
        # Legacy format
        if steps:
            parts.extend(steps[:5])
        for err in errors:
            parts.append(f'⚠ {err}')
        if final_line:
            parts.append(final_line)

    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _summarize_django_migrate(text, result):
    """Summarize Django migration output."""
    lines = text.rstrip('\n').split('\n')
    if not lines or (len(lines) == 1 and not lines[0]):
        return ''

    parts = []
    migrations_applied = []
    tables_created = []
    errors = []
    no_migrations = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        m = DJANGO_MIGRATE_APPLYING_RE.match(line)
        if m:
            migration_name = m.group(1)
            status = m.group(3)
            if status:
                migrations_applied.append(f'{migration_name}... {status}')
            else:
                # Incomplete line, might be followed by OK on next line
                migrations_applied.append(stripped)
            continue

        if DJANGO_MIGRATE_CREATING_RE.match(line):
            tables_created.append(stripped)
            continue

        if DJANGO_MIGRATE_NONE_RE.match(line):
            no_migrations = True
            parts.append(stripped)
            continue

        # Check for errors
        lower = stripped.lower()
        if any(p in lower for p in ['error', 'failed', 'exception', 'traceback']):
            errors.append(stripped)

    # Build summary
    if no_migrations:
        return '\n'.join(parts) if parts else ''

    if migrations_applied:
        # Group by app
        apps = {}
        for mig in migrations_applied:
            # Extract app name from "Applying app.migration... OK" or "app.migration... OK"
            clean = mig.replace('Applying ', '', 1)
            app_name = clean.split('.')[0] if '.' in clean else 'unknown'
            apps.setdefault(app_name, []).append(mig)

        total = len(migrations_applied)
        if len(apps) <= 2 and total <= 5:
            # Few apps, show individually
            for app_name, migs in apps.items():
                parts.extend(migs)
        else:
            # Many migrations, summarize per app
            for app_name, migs in apps.items():
                parts.append(f'{app_name}: {len(migs)} migration(s) applied')
            parts.append(f'({total} migrations total)')

    if tables_created:
        parts.append(f'{len(tables_created)} tables created')

    for err in errors:
        parts.append(f'⚠ {err}')

    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _summarize_django_collectstatic(text, result):
    """Summarize Django collectstatic output."""
    lines = text.rstrip('\n').split('\n')
    if not lines or (len(lines) == 1 and not lines[0]):
        return ''

    parts = []
    copied_count = 0
    post_processed_count = 0
    errors = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        m = COLLECTSTATIC_COPIED_RE.match(stripped)
        if m:
            copied_count = int(m.group(1))
            parts.append(stripped)
            continue

        m = COLLECTSTATIC_POST_RE.match(stripped)
        if m:
            post_processed_count = int(m.group(1))
            parts.append(stripped)
            continue

        # Check for errors
        lower = stripped.lower()
        if any(p in lower for p in ['error', 'failed', 'exception', 'warning']):
            errors.append(stripped)

    for err in errors:
        parts.append(f'⚠ {err}')

    if result != 0:
        parts.append(f'(Return code: {result})')

    return '\n'.join(parts) if parts else ''


def _summarize_generic(text, result):
    """Generic summary for unknown log formats, highlighting errors and key output."""
    lines = text.rstrip('\n').split('\n')
    if not lines or (len(lines) == 1 and not lines[0]):
        return ''

    # Collect error/warning lines
    error_patterns = ['error', 'failed', 'failure', 'exception', 'traceback',
                      'fatal', 'critical', 'warning', 'warn:', 'could not',
                      'refused', 'denied', 'timeout', 'permission denied']
    error_lines = []
    other_lines = []
    for line in lines:
        lower = line.lower()
        if any(p in lower for p in error_patterns):
            error_lines.append(line)
        else:
            other_lines.append(line)

    summary_parts = []

    # Add first few meaningful lines as context
    meaningful = [l for l in other_lines if l.strip()]
    if meaningful:
        summary_parts.extend(meaningful[:5])

    # Add error lines (deduplicated)
    seen = set()
    for line in error_lines:
        if line not in seen:
            seen.add(line)
            summary_parts.append(f'⚠ {line}')

    # Add return code indicator
    if result != 0:
        summary_parts.append(f'(Return code: {result})')

    return '\n'.join(summary_parts)


def build_summary(text, result, section_name=''):
    """Build a concise summary from log text, using format-specific summarizers when possible."""

    # Dispatch to format-specific summarizers based on section name
    section_lower = section_name.lower() if section_name else ''

    if 'docker rebuild' in section_lower or 'docker build' in section_lower:
        return _summarize_docker_build(text, result)

    if 'django migrate' in section_lower:
        return _summarize_django_migrate(text, result)

    if 'django collectstatic' in section_lower or 'collectstatic' in section_lower:
        return _summarize_django_collectstatic(text, result)

    # Auto-detect format from content when section name is not specific enough
    first_lines = text[:500]
    if BUILDKIT_BUILDING_RE.search(first_lines) or LEGACY_STEP_RE.search(first_lines):
        return _summarize_docker_build(text, result)
    if DJANGO_MIGRATE_APPLYING_RE.search(first_lines) or DJANGO_MIGRATE_CREATING_RE.search(first_lines):
        return _summarize_django_migrate(text, result)
    if COLLECTSTATIC_COPIED_RE.search(first_lines):
        return _summarize_django_collectstatic(text, result)

    return _summarize_generic(text, result)
