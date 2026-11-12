import io
import threading
from unittest import mock
from unittest.mock import patch

from django.test import TestCase, override_settings


@override_settings(PYTHON_BIN='python')
class RunParallelStepsTests(TestCase):
    """Test run_parallel_steps runs migration, collectstatic, and restart in parallel."""

    def _make_app(self):
        """Return a mock app with the attributes run_parallel_steps needs."""
        app = mock.MagicMock()
        app.static_files_mount.return_value = mock.MagicMock()
        return app

    def test_all_three_steps_called(self):
        """Migration, collectstatic, and restart are all invoked."""
        app = self._make_app()
        calls = []
        lock = threading.Lock()

        def capture_run(*args, **kwargs):
            with lock:
                calls.append((
                    'run',
                    args[2] if len(args) > 2 else kwargs.get('command', ''),
                ))
            return 0, b''

        def capture_restart(*args, **kwargs):
            with lock:
                calls.append(('restart',))
            return 0, b'started\n'

        with (
            patch(
                'adminconsole.util.docker._run_in_temp_container',
                side_effect=capture_run,
            ),
            patch(
                'adminconsole.util.docker._do_restart',
                side_effect=capture_restart,
            ),
        ):
            from adminconsole.util.docker import run_parallel_steps

            result = run_parallel_steps(app, 'test-app')

        self.assertEqual(result, [0, 0, 0])
        # Verify all three steps were called
        run_calls = [c for c in calls if c[0] == 'run']
        restart_calls = [c for c in calls if c[0] == 'restart']
        self.assertEqual(len(run_calls), 2)
        self.assertEqual(len(restart_calls), 1)
        # Check the commands
        commands = [c[1] for c in run_calls]
        self.assertIn('python -m manage migrate --noinput', commands)
        self.assertIn('python -m manage collectstatic --noinput -c', commands)

    def test_steps_run_in_parallel(self):
        """Migration and collectstatic start before either finishes; restart is sequential."""
        app = self._make_app()
        order = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def parallel_run(*args, **kwargs):
            with lock:
                order.append(('start', args[2] if len(args) > 2 else 'unknown'))
            barrier.wait(timeout=5)
            with lock:
                order.append(('end', args[2] if len(args) > 2 else 'unknown'))
            return 0, b''

        def parallel_restart(*args, **kwargs):
            with lock:
                order.append(('start', 'restart'))
            with lock:
                order.append(('end', 'restart'))
            return 0, b''

        with (
            patch(
                'adminconsole.util.docker._run_in_temp_container',
                side_effect=parallel_run,
            ),
            patch(
                'adminconsole.util.docker._do_restart',
                side_effect=parallel_restart,
            ),
        ):
            from adminconsole.util.docker import run_parallel_steps

            run_parallel_steps(app, 'test-app')

        # Migration and collectstatic should start before either ends
        run_starts = [
            i
            for i, (event, cmd) in enumerate(order)
            if event == 'start' and cmd != 'restart'
        ]
        run_ends = [
            i
            for i, (event, cmd) in enumerate(order)
            if event == 'end' and cmd != 'restart'
        ]
        self.assertEqual(len(run_starts), 2)
        self.assertEqual(len(run_ends), 2)
        # Both parallel steps should start before either ends
        self.assertLess(max(run_starts), min(run_ends))
        # Restart should happen after both parallel steps have ended
        restart_start = next(
            i
            for i, (event, cmd) in enumerate(order)
            if event == 'start' and cmd == 'restart'
        )
        self.assertGreater(restart_start, max(run_ends))

    def test_returns_exit_codes(self):
        """Return value contains exit codes for migrate, collectstatic, restart."""
        app = self._make_app()

        def failing_run(*args, **kwargs):
            cmd = args[2] if len(args) > 2 else ''
            if 'collectstatic' in cmd:
                return 1, b'error'
            return 0, b''

        def failing_restart(*args, **kwargs):
            return 2, b'failed'

        with (
            patch(
                'adminconsole.util.docker._run_in_temp_container',
                side_effect=failing_run,
            ),
            patch(
                'adminconsole.util.docker._do_restart',
                side_effect=failing_restart,
            ),
        ):
            from adminconsole.util.docker import run_parallel_steps

            result = run_parallel_steps(app, 'test-app')

        self.assertEqual(result, [0, 1, 2])

    def test_output_printed_in_order(self):
        """Output blocks are printed sequentially: migrate, collectstatic, restart."""
        app = self._make_app()

        def tagged_run(*args, **kwargs):
            cmd = args[2] if len(args) > 2 else ''
            if 'migrate' in cmd:
                return 0, b'migrate_output\n'
            return 0, b'collectstatic_output\n'

        def tagged_restart(*args, **kwargs):
            return 0, b'restart_output\n'

        stdout = io.StringIO()
        with (
            patch(
                'adminconsole.util.docker._run_in_temp_container',
                side_effect=tagged_run,
            ),
            patch(
                'adminconsole.util.docker._do_restart',
                side_effect=tagged_restart,
            ),
            patch('sys.stdout', stdout),
        ):
            from adminconsole.util.docker import run_parallel_steps

            run_parallel_steps(app, 'test-app')

        output = stdout.getvalue()
        # Headers should appear in order
        migrate_idx = output.index('# Django Migrate')
        collectstatic_idx = output.index('# Django Collectstatic')
        restart_idx = output.index('# Docker Start')
        self.assertLess(migrate_idx, collectstatic_idx)
        self.assertLess(collectstatic_idx, restart_idx)
        # Each output should follow its header
        self.assertLess(migrate_idx, output.index('migrate_output'))
        self.assertLess(collectstatic_idx, output.index('collectstatic_output'))
        self.assertLess(restart_idx, output.index('restart_output'))
