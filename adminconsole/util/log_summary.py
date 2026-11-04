import re


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
COLLECTSTATIC_COPIED_RE = re.compile(r'^(\d+)\s+static files?\s+(copied|found)', re.IGNORECASE)

# Django collectstatic: "456 post-processed" (standalone line)
COLLECTSTATIC_POST_RE = re.compile(r'^(\d+)\s+post-processed', re.IGNORECASE)

# Django collectstatic: "123 static files copied to '...', 456 post-processed."
COLLECTSTATIC_COMBINED_RE = re.compile(
    r'^(\d+)\s+static files?\s+(copied|found).*?,\s*(\d+)\s+post-processed', re.IGNORECASE
)

# Django collectstatic: "Copying ..."
COLLECTSTATIC_COPYING_RE = re.compile(r'^\s+Copying\s+')


def _summarize_docker_build(text, result):
    """Summarize a Docker build log (BuildKit, legacy, or #N hash format)."""
    lines = text.rstrip('\n').split('\n')
    if not lines or (len(lines) == 1 and not lines[0]):
        return ''

    summary_parts = []
    is_buildkit = False
    is_hash = False
    steps = []
    errors = []
    total_steps = None
    final_line = None

    # First pass: detect format
    for line in lines:
        stripped = line.strip()
        if BUILDKIT_BUILDING_RE.match(stripped):
            is_buildkit = True
            break
        if HASH_STEP_RE.match(stripped):
            is_hash = True
            break
        if LEGACY_STEP_RE.match(stripped):
            break

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
            # BuildKit step lines (running steps with ">")
            if BUILDKIT_STEP_RE.match(stripped):
                steps.append(stripped)
            # BuildKit completed step lines (" =>")
            elif BUILDKIT_DONE_STEP_RE.match(stripped):
                steps.append(stripped)
            elif BUILDKIT_EXPORT_RE.match(stripped):
                # Export lines are less interesting, skip in summary
                pass
            elif BUILDKIT_ERROR_RE.match(stripped):
                errors.append(stripped)
            elif BUILDKIT_SUCCESS_RE.search(stripped):
                final_line = stripped
        elif is_hash:
            # #N hash format
            if HASH_STATUS_RE.match(stripped):
                # e.g. "#1 DONE 0.0s" or "#3 CACHED" — skip status-only lines
                pass
            elif HASH_STEP_RE.match(stripped):
                # Extract the step description, e.g. "#1 [internal] load build definition from Dockerfile"
                m = HASH_STEP_RE.match(stripped)
                step_num = m.group(1)
                rest = stripped[len(f'#{step_num} '):]
                # Skip the driver line: "building with "default" instance using docker driver"
                if rest.startswith('building with'):
                    continue
                # Skip sub-steps like "transferring dockerfile: 1.59kB done"
                if rest.startswith('transferring') or rest.startswith('resolve') or rest.endswith(' done'):
                    continue
                # Skip progress-only lines like "..."
                if rest.strip() == '...':
                    continue
                # Skip long image reference lines (sha256 digests) that repeat the step info
                if '@sha256:' in rest and rest.count('/') > 3:
                    # Keep only the short form if it starts with a bracketed stage name
                    if not rest.startswith('[') and not rest.startswith('FROM'):
                        continue
                # Strip long sha256 suffixes from step descriptions for brevity
                rest = re.sub(r'@sha256:[a-f0-9]+', '', rest)
                steps.append(rest)
            # Check for errors in hash format
            lower = stripped.lower()
            if any(p in lower for p in ['error', 'failed', 'fatal']):
                errors.append(stripped)
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
    elif is_hash:
        # Hash format: show key steps and errors
        # Deduplicate steps (same step may appear multiple times with different status)
        seen = set()
        unique_steps = []
        for s in steps:
            if s not in seen:
                seen.add(s)
                unique_steps.append(s)
        if unique_steps:
            parts.extend(unique_steps[:8])
        for err in errors:
            parts.append(f'⚠ {err}')
        if final_line:
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
    apps_list = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for header lines like "Operations to perform:", "Running migrations:"
        if DJANGO_MIGRATE_HEADER_RE.match(stripped):
            continue

        # Check for "Apply all migrations: admin, auth, contenttypes, ..."
        m = DJANGO_MIGRATE_APPLY_ALL_RE.match(stripped)
        if m:
            apps_str = m.group(1).strip()
            if apps_str:
                apps_list = [a.strip() for a in apps_str.split(',') if a.strip()]
            continue

        m = DJANGO_MIGRATE_APPLYING_RE.match(stripped)
        if m:
            migration_name = m.group(1)
            status = m.group(3)
            if status:
                migrations_applied.append(f'{migration_name}... {status}')
            else:
                # Incomplete line, might be followed by OK on next line
                # Strip "Applying " prefix to keep summary shorter than input
                clean = stripped.replace('Applying ', '', 1)
                migrations_applied.append(clean)
            continue

        if DJANGO_MIGRATE_CREATING_RE.match(stripped):
            tables_created.append(stripped)
            continue

        if DJANGO_MIGRATE_NONE_RE.match(stripped):
            no_migrations = True
            continue

        # Check for errors
        lower = stripped.lower()
        if any(p in lower for p in ['error', 'failed', 'exception', 'traceback']):
            errors.append(stripped)

    # Build summary
    if no_migrations:
        if apps_list:
            parts.append(f'Apps: {", ".join(apps_list)}')
        parts.append('No migrations to apply.')
        for err in errors:
            parts.append(f'⚠ {err}')
        if result != 0:
            parts.append(f'(Return code: {result})')
        return '\n'.join(parts) if parts else ''

    if migrations_applied:
        # Group by app
        apps = {}
        for mig in migrations_applied:
            # Extract app name from "app.migration... OK"
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

        # Check for combined format: "123 static files copied to '...', 456 post-processed."
        m = COLLECTSTATIC_COMBINED_RE.match(stripped)
        if m:
            copied_count = int(m.group(1))
            post_processed_count = int(m.group(3))
            continue

        m = COLLECTSTATIC_COPIED_RE.match(stripped)
        if m:
            copied_count = int(m.group(1))
            continue

        m = COLLECTSTATIC_POST_RE.match(stripped)
        if m:
            post_processed_count = int(m.group(1))
            continue

        # Check for errors
        lower = stripped.lower()
        if any(p in lower for p in ['error', 'failed', 'exception', 'warning']):
            errors.append(stripped)

    # Build a concise summary
    if copied_count:
        parts.append(f'{copied_count} static files copied')
    if post_processed_count:
        parts.append(f'{post_processed_count} post-processed')

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


def _extract_duration(text):
    """Extract duration from log text (e.g., '4.2s', '12s', '0.6s')."""
    # BuildKit: "[+] Building 4.2s (14/18)"
    m = re.search(r'Building\s+([\d.]+)s', text)
    if m:
        return m.group(1)
    # Hash format: "#1 DONE 0.0s" — take the last DONE line's duration
    durations = re.findall(r'DONE\s+([\d.]+)s', text)
    if durations:
        return durations[-1]
    return None


def _count_docker_steps(text):
    """Count the number of Docker build steps."""
    # BuildKit: "[+] Building 1.2s (14/18)"
    m = re.search(r'\((\d+)/(\d+)\)', text)
    if m:
        return int(m.group(2))
    # Hash format: count unique step descriptions
    steps = set()
    for line in text.split('\n'):
        stripped = line.strip()
        m = HASH_STEP_RE.match(stripped)
        if m:
            step_num = m.group(1)
            rest = stripped[len(f'#{step_num} '):]
            if not rest.startswith('building with') and not rest.startswith('transferring') and not rest.startswith('resolve') and not rest.endswith(' done'):
                rest = re.sub(r'@sha256:[a-f0-9]+', '', rest)
                if rest.strip():
                    steps.add(rest)
    if steps:
        return len(steps)
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
    error_patterns = ['error', 'failed', 'exception', 'fatal', 'traceback']
    for line in text.split('\n'):
        lower = line.lower()
        if any(p in lower for p in error_patterns):
            return line.strip()
    return None


def _detect_format(text):
    """Detect the log format from content. Returns 'buildkit', 'hash', 'legacy', 'migrate', 'collectstatic', or None."""
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
    else:
        summary = _summarize_generic(text, result)

    # If the summary is identical to the full content, there's no point in showing it
    if summary.strip() == stripped:
        return ''

    return summary
