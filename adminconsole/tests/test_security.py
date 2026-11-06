import base64
import json
import os
import shutil
import smtplib
import socket
import ssl
import string
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from unittest import mock
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urlsplit, parse_qs

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import TestCase, Client, override_settings, modify_settings, tag
from docker.errors import NotFound

from adminconsole.models import App, AppEnv, GitHubKey
from adminconsole.util import generate_password, generate_secret_key
from adminconsole.util.admin import PASSWORD_ENV, SET_PASSWORD_SCRIPT
from adminconsole.util.git import git_clone, github_auth_env, remove_credentials
from adminconsole.util.network import NetworkMismatch


TOKEN = 'gho_TestToken123'


def git(*args, cwd):
    return subprocess.run(['git', *args], capture_output=True, text=True, cwd=cwd, check=True).stdout.strip()


# The GitHub token must never be stored in an app repository, which is mounted into the app container.
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
@override_settings(TEST_LOCALHOST=False)
class GitCredentialTests(TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        for patcher in [
            mock.patch.object(App, 'dir', new=property(lambda app: self.base / app.name)),
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
        self.assertEqual(base64.b64decode(header.removeprefix('Authorization: Basic ')).decode(),
                         f'{TOKEN}:x-oauth-basic')
        # ask git itself which urls get the header
        for url, expected in [
            ('https://github.com/juntagrico/foo.git', header),
            ('https://example.org/foo.git', None),
            ('https://github.com.example.org/foo.git', None),
            ('http://github.com/juntagrico/foo.git', None),
        ]:
            with self.subTest(url=url):
                proc = subprocess.run(['git', 'config', '--get-urlmatch', 'http.extraHeader', url],
                                      capture_output=True, text=True, env=env)
                self.assertEqual(proc.stdout.strip() or None, expected)

    def test_auth_env_disables_credential_helpers(self):
        # Replace system and global git config by a helper that hands out stored credentials.
        # The real credential store of the machine running the tests is never asked.
        config = self.base / 'gitconfig'
        config.write_text('[credential]\n\thelper = "!f() { echo username=stored; echo password=StoredSecret; }; f"\n')
        request = 'protocol=https\nhost=example.invalid\n\n'
        isolated = {'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(config), 'GIT_TERMINAL_PROMPT': '0',
                    'GCM_INTERACTIVE': 'never'}
        with mock.patch.dict('os.environ', isolated):
            # without the token environment, git asks the helper
            proc = subprocess.run(['git', 'credential', 'fill'], input=request, capture_output=True, text=True,
                                  cwd=self.base)
            self.assertIn('password=StoredSecret', proc.stdout)
            # with it, no helper is asked
            proc = subprocess.run(['git', 'credential', 'fill'], input=request, capture_output=True, text=True,
                                  cwd=self.base, env=github_auth_env(TOKEN))
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn('StoredSecret', proc.stdout)

    def test_clone_does_not_store_token(self):
        # clone a real local repository, passing a token
        source = self.base / 'source'
        source.mkdir()
        git('init', '-q', cwd=source)
        git('-c', 'user.name=t', '-c', 'user.email=t@example.org', 'commit', '-q', '--allow-empty', '-m', 'init',
            cwd=source)
        app = App.objects.create(name='foo', port=8010, git_clone_url=source.as_uri())
        app.dir.mkdir()

        with mock.patch('adminconsole.util.git.subprocess.run', wraps=subprocess.run) as run:
            self.assertTrue(git_clone(app, TOKEN))

        args, kwargs = run.call_args
        self.assertNotIn(TOKEN, ' '.join(args[0]))
        self.assertEqual(kwargs['env'], github_auth_env(TOKEN))
        self.assertEqual(git('remote', 'get-url', 'origin', cwd=app.code_dir), source.as_uri())
        encoded = base64.b64encode(f'{TOKEN}:x-oauth-basic'.encode()).decode()
        for file in (app.code_dir / '.git').rglob('*'):
            if file.is_file():
                content = file.read_bytes()
                self.assertNotIn(TOKEN.encode(), content, file)
                self.assertNotIn(encoded.encode(), content, file)

    def test_clone_without_token(self):
        app = App.objects.create(name='foo', port=8010, git_clone_url='https://github.com/a/b.git@main')
        with mock.patch('adminconsole.util.git.subprocess.run') as run:
            run.return_value = mock.MagicMock(returncode=0, stdout=b'')
            git_clone(app)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['git', 'clone', '-b', 'main', '--depth=1', 'https://github.com/a/b.git@main', 'code'])
        self.assertIsNone(kwargs['env'])

    def test_push_passes_token_only_to_git_push(self):
        from django.http import HttpResponse
        user = User.objects.create_user('owner')
        GitHubKey.objects.create(user=user, key=TOKEN)
        app = App.objects.create(name='foo', port=8010, user=user)
        app.code_dir.mkdir(parents=True)
        git('init', '-q', cwd=app.code_dir)
        git('remote', 'add', 'origin', 'https://github.com/a/b.git', cwd=app.code_dir)
        self.client.force_login(user)
        with mock.patch('subprocess.run') as run, \
                mock.patch('adminconsole.views.git.render', return_value=HttpResponse()):
            run.return_value = mock.MagicMock(returncode=0, stdout=b'')
            self.client.post(f'/git/push/{app.id}/')

        # The view runs: git add, git commit, git push
        # Only git push should have the auth env
        calls_with_env = [call for call in run.call_args_list if call.kwargs.get('env')]
        self.assertEqual(len(calls_with_env), 1, 'only git push should have env')
        push_call, = calls_with_env
        self.assertEqual(tuple(push_call.args[0]), ('git', 'push'))
        for call in run.call_args_list:
            self.assertNotIn(TOKEN, ' '.join(call.args[0]))

    def test_remove_credentials(self):
        for url, expected in [
            (f'https://{TOKEN}:x-oauth-basic@github.com/a/b.git', 'https://github.com/a/b.git'),
            ('https://user@github.com/a/b.git', 'https://github.com/a/b.git'),
            ('https://github.com/a/b.git', 'https://github.com/a/b.git'),
            ('git@github.com:a/b.git', 'git@github.com:a/b.git'),  # ssh, no credentials stored
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
        stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{self.log.as_posix()}"\n', newline='\n')
        stub.chmod(0o755)
        script = (SETUP_DIR / 'juntagrico-certbot').read_text().replace('\r\n', '\n')
        self.assertIn('exec /usr/local/bin/certbot ', script)
        self.wrapper = self.base / 'juntagrico-certbot'
        self.wrapper.write_text(script.replace('/usr/local/bin/certbot', stub.as_posix()), newline='\n')

    def run_wrapper(self, *args):
        return subprocess.run(['sh', self.wrapper.as_posix(), *args], capture_output=True, text=True)

    def test_valid_domain(self):
        proc = self.run_wrapper('foo.juntagrico.app')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.log.read_text().split('\n')[:-1],
                         ['--nginx', '--redirect', '--keep', '-n', '-d', 'foo.juntagrico.app'])

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
        with mock.patch('adminconsole.management.commands.add_domain.open', mock.mock_open(), create=True), \
                mock.patch('subprocess.run') as run:
            run.return_value = mock.MagicMock(stdout=b'')
            call_command('add_domain', 'foo.example.org')
        self.assertIn(mock.call(['sudo', CERTBOT_WRAPPER, 'foo.example.org'], stdout=subprocess.PIPE),
                      run.call_args_list)


# New apps are generated from a pinned version of the template, without running its hooks.
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
class CookiecutterTests(TestCase):
    def test_template_is_pinned_and_hooks_are_disabled(self):
        user = User.objects.create_user('owner')
        app = App.objects.create(name='foo', port=8010, user=user)
        self.client.force_login(user)
        data = {
            'project_slug': 'foo', 'organisation_name': 'Solawi Foo', 'street': 'Weg', 'number': '1', 'zip': '8000',
            'city': 'Zürich', 'PC': '80-1-1', 'IBAN': 'CH00', 'BIC': 'X', 'NAME': 'Bank', 'info_email': 'a@b.ch',
            'share_price': '250',
        }
        with mock.patch('adminconsole.views.create.cookiecutter') as cookiecutter:
            self.client.post(f'/ck/form/{app.id}/', data)

        kwargs = cookiecutter.call_args.kwargs
        self.assertRegex(kwargs['checkout'], '^[0-9a-f]{40}$')  # a commit, not a branch or tag that can move
        self.assertIs(kwargs['accept_hooks'], False)


def github_response(payload):
    """ simulated response of GitHub's token endpoint """
    response = mock.MagicMock()
    response.__enter__.return_value = BytesIO(json.dumps(payload).encode())
    return response


# The OAuth callback must only accept answers to a request started by the same session (state parameter).
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
@override_settings(GITHUB_CLIENT_ID='client-id', GITHUB_CLIENT_SECRET='client-secret')
class GitHubOAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('owner')
        self.client.force_login(self.user)
        patcher = mock.patch('adminconsole.views.git.r.urlopen')
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        self.urlopen.return_value = github_response({'access_token': TOKEN, 'scope': 'public_repo'})

    def start(self):
        """ starts the OAuth flow and returns the state sent to GitHub """
        response = self.client.get('/github/request')
        query = parse_qs(urlsplit(response['Location']).query)
        self.assertEqual(query['client_id'], ['client-id'])
        self.assertEqual(query['scope'], ['public_repo'])
        return query['state'][0]

    def assert_rejected(self, response):
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertFalse(self.urlopen.called, 'GitHub was contacted')

    def test_each_request_gets_a_new_state(self):
        first, second = self.start(), self.start()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(second), 40)
        self.assertEqual(self.client.session['github_oauth_state'], second)

    def test_callback_without_matching_state_is_rejected(self):
        for session_state, params in [
            (None, {'code': 'c', 'state': 'abc'}),  # flow never started
            ('abc', {'code': 'c'}),  # state missing
            ('abc', {'code': 'c', 'state': 'xyz'}),  # foreign state
            ('abc', {'code': 'c', 'state': 'äbc'}),  # non-ascii
        ]:
            with self.subTest(session_state=session_state, params=params):
                session = self.client.session
                session.pop('github_oauth_state', None)
                if session_state:
                    session['github_oauth_state'] = session_state
                session.save()
                self.assert_rejected(self.client.get('/github/callback', params))
                self.assertFalse(GitHubKey.objects.exists())

    def test_valid_callback_stores_token_once(self):
        state = self.start()
        session = self.client.session
        session['next'] = '/ca/repo/1/'
        session.save()

        response = self.client.get('/github/callback', {'code': 'c', 'state': state})
        self.assertRedirects(response, '/ca/repo/1/', fetch_redirect_response=False)
        self.assertEqual(GitHubKey.objects.get(user=self.user).key, TOKEN)

        # the state can be used only once
        self.urlopen.reset_mock()
        self.assert_rejected(self.client.get('/github/callback', {'code': 'c', 'state': state}))

    def test_token_request(self):
        state = self.start()
        self.client.get('/github/callback', {'code': 'the-code', 'state': state})
        request, = self.urlopen.call_args.args
        self.assertEqual(self.urlopen.call_args.kwargs['timeout'], 10)
        self.assertEqual(request.full_url, 'https://github.com/login/oauth/access_token')
        self.assertEqual(request.get_header('Accept'), 'application/json')
        self.assertEqual(parse_qs(request.data.decode()), {
            'code': ['the-code'], 'client_id': ['client-id'], 'client_secret': ['client-secret'],
        })

    def test_failures_keep_existing_token(self):
        GitHubKey.objects.create(user=self.user, key='existing')
        for description, side_effect, return_value in [
            ('error from GitHub', None, github_response({'error': 'bad_verification_code'})),
            ('network error', URLError('timeout'), None),
            ('invalid json', None, mock.MagicMock(**{'__enter__.return_value': BytesIO(b'access_token=x')})),
        ]:
            with self.subTest(description):
                self.urlopen.side_effect, self.urlopen.return_value = side_effect, return_value
                state = self.start()
                response = self.client.get('/github/callback', {'code': 'c', 'state': state})
                self.assertRedirects(response, '/', fetch_redirect_response=False)
                self.assertEqual(GitHubKey.objects.get(user=self.user).key, 'existing')

    def test_denied_access_does_not_contact_github(self):
        state = self.start()
        self.assert_rejected(self.client.get('/github/callback', {'error': 'access_denied', 'state': state}))


class SecretGenerationTests(TestCase):
    def test_generators_use_secrets(self):
        with mock.patch('adminconsole.util.secrets.choice', wraps=__import__('secrets').choice) as choice:
            password, key = generate_password(), generate_secret_key()
        self.assertEqual(choice.call_count, 70)
        self.assertEqual(len(password), 20)
        self.assertTrue(set(password) <= set(string.ascii_uppercase + string.digits))
        self.assertEqual(len(key), 50)
        self.assertTrue(set(key) <= set(string.ascii_letters + string.digits + string.punctuation))


# The admin password of an instance is independent of the database password and never appears in a command line.
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
@override_settings(PYTHON_BIN='python')
class AdminPasswordTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('owner', password='pw')
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        AppEnv.objects.create(app=self.app, juntagrico_database_password='DBPASSWORD')
        self.client.force_login(self.owner)
        patcher = mock.patch('docker.from_env')
        self.container = patcher.start().return_value.containers.get.return_value
        self.addCleanup(patcher.stop)
        self.container.exec_run.return_value = mock.MagicMock(exit_code=0, output=b'')

    def assert_not_cached(self, response):
        self.assertIn('no-store', response['Cache-Control'])

    def test_create_admin_step(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        with mock.patch.object(App, 'log_file', new_callable=mock.PropertyMock, return_value=str(tmp / 'log')), \
                mock.patch('subprocess.Popen') as popen:
            popen.return_value.pid = 4242
            response = self.client.post(f'/ca/createadmin/{self.app.id}/')

        password = popen.call_args.kwargs['env'][PASSWORD_ENV]
        self.assertEqual(popen.call_args.args[0], ['python', '-m', 'manage', 'create_admin', 'foo'])
        self.assertNotEqual(password, 'DBPASSWORD')
        self.assertEqual(len(password), 20)
        self.assertContains(response, password)
        self.assert_not_cached(response)

    def test_create_admin_command(self):
        with mock.patch.dict(os.environ, {PASSWORD_ENV: 'NEWPASSWORD'}):
            call_command('create_admin', 'foo')
        args, kwargs = self.container.exec_run.call_args
        self.assertEqual(args[0], ['python', '-m', 'manage', 'createadmin', '--noinput'])
        self.assertEqual(kwargs['environment']['DJANGO_SUPERUSER_USERNAME'], 'admin')
        self.assertEqual(kwargs['environment']['DJANGO_SUPERUSER_PASSWORD'], 'NEWPASSWORD')

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
        self.assertEqual(args[0], ['python', '-m', 'manage', 'shell', '-c', SET_PASSWORD_SCRIPT])
        self.assertNotIn(password, ' '.join(args[0]))
        self.assertNotEqual(password, 'DBPASSWORD')
        self.assertTemplateUsed(response, 'app/admin_password.html')
        self.assertContains(response, password)
        self.assert_not_cached(response)
        self.assertNotIn('messages', response.cookies)

    def test_reset_admin_password_failures(self):
        for description, exec_run in [
            ('no admin user', {'return_value': mock.MagicMock(exit_code=1, output=b'DoesNotExist')}),
            ('container not found', {'side_effect': NotFound('no such container')}),
        ]:
            with self.subTest(description):
                self.container.exec_run.reset_mock(return_value=True, side_effect=True)
                self.container.exec_run.configure_mock(**exec_run)
                response = self.client.post(f'/app/{self.app.id}/admin-password/')
                self.assertRedirects(response, f'/overview/{self.app.id}/', fetch_redirect_response=False)

    def test_set_password_script(self):
        # run the script that is executed in the app container against this test database
        admin = User.objects.create_user('admin', password='old')
        with mock.patch.dict(os.environ, {PASSWORD_ENV: 'NEWPASSWORD'}):
            exec(SET_PASSWORD_SCRIPT, {})
        admin.refresh_from_db()
        self.assertTrue(admin.check_password('NEWPASSWORD'))
        self.assertFalse(admin.check_password('old'))


REAL_GETADDRINFO = socket.getaddrinfo


def resolves_to(*addresses):
    """ simulated result of socket.getaddrinfo """
    return [(socket.AF_INET6 if ':' in a else socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, 25)) for a in addresses]


# The SMTP connection test runs in the console and must not reach its own network.
class SmtpCheckTests(TestCase):
    def setUp(self):
        for name, target in [('getaddrinfo', 'adminconsole.forms.socket.getaddrinfo'),
                             ('get_connection', 'adminconsole.forms.get_connection')]:
            patcher = mock.patch(target)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.getaddrinfo.return_value = resolves_to('8.8.8.8')

    def form(self, **data):
        from adminconsole.forms import EnvForm
        return EnvForm({'juntagrico_secret_key': 'x' * 50, 'juntagrico_email_host': 'mail.example.org',
                        'juntagrico_email_port': '587', 'juntagrico_email_security': 'tls', **data})

    def assert_rejected_without_connection(self, form, message):
        self.assertFalse(form.is_valid())
        self.assertIn(message, form.non_field_errors()[0])
        self.assertFalse(self.get_connection.called, 'a connection was made')

    def test_public_server_is_checked(self):
        self.assertTrue(self.form().is_valid())
        self.assertEqual(self.get_connection.call_args.kwargs['host'], 'mail.example.org')
        self.assertEqual(self.get_connection.call_args.kwargs['port'], 587)
        self.assertTrue(self.get_connection.return_value.open.called)

    def test_other_ports_are_not_checked(self):
        for port in ['22', '80', '5432', '2375', '8010']:
            with self.subTest(port=port):
                form = self.form(juntagrico_email_port=port)
                self.assertFalse(form.is_valid())
                self.assertIn('juntagrico_email_port', form.errors)

    def test_internal_addresses_are_not_checked(self):
        for addresses in [('127.0.0.1',), ('10.20.0.1',), ('192.168.1.1',), ('172.17.0.1',), ('169.254.169.254',),
                          ('100.64.0.1',), ('0.0.0.0',), ('::1',), ('fe80::1%eth0',), ('fd00::1',),
                          ('::ffff:127.0.0.1',), ('8.8.8.8', '10.0.0.1')]:
            with self.subTest(addresses=addresses):
                self.getaddrinfo.return_value = resolves_to(*addresses)
                self.assert_rejected_without_connection(self.form(), 'internen Netz')

    def test_localhost_is_not_checked(self):
        # resolve for real, this needs no network
        self.getaddrinfo.side_effect = REAL_GETADDRINFO
        self.assert_rejected_without_connection(self.form(juntagrico_email_host='localhost'), 'internen Netz')

    def test_unknown_server_and_missing_values(self):
        self.getaddrinfo.side_effect = socket.gaierror('not found')
        self.assert_rejected_without_connection(self.form(), 'nicht gefunden')
        self.assert_rejected_without_connection(self.form(juntagrico_email_host=''), 'kein E-Mail-Server')
        # port 'abc' is rejected at field level (ChoiceField), not in clean()
        form = self.form(juntagrico_email_port='abc')
        self.assertFalse(form.is_valid())
        self.assertIn('juntagrico_email_port', form.errors)

    def test_error_messages_have_no_details(self):
        for error, message in [
            (ConnectionRefusedError('[Errno 111] Connection refused'), 'lehnt die Verbindung ab'),
            (TimeoutError('timed out'), 'antwortet nicht'),
            (ssl.SSLError('WRONG_VERSION_NUMBER'), 'TLS/SSL'),
            (smtplib.SMTPServerDisconnected('Connection unexpectedly closed'), 'Prüfe deine Einstellungen'),
            (smtplib.SMTPConnectError(-1, b'HTTP/1.1 400 Bad Request'), 'Prüfe deine Einstellungen'),
        ]:
            with self.subTest(error=error):
                self.get_connection.return_value.open.side_effect = error
                form = self.form()
                self.assertFalse(form.is_valid())
                text = form.non_field_errors()[0]
                self.assertIn(message, text)
                for detail in ['Errno', 'timed out', 'WRONG_VERSION', 'unexpectedly', 'HTTP']:
                    self.assertNotIn(detail, text)

    def test_authentication_error_shows_server_answer(self):
        self.get_connection.return_value.open.side_effect = smtplib.SMTPAuthenticationError(
            535, b'5.7.8 Username and Password not accepted. Use an app password.')
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertIn('Use an app password', form.non_field_errors()[0])

    def test_skip_check(self):
        form = self.form(skip_check='')
        self.assertTrue(form.is_valid())
        self.assertFalse(self.getaddrinfo.called)
        self.assertFalse(self.get_connection.called)


MAIL_PASSWORD = 'MailSecret123'
SECRET_KEY = 'S' * 50


# Stored secrets of an app are never sent to the browser; an empty field keeps them.
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
class EnvSecretTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner')
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        self.env = AppEnv.objects.create(app=self.app, juntagrico_email_password=MAIL_PASSWORD,
                                         juntagrico_secret_key=SECRET_KEY, juntagrico_email_host='mail.example.org')

    def save(self, **data):
        from adminconsole.forms import EnvForm
        form = EnvForm({'juntagrico_email_host': 'mail.example.org', 'juntagrico_email_port': '587',
                        'juntagrico_email_security': 'none', 'skip_check': '', **data}, instance=self.env)
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
        self.save(juntagrico_email_password='NewMailPassword', juntagrico_secret_key='K' * 50)
        self.assertEqual(self.env.juntagrico_email_password, 'NewMailPassword')
        self.assertEqual(self.env.juntagrico_secret_key, 'K' * 50)

    def test_clear_password(self):
        self.save(clear_email_password='on')
        self.assertEqual(self.env.juntagrico_email_password, '')
        self.assertEqual(self.env.juntagrico_secret_key, SECRET_KEY)

    def test_generate_secret_key(self):
        self.save(new_secret_key='on')
        self.assertNotEqual(self.env.juntagrico_secret_key, SECRET_KEY)
        self.assertEqual(len(self.env.juntagrico_secret_key), 50)
        self.assertEqual(self.env.juntagrico_email_password, MAIL_PASSWORD)

    def test_failed_check_keeps_typed_password(self):
        # after a failed check the page offers "skip check and save", which must save the new password
        self.client.force_login(self.owner)
        with mock.patch('adminconsole.forms.socket.getaddrinfo', return_value=resolves_to('8.8.8.8')), \
                mock.patch('adminconsole.forms.get_connection') as get_connection:
            get_connection.return_value.open.side_effect = ConnectionRefusedError()
            content = self.client.post(f'/env/{self.app.id}/', {
                'juntagrico_email_host': 'mail.example.org', 'juntagrico_email_port': '587',
                'juntagrico_email_security': 'none',
                'juntagrico_email_password': 'TypedNewPassword',
            }).content.decode()
        self.assertIn('Prüfung überspringen', content)
        self.assertIn('value="TypedNewPassword"', content)
        self.assertNotIn(MAIL_PASSWORD, content)
        self.assertNotIn(SECRET_KEY, content)

    def test_smtp_check_uses_stored_password(self):
        from adminconsole.forms import EnvForm
        with mock.patch('adminconsole.forms.socket.getaddrinfo', return_value=resolves_to('8.8.8.8')), \
                mock.patch('adminconsole.forms.get_connection') as get_connection:
            for data, expected in [({}, MAIL_PASSWORD), ({'clear_email_password': 'on'}, '')]:
                with self.subTest(data=data):
                    form = EnvForm({'juntagrico_email_host': 'mail.example.org', 'juntagrico_email_port': '587',
                                    'juntagrico_email_security': 'none', **data}, instance=self.env)
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertEqual(get_connection.call_args.kwargs['password'], expected)


def docker_network(subnet='172.30.0.0/22', gateway='172.30.0.1', icc='false', bridge='br-juntagrico'):
    """ simulated existing Docker network """
    network = mock.MagicMock()
    network.name = 'juntagrico-apps'
    network.attrs = {'Driver': 'bridge', 'IPAM': {'Config': [{'Subnet': subnet, 'Gateway': gateway}]},
                     'Options': {'com.docker.network.bridge.enable_icc': icc,
                                 'com.docker.network.bridge.name': bridge}}
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
        self.assertEqual(kwargs['command'],
                        ['gunicorn', '--no-control-socket', '--forwarded-allow-ips', '172.30.0.1',
                         '--bind', '0.0.0.0:8010', '-t', '600', 'foo.wsgi'])
        self.assertEqual(kwargs['mem_limit'], '600m')
        # the database is reached at the gateway; the last value of a variable wins
        self.assertEqual(kwargs['environment'][-1], 'JUNTAGRICO_DATABASE_HOST=172.30.0.1')
        # the stored setting is unchanged, so switching back works
        self.assertEqual(AppEnv.objects.get(app=self.app).juntagrico_database_host, 'localhost')

    def test_network_is_created_if_missing(self):
        App.objects.filter(pk=self.app.pk).update(isolated_network=True)
        self.client.networks.get.side_effect = NotFound('no such network')
        self.client.networks.create.return_value = docker_network()
        self.restart()
        args, kwargs = self.client.networks.create.call_args
        self.assertEqual(args, ('juntagrico-apps',))
        self.assertEqual(kwargs['driver'], 'bridge')
        pool, = kwargs['ipam']['Config']
        self.assertEqual((pool['Subnet'], pool['Gateway']), ('172.30.0.0/22', '172.30.0.1'))
        self.assertEqual(kwargs['options'], {'com.docker.network.bridge.enable_icc': 'false',
                                             'com.docker.network.bridge.name': 'br-juntagrico'})

    @patch('adminconsole.management.commands.restart.stop_container')
    def test_wrong_network_keeps_the_running_container(self, mock_stop):
        App.objects.filter(pk=self.app.pk).update(isolated_network=True)
        for network in [docker_network(subnet='172.31.0.0/16'), docker_network(icc='true'),
                        docker_network(bridge='br-other'), docker_network(gateway='172.30.0.254')]:
            with self.subTest(attrs=network.attrs):
                self.client.reset_mock()
                self.client.networks.get.return_value = network
                with self.assertRaises(NetworkMismatch):
                    self.restart()
                self.assertFalse(self.client.containers.run.called, 'a new container was started')

    @override_settings(APPS_NETWORK={'name': 'juntagrico-apps', 'subnet': '10.99.0.0/24',
                                      'gateway': '10.99.0.1', 'bridge': 'br-juntagrico'},
                        APPS_MEMORY_LIMIT='1g')
    def test_settings(self):
        App.objects.filter(pk=self.app.pk).update(isolated_network=True)
        self.client.networks.get.return_value = docker_network(subnet='10.99.0.0/24', gateway='10.99.0.1')
        kwargs = self.restart()
        self.assertEqual(kwargs['environment'][-1], 'JUNTAGRICO_DATABASE_HOST=10.99.0.1')
        self.assertEqual(kwargs['mem_limit'], '1g')

    def test_setup_files(self):
        self.assertIn('net.ipv4.ip_nonlocal_bind = 1', (SETUP_DIR / '99-juntagrico-nonlocal-bind.conf').read_text())
        firewall = (SETUP_DIR / 'juntagrico-apps-firewall').read_text()
        self.assertIn('BRIDGE=br-juntagrico', firewall)
        unit = (SETUP_DIR / 'juntagrico-apps-firewall.service').read_text()
        self.assertIn('Before=network-pre.target docker.service', unit)
        self.assertIn('ExecStart=/usr/local/sbin/juntagrico-apps-firewall', unit)


# Exporting member data needs the password of the user, so a stolen session alone is not enough.
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
class ExportConfirmationTests(TestCase):
    EXPORTS = ['/dumpdata/{}/', '/pgdump/{}/']

    def setUp(self):
        self.owner = User.objects.create_user('owner', password='secret-pw')
        self.app = App.objects.create(name='foo', port=8010, user=self.owner)
        AppEnv.objects.create(app=self.app, juntagrico_database_name='foo')
        self.client.force_login(self.owner)
        for name, target in [('docker', 'docker.from_env'), ('run', 'subprocess.run')]:
            patcher = mock.patch(target)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.docker.return_value.containers.get.return_value.exec_run.return_value = mock.MagicMock(output=b'[]')
        self.run.return_value = mock.MagicMock(stdout=b'-- dump')

    def exported(self):
        return self.docker.return_value.containers.get.return_value.exec_run.called or self.run.called

    def test_get_asks_for_password(self):
        for url in self.EXPORTS:
            with self.subTest(url=url):
                response = self.client.get(url.format(self.app.id))
                self.assertTemplateUsed(response, 'generic/confirm_password.html')
                self.assertFalse(self.exported())

    def test_wrong_password_exports_nothing(self):
        for url in self.EXPORTS:
            with self.subTest(url=url), self.assertLogs('adminconsole.security', 'WARNING') as logs:
                response = self.client.post(url.format(self.app.id), {'password': 'wrong'})
                self.assertContains(response, 'Das Passwort ist falsch.')
                self.assertFalse(self.exported())
                self.assertIn('wrong password', logs.output[0])

    def test_correct_password_exports_and_logs(self):
        for url, extension in zip(self.EXPORTS, ['json', 'sql']):
            with self.subTest(url=url), self.assertLogs('adminconsole.security', 'INFO') as logs:
                response = self.client.post(url.format(self.app.id), {'password': 'secret-pw'},
                                            HTTP_X_REAL_IP='203.0.113.7')
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
        other.force_login(User.objects.create_user('other', password='other-pw'))
        for url in self.EXPORTS:
            with self.subTest(url=url):
                self.assertEqual(client.post(url.format(self.app.id), {'password': 'secret-pw'}).status_code, 403)
                response = other.post(url.format(self.app.id), {'password': 'other-pw'})
                self.assertRedirects(response, '/', fetch_redirect_response=False)
                self.assertFalse(self.exported())


# The progress check must not reveal whether other processes exist on the server.
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
class PidCheckTests(TestCase):
    def test_only_console_processes_are_reported(self):
        from adminconsole.util import pid_finished
        # a process like the ones the console starts (python -m manage ...)
        job = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '-m', 'manage'])
        self.addCleanup(job.kill)
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.addCleanup(other.kill)
        self.assertFalse(pid_finished(job.pid), 'running console job reported as finished')
        self.assertTrue(pid_finished(other.pid), 'other process revealed')
        self.assertTrue(pid_finished(os.getpid()), 'test runner revealed')
        self.assertTrue(pid_finished(4 if os.name == 'nt' else 1), 'system process revealed')
        job.kill()
        job.wait()
        self.assertTrue(pid_finished(job.pid))

    def test_view(self):
        user = User.objects.create_user('owner')
        self.client.force_login(user)
        with mock.patch('adminconsole.views.pid_finished', return_value=True) as finished:
            self.assertEqual(self.client.get('/pid/1/').json(), {'finished': True})
        finished.assert_called_once_with(1)


# create_database quotes the names; the statements take no parameters.
class CreateDatabaseTests(TestCase):
    def statements(self, name, password='ABC123', replace=False):
        from adminconsole.util.create_app import create_database
        app = App.objects.create(name=name, port=8010 + App.objects.count())
        env = AppEnv.objects.create(app=app)
        cursor = mock.MagicMock()
        with mock.patch('adminconsole.util.create_app.connection') as connection, \
                mock.patch('adminconsole.util.create_app.generate_password', return_value=password):
            connection.ops.quote_name = lambda value: '"%s"' % value
            connection.cursor.return_value.__enter__.return_value = cursor
            create_database(env, name, name, replace=replace)
        return [call.args[0] for call in cursor.execute.call_args_list]

    def test_statements(self):
        self.assertEqual(self.statements('foo-staging', replace=True), [
            'SET ROLE "foo_staging"',
            'DROP DATABASE IF EXISTS "foo_staging"',
            'RESET ROLE',
            'DROP USER IF EXISTS "foo_staging"',
            "CREATE USER \"foo_staging\" WITH PASSWORD 'ABC123'",
            "ALTER ROLE \"foo_staging\" SET client_encoding TO 'utf8'",
            "ALTER ROLE \"foo_staging\" SET default_transaction_isolation TO 'read committed'",
            "ALTER ROLE \"foo_staging\" SET timezone TO 'Europe/Zurich'",
            "CREATE DATABASE \"foo_staging\" OWNER \"foo_staging\" TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8'",
        ])

    def test_password_must_be_alphanumeric(self):
        for password in ["abc'; DROP USER x; --", 'äöü123', 'with space']:
            with self.subTest(password=password), self.assertRaises(ValueError):
                self.statements(f'app{len(password)}', password=password)
