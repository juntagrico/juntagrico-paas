import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings, modify_settings

from adminconsole.models import App, AppEnv


# Actions that change state must only run on POST with a valid CSRF token.
ACTIONS = [
    '/reload/{}/',
    '/rebuild/{}/',
    '/crestart/{}/',
    '/migrate/{}/',
    '/collectstatic/{}/',
    '/gdl/{}/',
    '/env/restart/{}/',
    '/ca/clonerepo/{}/',
    '/git/push/{}/',
    '/ca/db/{}/',
    '/ca/domain/{}/',
    '/ca/cronjob/{}/',
    '/ca/build/{}/',
    '/ca/createadmin/{}/',
]


# 2FA is not under test here: logged-in test users must not be sent to the 2FA setup
@modify_settings(MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']})
@override_settings(PYTHON_BIN='python', APPS_DOMAIN='.example.org')
class CsrfProtectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pw')
        self.other = User.objects.create_user('other', password='pw')
        self.app = App.objects.create(name='foo', port=8010, user=self.owner, version=1, git_clone_url='https://x/y.git')
        AppEnv.objects.create(app=self.app)

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / 'build').mkdir()
        self.mocks = {}
        for name, target in {
            'popen': 'subprocess.Popen',
            'run': 'subprocess.run',
            'docker': 'docker.from_env',
            'create_database': 'adminconsole.views.create.create_database',
            'git_clone': 'adminconsole.views.git.git_clone',
            'make_dirs': 'adminconsole.views.git.make_dirs',
            'sleep': 'adminconsole.views.sleep',
        }.items():
            patcher = mock.patch(target)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in {'dir': tmp, 'log_file': str(tmp / 'log.txt')}.items():
            patcher = mock.patch.object(App, name, new_callable=mock.PropertyMock, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.mocks['popen'].return_value.pid = 4242
        self.mocks['run'].return_value = mock.MagicMock(returncode=0, stdout=b'')
        self.mocks['git_clone'].return_value = True
        self.mocks['make_dirs'].return_value = True
        container = self.mocks['docker'].return_value.containers.get.return_value
        container.exec_run.return_value = mock.MagicMock(output=b'ok', exit_code=0)
        container.attrs = {'State': {'StartedAt': '2026-10-18T10:00:00.000Z'}}

    def assert_no_action(self):
        for name, m in self.mocks.items():
            if name != 'sleep':
                self.assertFalse(m.called, f'{name} was called')

    def assert_action(self):
        self.assertTrue(any(m.called for name, m in self.mocks.items() if name != 'sleep'))

    def test_get_only_shows_confirmation(self):
        self.client.force_login(self.owner)
        for url in ACTIONS:
            with self.subTest(url=url):
                response = self.client.get(url.format(self.app.id))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'generic/submit.html')
                self.assert_no_action()

    def test_post_without_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url in ACTIONS:
            with self.subTest(url=url):
                response = client.post(url.format(self.app.id))
                self.assertEqual(response.status_code, 403)
                self.assert_no_action()

    def test_post_by_owner_runs_action(self):
        self.client.force_login(self.owner)
        for url in ACTIONS:
            with self.subTest(url=url):
                for m in self.mocks.values():
                    m.reset_mock()
                response = self.client.post(url.format(self.app.id))
                self.assertIn(response.status_code, (200, 302))
                self.assert_action()

    def test_post_by_other_user_runs_nothing(self):
        self.client.force_login(self.other)
        for url in ACTIONS:
            with self.subTest(url=url):
                response = self.client.post(url.format(self.app.id))
                self.assertRedirects(response, '/', fetch_redirect_response=False)
                self.assert_no_action()

    def test_env_form_applies_settings_directly(self):
        # saving the env form of a v1 app applies the settings without a second request
        self.client.force_login(self.owner)
        response = self.client.post(f'/env/{self.app.id}/', {
            'juntagrico_email_port': '25', 'juntagrico_secret_key': 'x' * 50, 'skip_check': '1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'wait_next.html')
        self.assertIn('reload_env', self.mocks['popen'].call_args.args[0])

    def test_overview_uses_forms_for_actions(self):
        self.client.force_login(self.owner)
        response = self.client.get(f'/overview/{self.app.id}/')
        content = response.content.decode()
        for path in ['/reload/', '/rebuild/', '/migrate/', '/collectstatic/', '/crestart/', '/gdl/']:
            with self.subTest(path=path):
                self.assertNotIn(f'href="{path}{self.app.id}/"', content)
                self.assertIn(f'action="{path}{self.app.id}/" method="post"', content)
        self.assert_no_action_except_status()

    def assert_no_action_except_status(self):
        # the overview only reads the container status
        self.assertFalse(self.mocks['popen'].called)
        self.assertFalse(self.mocks['run'].called)
        container = self.mocks['docker'].return_value.containers.get.return_value
        self.assertFalse(container.exec_run.called)
        self.assertFalse(container.restart.called)
