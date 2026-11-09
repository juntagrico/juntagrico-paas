import base64
import os
import shutil
import smtplib
import socket
import ssl
import string
import subprocess  # nosec: B404
import sys
import tempfile
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import TestCase, Client, override_settings, modify_settings, tag
from docker.errors import NotFound

from adminconsole.models import App, AppEnv
from adminconsole.util import generate_password, generate_secret_key
from adminconsole.util.admin import PASSWORD_ENV, SET_PASSWORD_SCRIPT
from adminconsole.util.git import git_clone, github_auth_env, remove_credentials
from adminconsole.util.network import NetworkMismatch


TOKEN = 'gho_TestToken123'  # nosec: B105


def git(*args, cwd):
    return subprocess.run(  # nosec B603, B607
        ['git', *args], capture_output=True, text=True, cwd=cwd, check=True
    ).stdout.strip()


# The GitHub token must never be stored in an app repository, which is mounted into the app container.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
@override_settings(TEST_LOCALHOST=False)
class GitCredentialTests(TestCase):
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
            # git must not find a repository outside of the test directory
            mock.patch.dict('os.environ', {'GIT_CEILING_DIRECTORIES': str(self.base)}),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_app(self, name, origin=None):
        app = App.objects.create(name=name, port=8010 + App.objects.count())
        if origin is not None:
            app.code_dir.mkdir(parents=True)
            git('init', '-q', cwd=app.code_dir)
            git('remote', 'add', 'origin', origin, cwd=app.code_dir)
        return app

    def test_auth_env_sends_token_only_to_github(self):
        env = github_auth_env(TOKEN)
        header = env['GIT_CONFIG_VALUE_0']
        self.assertEqual(
            base64.b64decode(header.removeprefix('Authorization: Basic ')).decode(),
            f'x-access-token:{TOKEN}',
        )
        # ask git itself which urls get the header
        for url, expected in [
            ('https://github.com/juntagrico/foo.git', header),
            ('https://example.org/foo.git', None),
            ('https://github.com.example.org/foo.git', None),
            ('http://github.com/juntagrico/foo.git', None),
        ]:
            with self.subTest(url=url):
                proc = subprocess.run(  # nosec: B603, B607
                    ['git', 'config', '--get-urlmatch', 'http.extraHeader', url],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                self.assertEqual(proc.stdout.strip() or None, expected)

    def test_auth_env_disables_credential_helpers(self):
        # Replace system and global git config by a helper that hands out stored credentials.
        # The real credential store of the machine running the tests is never asked.
        config = self.base / 'gitconfig'
        config.write_text(
            '[credential]\n\thelper = "!f() { echo username=stored; echo password=StoredSecret; }; f"\n'
        )
        request = 'protocol=https\nhost=example.invalid\n\n'
        isolated = {
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': str(config),
            'GIT_TERMINAL_PROMPT': '0',
            'GCM_INTERACTIVE': 'never',
        }
        with mock.patch.dict('os.environ', isolated):
            # without the token environment, git asks the helper
            proc = subprocess.run(  # nosec: B603, B607
                ['git', 'credential', 'fill'],
                input=request,
                capture_output=True,
                text=True,
                cwd=self.base,
            )
            self.assertIn('password=StoredSecret', proc.stdout)
            # with it, no helper is asked
            proc = subprocess.run(  # nosec: B603, B607
                ['git', 'credential', 'fill'],
                input=request,
                capture_output=True,
                text=True,
                cwd=self.base,
                env=github_auth_env(TOKEN),
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn('StoredSecret', proc.stdout)

    def test_clone_does_not_store_token(self):
        # clone a real local repository, passing a token
        source = self.base / 'source'
        source.mkdir()
        git('init', '-q', '-b', 'main', cwd=source)
        git(
            '-c',
            'user.name=t',
            '-c',
            'user.email=t@example.org',
            'commit',
            '-q',
            '--allow-empty',
            '-m',
            'init',
            cwd=source,
        )
        app = App.objects.create(name='foo', port=8010, git_clone_url=source.as_uri())
        app.work_dir.mkdir()

        with (
            mock.patch.object(app, 'get_installation_token', return_value=TOKEN),
            mock.patch(
                'adminconsole.util.git.subprocess.run', wraps=subprocess.run
            ) as run,
        ):
            self.assertTrue(git_clone(app))

        args, kwargs = run.call_args
        self.assertNotIn(TOKEN, ' '.join(str(a) for a in args[0]))
        self.assertEqual(kwargs['env'], github_auth_env(TOKEN))
        self.assertEqual(
            git('remote', 'get-url', 'origin', cwd=app.code_dir), source.as_uri()
        )
        encoded = base64.b64encode(f'x-access-token:{TOKEN}'.encode()).decode()
        for file in (app.code_dir / '.git').rglob('*'):
            if file.is_file():
                content = file.read_bytes()
                self.assertNotIn(TOKEN.encode(), content, file)
                self.assertNotIn(encoded.encode(), content, file)

    def test_clone_without_token(self):
        app = App.objects.create(
            name='foo', port=8010, git_clone_url='https://github.com/a/b.git@main'
        )
        with (
            mock.patch.object(app, 'get_installation_token', return_value=None),
            mock.patch('adminconsole.util.git.subprocess.run') as run,
        ):
            run.return_value = mock.MagicMock(returncode=0, stdout=b'')
            git_clone(app)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ['git', 'clone', '-b', 'main', '--depth=1'])
        self.assertEqual(args[0][5], 'https://github.com/a/b.git@main')
        self.assertEqual(Path(args[0][6]), app.code_dir)
        self.assertIsNone(kwargs['env'])

    def test_remove_credentials(self):
        for url, expected in [
            (
                f'https://x-access-token:{TOKEN}@github.com/a/b.git',
                'https://github.com/a/b.git',
            ),
            ('https://user@github.com/a/b.git', 'https://github.com/a/b.git'),
            ('https://github.com/a/b.git', 'https://github.com/a/b.git'),
            (
                'git@github.com:a/b.git',
                'git@github.com:a/b.git',
            ),  # ssh, no credentials stored
        ]:
            with self.subTest(url=url):
                self.assertEqual(remove_credentials(url), expected)


SETUP_DIR = Path(__file__).resolve().parent.parent.parent / 'setup'
CERTBOT_WRAPPER = '/usr/local/sbin/juntagrico-certbot'


# The juntagrico user may run only the certbot wrapper as root, which must not accept additional arguments.
class CertbotWrapperTests(TestCase):
    def setUp(self):
        if not shutil.which('sh'):
            self.skipTest('needs a POSIX shell')
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        # replace certbot by a stub that records its arguments
        self.log = self.base / 'certbot-args'
        stub = self.base / 'certbot'
        stub.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$@" > "{self.log.as_posix()}"\n', newline='\n'
        )
        stub.chmod(0o755)
        script = (SETUP_DIR / 'juntagrico-certbot').read_text().replace('\r\n', '\n')
        self.assertIn('exec /usr/local/bin/certbot ', script)
        self.wrapper = self.base / 'juntagrico-certbot'
        self.wrapper.write_text(
            script.replace('/usr/local/bin/certbot', stub.as_posix()), newline='\n'
        )

    def run_wrapper(self, *args):
        return subprocess.run(  # nosec: B603, B607
            ['sh', self.wrapper.as_posix(), *args], capture_output=True, text=True
        )

    def test_valid_domain(self):
        proc = self.run_wrapper('foo.juntagrico.app')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self.log.read_text().split('\n')[:-1],
            ['--nginx', '--redirect', '--keep', '-n', '-d', 'foo.juntagrico.app'],
        )

    def test_rejects_invalid_arguments(self):
        for args in [
            (),
            ('',),
            ('foo.juntagrico.app', '--pre-hook=id'),
            ('--pre-hook=id',),
            ('-d',),
            ('foo.juntagrico.app --pre-hook=id',),
            ('foo.juntagrico.app;id',),
            ('$(id).juntagrico.app',),
            ('foo/bar.ch',),
            ('.foo.ch',),
            ('foo..ch',),
            ('föö.ch',),
            ('foo.ch\nbar.ch',),
        ]:
            with self.subTest(args=args):
                proc = self.run_wrapper(*args)
                self.assertEqual(proc.returncode, 2)
                self.assertFalse(self.log.exists(), 'certbot was called')

    def test_sudo_rule_allows_only_the_wrapper(self):
        rule = (SETUP_DIR / '50-juntagrico-paas').read_text().strip()
        self.assertEqual(rule, f'juntagrico ALL=(root) NOPASSWD: {CERTBOT_WRAPPER}')

    def test_add_domain_uses_wrapper(self):
        app = App.objects.create(name='foo', port=8010)
        app.domains.create(name='foo.example.org')
        with (
            mock.patch(
                'adminconsole.management.commands.add_domain.open',
                mock.mock_open(),
                create=True,
            ),
            mock.patch('subprocess.run') as run,
        ):
            run.return_value = mock.MagicMock(stdout=b'')
            call_command('add_domain', 'foo.example.org')
        self.assertIn(
            mock.call(
                ['sudo', CERTBOT_WRAPPER, 'foo.example.org'], stdout=subprocess.PIPE
            ),
            run.call_args_list,
        )


# New apps are generated from a pinned version of the template, without running its hooks.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class CookiecutterTests(TestCase):
    def test_template_is_pinned_and_hooks_are_disabled(self):
        user = User.objects.create_user('owner')
        app = App.objects.create(name='foo', port=8010, user=user)
        self.client.force_login(user)
        data = {
            'project_slug': 'foo',
            'organisation_name': 'Solawi Foo',
            'street': 'Weg',
            'number': '1',
            'zip': '8000',
            'city': 'Zürich',
            'PC': '80-1-1',
            'IBAN': 'CH00',
            'BIC': 'X',
            'NAME': 'Bank',
            'info_email': 'a@b.ch',
            'share_price': '250',
        }
        with mock.patch('adminconsole.views.create.cookiecutter') as cookiecutter:
            self.client.post(f'/ck/form/{app.id}/', data)

        kwargs = cookiecutter.call_args.kwargs
        self.assertRegex(
            kwargs['checkout'], '^[0-9a-f]{40}$'
        )  # a commit, not a branch or tag that can move
        self.assertIs(kwargs['accept_hooks'], False)

    def test_always_goes_to_env_form(self):
        """Cookiecutter runs git push directly and redirects to env form on success."""
        user = User.objects.create_user('owner')
        app = App.objects.create(name='baz', port=8012, user=user)
        self.client.force_login(user)
        data = {
            'project_slug': 'baz',
            'organisation_name': 'Solawi Baz',
            'street': 'Weg',
            'number': '1',
            'zip': '8000',
            'city': 'Zürich',
            'PC': '80-1-1',
            'IBAN': 'CH00',
            'BIC': 'X',
            'NAME': 'Bank',
            'info_email': 'a@b.ch',
            'share_price': '250',
        }
        with (
            mock.patch('adminconsole.views.create.cookiecutter'),
            mock.patch('adminconsole.views.create.test_localhost', return_value=False),
            mock.patch('adminconsole.views.create.git_push_app', return_value=True),
        ):
            resp = self.client.post(f'/ck/form/{app.id}/', data)
        # Should redirect to env form (git push runs directly, no intermediate step)
        self.assertRedirects(
            resp, f'/ca/env/form/{app.id}/', fetch_redirect_response=False
        )


class SecretGenerationTests(TestCase):
    def test_generators_use_secrets(self):
        with mock.patch(
            'adminconsole.util.secrets.choice', wraps=__import__('secrets').choice
        ) as choice:
            password, key = generate_password(), generate_secret_key()
        self.assertEqual(choice.call_count, 70)
        self.assertEqual(len(password), 20)
        self.assertTrue(set(password) <= set(string.ascii_uppercase + string.digits))
        self.assertEqual(len(key), 50)
        self.assertTrue(
            set(key) <= set(string.ascii_letters + string.digits + string.punctuation)
        )


# The admin password of an instance is independent of the database password and never appears in a command line.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
@override_settings(PYTHON_BIN='python')
class AdminPasswordTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('owner', password='pw')  # nosec: B106
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        AppEnv.objects.create(app=self.app, juntagrico_database_password='DBPASSWORD')  # nosec: B106
        self.client.force_login(self.owner)
        patcher = mock.patch('docker.from_env')
        self.container = patcher.start().return_value.containers.get.return_value
        self.addCleanup(patcher.stop)
        self.container.exec_run.return_value = mock.MagicMock(exit_code=0, output=b'')

    def assert_not_cached(self, response):
        self.assertIn('no-store', response['Cache-Control'])

    def test_create_admin_command(self):
        with mock.patch.dict(os.environ, {PASSWORD_ENV: 'NEWPASSWORD'}):
            call_command('create_admin', 'foo')
        args, kwargs = self.container.exec_run.call_args
        self.assertEqual(
            args[0], ['python', '-m', 'manage', 'createadmin', '--noinput']
        )
        self.assertEqual(kwargs['environment']['DJANGO_SUPERUSER_USERNAME'], 'admin')
        self.assertEqual(
            kwargs['environment']['DJANGO_SUPERUSER_PASSWORD'], 'NEWPASSWORD'
        )

    def test_create_admin_command_requires_password(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PASSWORD_ENV, None)
            with self.assertRaises(CommandError):
                call_command('create_admin', 'foo')
        self.assertFalse(self.container.exec_run.called)

    def test_reset_admin_password(self):
        response = self.client.post(f'/app/{self.app.id}/admin-password/')

        args, kwargs = self.container.exec_run.call_args
        password = kwargs['environment'][PASSWORD_ENV]
        self.assertEqual(
            args[0], ['python', '-m', 'manage', 'shell', '-c', SET_PASSWORD_SCRIPT]
        )
        self.assertNotIn(password, ' '.join(args[0]))
        self.assertNotEqual(password, 'DBPASSWORD')
        self.assertTemplateUsed(response, 'app/admin_password.html')
        self.assertContains(response, password)
        self.assert_not_cached(response)
        self.assertNotIn('messages', response.cookies)

    def test_reset_admin_password_failures(self):
        for description, exec_run in [
            (
                'no admin user',
                {'return_value': mock.MagicMock(exit_code=1, output=b'DoesNotExist')},
            ),
            ('container not found', {'side_effect': NotFound('no such container')}),
        ]:
            with self.subTest(description):
                self.container.exec_run.reset_mock(return_value=True, side_effect=True)
                self.container.exec_run.configure_mock(**exec_run)
                response = self.client.post(f'/app/{self.app.id}/admin-password/')
                self.assertRedirects(
                    response, f'/overview/{self.app.id}/', fetch_redirect_response=False
                )

    def test_set_password_script(self):
        # run the script that is executed in the app container against this test database
        admin = User.objects.create_user('admin', password='old')  # nosec: B106
        with mock.patch.dict(os.environ, {PASSWORD_ENV: 'NEWPASSWORD'}):
            exec(SET_PASSWORD_SCRIPT, {})  # nosec: B102
        admin.refresh_from_db()
        self.assertTrue(admin.check_password('NEWPASSWORD'))
        self.assertFalse(admin.check_password('old'))


REAL_GETADDRINFO = socket.getaddrinfo


def resolves_to(*addresses):
    """simulated result of socket.getaddrinfo"""
    return [
        (
            socket.AF_INET6 if ':' in a else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            '',
            (a, 25),
        )
        for a in addresses
    ]


# The SMTP connection test runs in the console and must not reach its own network.
class SmtpCheckTests(TestCase):
    def setUp(self):
        for name, target in [
            ('getaddrinfo', 'adminconsole.forms.socket.getaddrinfo'),
            ('get_connection', 'adminconsole.forms.get_connection'),
        ]:
            patcher = mock.patch(target)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.getaddrinfo.return_value = resolves_to('8.8.8.8')

    def form(self, **data):
        from adminconsole.forms import EnvForm

        return EnvForm({
            'juntagrico_secret_key': 'x' * 50,
            'juntagrico_email_host': 'mail.example.org',
            'juntagrico_email_port': '587',
            'juntagrico_email_security': 'tls',
            **data,
        })

    def assert_rejected_without_connection(self, form, message):
        self.assertFalse(form.is_valid())
        self.assertIn(message, form.non_field_errors()[0])
        self.assertFalse(self.get_connection.called, 'a connection was made')

    def test_public_server_is_checked(self):
        self.assertTrue(self.form().is_valid())
        self.assertEqual(
            self.get_connection.call_args.kwargs['host'], 'mail.example.org'
        )
        self.assertEqual(self.get_connection.call_args.kwargs['port'], 587)
        self.assertTrue(self.get_connection.return_value.open.called)

    def test_other_ports_are_not_checked(self):
        for port in ['22', '80', '5432', '2375', '8010']:
            with self.subTest(port=port):
                form = self.form(juntagrico_email_port=port)
                self.assertFalse(form.is_valid())
                self.assertIn('juntagrico_email_port', form.errors)

    def test_internal_addresses_are_not_checked(self):
        for addresses in [
            ('127.0.0.1',),
            ('10.20.0.1',),
            ('192.168.1.1',),
            ('172.17.0.1',),
            ('169.254.169.254',),
            ('100.64.0.1',),
            ('0.0.0.0',),  # nosec: B104
            ('::1',),
            ('fe80::1%eth0',),
            ('fd00::1',),
            ('::ffff:127.0.0.1',),
            ('8.8.8.8', '10.0.0.1'),
        ]:
            with self.subTest(addresses=addresses):
                self.getaddrinfo.return_value = resolves_to(*addresses)
                self.assert_rejected_without_connection(self.form(), 'internen Netz')

    def test_localhost_is_not_checked(self):
        # resolve for real, this needs no network
        self.getaddrinfo.side_effect = REAL_GETADDRINFO
        self.assert_rejected_without_connection(
            self.form(juntagrico_email_host='localhost'), 'internen Netz'
        )

    def test_unknown_server_and_missing_values(self):
        self.getaddrinfo.side_effect = socket.gaierror('not found')
        self.assert_rejected_without_connection(self.form(), 'nicht gefunden')
        self.assert_rejected_without_connection(
            self.form(juntagrico_email_host=''), 'kein E-Mail-Server'
        )
        # port 'abc' is rejected at field level (ChoiceField), not in clean()
        form = self.form(juntagrico_email_port='abc')
        self.assertFalse(form.is_valid())
        self.assertIn('juntagrico_email_port', form.errors)

    def test_error_messages_have_no_details(self):
        for error, message in [
            (
                ConnectionRefusedError('[Errno 111] Connection refused'),
                'lehnt die Verbindung ab',
            ),
            (TimeoutError('timed out'), 'antwortet nicht'),
            (ssl.SSLError('WRONG_VERSION_NUMBER'), 'TLS/SSL'),
            (
                smtplib.SMTPServerDisconnected('Connection unexpectedly closed'),
                'Prüfe deine Einstellungen',
            ),
            (
                smtplib.SMTPConnectError(-1, b'HTTP/1.1 400 Bad Request'),
                'Prüfe deine Einstellungen',
            ),
        ]:
            with self.subTest(error=error):
                self.get_connection.return_value.open.side_effect = error
                form = self.form()
                self.assertFalse(form.is_valid())
                text = form.non_field_errors()[0]
                self.assertIn(message, text)
                for detail in [
                    'Errno',
                    'timed out',
                    'WRONG_VERSION',
                    'unexpectedly',
                    'HTTP',
                ]:
                    self.assertNotIn(detail, text)

    def test_authentication_error_shows_server_answer(self):
        self.get_connection.return_value.open.side_effect = (
            smtplib.SMTPAuthenticationError(
                535, b'5.7.8 Username and Password not accepted. Use an app password.'
            )
        )
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertIn('Use an app password', form.non_field_errors()[0])

    def test_skip_check(self):
        form = self.form(skip_check='')
        self.assertTrue(form.is_valid())
        self.assertFalse(self.getaddrinfo.called)
        self.assertFalse(self.get_connection.called)


MAIL_PASSWORD = 'MailSecret123'  # nosec: B105
SECRET_KEY = 'S' * 50


# Stored secrets of an app are never sent to the browser; an empty field keeps them.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class EnvSecretTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner')
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        self.env = AppEnv.objects.create(
            app=self.app,
            juntagrico_email_password=MAIL_PASSWORD,
            juntagrico_secret_key=SECRET_KEY,
            juntagrico_email_host='mail.example.org',
        )

    def save(self, **data):
        from adminconsole.forms import EnvForm

        form = EnvForm(
            {
                'juntagrico_email_host': 'mail.example.org',
                'juntagrico_email_port': '587',
                'juntagrico_email_security': 'none',
                'skip_check': '',
                **data,
            },
            instance=self.env,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.env.refresh_from_db()

    def test_pages_do_not_contain_secrets(self):
        self.client.force_login(self.owner)
        with mock.patch('docker.from_env'):
            for url in [f'/env/{self.app.id}/', f'/ca/env/form/{self.app.id}/']:
                with self.subTest(url=url):
                    content = self.client.get(url).content.decode()
                    self.assertNotIn(MAIL_PASSWORD, content)
                    self.assertNotIn(SECRET_KEY, content)
                    self.assertIn('Ein Passwort ist gespeichert', content)
                    self.assertEqual(content.count('autocomplete="new-password"'), 2)

    def test_empty_fields_keep_stored_values(self):
        self.save()
        self.assertEqual(self.env.juntagrico_email_password, MAIL_PASSWORD)
        self.assertEqual(self.env.juntagrico_secret_key, SECRET_KEY)

    def test_new_values(self):
        self.save(
            juntagrico_email_password='NewMailPassword',  # nosec: B106
            juntagrico_secret_key='K' * 50,
        )
        self.assertEqual(self.env.juntagrico_email_password, 'NewMailPassword')
        self.assertEqual(self.env.juntagrico_secret_key, 'K' * 50)

    def test_clear_password(self):
        self.save(clear_email_password='on')  # nosec: B106
        self.assertEqual(self.env.juntagrico_email_password, '')
        self.assertEqual(self.env.juntagrico_secret_key, SECRET_KEY)

    def test_generate_secret_key(self):
        self.save(new_secret_key='on')  # nosec: B106
        self.assertNotEqual(self.env.juntagrico_secret_key, SECRET_KEY)
        self.assertEqual(len(self.env.juntagrico_secret_key), 50)
        self.assertEqual(self.env.juntagrico_email_password, MAIL_PASSWORD)

    def test_failed_check_keeps_typed_password(self):
        # after a failed check the page offers "skip check and save", which must save the new password
        self.client.force_login(self.owner)
        with (
            mock.patch(
                'adminconsole.forms.socket.getaddrinfo',
                return_value=resolves_to('8.8.8.8'),
            ),
            mock.patch('adminconsole.forms.get_connection') as get_connection,
        ):
            get_connection.return_value.open.side_effect = ConnectionRefusedError()
            content = self.client.post(
                f'/env/{self.app.id}/',
                {
                    'juntagrico_email_host': 'mail.example.org',
                    'juntagrico_email_port': '587',
                    'juntagrico_email_security': 'none',
                    'juntagrico_email_password': 'TypedNewPassword',
                },
            ).content.decode()
        self.assertIn('Prüfung überspringen', content)
        self.assertIn('value="TypedNewPassword"', content)
        self.assertNotIn(MAIL_PASSWORD, content)
        self.assertNotIn(SECRET_KEY, content)

    def test_smtp_check_uses_stored_password(self):
        from adminconsole.forms import EnvForm

        with (
            mock.patch(
                'adminconsole.forms.socket.getaddrinfo',
                return_value=resolves_to('8.8.8.8'),
            ),
            mock.patch('adminconsole.forms.get_connection') as get_connection,
        ):
            for data, expected in [
                ({}, MAIL_PASSWORD),
                ({'clear_email_password': 'on'}, ''),
            ]:
                with self.subTest(data=data):
                    form = EnvForm(
                        {
                            'juntagrico_email_host': 'mail.example.org',
                            'juntagrico_email_port': '587',
                            'juntagrico_email_security': 'none',
                            **data,
                        },
                        instance=self.env,
                    )
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertEqual(
                        get_connection.call_args.kwargs['password'], expected
                    )


def docker_network(
    subnet='172.30.0.0/22', gateway='172.30.0.1', icc='false', bridge='br-juntagrico'
):
    """simulated existing Docker network"""
    network = mock.MagicMock()
    network.name = 'juntagrico-apps'
    network.attrs = {
        'Driver': 'bridge',
        'IPAM': {'Config': [{'Subnet': subnet, 'Gateway': gateway}]},
        'Options': {
            'com.docker.network.bridge.enable_icc': icc,
            'com.docker.network.bridge.name': bridge,
        },
    }
    return network


# Apps with network isolation run in their own network; all other apps stay in the host network.
@tag('docker')
class NetworkIsolationTests(TestCase):
    def setUp(self):
        self.app = App.objects.create(name='foo', port=8010, wsgi='foo.wsgi')
        AppEnv.objects.create(app=self.app, juntagrico_database_host='localhost')
        patcher = mock.patch('docker.from_env')
        self.client = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.client.networks.get.return_value = docker_network()

    def restart(self):
        with mock.patch('builtins.print'):
            call_command('restart', 'foo')
        return self.client.containers.run.call_args.kwargs

    def test_without_isolation_nothing_changes(self):
        kwargs = self.restart()
        self.assertEqual(kwargs['network_mode'], 'host')
        for key in ['network', 'ports', 'command', 'mem_limit']:
            self.assertNotIn(key, kwargs)
        self.assertIn('JUNTAGRICO_DATABASE_HOST=localhost', kwargs['environment'])
        self.assertNotIn('JUNTAGRICO_DATABASE_HOST=172.30.0.1', kwargs['environment'])
        self.assertFalse(self.client.networks.get.called)

    def test_with_isolation(self):
        App.objects.filter(pk=self.app.pk).update(isolated_network=True)
        kwargs = self.restart()
        self.assertNotIn('network_mode', kwargs)
        self.assertEqual(kwargs['network'], 'juntagrico-apps')
        self.assertEqual(kwargs['ports'], {'8010/tcp': ('127.0.0.1', 8010)})
        self.assertEqual(
            kwargs['command'],
            [
                'gunicorn',
                '--no-control-socket',
                '--forwarded-allow-ips',
                '172.30.0.1',
                '--bind',
                '0.0.0.0:8010',
                '-t',
                '600',
                'foo.wsgi',
            ],
        )
        self.assertEqual(kwargs['mem_limit'], '600m')
        # the database is reached at the gateway; the last value of a variable wins
        self.assertEqual(
            kwargs['environment'][-1], 'JUNTAGRICO_DATABASE_HOST=172.30.0.1'
        )
        # the stored setting is unchanged, so switching back works
        self.assertEqual(
            AppEnv.objects.get(app=self.app).juntagrico_database_host, 'localhost'
        )

    def test_network_is_created_if_missing(self):
        App.objects.filter(pk=self.app.pk).update(isolated_network=True)
        self.client.networks.get.side_effect = NotFound('no such network')
        self.client.networks.create.return_value = docker_network()
        self.restart()
        args, kwargs = self.client.networks.create.call_args
        self.assertEqual(args, ('juntagrico-apps',))
        self.assertEqual(kwargs['driver'], 'bridge')
        (pool,) = kwargs['ipam']['Config']
        self.assertEqual(
            (pool['Subnet'], pool['Gateway']), ('172.30.0.0/22', '172.30.0.1')
        )
        self.assertEqual(
            kwargs['options'],
            {
                'com.docker.network.bridge.enable_icc': 'false',
                'com.docker.network.bridge.name': 'br-juntagrico',
            },
        )

    @patch('adminconsole.management.commands.restart.stop_container')
    def test_wrong_network_keeps_the_running_container(self, mock_stop):
        App.objects.filter(pk=self.app.pk).update(isolated_network=True)
        for network in [
            docker_network(subnet='172.31.0.0/16'),
            docker_network(icc='true'),
            docker_network(bridge='br-other'),
            docker_network(gateway='172.30.0.254'),
        ]:
            with self.subTest(attrs=network.attrs):
                self.client.reset_mock()
                self.client.networks.get.return_value = network
                with self.assertRaises(NetworkMismatch):
                    self.restart()
                self.assertFalse(
                    self.client.containers.run.called, 'a new container was started'
                )

    @override_settings(
        APPS_NETWORK={
            'name': 'juntagrico-apps',
            'subnet': '10.99.0.0/24',
            'gateway': '10.99.0.1',
            'bridge': 'br-juntagrico',
        },
        APPS_MEMORY_LIMIT='1g',
    )
    def test_settings(self):
        App.objects.filter(pk=self.app.pk).update(isolated_network=True)
        self.client.networks.get.return_value = docker_network(
            subnet='10.99.0.0/24', gateway='10.99.0.1'
        )
        kwargs = self.restart()
        self.assertEqual(
            kwargs['environment'][-1], 'JUNTAGRICO_DATABASE_HOST=10.99.0.1'
        )
        self.assertEqual(kwargs['mem_limit'], '1g')

    def test_setup_files(self):
        self.assertIn(
            'net.ipv4.ip_nonlocal_bind = 1',
            (SETUP_DIR / '99-juntagrico-nonlocal-bind.conf').read_text(),
        )
        firewall = (SETUP_DIR / 'juntagrico-apps-firewall').read_text()
        self.assertIn('BRIDGE=br-juntagrico', firewall)
        unit = (SETUP_DIR / 'juntagrico-apps-firewall.service').read_text()
        self.assertIn('Before=network-pre.target docker.service', unit)
        self.assertIn('ExecStart=/usr/local/sbin/juntagrico-apps-firewall', unit)


# Exporting member data needs the password of the user, so a stolen session alone is not enough.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class ExportConfirmationTests(TestCase):
    EXPORTS = ['/dumpdata/{}/', '/pgdump/{}/']

    def setUp(self):
        self.owner = User.objects.create_user('owner', password='secret-pw')  # nosec: B106
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        AppEnv.objects.create(app=self.app, juntagrico_database_name='foo')
        self.client.force_login(self.owner)
        for name, target in [('docker', 'docker.from_env'), ('run', 'subprocess.run')]:
            patcher = mock.patch(target)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.docker.return_value.containers.get.return_value.exec_run.return_value = (
            mock.MagicMock(output=b'[]')
        )
        self.run.return_value = mock.MagicMock(stdout=b'-- dump')

    def exported(self):
        return (
            self.docker.return_value.containers.get.return_value.exec_run.called
            or self.run.called
        )

    def test_get_asks_for_password(self):
        for url in self.EXPORTS:
            with self.subTest(url=url):
                response = self.client.get(url.format(self.app.id))
                self.assertTemplateUsed(response, 'generic/confirm_password.html')
                self.assertFalse(self.exported())

    def test_wrong_password_exports_nothing(self):
        for url in self.EXPORTS:
            with (
                self.subTest(url=url),
                self.assertLogs('adminconsole.security', 'WARNING') as logs,
            ):
                response = self.client.post(
                    url.format(self.app.id), {'password': 'wrong'}
                )
                self.assertContains(response, 'Das Passwort ist falsch.')
                self.assertFalse(self.exported())
                self.assertIn('wrong password', logs.output[0])

    def test_correct_password_exports_and_logs(self):
        for url, extension in zip(self.EXPORTS, ['json', 'sql']):
            with (
                self.subTest(url=url),
                self.assertLogs('adminconsole.security', 'INFO') as logs,
            ):
                response = self.client.post(
                    url.format(self.app.id),
                    {'password': 'secret-pw'},
                    HTTP_X_REAL_IP='203.0.113.7',
                )
                self.assertIn(f'.{extension}', response['Content-Disposition'])
                self.assertIn('owner exports', logs.output[0])
                self.assertIn('foo', logs.output[0])
                self.assertIn('203.0.113.7', logs.output[0])

    def test_too_many_wrong_passwords_log_out(self):
        url = self.EXPORTS[1].format(self.app.id)
        with self.assertLogs('adminconsole.security', 'WARNING'):
            for _ in range(4):
                self.client.post(url, {'password': 'wrong'})
            self.assertTrue(self.client.session.get('_auth_user_id'))
            response = self.client.post(url, {'password': 'wrong'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.client.session.get('_auth_user_id'), 'still logged in')
        self.assertFalse(self.exported())

    def test_correct_password_resets_failures(self):
        url = self.EXPORTS[1].format(self.app.id)
        with self.assertLogs('adminconsole.security', 'INFO'):
            for _ in range(4):
                self.client.post(url, {'password': 'wrong'})
            self.client.post(url, {'password': 'secret-pw'})
            self.client.post(url, {'password': 'wrong'})
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_csrf_and_other_users(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        other = Client()
        other.force_login(User.objects.create_user('other', password='other-pw'))  # nosec: B106
        for url in self.EXPORTS:
            with self.subTest(url=url):
                self.assertEqual(
                    client.post(
                        url.format(self.app.id), {'password': 'secret-pw'}
                    ).status_code,
                    403,
                )
                response = other.post(url.format(self.app.id), {'password': 'other-pw'})
                self.assertRedirects(response, '/', fetch_redirect_response=False)
                self.assertFalse(self.exported())


# The progress check must not reveal whether other processes exist on the server.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class PidCheckTests(TestCase):
    def test_only_console_processes_are_reported(self):
        from adminconsole.util import pid_finished

        # a process like the ones the console starts (python -m manage ...)
        job = subprocess.Popen([  # nosec: B603, B607
            sys.executable,
            '-c',
            'import time; time.sleep(30)',
            '-m',
            'manage',
        ])
        self.addCleanup(job.kill)
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])  # nosec: B603, B607
        self.addCleanup(other.kill)
        self.assertFalse(
            pid_finished(job.pid), 'running console job reported as finished'
        )
        self.assertTrue(pid_finished(other.pid), 'other process revealed')
        self.assertTrue(pid_finished(os.getpid()), 'test runner revealed')
        self.assertTrue(
            pid_finished(4 if os.name == 'nt' else 1), 'system process revealed'
        )
        job.kill()
        job.wait()
        self.assertTrue(pid_finished(job.pid))

    def test_view(self):
        user = User.objects.create_user('owner')
        self.client.force_login(user)
        with mock.patch(
            'adminconsole.views.generic.pid_finished', return_value=True
        ) as finished:
            self.assertEqual(self.client.get('/pid/1/').json(), {'finished': True})
        finished.assert_called_once_with(1)


# create_database quotes the names; the statements take no parameters.
class CreateDatabaseTests(TestCase):
    def statements(self, name, password='ABC123', replace=False):  # nosec: B107
        from adminconsole.util.create_app import create_database

        app = App.objects.create(name=name, port=8010 + App.objects.count())
        env = AppEnv.objects.create(app=app)
        cursor = mock.MagicMock()
        cursor.fetchone.return_value = None  # user/db don't exist, so CREATE runs
        with (
            mock.patch('adminconsole.util.create_app.connection') as connection,
            mock.patch(
                'adminconsole.util.create_app.generate_password', return_value=password
            ),
        ):
            connection.ops.quote_name = lambda value: '"%s"' % value
            connection.cursor.return_value.__enter__.return_value = cursor
            create_database(env, name, name, replace=replace)
        return [call.args[0] for call in cursor.execute.call_args_list]

    def test_statements(self):
        self.assertEqual(
            self.statements('foo-staging', replace=True),
            [
                'SET ROLE "foo_staging"',
                'DROP DATABASE IF EXISTS "foo_staging"',
                'RESET ROLE',
                'DROP USER IF EXISTS "foo_staging"',
                'CREATE USER "foo_staging"',
                'ALTER ROLE "foo_staging" WITH PASSWORD \'ABC123\'',
                'ALTER ROLE "foo_staging" SET client_encoding TO \'utf8\'',
                'ALTER ROLE "foo_staging" SET default_transaction_isolation TO \'read committed\'',
                'ALTER ROLE "foo_staging" SET timezone TO \'Europe/Zurich\'',
                "SELECT 1 FROM pg_database WHERE datname = 'foo_staging'",
                "CREATE DATABASE \"foo_staging\" OWNER \"foo_staging\" TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8'",
            ],
        )

    def test_statements_non_replace(self):
        """Non-replace mode skips DROP statements and checks existence before creating."""
        self.assertEqual(
            self.statements('bar', replace=False),
            [
                "SELECT 1 FROM pg_roles WHERE rolname = 'bar'",
                'CREATE USER "bar"',
                'ALTER ROLE "bar" WITH PASSWORD \'ABC123\'',
                'ALTER ROLE "bar" SET client_encoding TO \'utf8\'',
                'ALTER ROLE "bar" SET default_transaction_isolation TO \'read committed\'',
                'ALTER ROLE "bar" SET timezone TO \'Europe/Zurich\'',
                "SELECT 1 FROM pg_database WHERE datname = 'bar'",
                "CREATE DATABASE \"bar\" OWNER \"bar\" TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8'",
            ],
        )

    def test_password_must_be_alphanumeric(self):
        from adminconsole.util.create_app import create_database

        for password in ["abc'; DROP USER x; --", 'äöü123', 'with space']:
            with self.subTest(password=password):
                app = App.objects.create(
                    name=f'app{len(password)}', port=8010 + App.objects.count()
                )
                env = AppEnv.objects.create(app=app)
                with (
                    mock.patch('adminconsole.util.create_app.connection') as connection,
                    mock.patch(
                        'adminconsole.util.create_app.generate_password',
                        return_value=password,
                    ),
                ):
                    connection.ops.quote_name = lambda value: '"%s"' % value
                    cursor = mock.MagicMock()
                    connection.cursor.return_value.__enter__.return_value = cursor
                    result = create_database(env, app.name, app.name)
                self.assertFalse(result)


# The create_admin_user utility creates the admin user in a container (idempotent).
class CreateAdminUserTests(TestCase):
    def setUp(self):
        patcher = mock.patch('docker.from_env')
        self.docker_mock = patcher.start().return_value
        self.addCleanup(patcher.stop)
        self.container = self.docker_mock.containers.get.return_value
        self.container.exec_run.return_value = mock.MagicMock(exit_code=0, output=b'')

    def test_creates_admin_successfully(self):
        from adminconsole.util.admin import create_admin_user

        result = create_admin_user('foo', 'SecretPw')
        self.assertTrue(result)
        args, kwargs = self.container.exec_run.call_args
        self.assertEqual(
            args[0], ['python', '-m', 'manage', 'createadmin', '--noinput']
        )
        self.assertEqual(kwargs['environment']['DJANGO_SUPERUSER_PASSWORD'], 'SecretPw')

    def test_fallback_sets_password_when_user_exists(self):
        """When createadmin fails (user exists), set_admin_password is called as fallback."""
        from adminconsole.util.admin import create_admin_user, PASSWORD_ENV

        # First call (createadmin) fails, second call (set_admin_password fallback) succeeds
        self.container.exec_run.side_effect = [
            mock.MagicMock(exit_code=1, output=b'User exists'),
            mock.MagicMock(exit_code=0, output=b''),
        ]
        result = create_admin_user('foo', 'NewPw')
        self.assertTrue(result)
        # Should be called twice: first createadmin, then set_admin_password
        self.assertEqual(self.container.exec_run.call_count, 2)
        second_call = self.container.exec_run.call_args_list[1]
        self.assertEqual(second_call.kwargs['environment'][PASSWORD_ENV], 'NewPw')

    def test_returns_false_when_container_not_found(self):
        from adminconsole.util.admin import create_admin_user

        self.docker_mock.containers.get.side_effect = NotFound('no such container')
        result = create_admin_user('foo', 'pw')
        self.assertFalse(result)

    def test_returns_false_when_fallback_fails(self):
        """When both createadmin and the fallback fail, return False."""
        from adminconsole.util.admin import create_admin_user

        self.container.exec_run.return_value = mock.MagicMock(
            exit_code=1, output=b'Error'
        )
        result = create_admin_user('foo', 'pw')
        self.assertFalse(result)


# The setup_domain utility creates the default domain and requests an SSL certificate.
class SetupDomainTests(TestCase):
    def setUp(self):
        self.app = App.objects.create(name='foo', port=8010)

    def test_success(self):
        from adminconsole.util.create_app import setup_domain

        with (
            mock.patch('adminconsole.util.create_app.subprocess.run') as run,
            mock.patch('builtins.open', mock.mock_open()),
        ):
            run.return_value = mock.MagicMock(returncode=0, stdout=b'ok')
            result = setup_domain(self.app)
        self.assertTrue(result)
        run.assert_called_once()
        self.assertIn('/usr/local/sbin/juntagrico-certbot', run.call_args[0][0])

    def test_certbot_failure(self):
        from adminconsole.util.create_app import setup_domain

        with (
            mock.patch('adminconsole.util.create_app.subprocess.run') as run,
            mock.patch('builtins.open', mock.mock_open()),
        ):
            run.return_value = mock.MagicMock(returncode=1, stdout=b'error')
            result = setup_domain(self.app)
        self.assertFalse(result)


# The create_default_cronjobs utility creates default/required cronjobs for an app.
class CreateDefaultCronjobsTests(TestCase):
    def test_creates_default_and_required_cronjobs(self):
        from adminconsole.util.create_app import create_default_cronjobs

        app = App.objects.create(name='foo', port=8010)
        cronjobs = [
            {
                'id': 'cj1',
                'default': True,
                'timing': 'daily',
                'default_hour': 23,
                'default_minute': 0,
            },
            {
                'id': 'cj2',
                'required': True,
                'timing': 'hourly',
                'default_minute': 'spread',
            },
            {'id': 'cj3', 'default': False, 'required': False, 'timing': 'fixed'},
        ]
        with mock.patch(
            'adminconsole.util.create_app.get_available_cronjobs', return_value=cronjobs
        ):
            create_default_cronjobs(app)
        # cj1 (default) and cj2 (required) should be created; cj3 should not
        created = list(app.cronjobs.values_list('cronjob_id', 'minute', 'hour'))
        self.assertEqual(len(created), 2)
        ids = {row[0] for row in created}
        self.assertEqual(ids, {'cj1', 'cj2'})
        # cj1: daily, hour=23, minute=0
        cj_map = {
            row[0]: (row[1], row[2])
            for row in app.cronjobs.values_list('cronjob_id', 'hour', 'minute')
        }
        self.assertEqual(cj_map['cj1'], (23, 0))
        # cj2: hourly, minute = port % 60 = 8010 % 60 = 30
        self.assertEqual(cj_map['cj2'], (None, 30))

    def test_idempotent_on_second_call(self):
        """Calling twice does not create duplicates."""
        from adminconsole.util.create_app import create_default_cronjobs

        app = App.objects.create(name='bar', port=8020)
        cronjobs = [
            {'id': 'cj1', 'default': True, 'timing': 'fixed'},
        ]
        with mock.patch(
            'adminconsole.util.create_app.get_available_cronjobs', return_value=cronjobs
        ):
            create_default_cronjobs(app)
            create_default_cronjobs(app)
        self.assertEqual(app.cronjobs.count(), 1)


# The setup command checks for PASSWORD_ENV and fails immediately if missing.
class SetupCommandTests(TestCase):
    def test_fails_without_password_env(self):
        from adminconsole.util.admin import PASSWORD_ENV

        app = App.objects.create(name='foo', port=8010)
        # Remove PASSWORD_ENV if it happens to be set
        saved = os.environ.pop(PASSWORD_ENV, None)
        try:
            with mock.patch('builtins.print', autospec=True) as mock_print:
                call_command('setup', app.name)
            # Should print failure message
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any('Passwort nicht gesetzt' in c for c in calls))
            self.assertTrue(any('Return 1' in c for c in calls))
        finally:
            if saved is not None:
                os.environ[PASSWORD_ENV] = saved

    def test_fails_when_database_creation_returns_false(self):
        from adminconsole.util.admin import PASSWORD_ENV

        app = App.objects.create(name='bar', port=8011)
        os.environ[PASSWORD_ENV] = 'testpass123'
        try:
            with (
                mock.patch(
                    'adminconsole.management.commands.setup.create_database',
                    return_value=False,
                ),
                mock.patch('builtins.print', autospec=True) as mock_print,
            ):
                call_command('setup', app.name)
            calls = [str(c) for c in mock_print.call_args_list]
            self.assertTrue(any('Return 1' in c for c in calls))
        finally:
            os.environ.pop(PASSWORD_ENV, None)


# The git_pull function clones the repo if .git doesn't exist yet.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class GitPullCloneFallbackTests(TestCase):
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
            mock.patch.dict('os.environ', {'GIT_CEILING_DIRECTORIES': str(self.base)}),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_clones_when_git_dir_missing(self):
        """If .git doesn't exist, git_pull clones the repo first."""
        from adminconsole.util.git import git_pull

        app = App.objects.create(
            name='foo',
            port=8010,
            git_clone_url='https://github.com/a/b.git',
            git_branch='main',
        )
        app.work_dir.mkdir()
        with (
            mock.patch('adminconsole.util.git.test_localhost', return_value=True),
            mock.patch('adminconsole.util.git.git_clone', return_value=True) as clone,
            mock.patch('adminconsole.util.git.run_git') as run_git,
            mock.patch.object(app, 'get_installation_token', return_value=None),
        ):
            run_git.return_value = mock.MagicMock(returncode=0, stdout='abc123')
            result = git_pull(app)
        clone.assert_called_once_with(app)
        self.assertEqual(result, 0)

    def test_returns_minus1_when_clone_fails(self):
        """If clone fails during fallback, return -1."""
        from adminconsole.util.git import git_pull

        app = App.objects.create(
            name='foo', port=8010, git_clone_url='https://github.com/a/b.git'
        )
        app.work_dir.mkdir()
        with (
            mock.patch('adminconsole.util.git.test_localhost', return_value=True),
            mock.patch('adminconsole.util.git.git_clone', return_value=False),
        ):
            result = git_pull(app)
        self.assertEqual(result, -1)


# The git_push_app function adds, commits, and pushes changes.
class GitPushAppTests(TestCase):
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

    def test_push_success(self):
        from adminconsole.util.git import git_push_app

        app = App.objects.create(name='foo', port=8010)
        app.work_dir.mkdir()
        output = []
        with (
            mock.patch('adminconsole.util.git.subprocess.run') as run,
            mock.patch.object(app, 'get_installation_token', return_value=None),
        ):
            run.return_value = mock.MagicMock(returncode=0, stdout=b'ok')
            result = git_push_app(app, output)
        self.assertTrue(result)
        # Should call git add, commit, push
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[0][0][0][1], 'add')
        self.assertEqual(run.call_args_list[1][0][0][1], 'commit')
        self.assertEqual(run.call_args_list[2][0][0][1], 'push')

    def test_push_failure(self):
        from adminconsole.util.git import git_push_app

        app = App.objects.create(name='foo', port=8010)
        app.work_dir.mkdir()
        output = []
        with (
            mock.patch('adminconsole.util.git.subprocess.run') as run,
            mock.patch.object(app, 'get_installation_token', return_value=None),
        ):
            run.side_effect = [
                mock.MagicMock(returncode=0, stdout=b''),
                mock.MagicMock(returncode=0, stdout=b''),
                mock.MagicMock(returncode=1, stdout=b'error'),
            ]
            result = git_push_app(app, output)
        self.assertFalse(result)


# The env_form view passes the admin password via environment variable.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class EnvFormViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner')
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        AppEnv.objects.create(app=self.app)
        self.client.force_login(self.owner)

    def test_post_passes_password_env(self):
        """POST to env_form passes PASSWORD_ENV to the setup subprocess."""
        from adminconsole.util.admin import PASSWORD_ENV

        data = {
            'juntagrico_secret_key': 'x' * 50,
            'juntagrico_email_host': 'mail.example.org',
            'juntagrico_email_port': '587',
            'juntagrico_email_security': 'none',
            'skip_check': '',
            'env_vars-TOTAL_FORMS': '0',
            'env_vars-INITIAL_FORMS': '0',
            'env_vars-MIN_NUM_FORMS': '0',
            'env_vars-MAX_NUM_FORMS': '50',
        }
        with (
            mock.patch('subprocess.Popen') as mock_popen,
            mock.patch.object(
                App, 'log_file', new=property(lambda self: '/tmp/test.log')
            ),
            mock.patch('builtins.open', mock.mock_open()),
        ):
            mock_popen.return_value = mock.MagicMock(pid=12345)
            resp = self.client.post(f'/ca/env/form/{self.app.id}/', data)
        # Verify PASSWORD_ENV is passed
        call_kwargs = mock_popen.call_args.kwargs
        self.assertIn(PASSWORD_ENV, call_kwargs.get('env', {}))
        # Password should be a non-empty string
        self.assertTrue(call_kwargs['env'][PASSWORD_ENV])
        # Response should contain the password in context
        self.assertEqual(resp.status_code, 200)


# The repo_source view lets the user choose between a clone URL and GitHub.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class RepoSourceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner')
        self.client.force_login(self.owner)
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)

    def test_get_shows_install_button_without_installation(self):
        """Without a GitHubKey, the install button is shown, not the repo list link."""
        resp = self.client.get(f'/ca/source/{self.app.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'clone_url')
        self.assertContains(resp, 'GitHub App installieren')
        self.assertNotContains(resp, 'Repo aus Liste auswählen')

    def test_get_shows_repo_link_with_installation(self):
        """With a GitHubKey installation_id, the repo list link is shown, not the install button."""
        from adminconsole.models import GitHubKey

        GitHubKey.objects.create(user=self.owner, installation_id='123')
        resp = self.client.get(f'/ca/source/{self.app.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'clone_url')
        self.assertContains(resp, 'Repo aus Liste auswählen')
        self.assertNotContains(resp, 'GitHub App installieren')

    def test_clone_action_validates_and_saves_url(self):
        """Clone URL path runs clone directly and redirects to overwrite check on success."""
        with (
            mock.patch('adminconsole.util.git.test_localhost', return_value=True),
            mock.patch('adminconsole.util.git.git_clone', return_value=True),
        ):
            resp = self.client.post(
                f'/ca/source/{self.app.id}/',
                {'action': 'clone', 'clone_url': 'https://github.com/user/repo.git'},
            )
        self.app.refresh_from_db()
        self.assertEqual(self.app.git_clone_url, 'https://github.com/user/repo.git')
        self.assertRedirects(
            resp, f'/ca/overwrite/{self.app.id}/', fetch_redirect_response=False
        )

    def test_clone_action_accepts_non_github_url(self):
        """Non-GitHub URLs (e.g., GitLab) are accepted and redirect to overwrite check on success."""
        with (
            mock.patch('adminconsole.util.git.test_localhost', return_value=True),
            mock.patch('adminconsole.util.git.git_clone', return_value=True),
        ):
            resp = self.client.post(
                f'/ca/source/{self.app.id}/',
                {'action': 'clone', 'clone_url': 'https://gitlab.com/user/repo.git'},
            )
        self.app.refresh_from_db()
        self.assertEqual(self.app.git_clone_url, 'https://gitlab.com/user/repo.git')
        self.assertRedirects(
            resp, f'/ca/overwrite/{self.app.id}/', fetch_redirect_response=False
        )

    def test_clone_action_rejects_invalid_url(self):
        with (
            mock.patch('adminconsole.util.git.test_localhost', return_value=False),
            mock.patch('adminconsole.util.git.subprocess.run') as run,
        ):
            run.return_value.returncode = 2  # git ls-remote failure
            resp = self.client.post(
                f'/ca/source/{self.app.id}/',
                {'action': 'clone', 'clone_url': 'https://github.com/nonexistent.git'},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'konnte nicht erreicht werden')
        self.app.refresh_from_db()
        self.assertEqual(self.app.git_clone_url, '')

    def test_github_action_redirects_to_installation(self):
        with override_settings(GITHUB_APP_SLUG='my-github-app'):
            resp = self.client.post(
                f'/ca/source/{self.app.id}/',
                {'action': 'github'},
            )
        self.assertIn('/apps/my-github-app/installations/new?state=', resp['Location'])
        # Verify state token was stored in session
        session = self.client.session
        self.assertIn('github_install_state', session)
        self.assertIn(session['github_install_state'], resp['Location'])

    def test_skips_to_clone_when_url_already_set(self):
        self.app.git_clone_url = 'https://github.com/user/repo.git'
        self.app.save()
        resp = self.client.get(f'/ca/source/{self.app.id}/')
        self.assertRedirects(
            resp, f'/ca/clonerepo/{self.app.id}/', fetch_redirect_response=False
        )

    def test_other_user_cannot_access(self):
        other = User.objects.create_user('other', password='pw')  # nosec: B106
        self.client.force_login(other)
        resp = self.client.get(f'/ca/source/{self.app.id}/')
        self.assertRedirects(resp, '/', fetch_redirect_response=False)


# validate_clone_url checks whether a URL points to an accessible repo.
class ValidateCloneUrlTests(TestCase):
    def test_empty_url(self):
        from adminconsole.util.git import validate_clone_url

        self.assertIsNotNone(validate_clone_url(''))
        self.assertIsNotNone(validate_clone_url('  '))
        self.assertIsNotNone(validate_clone_url(None))

    def test_valid_url_in_localhost_mode(self):
        from adminconsole.util.git import validate_clone_url

        with mock.patch('adminconsole.util.git.test_localhost', return_value=True):
            error = validate_clone_url('https://github.com/any/thing.git')
        self.assertIsNone(error, 'should pass in localhost mode')

    def test_invalid_url_outside_localhost(self):
        from adminconsole.util.git import validate_clone_url

        with (
            mock.patch('adminconsole.util.git.test_localhost', return_value=False),
            mock.patch('adminconsole.util.git.subprocess.run') as run,
        ):
            run.return_value.returncode = 2
            error = validate_clone_url('https://github.com/nope.git')
        self.assertIsNotNone(error)
        run.assert_called_once()
        args = run.call_args[0][0]
        self.assertEqual(
            args, ['git', 'ls-remote', '--exit-code', 'https://github.com/nope.git']
        )


# The select_repo view lists repos from the current user's GitHub App installation.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class SelectRepoTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner')
        self.client.force_login(self.owner)
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        from adminconsole.models import GitHubKey

        GitHubKey.objects.create(user=self.owner, installation_id='123')

    def test_get_shows_repo_list(self):
        with mock.patch(
            'adminconsole.views.git.list_installation_repos',
            return_value=[{'full_name': 'myorg/repo1', 'name': 'repo1'}],
        ):
            resp = self.client.get(f'/ca/repo/{self.app.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'myorg/repo1')

    def test_post_selects_repo_and_saves_url(self):
        """Selecting a repo runs clone and redirects to overwrite check on success."""
        with (
            mock.patch(
                'adminconsole.views.git.list_installation_repos', return_value=[]
            ),
            mock.patch('adminconsole.views.git.git_clone', return_value=True),
        ):
            resp = self.client.post(
                f'/ca/repo/{self.app.id}/',
                {
                    'repo_full_name': 'myorg/repo1',
                },
            )
        self.app.refresh_from_db()
        self.assertEqual(self.app.git_clone_url, 'https://github.com/myorg/repo1.git')
        self.assertRedirects(
            resp, f'/ca/overwrite/{self.app.id}/', fetch_redirect_response=False
        )

    def test_redirects_to_source_when_no_github_key(self):
        from adminconsole.models import GitHubKey

        GitHubKey.objects.filter(user=self.owner).delete()
        resp = self.client.get(f'/ca/repo/{self.app.id}/')
        self.assertRedirects(
            resp, f'/ca/source/{self.app.id}/', fetch_redirect_response=False
        )

    def test_skips_to_clone_when_url_already_set(self):
        self.app.git_clone_url = 'https://github.com/user/repo.git'
        self.app.save()
        resp = self.client.get(f'/ca/repo/{self.app.id}/')
        self.assertRedirects(
            resp, f'/ca/clonerepo/{self.app.id}/', fetch_redirect_response=False
        )

    def test_other_user_cannot_access(self):
        other = User.objects.create_user('other', password='pw')  # nosec: B106
        self.client.force_login(other)
        resp = self.client.get(f'/ca/repo/{self.app.id}/')
        self.assertRedirects(resp, '/', fetch_redirect_response=False)


# The github_callback view captures installation_id after GitHub App installation.
# A single-use state token in the session prevents installation_id spoofing.
@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
class GithubCallbackTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('owner')
        self.client.force_login(self.user)
        # Set up the single-use state token that repo_source generates
        session = self.client.session
        session['github_install_state'] = 'test-state-token'
        session.save()

    def test_callback_stores_installation_id(self):
        from adminconsole.models import GitHubKey

        resp = self.client.get(
            '/github/callback',
            {
                'installation_id': '456',
                'setup_action': 'install',
                'state': 'test-state-token',
            },
        )
        # Without app_id in session, redirects to home
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        self.assertEqual(GitHubKey.objects.get(user=self.user).installation_id, '456')

    def test_callback_redirects_to_select_repo(self):
        """When app_id is in the session, redirect to repo selection."""
        from adminconsole.models import App, GitHubKey

        app = App.objects.create(name='test-app', port=8010, user=self.user)
        session = self.client.session
        session['github_install_app_id'] = app.id
        session.save()

        resp = self.client.get(
            '/github/callback',
            {
                'installation_id': '456',
                'setup_action': 'install',
                'state': 'test-state-token',
            },
        )
        self.assertRedirects(resp, f'/ca/repo/{app.id}/', fetch_redirect_response=False)
        self.assertEqual(GitHubKey.objects.get(user=self.user).installation_id, '456')
        # Verify session is cleaned up
        session = self.client.session
        self.assertNotIn('github_install_app_id', session)
        self.assertNotIn('github_install_state', session)

    def test_callback_pending_approval(self):
        resp = self.client.get(
            '/github/callback',
            {'setup_action': 'request', 'state': 'test-state-token'},
        )
        self.assertRedirects(resp, '/', fetch_redirect_response=False)

    def test_callback_missing_installation_id(self):
        resp = self.client.get(
            '/github/callback',
            {'state': 'test-state-token'},
        )
        self.assertRedirects(resp, '/', fetch_redirect_response=False)

    def test_callback_does_not_require_code(self):
        """The callback no longer needs an OAuth code parameter."""
        from adminconsole.models import GitHubKey

        resp = self.client.get(
            '/github/callback',
            {'installation_id': '789', 'state': 'test-state-token'},
        )
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        self.assertEqual(GitHubKey.objects.get(user=self.user).installation_id, '789')

    def test_callback_rejected_without_state_token(self):
        """Callback is rejected if no state token is in the session."""
        from adminconsole.models import GitHubKey

        # Remove the state token set in setUp
        session = self.client.session
        del session['github_install_state']
        session.save()

        resp = self.client.get(
            '/github/callback',
            {
                'installation_id': '999',
                'setup_action': 'install',
                'state': 'test-state-token',
            },
        )
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        # installation_id should NOT be stored
        self.assertFalse(GitHubKey.objects.filter(user=self.user).exists())

    def test_callback_state_token_is_single_use(self):
        """State token is consumed after the first callback, preventing replay."""
        from adminconsole.models import GitHubKey

        # First callback succeeds
        resp = self.client.get(
            '/github/callback',
            {
                'installation_id': '456',
                'setup_action': 'install',
                'state': 'test-state-token',
            },
        )
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        self.assertEqual(GitHubKey.objects.get(user=self.user).installation_id, '456')
        # Second callback with the same session (no state token left) is rejected
        resp = self.client.get(
            '/github/callback',
            {
                'installation_id': '999',
                'setup_action': 'install',
                'state': 'test-state-token',
            },
        )
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        # installation_id should still be the original value
        self.assertEqual(GitHubKey.objects.get(user=self.user).installation_id, '456')

    def test_callback_rejected_with_mismatched_state(self):
        """Callback is rejected if the URL state doesn't match the session state."""
        from adminconsole.models import GitHubKey

        resp = self.client.get(
            '/github/callback',
            {
                'installation_id': '999',
                'setup_action': 'install',
                'state': 'wrong-state-token',
            },
        )
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        # installation_id should NOT be stored
        self.assertFalse(GitHubKey.objects.filter(user=self.user).exists())


# App.get_installation_token() looks up the app owner's installation token.
class InstallationTokenForAppTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('owner')
        self.app = App.objects.create(name='foo', port=8010, user=self.user)
        from adminconsole.models import GitHubKey

        GitHubKey.objects.create(user=self.user, installation_id='456')

    def test_returns_token_when_github_key_exists(self):
        with mock.patch(
            'adminconsole.util.git.get_installation_access_token',
            return_value='install-token-123',
        ) as mock_token:
            token = self.app.get_installation_token()
        self.assertEqual(token, 'install-token-123')
        mock_token.assert_called_once_with(456)

    def test_returns_none_when_no_github_key(self):
        from adminconsole.models import GitHubKey

        GitHubKey.objects.filter(user=self.user).delete()
        token = self.app.get_installation_token()
        self.assertIsNone(token)

    def test_returns_none_when_app_has_no_user(self):
        self.app.user = None
        self.app.save()
        token = self.app.get_installation_token()
        self.assertIsNone(token)

    def test_returns_none_when_installation_id_is_invalid(self):
        from adminconsole.models import GitHubKey

        GitHubKey.objects.filter(user=self.user).update(installation_id='not-a-number')
        token = self.app.get_installation_token()
        self.assertIsNone(token)

    def test_returns_none_when_token_generation_fails(self):
        with mock.patch(
            'adminconsole.util.git.get_installation_access_token',
            return_value=None,
        ):
            token = self.app.get_installation_token()
        self.assertIsNone(token)
