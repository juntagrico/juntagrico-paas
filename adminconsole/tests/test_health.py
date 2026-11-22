import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, Client, modify_settings, override_settings
from django.urls import reverse

from adminconsole.models import App, JuntagricoVersion
from adminconsole.util import get_juntagrico_version_badge
from adminconsole.util.docker import get_container_statuses


@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
@override_settings(PYTHON_BIN='python')
class GetContainerStatusesTests(TestCase):
    """Test get_container_statuses() with mocked Docker API."""

    def _make_container(self, name, status, health=None):
        """Helper to create a mock container with the given name, status, and health."""
        container = MagicMock()
        container.name = name
        container.status = status
        if health is not None:
            container.attrs = {'State': {'Health': {'Status': health}}}
        else:
            container.attrs = {'State': {}}
        return container

    def test_returns_running_for_running_container(self):
        """Running container should have running=True."""
        containers = [self._make_container('myapp', 'running')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {})
        self.assertTrue(result['myapp']['running'])

    def test_returns_running_for_created_container(self):
        """Created container should have running=True."""
        containers = [self._make_container('myapp', 'created')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {})
        self.assertTrue(result['myapp']['running'])

    def test_returns_running_for_restarting_container(self):
        """Restarting container should have running=True."""
        containers = [self._make_container('myapp', 'restarting')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {})
        self.assertTrue(result['myapp']['running'])

    def test_returns_not_running_for_exited_container(self):
        """Exited container should have running=False."""
        containers = [self._make_container('myapp', 'exited')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {})
        self.assertFalse(result['myapp']['running'])

    def test_returns_not_running_for_missing_container(self):
        """Container not in Docker should not appear in results."""
        containers = []
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {})
        self.assertNotIn('myapp', result)

    def test_health_none_for_v2_app(self):
        """V2 apps should not have health status (no HEALTHCHECK)."""
        containers = [self._make_container('myapp', 'running', 'healthy')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {'myapp': 2})
        self.assertIsNone(result['myapp']['health'])

    def test_health_healthy_for_v3_app(self):
        """V3+ apps with healthy status should return 'healthy'."""
        containers = [self._make_container('myapp', 'running', 'healthy')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {'myapp': 3})
        self.assertEqual(result['myapp']['health'], 'healthy')

    def test_health_unhealthy_for_v3_app(self):
        """V3+ apps with unhealthy status should return 'unhealthy'."""
        containers = [self._make_container('myapp', 'running', 'unhealthy')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {'myapp': 3})
        self.assertEqual(result['myapp']['health'], 'unhealthy')

    def test_health_starting_for_v3_app(self):
        """V3+ apps with starting status should return 'starting'."""
        containers = [self._make_container('myapp', 'running', 'starting')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {'myapp': 3})
        self.assertEqual(result['myapp']['health'], 'starting')

    def test_health_none_when_no_healthcheck(self):
        """V3+ app without HEALTHCHECK in Dockerfile should have health=None."""
        container = self._make_container('myapp', 'running')
        # No 'Health' key in State
        container.attrs = {'State': {}}
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = [container]
            result = get_container_statuses({'myapp'}, {'myapp': 3})
        self.assertIsNone(result['myapp']['health'])

    def test_filters_by_app_names(self):
        """Only requested app names should appear in results."""
        containers = [
            self._make_container('myapp', 'running'),
            self._make_container('otherapp', 'running'),
        ]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'}, {})
        self.assertIn('myapp', result)
        self.assertNotIn('otherapp', result)

    def test_multiple_containers(self):
        """Multiple containers should all be returned with correct status."""
        containers = [
            self._make_container('app1', 'running', 'healthy'),
            self._make_container('app2', 'exited'),
            self._make_container('app3', 'running', 'unhealthy'),
        ]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses(
                {'app1', 'app2', 'app3'}, {'app1': 3, 'app2': 2, 'app3': 3}
            )
        self.assertTrue(result['app1']['running'])
        self.assertEqual(result['app1']['health'], 'healthy')
        self.assertFalse(result['app2']['running'])
        self.assertIsNone(result['app2']['health'])
        self.assertTrue(result['app3']['running'])
        self.assertEqual(result['app3']['health'], 'unhealthy')

    def test_default_app_versions_empty(self):
        """When app_versions is None, health should be None for all apps."""
        containers = [self._make_container('myapp', 'running', 'healthy')]
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value.containers.list.return_value = containers
            result = get_container_statuses({'myapp'})
        self.assertIsNone(result['myapp']['health'])


@modify_settings(
    MIDDLEWARE={'remove': ['adminconsole.middleware.RequireOTPMiddleware']}
)
@override_settings(PYTHON_BIN='python')
class HealthStatusViewTests(TestCase):
    """Test the /api/health/ AJAX endpoint."""

    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pw')
        self.superuser = User.objects.create_superuser(
            'admin', password='admin', email='admin@example.com'
        )
        self.app_v2 = App.objects.create(
            name='app-v2', port=8010, version=2, user=self.owner
        )
        self.app_v3 = App.objects.create(
            name='app-v3', port=8011, version=3, user=self.owner
        )
        self.staging_app = App.objects.create(
            name='app-v3-staging',
            port=8012,
            version=3,
            staging_of=self.app_v3,
            user=self.owner,
        )
        self.other_app = App.objects.create(
            name='other-app',
            port=8013,
            version=3,
            user=User.objects.create_user('other', password='other'),
        )
        self.client = Client()

    def _mock_containers(self, containers):
        """Helper to create a patch for docker.from_env with the given containers."""
        mock_client = MagicMock()
        mock_client.containers.list.return_value = containers
        return mock_client

    def _make_container(self, name, status, health=None):
        """Helper to create a mock container."""
        container = MagicMock()
        container.name = name
        container.status = status
        if health is not None:
            container.attrs = {'State': {'Health': {'Status': health}}}
        else:
            container.attrs = {'State': {}}
        return container

    def test_anonymous_user_redirects_to_login(self):
        """Unauthenticated requests should redirect to login."""
        resp = self.client.get(reverse('health-status'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_regular_user_sees_only_own_apps(self):
        """Non-superuser should see only apps assigned to them."""
        containers = [
            self._make_container('app-v2', 'running'),
            self._make_container('app-v3', 'running', 'healthy'),
            self._make_container('other-app', 'running', 'unhealthy'),
        ]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('app-v2', data)
        self.assertIn('app-v3', data)
        self.assertNotIn('other-app', data)

    def test_superuser_sees_all_apps(self):
        """Superuser should see all apps, including other users' apps."""
        containers = [
            self._make_container('app-v2', 'running'),
            self._make_container('app-v3', 'running', 'healthy'),
            self._make_container('other-app', 'running', 'unhealthy'),
        ]
        self.client.force_login(self.superuser)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('app-v2', data)
        self.assertIn('app-v3', data)
        self.assertIn('other-app', data)

    def test_includes_staging_apps(self):
        """Staging apps should be included in the health response."""
        containers = [
            self._make_container('app-v3', 'running', 'healthy'),
            self._make_container('app-v3-staging', 'running', 'starting'),
        ]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('app-v3-staging', data)
        self.assertEqual(data['app-v3-staging']['health'], 'starting')

    def test_v2_app_has_no_health(self):
        """V2 apps should have health=None in the response."""
        containers = [self._make_container('app-v2', 'running')]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        self.assertIsNone(data['app-v2']['health'])

    def test_v3_app_has_health(self):
        """V3 apps should have health status in the response."""
        containers = [self._make_container('app-v3', 'running', 'healthy')]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        self.assertEqual(data['app-v3']['health'], 'healthy')

    def test_running_status_reflects_container_state(self):
        """Running status should be False for exited containers."""
        containers = [self._make_container('app-v3', 'exited')]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        self.assertFalse(data['app-v3']['running'])

    def test_missing_container_not_in_response(self):
        """Apps without running containers should not appear in the response."""
        containers = []
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        self.assertNotIn('app-v3', data)

    def test_response_is_json(self):
        """Response content type should be JSON."""
        containers = [self._make_container('app-v3', 'running', 'healthy')]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        self.assertEqual(resp['Content-Type'], 'application/json')

    def test_response_format(self):
        """Response should be a dict of app_name -> {running, health, juntagrico_badge}."""
        containers = [
            self._make_container('app-v3', 'running', 'healthy'),
            self._make_container('app-v2', 'exited'),
        ]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        for status in data.values():
            self.assertIn('running', status)
            self.assertIn('health', status)
            self.assertIn('juntagrico_badge', status)
            self.assertIsInstance(status['running'], bool)

    def test_response_includes_juntagrico_badge(self):
        """Response should include juntagrico_badge computed from DB."""
        self.app_v3.juntagrico_version = '2.0.14'
        self.app_v3.save()
        JuntagricoVersion.objects.create(version='2.0.14')
        containers = [self._make_container('app-v3', 'running', 'healthy')]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        self.assertEqual(data['app-v3']['juntagrico_badge'], 'success')

    def test_badge_danger_for_unsupported_version(self):
        """Apps with versions below min_version should get danger badge."""
        self.app_v3.juntagrico_version = '1.5.0'
        self.app_v3.save()
        containers = [self._make_container('app-v3', 'running', 'healthy')]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        self.assertEqual(data['app-v3']['juntagrico_badge'], 'danger')

    def test_badge_warning_for_non_latest_supported(self):
        """Supported but non-latest bugfix versions should get warning badge."""
        self.app_v3.juntagrico_version = '2.0.10'
        self.app_v3.save()
        # Only 2.0.14 is stored (the latest), 2.0.10 is not in DB
        JuntagricoVersion.objects.create(version='2.0.14')
        containers = [self._make_container('app-v3', 'running', 'healthy')]
        self.client.force_login(self.owner)
        with patch('docker.from_env') as mock_docker:
            mock_docker.return_value = self._mock_containers(containers)
            resp = self.client.get(reverse('health-status'))
        data = resp.json()
        self.assertEqual(data['app-v3']['juntagrico_badge'], 'warning')


class JuntagricoVersionBadgeTests(TestCase):
    """Test the get_juntagrico_version_badge() function."""

    def setUp(self):
        JuntagricoVersion.objects.all().delete()

    def test_empty_version_returns_warning(self):
        """Empty version string should return warning."""
        self.assertEqual(get_juntagrico_version_badge(''), 'warning')
        self.assertEqual(get_juntagrico_version_badge(None), 'warning')

    def test_below_min_version_returns_danger(self):
        """Versions below min_version should return danger."""
        self.assertEqual(get_juntagrico_version_badge('1.5.0'), 'danger')
        self.assertEqual(get_juntagrico_version_badge('1.9.9'), 'danger')

    def test_latest_bugfix_returns_success(self):
        """Latest bugfix of a supported version should return success."""
        JuntagricoVersion.objects.create(version='2.0.14')
        JuntagricoVersion.objects.create(version='2.1.1')
        self.assertEqual(get_juntagrico_version_badge('2.0.14'), 'success')
        self.assertEqual(get_juntagrico_version_badge('2.1.1'), 'success')

    def test_older_bugfix_returns_warning(self):
        """Older bugfix of a supported version should return warning."""
        # Only the latest (2.0.14) is stored, 2.0.10 is not in DB
        JuntagricoVersion.objects.create(version='2.0.14')
        self.assertEqual(get_juntagrico_version_badge('2.0.10'), 'warning')

    def test_unsupported_version_returns_danger(self):
        """Versions below min_version should return danger regardless of DB."""
        self.assertEqual(get_juntagrico_version_badge('1.5.0'), 'danger')

    def test_invalid_version_returns_warning(self):
        """Invalid version strings should return warning."""
        self.assertEqual(get_juntagrico_version_badge('abc'), 'warning')
        self.assertEqual(get_juntagrico_version_badge('2.x.1'), 'warning')

    def test_version_not_in_db_returns_warning(self):
        """Version not in DB but above min_version should return warning."""
        self.assertEqual(get_juntagrico_version_badge('2.0.14'), 'warning')

    @override_settings(JUNTAGRICO_MIN_VERSION='2.1.0')
    def test_custom_min_version(self):
        """Custom min_version setting should be respected."""
        JuntagricoVersion.objects.create(version='2.1.1')
        # 2.0.14 is below custom min 2.1.0
        self.assertEqual(get_juntagrico_version_badge('2.0.14'), 'danger')
        # 2.1.1 is the latest bugfix of 2.1.x
        self.assertEqual(get_juntagrico_version_badge('2.1.1'), 'success')


class UpdateJuntagricoVersionsCommandTests(TestCase):
    """Test the update_juntagrico_versions management command."""

    def setUp(self):
        JuntagricoVersion.objects.all().delete()

    def test_fetches_and_creates_versions(self):
        """Command should create only latest stable versions from PyPI."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'releases': {
                '2.0.13': [],
                '2.0.14': [],
                '2.1.1': [],
                '2.1.0a1': [],
                '1.5.0': [],
            }
        }).encode('utf-8')
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None
        with patch('urllib.request.urlopen', return_value=mock_response):
            with patch('urllib.request.Request'):
                call_command('update_juntagrico_versions', stdout=MagicMock())
        # Only latest per major.minor should be stored (2.0.14 and 2.1.1)
        # 2.0.13 is not the latest, 1.5.0 is below min, 2.1.0a1 is a pre-release
        self.assertEqual(JuntagricoVersion.objects.count(), 2)
        self.assertTrue(JuntagricoVersion.objects.filter(version='2.0.14').exists())
        self.assertTrue(JuntagricoVersion.objects.filter(version='2.1.1').exists())
        # 2.0.13 should not exist (not the latest for 2.0.x)
        self.assertFalse(JuntagricoVersion.objects.filter(version='2.0.13').exists())
        # 1.5.0 should not exist (below min_version)
        self.assertFalse(JuntagricoVersion.objects.filter(version='1.5.0').exists())
        # Pre-release should not exist
        self.assertFalse(JuntagricoVersion.objects.filter(version='2.1.0a1').exists())

    def test_handles_network_error(self):
        """Command should handle network errors gracefully."""
        with patch('urllib.request.urlopen', side_effect=Exception('timeout')):
            with patch('urllib.request.Request'):
                call_command('update_juntagrico_versions', stdout=MagicMock())
        self.assertEqual(JuntagricoVersion.objects.count(), 0)

    def test_updates_existing_versions(self):
        """Command should update existing records."""
        JuntagricoVersion.objects.create(version='2.0.14')
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'releases': {
                '2.0.14': [],
            }
        }).encode('utf-8')
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None
        with patch('urllib.request.urlopen', return_value=mock_response):
            with patch('urllib.request.Request'):
                call_command('update_juntagrico_versions', stdout=MagicMock())
        self.assertTrue(JuntagricoVersion.objects.filter(version='2.0.14').exists())

    def test_removes_old_versions_below_new_min(self):
        """Versions below the new min_version should be removed."""
        JuntagricoVersion.objects.create(version='1.5.0')
        JuntagricoVersion.objects.create(version='2.0.14')
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'releases': {
                '2.0.14': [],
                '1.5.0': [],
            }
        }).encode('utf-8')
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None
        with patch('urllib.request.urlopen', return_value=mock_response):
            with patch('urllib.request.Request'):
                call_command('update_juntagrico_versions', stdout=MagicMock())
        # 1.5.0 should be removed (below min_version 2.0.0)
        self.assertFalse(JuntagricoVersion.objects.filter(version='1.5.0').exists())
        self.assertTrue(JuntagricoVersion.objects.filter(version='2.0.14').exists())

    def test_ignores_prereleases(self):
        """Pre-release versions should not be stored."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'releases': {
                '2.0.14': [],
                '2.1.0a1': [],
                '2.1.0b1': [],
                '2.1.0rc1': [],
                '2.1.1': [],
            }
        }).encode('utf-8')
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None
        with patch('urllib.request.urlopen', return_value=mock_response):
            with patch('urllib.request.Request'):
                call_command('update_juntagrico_versions', stdout=MagicMock())
        # Only stable releases should be stored
        self.assertEqual(JuntagricoVersion.objects.count(), 2)
        self.assertTrue(JuntagricoVersion.objects.filter(version='2.0.14').exists())
        self.assertTrue(JuntagricoVersion.objects.filter(version='2.1.1').exists())
        self.assertFalse(JuntagricoVersion.objects.filter(version='2.1.0a1').exists())
        self.assertFalse(JuntagricoVersion.objects.filter(version='2.1.0rc1').exists())

    def test_removes_outdated_latest(self):
        """Old latest versions should be removed when superseded."""
        # Simulate: 2.0.14 was the latest, now 2.0.15 is released
        JuntagricoVersion.objects.create(version='2.0.14')
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'releases': {
                '2.0.14': [],
                '2.0.15': [],
            }
        }).encode('utf-8')
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None
        with patch('urllib.request.urlopen', return_value=mock_response):
            with patch('urllib.request.Request'):
                call_command('update_juntagrico_versions', stdout=MagicMock())
        # Only 2.0.15 should remain
        self.assertEqual(JuntagricoVersion.objects.count(), 1)
        self.assertFalse(JuntagricoVersion.objects.filter(version='2.0.14').exists())
        self.assertTrue(JuntagricoVersion.objects.filter(version='2.0.15').exists())
