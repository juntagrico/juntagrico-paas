from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, Client, modify_settings, override_settings
from django.urls import reverse

from adminconsole.models import App
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
        """Response should be a dict of app_name -> {running, health}."""
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
            self.assertIsInstance(status['running'], bool)
