import unittest
import time

from adminconsole.util.log_summary import (
    _is_error_line,
    _summarize_docker_build,
    _summarize_django_migrate,
    _summarize_django_collectstatic,
    _summarize_psql,
    _summarize_generic,
    _extract_duration,
    _count_docker_steps,
    _count_migrations,
    _count_collectstatic_files,
    _count_psql_tables,
    _count_psql_rows,
    _get_first_error,
    _detect_format,
    build_summary,
    build_header_summary,
)


# =============================================================================
# _is_error_line
# =============================================================================

class TestIsErrorLine(unittest.TestCase):
    """Test error detection with word boundaries and false positive filters."""

    # -- True errors --

    def test_detects_error_word(self):
        self.assertTrue(_is_error_line('ERROR: something failed'))

    def test_detects_failed_word(self):
        self.assertTrue(_is_error_line('Connection failed'))

    def test_detects_failure_word(self):
        self.assertTrue(_is_error_line('Build failure detected'))

    def test_detects_exception_word(self):
        self.assertTrue(_is_error_line('An exception occurred'))

    def test_detects_traceback(self):
        self.assertTrue(_is_error_line('Traceback (most recent call last)'))

    def test_detects_fatal(self):
        self.assertTrue(_is_error_line('Fatal: disk full'))

    def test_detects_critical(self):
        self.assertTrue(_is_error_line('CRITICAL: service down'))

    def test_detects_warning(self):
        self.assertTrue(_is_error_line('WARNING: deprecated API'))

    def test_detects_warn_colon(self):
        self.assertTrue(_is_error_line('WARN: low memory'))

    def test_detects_could_not(self):
        self.assertTrue(_is_error_line('Could not connect to database'))

    def test_detects_refused(self):
        self.assertTrue(_is_error_line('Connection refused'))

    def test_detects_denied(self):
        self.assertTrue(_is_error_line('Permission denied'))

    def test_detects_timeout(self):
        self.assertTrue(_is_error_line('Request timeout after 30s'))

    def test_detects_permission_denied(self):
        self.assertTrue(_is_error_line('Permission denied for user'))

    def test_detects_compound_error(self):
        self.assertTrue(_is_error_line('django.db.utils.OperationalError: connection refused'))

    def test_detects_compound_exception(self):
        self.assertTrue(_is_error_line('FileNotFoundError: no such file'))

    def test_detects_psql_error(self):
        self.assertTrue(_is_error_line('ERROR: must be able to SET ROLE'))

    def test_detects_psql_connection_error(self):
        self.assertTrue(_is_error_line('psql: error: connection to server failed'))

    # -- False positives --

    def test_ignores_liberror_perl(self):
        self.assertFalse(_is_error_line('git-man libbrotli1 liberror-perl libexpat1'))

    def test_ignores_get_line(self):
        self.assertFalse(_is_error_line('Get:29 http://deb.debian.org/debian trixie/main amd64 liberror-perl all 0.17030-1'))

    def test_ignores_selecting(self):
        self.assertFalse(_is_error_line('Selecting previously unselected package liberror-perl.'))

    def test_ignores_preparing(self):
        self.assertFalse(_is_error_line('Preparing to unpack .../28-liberror-perl_0.17030-1_all.deb ...'))

    def test_ignores_unpacking(self):
        self.assertFalse(_is_error_line('Unpacking liberror-perl (0.17030-1) ...'))

    def test_ignores_setting_up(self):
        self.assertFalse(_is_error_line('Setting up liberror-perl (0.17030-1) ...'))

    def test_ignores_deleting(self):
        self.assertFalse(_is_error_line("Deleting 'fontawesomefree/svgs/brands/critical-role.svg'"))

    def test_ignores_deleting_with_path(self):
        self.assertFalse(_is_error_line("Deleting 'js/critical-validation.js'"))

    def test_ignores_package_list(self):
        self.assertFalse(_is_error_line('git git-man libbrotli1 libcurl3t64-gnutls liberror-perl'))

    # -- Non-error lines --

    def test_clean_line(self):
        self.assertFalse(_is_error_line('Step 1/7: FROM ubuntu'))

    def test_empty_line(self):
        self.assertFalse(_is_error_line(''))

    def test_info_line(self):
        self.assertFalse(_is_error_line('INFO: starting migration'))


# =============================================================================
# _summarize_docker_build
# =============================================================================

class TestSummarizeDockerBuild(unittest.TestCase):
    """Test Docker build log summarizer."""

    def test_buildkit_success_returns_empty(self):
        log = '[+] Building 4.2s (14/18) docker:default\n => [builder 1/6] FROM ubuntu\n => [builder 2/6] RUN apt update\n'
        self.assertEqual(_summarize_docker_build(log, 0), '')

    def test_buildkit_failure_returns_errors(self):
        log = '[+] Building 2.1s (5/8)\nERROR: process did not complete successfully: exit code: 1\n'
        summary = _summarize_docker_build(log, 1)
        self.assertIn('⚠ ERROR:', summary)
        self.assertIn('Rückgabewert: 1', summary)

    def test_hash_format_success_returns_empty(self):
        log = '#1 [internal] load build definition\n#1 DONE 0.0s\n#2 [app 1/3] RUN pip install\n#2 DONE 3.5s\n'
        self.assertEqual(_summarize_docker_build(log, 0), '')

    def test_hash_format_with_liberror_perl(self):
        log = '#9 2.843   git-man libbrotli1 liberror-perl\n#9 7.270 Selecting previously unselected package liberror-perl.\n#9 DONE 8s\n'
        self.assertEqual(_summarize_docker_build(log, 0), '')

    def test_legacy_docker_success(self):
        log = 'Step 1/7: FROM ubuntu\nStep 2/7: RUN apt update\nSuccessfully built abc123\n'
        self.assertEqual(_summarize_docker_build(log, 0), '')

    def test_legacy_docker_failure(self):
        # "The command returned a non-zero code" doesn't match error keywords,
        # so only the return code appears in the summary
        log = 'Step 3/5: RUN pip install\nThe command returned a non-zero code: 1\n'
        summary = _summarize_docker_build(log, 1)
        self.assertIn('Rückgabewert: 1', summary)

    def test_empty_log(self):
        self.assertEqual(_summarize_docker_build('', 0), '')


# =============================================================================
# _summarize_django_migrate
# =============================================================================

class TestSummarizeDjangoMigrate(unittest.TestCase):
    """Test Django migrate log summarizer."""

    def test_migrations_applied_returns_empty(self):
        log = 'Operations to perform:\nApplying admin.0001_initial... OK\nApplying auth.0002_alter... OK\n'
        self.assertEqual(_summarize_django_migrate(log, 0), '')

    def test_no_migrations_returns_empty(self):
        log = 'Operations to perform:\nRunning migrations:\nNo migrations to apply.\n'
        self.assertEqual(_summarize_django_migrate(log, 0), '')

    def test_migrate_error(self):
        log = 'Applying admin.0001... Traceback (most recent call last)\n  File "..." \nOperationalError: no such table\n'
        summary = _summarize_django_migrate(log, 1)
        self.assertIn('⚠', summary)
        self.assertIn('Traceback', summary)

    def test_empty_log(self):
        self.assertEqual(_summarize_django_migrate('', 0), '')


# =============================================================================
# _summarize_django_collectstatic
# =============================================================================

class TestSummarizeDjangoCollectstatic(unittest.TestCase):
    """Test Django collectstatic log summarizer."""

    def test_collectstatic_success(self):
        log = "Copying 1234 files\n295 static files copied to '/code/static', 295 post-processed.\n"
        self.assertEqual(_summarize_django_collectstatic(log, 0), '')

    def test_collectstatic_with_deleting(self):
        log = "Deleting 'critical-role.svg'\n123 static files copied.\n"
        self.assertEqual(_summarize_django_collectstatic(log, 0), '')

    def test_collectstatic_error(self):
        log = "Copying file\nERROR: Permission denied\n"
        summary = _summarize_django_collectstatic(log, 1)
        self.assertIn('⚠', summary)

    def test_empty_log(self):
        self.assertEqual(_summarize_django_collectstatic('', 0), '')


# =============================================================================
# _summarize_psql
# =============================================================================

class TestSummarizePsql(unittest.TestCase):
    """Test psql/pg_dump restore log summarizer."""

    def test_psql_success(self):
        log = 'CREATE TABLE\nCOPY 100\nALTER TABLE\nCOPY 200\n'
        self.assertEqual(_summarize_psql(log, 0), '')

    def test_psql_with_error(self):
        log = 'CREATE TABLE\nERROR: must be able to SET ROLE "postgres"\nCOPY 0\n'
        summary = _summarize_psql(log, 1)
        self.assertIn('⚠ ERROR:', summary)
        self.assertIn('Rückgabewert: 1', summary)

    def test_psql_empty(self):
        self.assertEqual(_summarize_psql('', 0), '')


# =============================================================================
# _summarize_generic
# =============================================================================

class TestSummarizeGeneric(unittest.TestCase):
    """Test generic log summarizer (fallback for unknown formats)."""

    def test_generic_success(self):
        log = 'Starting task\nProcessing items\nDone\n'
        self.assertEqual(_summarize_generic(log, 0), '')

    def test_generic_with_errors(self):
        log = 'Starting\nFailed to connect\nRetrying\nDone\n'
        summary = _summarize_generic(log, 0)
        self.assertIn('⚠ Failed to connect', summary)

    def test_generic_deduplicates(self):
        log = 'ERROR: timeout\nERROR: timeout\nERROR: timeout\n'
        summary = _summarize_generic(log, 0)
        # Should appear only once due to deduplication
        self.assertEqual(summary.count('⚠'), 1)

    def test_generic_with_return_code(self):
        log = 'Some output\n'
        summary = _summarize_generic(log, 1)
        self.assertIn('Rückgabewert: 1', summary)

    def test_generic_empty(self):
        self.assertEqual(_summarize_generic('', 0), '')


# =============================================================================
# _extract_duration
# =============================================================================

class TestExtractDuration(unittest.TestCase):
    """Test duration extraction from Docker build logs."""

    def test_buildkit_duration(self):
        log = '[+] Building 4.2s (14/18) docker:default\n'
        self.assertEqual(_extract_duration(log), '4.2')

    def test_hash_format_sums_durations(self):
        log = '#1 DONE 0.5s\n#2 DONE 1.2s\n#3 CACHED\n#4 DONE 0.3s\n'
        # Whole-number sums are formatted as integers
        self.assertEqual(_extract_duration(log), '2')

    def test_hash_format_integer(self):
        log = '#1 DONE 1s\n#2 DONE 2s\n'
        self.assertEqual(_extract_duration(log), '3')

    def test_no_duration(self):
        log = 'Some random output\n'
        self.assertIsNone(_extract_duration(log))

    def test_empty(self):
        self.assertIsNone(_extract_duration(''))


# =============================================================================
# _count_docker_steps
# =============================================================================

class TestCountDockerSteps(unittest.TestCase):
    """Test Docker step counting."""

    def test_buildkit_steps(self):
        log = '[+] Building 4.2s (14/18) docker:default\n'
        self.assertEqual(_count_docker_steps(log), 18)

    def test_hash_format_max_step(self):
        log = '#1 DONE 0.0s\n#5 DONE 1.0s\n#8 DONE 0.5s\n'
        self.assertEqual(_count_docker_steps(log), 8)

    def test_legacy_steps(self):
        log = 'Step 1/7: FROM ubuntu\nStep 2/7: RUN apt\nStep 7/7: CMD\n'
        self.assertEqual(_count_docker_steps(log), 7)

    def test_no_steps(self):
        self.assertIsNone(_count_docker_steps('random output'))

    def test_empty(self):
        self.assertIsNone(_count_docker_steps(''))


# =============================================================================
# _count_migrations
# =============================================================================

class TestCountMigrations(unittest.TestCase):
    """Test migration counting."""

    def test_counts_applying_lines(self):
        log = 'Applying admin.0001... OK\nApplying auth.0002... OK\nApplying sessions.0001... OK\n'
        self.assertEqual(_count_migrations(log), 3)

    def test_no_migrations(self):
        log = 'No migrations to apply.\n'
        self.assertEqual(_count_migrations(log), 0)

    def test_with_headers(self):
        log = 'Operations to perform:\nApplying contenttypes.0001... OK\n'
        self.assertEqual(_count_migrations(log), 1)

    def test_empty(self):
        self.assertEqual(_count_migrations(''), 0)


# =============================================================================
# _count_collectstatic_files
# =============================================================================

class TestCountCollectstaticFiles(unittest.TestCase):
    """Test collectstatic file counting."""

    def test_combined_format(self):
        log = "Copying files\n295 static files copied to '/code/static', 295 post-processed.\n"
        self.assertEqual(_count_collectstatic_files(log), 295)

    def test_standalone_format(self):
        log = "1234 static files copied.\n"
        self.assertEqual(_count_collectstatic_files(log), 1234)

    def test_found_format(self):
        log = "0 static files found.\n"
        self.assertEqual(_count_collectstatic_files(log), 0)

    def test_no_count(self):
        self.assertEqual(_count_collectstatic_files('random output'), 0)


# =============================================================================
# _count_psql_tables
# =============================================================================

class TestCountPsqlTables(unittest.TestCase):
    """Test psql table counting."""

    def test_counts_create_table(self):
        log = 'CREATE TABLE users\nCREATE TABLE orders\nALTER TABLE\n'
        self.assertEqual(_count_psql_tables(log), 2)

    def test_no_tables(self):
        self.assertEqual(_count_psql_tables('SET\nCOPY 100\n'), 0)

    def test_empty(self):
        self.assertEqual(_count_psql_tables(''), 0)


# =============================================================================
# _count_psql_rows
# =============================================================================

class TestCountPsqlRows(unittest.TestCase):
    """Test psql row counting."""

    def test_sums_copy_lines(self):
        log = 'COPY 100\nCOPY 200\nCOPY 50\n'
        self.assertEqual(_count_psql_rows(log), 350)

    def test_copy_zero(self):
        log = 'COPY 0\nCOPY 0\n'
        self.assertEqual(_count_psql_rows(log), 0)

    def test_no_copy(self):
        self.assertEqual(_count_psql_rows('CREATE TABLE\n'), 0)


# =============================================================================
# _get_first_error
# =============================================================================

class TestGetFirstError(unittest.TestCase):
    """Test first error extraction."""

    def test_returns_first_error(self):
        log = 'OK\nERROR: first error\nERROR: second error\n'
        self.assertEqual(_get_first_error(log), 'ERROR: first error')

    def test_no_error(self):
        self.assertIsNone(_get_first_error('All good\nNo problems\n'))

    def test_empty(self):
        self.assertIsNone(_get_first_error(''))


# =============================================================================
# _detect_format
# =============================================================================

class TestDetectFormat(unittest.TestCase):
    """Test log format auto-detection."""

    def test_detects_buildkit(self):
        self.assertEqual(_detect_format('[+] Building 4.2s (14/18)'), 'buildkit')

    def test_detects_hash_format(self):
        self.assertEqual(_detect_format('#1 [internal] load build definition'), 'hash')

    def test_detects_legacy(self):
        self.assertEqual(_detect_format('Step 1/7: FROM ubuntu'), 'legacy')

    def test_detects_migrate_applying(self):
        self.assertEqual(_detect_format('Applying admin.0001... OK'), 'migrate')

    def test_detects_migrate_header(self):
        self.assertEqual(_detect_format('Operations to perform:\nRunning migrations:'), 'migrate')

    def test_detects_migrate_create(self):
        self.assertEqual(_detect_format('Creating table auth_user'), 'migrate')

    def test_detects_collectstatic(self):
        self.assertEqual(_detect_format("295 static files copied to '/code/static'"), 'collectstatic')

    def test_detects_psql(self):
        self.assertEqual(_detect_format('CREATE TABLE public.users'), 'psql')

    def test_no_detection(self):
        self.assertIsNone(_detect_format('Some random output\n'))

    def test_empty(self):
        self.assertIsNone(_detect_format(''))


# =============================================================================
# build_summary (public API)
# =============================================================================

class TestBuildSummary(unittest.TestCase):
    """Test the public build_summary() dispatcher."""

    def test_docker_by_section_name(self):
        log = '[+] Building 4.2s (14/18)\n => [builder 1/6] FROM ubuntu\n'
        self.assertEqual(build_summary(log, 0, 'Docker Rebuild'), '')

    def test_docker_by_auto_detect(self):
        log = '[+] Building 4.2s (14/18)\n => [builder 1/6] FROM ubuntu\n'
        self.assertEqual(build_summary(log, 0, ''), '')

    def test_migrate_by_section_name(self):
        log = 'Applying admin.0001... OK\n'
        self.assertEqual(build_summary(log, 0, 'Django Migrate'), '')

    def test_collectstatic_by_section_name(self):
        log = "295 static files copied to '/code/static', 295 post-processed.\n"
        self.assertEqual(build_summary(log, 0, 'Django Collectstatic'), '')

    def test_psql_by_section_name(self):
        log = 'CREATE TABLE\nCOPY 100\n'
        self.assertEqual(build_summary(log, 0, 'Clone Database'), '')

    def test_generic_fallback(self):
        log = 'Starting task\nDone\n'
        self.assertEqual(build_summary(log, 0, 'Unknown Step'), '')

    def test_error_summary(self):
        log = 'ERROR: something failed\n'
        summary = build_summary(log, 1, 'Unknown Step')
        self.assertIn('⚠', summary)

    def test_empty_text(self):
        self.assertEqual(build_summary('', 0, 'Any Step'), '')

    def test_summary_equals_content_suppressed(self):
        # A single clean line with no errors should return empty summary
        log = 'No migrations to apply.'
        self.assertEqual(build_summary(log, 0, 'Django Migrate'), '')


# =============================================================================
# build_header_summary (public API)
# =============================================================================

class TestBuildHeaderSummary(unittest.TestCase):
    """Test the public build_header_summary() dispatcher."""

    def test_docker_buildkit_header(self):
        log = '[+] Building 4.2s (14/18) docker:default\n'
        header = build_header_summary(log, 0, 'Docker Rebuild')
        self.assertIn('18 Schritte', header)
        self.assertIn('4.2s', header)

    def test_docker_hash_header(self):
        log = '#1 DONE 0.5s\n#8 DONE 1.2s\n'
        header = build_header_summary(log, 0, 'Docker Rebuild')
        self.assertIn('8 Schritte', header)
        self.assertIn('1.7s', header)

    def test_docker_legacy_header(self):
        log = 'Step 1/7: FROM ubuntu\nStep 7/7: CMD\n'
        header = build_header_summary(log, 0, 'Docker Rebuild')
        self.assertIn('7 Schritte', header)

    def test_migrate_header(self):
        log = 'Applying admin.0001... OK\nApplying auth.0002... OK\n'
        header = build_header_summary(log, 0, 'Django Migrate')
        self.assertIn('2 Migration(en) angewendet', header)

    def test_migrate_no_migrations_header(self):
        log = 'Operations to perform:\nRunning migrations:\nNo migrations to apply.\n'
        header = build_header_summary(log, 0, 'Django Migrate')
        self.assertIn('Keine Migrationen anzuwenden', header)

    def test_collectstatic_header(self):
        log = "295 static files copied to '/code/static', 295 post-processed.\n"
        header = build_header_summary(log, 0, 'Django Collectstatic')
        self.assertIn('295 Dateien kopiert', header)

    def test_psql_header(self):
        log = 'CREATE TABLE\nCREATE TABLE\nCOPY 100\nCOPY 200\n'
        header = build_header_summary(log, 0, 'Clone Database')
        self.assertIn('2 Tabelle(n)', header)
        self.assertIn('300 Zeilen', header)

    def test_error_header(self):
        log = 'ERROR: connection refused\n'
        header = build_header_summary(log, 1, 'Any Step')
        self.assertEqual(header, 'ERROR: connection refused')

    def test_error_header_truncated(self):
        log = 'ERROR: ' + 'a' * 100 + '\n'
        header = build_header_summary(log, 1, 'Any Step')
        self.assertTrue(header.endswith('...'))
        self.assertEqual(len(header), 80)

    def test_empty_header(self):
        self.assertEqual(build_header_summary('', 0, 'Any Step'), '')

    def test_auto_detect_header(self):
        log = '[+] Building 4.2s (14/18)\n'
        header = build_header_summary(log, 0, '')
        self.assertIn('18 Schritte', header)

    def test_collectstatic_auto_detect(self):
        log = "295 static files copied to '/code/static', 295 post-processed.\n"
        header = build_header_summary(log, 0, '')
        self.assertIn('295 Dateien kopiert', header)


# =============================================================================
# Performance
# =============================================================================

class TestPerformance(unittest.TestCase):
    """Basic performance smoke tests to detect regressions."""

    def test_large_docker_log(self):
        """Simulate a large Docker build log with 500 steps."""
        lines = ['#0 building with default driver\n']
        for i in range(1, 501):
            lines.append(f'#{i} [app {i}/500] RUN step {i}\n')
            lines.append(f'#{i} DONE {i}.0s\n')
        log = ''.join(lines)

        start = time.perf_counter()
        build_summary(log, 0, 'Docker Rebuild')
        build_header_summary(log, 0, 'Docker Rebuild')
        elapsed = time.perf_counter() - start

        # Should complete in under 1 second for 500 steps
        self.assertLess(elapsed, 1.0, f'Large Docker log took {elapsed:.3f}s, expected < 1s')

    def test_large_psql_log(self):
        """Simulate a large pg_dump restore with 200 tables."""
        lines = []
        for i in range(200):
            lines.append(f'CREATE TABLE table_{i}\n')
            lines.append(f'COPY {i * 10}\n')
        log = ''.join(lines)

        start = time.perf_counter()
        build_summary(log, 0, 'Clone Database')
        build_header_summary(log, 0, 'Clone Database')
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 1.0, f'Large psql log took {elapsed:.3f}s, expected < 1s')

    def test_large_generic_log(self):
        """Simulate a large generic log with 1000 lines."""
        lines = [f'Line {i}: some output\n' for i in range(1000)]
        lines.insert(500, 'ERROR: something went wrong\n')
        log = ''.join(lines)

        start = time.perf_counter()
        build_summary(log, 0, 'Unknown Step')
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 1.0, f'Large generic log took {elapsed:.3f}s, expected < 1s')


if __name__ == '__main__':
    unittest.main()
