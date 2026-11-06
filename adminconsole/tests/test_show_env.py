import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from adminconsole.models import App, AppEnv, AppEnvVar
from adminconsole.views import _is_sensitive_key, _mask_value


# =============================================================================
# _is_sensitive_key
# =============================================================================

class TestIsSensitiveKey(unittest.TestCase):
    """Test sensitive key detection based on key name patterns."""

    def test_secret_key_is_sensitive(self):
        self.assertTrue(_is_sensitive_key('SECRET_KEY'))

    def test_secret_lowercase(self):
        self.assertTrue(_is_sensitive_key('my_secret_value'))

    def test_password_key_is_sensitive(self):
        self.assertTrue(_is_sensitive_key('DATABASE_PASSWORD'))

    def test_password_lowercase(self):
        self.assertTrue(_is_sensitive_key('user_password'))

    def test_mixed_case_secret(self):
        self.assertTrue(_is_sensitive_key('ApiSecret'))

    def test_mixed_case_password(self):
        self.assertTrue(_is_sensitive_key('DbPassword'))

    def test_normal_key_not_sensitive(self):
        self.assertFalse(_is_sensitive_key('DATABASE_HOST'))

    def test_debug_key_not_sensitive(self):
        self.assertFalse(_is_sensitive_key('DEBUG'))

    def test_allowed_hosts_not_sensitive(self):
        self.assertFalse(_is_sensitive_key('ALLOWED_HOSTS'))

    def test_empty_string_not_sensitive(self):
        self.assertFalse(_is_sensitive_key(''))

    def test_secret_as_substring_in_value_not_key(self):
        """Key containing 'SECRET' as part of a different word should still match."""
        self.assertTrue(_is_sensitive_key('SECRETARY'))

    def test_password_as_substring(self):
        self.assertTrue(_is_sensitive_key('PASSWORD_RESET'))


# =============================================================================
# _mask_value
# =============================================================================

class TestMaskValue(unittest.TestCase):
    """Test recursive value masking for sensitive keys and secret values."""

    # -- Scalar values --

    def test_plain_string_unchanged(self):
        self.assertEqual(_mask_value('hello'), 'hello')

    def test_plain_string_with_secret_substring(self):
        self.assertEqual(_mask_value('prefix_my_secret_suffix', {'my_secret'}), 'prefix_****_suffix')

    def test_multiple_secret_replacements(self):
        result = _mask_value('abc_secret1_xyz_secret2_end', {'secret1', 'secret2'})
        self.assertEqual(result, 'abc_****_xyz_****_end')

    def test_integer_unchanged(self):
        self.assertEqual(_mask_value(42, {'secret'}), 42)

    def test_boolean_unchanged(self):
        self.assertEqual(_mask_value(True, {'secret'}), True)

    def test_none_unchanged(self):
        self.assertEqual(_mask_value(None, {'secret'}), None)

    def test_empty_secret_set(self):
        self.assertEqual(_mask_value('my_secret_value', set()), 'my_secret_value')

    # -- Dict values --

    def test_dict_sensitive_key_masked(self):
        result = _mask_value({'SECRET_KEY': 'actual_secret', 'DEBUG': True})
        self.assertEqual(result, {'SECRET_KEY': '****', 'DEBUG': True})

    def test_dict_password_key_masked(self):
        result = _mask_value({'DB_PASSWORD': 'pass123', 'DB_HOST': 'localhost'})
        self.assertEqual(result, {'DB_PASSWORD': '****', 'DB_HOST': 'localhost'})

    def test_dict_no_sensitive_keys(self):
        result = _mask_value({'DEBUG': True, 'HOST': 'localhost'})
        self.assertEqual(result, {'DEBUG': True, 'HOST': 'localhost'})

    def test_dict_nested_with_sensitive_key(self):
        input_val = {'OUTER': {'SECRET_KEY': 'hidden', 'VISIBLE': 'shown'}}
        result = _mask_value(input_val)
        self.assertEqual(result, {'OUTER': {'SECRET_KEY': '****', 'VISIBLE': 'shown'}})

    def test_dict_deeply_nested(self):
        input_val = {'L1': {'L2': {'L3': {'PASSWORD': 'deep_secret'}}}}
        result = _mask_value(input_val)
        self.assertEqual(result, {'L1': {'L2': {'L3': {'PASSWORD': '****'}}}})

    def test_dict_with_secret_value_substring(self):
        secret_vals = {'my_db_password'}
        input_val = {'DATABASE_URL': 'postgres://user:my_db_password@host/db'}
        result = _mask_value(input_val, secret_vals)
        self.assertEqual(result, {'DATABASE_URL': 'postgres://user:****@host/db'})

    # -- List/Tuple values --

    def test_list_of_strings_with_secret(self):
        secret_vals = {'top_secret'}
        result = _mask_value(['hello', 'top_secret', 'world'], secret_vals)
        self.assertEqual(result, ['hello', '****', 'world'])

    def test_list_of_strings_no_secret(self):
        result = _mask_value(['hello', 'world'], {'other'})
        self.assertEqual(result, ['hello', 'world'])

    def test_list_of_integers(self):
        result = _mask_value([1, 2, 3], {'secret'})
        self.assertEqual(result, [1, 2, 3])

    def test_tuple_preserved(self):
        result = _mask_value(('a', 'b', 'c'), set())
        self.assertIsInstance(result, tuple)
        self.assertEqual(result, ('a', 'b', 'c'))

    def test_nested_list_with_dict(self):
        input_val = [{'PASSWORD': 'secret'}, 'normal']
        result = _mask_value(input_val)
        self.assertEqual(result, [{'PASSWORD': '****'}, 'normal'])

    def test_list_with_secret_substring(self):
        secret_vals = {'my_key'}
        result = _mask_value(['prefix_my_key_suffix'], secret_vals)
        self.assertEqual(result, ['prefix_****_suffix'])

    # -- Complex nested structures --

    def test_complex_nested_structure(self):
        input_val = {
            'SECRET_KEY': 'should_be_masked',
            'DATABASES': {
                'default': {
                    'PASSWORD': 'db_pass',
                    'HOST': 'localhost',
                    'PORT': 5432,
                }
            },
            'ALLOWED_HOSTS': ['example.com', 'localhost'],
            'DEBUG': True,
        }
        result = _mask_value(input_val, {'some_env_secret'})
        self.assertEqual(result['SECRET_KEY'], '****')
        self.assertEqual(result['DATABASES']['default']['PASSWORD'], '****')
        self.assertEqual(result['DATABASES']['default']['HOST'], 'localhost')
        self.assertEqual(result['DATABASES']['default']['PORT'], 5432)
        self.assertEqual(result['ALLOWED_HOSTS'], ['example.com', 'localhost'])
        self.assertEqual(result['DEBUG'], True)

    def test_empty_dict(self):
        self.assertEqual(_mask_value({}), {})

    def test_empty_list(self):
        self.assertEqual(_mask_value([], set()), [])


# =============================================================================
# show_env view (integration tests with mocked Docker)
# =============================================================================

class ShowEnvTests(TestCase):
    """Test the show_env view with mocked Docker container."""

    password = 'test-password'

    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'admin@example.com', self.password)
        self.app = App.objects.create(name='testapp', port=8001, user=self.user)
        self.env = AppEnv.objects.create(app=self.app, juntagrico_secret_key='my-secret-key')

    def add_device(self):
        return TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)

    def login_verified(self):
        device = self.add_device()
        self.client.force_login(self.user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def _mock_container(self, output_bytes):
        """Create a mock Docker container that returns the given exec_run output."""
        mock_container = MagicMock()
        mock_container.exec_run.return_value = MagicMock(output=output_bytes)
        return mock_container

    def test_show_env_accessible(self):
        """Authenticated user can access show_env."""
        mock_container = self._mock_container(b'DEBUG = True\n')
        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
            self.assertEqual(response.status_code, 200)

    def test_show_env_parses_simple_settings(self):
        """Simple key=value lines are parsed correctly."""
        output = b'DEBUG = True\nALLOWED_HOSTS = [\'localhost\', \'example.com\']\n'
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('settings', response.context)
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['DEBUG'], True)
        self.assertEqual(settings['ALLOWED_HOSTS'], ['localhost', 'example.com'])

    def test_show_env_masks_secret_key(self):
        """Keys containing SECRET or PASSWORD are masked."""
        output = b"SECRET_KEY = 'actual_secret'\nDEBUG = True\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        self.assertEqual(response.status_code, 200)
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['SECRET_KEY'], '****')
        self.assertEqual(settings['DEBUG'], True)

    def test_show_env_masks_password_key(self):
        """Keys containing PASSWORD are masked."""
        output = b"DATABASE_PASSWORD = 'super_secret'\nDATABASE_HOST = 'localhost'\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['DATABASE_PASSWORD'], '****')
        self.assertEqual(settings['DATABASE_HOST'], 'localhost')

    def test_show_env_masks_secret_env_var_values(self):
        """Values matching secret AppEnvVar values are masked as substrings."""
        AppEnvVar.objects.create(env=self.env, key='MY_API_KEY', value='api_secret_123', secret=True)
        output = b"API_KEY = 'api_secret_123'\nAPI_URL = 'https://api.example.com'\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['API_KEY'], '****')
        self.assertEqual(settings['API_URL'], 'https://api.example.com')

    def test_show_env_masks_nested_secret_keys(self):
        """Sensitive keys inside nested dicts are masked recursively."""
        output = b"DATABASES = {'default': {'PASSWORD': 'db_pass', 'HOST': 'localhost'}}\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['DATABASES']['default']['PASSWORD'], '****')
        self.assertEqual(settings['DATABASES']['default']['HOST'], 'localhost')

    def test_show_env_masks_env_secret_key(self):
        """The juntagrico_secret_key from AppEnv is masked in settings values."""
        self.env.juntagrico_secret_key = 'env_secret_key_value'
        self.env.save()
        output = b"SECRET_KEY = 'env_secret_key_value'\nDEBUG = True\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        # SECRET_KEY is masked by the key name pattern
        self.assertEqual(settings['SECRET_KEY'], '****')

    def test_show_env_empty_output(self):
        """Empty diffsettings output returns empty settings list."""
        mock_container = self._mock_container(b'')

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['settings'], [])

    def test_show_env_skips_diff_separators(self):
        """Lines starting with --- or +++ are skipped."""
        output = b'--- Django defaults\n+++ Current settings\nDEBUG = True\n'
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['DEBUG'], True)
        self.assertNotIn('---', settings)

    def test_show_env_strips_triple_hash(self):
        """The ### marker is stripped from setting lines."""
        output = b"DEBUG = True ###\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['DEBUG'], True)

    def test_show_env_falls_back_to_string(self):
        """Values that cannot be parsed as Python literals are kept as strings."""
        output = b"MY_SETTING = some_unquoted_value\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['MY_SETTING'], 'some_unquoted_value')

    def test_show_env_docker_error(self):
        """Docker errors are handled gracefully."""
        from docker.errors import DockerException
        mock_container = MagicMock()
        mock_container.exec_run.side_effect = DockerException('Connection refused')

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['settings'], [])

    def test_show_env_ownership_check(self):
        """Non-owner is redirected to home by the owner_of_app decorator."""
        other_user = User.objects.create_user('other', 'other@example.com', self.password)
        self.client.force_login(other_user)
        response = self.client.get(f'/env/show/{self.app.id}/')
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_show_env_anonymous_redirects(self):
        """Anonymous users are redirected to login."""
        response = self.client.get(f'/env/show/{self.app.id}/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_show_env_list_in_setting(self):
        """List values in settings are preserved."""
        output = b"INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth']\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['INSTALLED_APPS'], ['django.contrib.admin', 'django.contrib.auth'])

    def test_show_env_tuple_in_setting(self):
        """Tuple values in settings are preserved."""
        output = b"TIME_ZONE = ('UTC',)\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['TIME_ZONE'], ('UTC',))

    def test_show_env_secret_in_nested_list(self):
        """Secret values inside nested lists are masked."""
        AppEnvVar.objects.create(env=self.env, key='TOKEN', value='hidden_token', secret=True)
        output = b"MY_LIST = ['visible', 'hidden_token', 'also_visible']\n"
        mock_container = self._mock_container(output)

        self.login_verified()
        with patch.object(App, 'container', new_callable=lambda: property(lambda self: mock_container)):
            response = self.client.get(f'/env/show/{self.app.id}/')
        settings = {s['key']: s['value'] for s in response.context['settings']}
        self.assertEqual(settings['MY_LIST'], ['visible', '****', 'also_visible'])


if __name__ == '__main__':
    unittest.main()
