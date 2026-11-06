from django.contrib.auth.models import User
from django.test import TestCase, tag
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice


class TwoFactorTests(TestCase):
    password = 'correct-horse-battery'  # nosec: B105

    def setUp(self):
        self.user = User.objects.create_superuser(
            'admin', 'admin@example.com', self.password
        )

    def add_device(self):
        return TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)

    def login_verified(self):
        device = self.add_device()
        self.client.force_login(self.user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse('home'))
        self.assertRedirects(
            response,
            reverse('two_factor:login') + '?next=/',
            fetch_redirect_response=False,
        )

    def test_owner_decorator_sends_anonymous_to_login(self):
        response = self.client.get(reverse('overview', args=[1]))
        self.assertRedirects(
            response,
            reverse('two_factor:login') + '?next=/overview/1/',
            fetch_redirect_response=False,
        )

    @tag('docker')
    def test_user_without_device_has_access(self):
        """Users without a 2FA device can access the console with password-only login."""
        self.client.force_login(self.user)
        for url in [reverse('home'), reverse('profile'), '/admin/']:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code, 200, f'{url} returned {response.status_code}'
            )

    def test_unverified_session_with_device_is_logged_out(self):
        """Users with a 2FA device must complete OTP verification."""
        self.add_device()
        self.client.force_login(self.user)
        response = self.client.get(reverse('profile'))
        self.assertRedirects(
            response,
            reverse('two_factor:login') + '?next=/profile',
            fetch_redirect_response=False,
        )
        self.assertNotIn('_auth_user_id', self.client.session)

    @tag('docker')
    def test_verified_user_has_access(self):
        self.login_verified()
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_password_reset_is_reachable(self):
        self.assertEqual(self.client.get(reverse('password_reset')).status_code, 200)
