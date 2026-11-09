import contextlib
import io
import shutil
import tempfile
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, Client, override_settings, modify_settings
from django.urls import reverse

from adminconsole.models import App, AppEnv


@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
@override_settings(PYTHON_BIN='python')
class StagingCreationTests(TestCase):
    """Test the staging creation flow: views, management command, and redirects."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        for patcher in [
            mock.patch.object(
                App, 'dir', new=property(lambda app: self.base / app.name)
            ),
            mock.patch.object(
                App, 'work_dir', new=property(lambda app: self.base / app.name)
            ),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.owner = User.objects.create_user('owner', password='pw')
        self.prod_app = App.objects.create(
            name='prod-app',
            port=8010,
            git_clone_url='https://github.com/example/repo.git',
            git_branch='main',
            user=self.owner,
        )
        AppEnv.objects.create(
            app=self.prod_app,
            juntagrico_database_host='localhost',
            juntagrico_database_name='prod_db',
            juntagrico_database_password='secret',
        )
        self.client = Client()
        self.client.force_login(self.owner)

    # ------------------------------------------------------------------
    # staging.py: create view
    # ------------------------------------------------------------------

    def test_create_get_shows_form_when_no_staging_exists(self):
        """GET on staging-create shows the submit form when no staging exists."""
        resp = self.client.get(reverse('staging-create', args=[self.prod_app.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'generic/submit.html')
        self.assertIn('Staging für prod-app einrichten', resp.content.decode())

    def test_create_get_redirects_when_staging_already_installed(self):
        """GET redirects to overview if staging already exists and is installed."""
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
            installation_pending=False,
        )
        with patch('docker.from_env'):
            resp = self.client.get(reverse('staging-create', args=[self.prod_app.id]))
        self.assertRedirects(
            resp, reverse('overview', args=[staging.id]), fetch_redirect_response=False
        )

    def test_create_get_shows_form_when_staging_pending(self):
        """GET shows the form if staging exists but installation is still pending."""
        App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
            installation_pending=True,
        )
        resp = self.client.get(reverse('staging-create', args=[self.prod_app.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'generic/submit.html')

    def test_create_get_error_when_app_is_already_staging(self):
        """GET shows error if the target app is itself a staging app."""
        staging = App.objects.create(
            name='some-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        with patch('docker.from_env'):
            resp = self.client.get(reverse('staging-create', args=[staging.id]))
        self.assertRedirects(
            resp, reverse('overview', args=[staging.id]), fetch_redirect_response=False
        )

    def test_create_post_creates_staging_app(self):
        """POST creates a new staging App and spawns setup_staging."""
        with patch('subprocess.Popen') as mock_popen:
            mock_popen.return_value.pid = 12345
            resp = self.client.post(reverse('staging-create', args=[self.prod_app.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'flow/wait_redeploy.html')
        staging = App.objects.get(name='prod-app-staging')
        self.assertEqual(staging.staging_of, self.prod_app)
        self.assertEqual(staging.git_clone_url, self.prod_app.git_clone_url)
        self.assertEqual(staging.git_branch, self.prod_app.git_branch)
        self.assertEqual(staging.port, 10000 + self.prod_app.port)
        self.assertTrue(staging.installation_pending)
        self.assertEqual(staging.version, 2)

        # Verify subprocess was spawned
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        self.assertIn('setup_staging', call_args[0][0])
        self.assertIn('prod-app-staging', call_args[0][0])

    def test_create_post_reuses_pending_staging(self):
        """POST reuses an existing pending staging instead of creating a duplicate."""
        App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
            installation_pending=True,
        )
        with patch('subprocess.Popen') as mock_popen:
            mock_popen.return_value.pid = 12345
            self.client.post(reverse('staging-create', args=[self.prod_app.id]))

        # Should have reused the existing app, not created a new one
        self.assertEqual(App.objects.filter(name='prod-app-staging').count(), 1)
        self.assertEqual(mock_popen.call_count, 1)

    def test_create_post_resets_properties_on_reuse(self):
        """POST resets staging properties from current prod app on reuse."""
        existing = App.objects.create(
            name='old-name-staging',
            port=19999,
            staging_of=self.prod_app,
            user=self.owner,
            git_clone_url='https://old-url.git',
            git_branch='old-branch',
            installation_pending=True,
        )
        # Simulate prod app changed
        self.prod_app.git_clone_url = 'https://github.com/example/updated.git'
        self.prod_app.git_branch = 'develop'
        self.prod_app.save()

        with patch('subprocess.Popen') as mock_popen:
            mock_popen.return_value.pid = 12345
            self.client.post(reverse('staging-create', args=[self.prod_app.id]))

        existing.refresh_from_db()
        self.assertEqual(existing.name, 'prod-app-staging')
        self.assertEqual(
            existing.git_clone_url, 'https://github.com/example/updated.git'
        )
        self.assertEqual(existing.git_branch, 'develop')
        self.assertEqual(existing.port, 10000 + self.prod_app.port)
        self.assertTrue(existing.installation_pending)

    def test_create_post_redirects_when_staging_installed(self):
        """POST redirects to overview if staging already exists and is installed."""
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
            installation_pending=False,
        )
        with patch('docker.from_env'):
            resp = self.client.post(reverse('staging-create', args=[self.prod_app.id]))
        self.assertRedirects(
            resp, reverse('overview', args=[staging.id]), fetch_redirect_response=False
        )

    # ------------------------------------------------------------------
    # setup_staging management command
    # ------------------------------------------------------------------

    def test_setup_staging_requires_staging_app(self):
        """Command fails if the app is not a staging app."""
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            call_command('setup_staging', self.prod_app.name)
        output = stdout.getvalue()
        self.assertIn('is not a staging app', output)
        self.assertIn('Return 1', output)

    def test_setup_staging_re_clones_if_code_dir_exists(self):
        """Step 1 always runs git clone (which deletes existing code dir first)."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        staging.code_dir.mkdir(parents=True)

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.setup_staging.git_clone',
                return_value=True,
            ) as mock_clone,
            mock.patch('adminconsole.management.commands.setup_staging.call_command'),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.run_parallel_steps',
                return_value=[0, 0, 0],
            ),
        ):
            call_command('setup_staging', staging.name)

        mock_clone.assert_called_once()

    def test_setup_staging_clones_if_code_dir_missing(self):
        """Step 1 runs git clone if code directory does not exist."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        # code_dir does not exist

        with (
            mock.patch(
                'adminconsole.management.commands.setup_staging.git_clone',
                return_value=True,
            ) as mock_clone,
            mock.patch('adminconsole.management.commands.setup_staging.call_command'),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.run_parallel_steps',
                return_value=[0, 0, 0],
            ),
        ):
            call_command('setup_staging', staging.name)

        mock_clone.assert_called_once()

    def test_setup_staging_copies_appenv(self):
        """Step 2 copies AppEnv from production if staging has no AppEnv."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        staging.code_dir.mkdir(parents=True)

        with (
            mock.patch('adminconsole.management.commands.setup_staging.call_command'),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.run_parallel_steps',
                return_value=[0, 0, 0],
            ),
        ):
            call_command('setup_staging', staging.name)

        staging.refresh_from_db()
        self.assertTrue(hasattr(staging, 'env'))
        staging_env = staging.env
        self.assertEqual(staging_env.juntagrico_database_host, 'localhost')
        self.assertEqual(staging_env.juntagrico_database_name, 'prod_db')
        self.assertEqual(staging_env.juntagrico_email_user, '')
        self.assertEqual(staging_env.juntagrico_email_password, '')

    def test_setup_staging_skips_appenv_if_exists(self):
        """Step 2 does not overwrite existing AppEnv."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        staging.code_dir.mkdir(parents=True)
        AppEnv.objects.create(
            app=staging,
            juntagrico_database_host='custom-host',
            juntagrico_database_name='custom-db',
        )

        with (
            mock.patch('adminconsole.management.commands.setup_staging.call_command'),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.run_parallel_steps',
                return_value=[0, 0, 0],
            ),
        ):
            call_command('setup_staging', staging.name)

        staging.refresh_from_db()
        self.assertEqual(staging.env.juntagrico_database_host, 'custom-host')

    def test_setup_staging_marks_installation_complete(self):
        """After success, installation_pending is set to False."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
            installation_pending=True,
        )
        staging.code_dir.mkdir(parents=True)

        with (
            mock.patch(
                'adminconsole.management.commands.setup_staging.call_command',
                return_value=0,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.run_parallel_steps',
                return_value=[0, 0, 0],
            ),
        ):
            call_command('setup_staging', staging.name)

        staging.refresh_from_db()
        self.assertFalse(staging.installation_pending)

    def test_setup_staging_aborts_on_git_clone_failure(self):
        """Command stops if git clone fails."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.setup_staging.git_clone',
                return_value=False,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.call_command'
            ) as mock_call,
        ):
            call_command('setup_staging', staging.name)

        output = stdout.getvalue()
        self.assertIn('Return 1', output)
        mock_call.assert_not_called()

    def test_setup_staging_aborts_on_clone_db_failure(self):
        """Command stops if clone_db fails."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        staging.code_dir.mkdir(parents=True)

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.setup_staging.call_command',
                return_value=1,
            ),
        ):
            call_command('setup_staging', staging.name)

        output = stdout.getvalue()
        self.assertIn('Return 1', output)

    def test_setup_staging_aborts_on_domain_failure(self):
        """Command stops if setup_domain fails."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        staging.code_dir.mkdir(parents=True)

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.setup_staging.call_command',
                return_value=0,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=False,
            ),
        ):
            call_command('setup_staging', staging.name)

        output = stdout.getvalue()
        self.assertIn('Return 1', output)

    def test_setup_staging_aborts_on_rebuild_failure(self):
        """Command stops if rebuild fails."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        staging.code_dir.mkdir(parents=True)

        def selective_call_command(cmd, *args, **kwargs):
            if cmd == 'clone_db':
                return 0
            if cmd == 'rebuild':
                return 1
            return 0

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.setup_staging.call_command',
                side_effect=selective_call_command,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
        ):
            call_command('setup_staging', staging.name)

        output = stdout.getvalue()
        self.assertIn('Return 1', output)

    def test_setup_staging_aborts_on_parallel_steps_failure(self):
        """Command stops if parallel migration/collectstatic/restart fails."""
        staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        staging.code_dir.mkdir(parents=True)

        def selective_call_command(cmd, *args, **kwargs):
            return 0

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.setup_staging.call_command',
                side_effect=selective_call_command,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.run_parallel_steps',
                return_value=[0, 1, 0],
            ),
        ):
            call_command('setup_staging', staging.name)

        output = stdout.getvalue()
        self.assertIn('Return 1', output)

    # ------------------------------------------------------------------
    # overview view: staging redirects
    # ------------------------------------------------------------------

    def test_overview_redirects_pending_staging_to_create(self):
        """Overview redirects staging with installation_pending to staging-create."""
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
            installation_pending=True,
        )
        resp = self.client.get(reverse('overview', args=[staging.id]))
        self.assertRedirects(
            resp,
            reverse('staging-create', args=[self.prod_app.id]),
            fetch_redirect_response=False,
        )

    def test_overview_does_not_redirect_installed_staging(self):
        """Overview shows normal page for installed staging app."""
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
            installation_pending=False,
        )
        with patch.object(
            App, 'running', new_callable=mock.PropertyMock
        ) as mock_running:
            mock_running.return_value = False
            resp = self.client.get(reverse('overview', args=[staging.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'app/overview.html')

    def test_overview_redirects_pending_prod_to_env_form(self):
        """Overview redirects production app with installation_pending to env form."""
        self.prod_app.installation_pending = True
        self.prod_app.save()
        resp = self.client.get(reverse('overview', args=[self.prod_app.id]))
        self.assertRedirects(
            resp,
            reverse('ca-create-env', args=[self.prod_app.id]),
            fetch_redirect_response=False,
        )

    # ------------------------------------------------------------------
    # staging_result view:
    # ------------------------------------------------------------------

    def test_staging_result_no_retry_url_for_successful_staging(self):
        """staging_result does not include retry_url when all sections succeed."""
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        log_content = '# Git Clone\nReturn 0\n# AppEnv kopieren\nReturn 0\n'
        Path(staging.log_file).write_text(log_content)

        resp = self.client.get(reverse('staging-result', args=[staging.id]))
        self.assertFalse(resp.context['overall_failed'])
        self.assertNotIn('retry_url', resp.context)

    def test_show_result_no_retry_url_for_prod_app(self):
        """show_result does not include retry_url for non-staging apps."""
        # Write a log file with a failed section for a production app
        log_content = '# Setup\nerror\nReturn 1\n'
        Path(self.prod_app.log_file).write_text(log_content)

        resp = self.client.get(reverse('show-result', args=[self.prod_app.id]))
        self.assertTrue(resp.context['overall_failed'])
        self.assertNotIn('retry_url', resp.context)

    # ------------------------------------------------------------------
    # clone_db and renew views
    # ------------------------------------------------------------------

    def test_clone_db_view(self):
        """clone_db view spawns the clone_db command."""
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        with patch('subprocess.Popen') as mock_popen:
            mock_popen.return_value.pid = 99999
            resp = self.client.post(reverse('staging-clone-db', args=[staging.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'flow/wait_next.html')
        call_args = mock_popen.call_args
        self.assertIn('clone_db', call_args[0][0])

    def test_renew_view(self):
        """renew view calls app.renew() and redirects to overview."""
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        with patch('docker.from_env'):
            resp = self.client.post(reverse('staging-renew', args=[staging.id]))
        self.assertRedirects(
            resp, reverse('overview', args=[staging.id]), fetch_redirect_response=False
        )
        staging.refresh_from_db()
        self.assertIsNotNone(staging.run_until)

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def test_create_denied_for_other_user(self):
        """Non-owner cannot create staging for an app they don't own."""
        other = User.objects.create_user('other', password='pw')
        self.client.force_login(other)
        resp = self.client.get(reverse('staging-create', args=[self.prod_app.id]))
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)

    def test_clone_db_denied_for_other_user(self):
        """Non-owner cannot clone DB for an app they don't own."""
        other = User.objects.create_user('other', password='pw')
        staging = App.objects.create(
            name='prod-app-staging',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        self.client.force_login(other)
        resp = self.client.post(reverse('staging-clone-db', args=[staging.id]))
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)

    def test_create_allowed_for_superuser(self):
        """Superuser can create staging for any app."""
        superuser = User.objects.create_superuser('admin', password='pw')
        self.client.force_login(superuser)
        resp = self.client.get(reverse('staging-create', args=[self.prod_app.id]))
        self.assertEqual(resp.status_code, 200)


@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class CloneDbCommandTests(TestCase):
    """Test the clone_db management command directly."""

    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pw')
        self.prod_app = App.objects.create(
            name='prod-app',
            port=8010,
            git_clone_url='https://github.com/example/repo.git',
            git_branch='main',
            user=self.owner,
        )
        AppEnv.objects.create(
            app=self.prod_app,
            juntagrico_database_host='localhost',
            juntagrico_database_name='prod_db',
            juntagrico_database_password='secret',
        )
        self.staging = App.objects.create(
            name='staging-app',
            port=18010,
            staging_of=self.prod_app,
            user=self.owner,
        )
        AppEnv.objects.create(
            app=self.staging,
            juntagrico_database_host='localhost',
            juntagrico_database_name='staging_db',
            juntagrico_database_password='pw',
            juntagrico_database_user='staging_user',
        )

    def test_clone_db_timeout_kills_processes(self):
        """When pg_dump | psql exceeds timeout, processes are killed and command returns 1."""
        import subprocess
        from adminconsole.management.commands.clone_db import Command

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.clone_db.create_database',
                return_value=True,
            ),
            mock.patch('subprocess.Popen') as mock_popen,
        ):
            dump_mock = mock.MagicMock()
            load_mock = mock.MagicMock()
            dump_mock.communicate.side_effect = subprocess.TimeoutExpired(
                'pg_dump', 300
            )
            mock_popen.side_effect = [load_mock, dump_mock]
            cmd = Command()
            result = cmd.handle(
                app_name=[self.staging.name], timeout=300, no_restart=False
            )

        self.assertEqual(result, 1)
        dump_mock.kill.assert_called_once()
        load_mock.kill.assert_called_once()
        output = stdout.getvalue()
        self.assertIn('timed out', output)
        self.assertIn('Return 1', output)

    def test_clone_db_default_timeout(self):
        """The default timeout is 300 seconds."""
        import subprocess
        from adminconsole.management.commands.clone_db import Command

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch(
                'adminconsole.management.commands.clone_db.create_database',
                return_value=True,
            ),
            mock.patch('subprocess.Popen') as mock_popen,
        ):
            dump_mock = mock.MagicMock()
            load_mock = mock.MagicMock()
            dump_mock.communicate.side_effect = subprocess.TimeoutExpired(
                'pg_dump', 300
            )
            mock_popen.side_effect = [load_mock, dump_mock]
            cmd = Command()
            cmd.handle(app_name=[self.staging.name], timeout=300, no_restart=False)

        output = stdout.getvalue()
        self.assertIn('300', output)

    def test_setup_staging_passes_timeout_to_clone_db(self):
        """setup_staging passes --timeout through to clone_db."""
        import shutil
        from pathlib import Path
        import tempfile

        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)

        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            mock.patch.object(App, 'dir', new=property(lambda app: base / app.name)),
            mock.patch(
                'adminconsole.management.commands.setup_staging.git_clone',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.call_command',
            ) as mock_call,
            mock.patch(
                'adminconsole.management.commands.setup_staging.setup_domain',
                return_value=True,
            ),
            mock.patch(
                'adminconsole.management.commands.setup_staging.run_parallel_steps',
                return_value=[0, 0, 0],
            ),
        ):
            call_command('setup_staging', self.staging.name, timeout=120)

        # Find the clone_db call among all call_command invocations
        clone_db_calls = [
            c for c in mock_call.call_args_list if c[0] and c[0][0] == 'clone_db'
        ]
        self.assertEqual(len(clone_db_calls), 1)
        self.assertIn('--timeout', clone_db_calls[0][0])
        # --timeout is followed by the value 120
        timeout_idx = list(clone_db_calls[0][0]).index('--timeout')
        self.assertEqual(clone_db_calls[0][0][timeout_idx + 1], 120)
