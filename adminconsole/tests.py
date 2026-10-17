from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice


class TwoFactorTests(TestCase):
    password = 'correct-horse-battery'

    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'admin@example.com', self.password)

    def add_device(self):
        return TOTPDevice.objects.create(user=self.user, name='default', confirmed=True)

    def login_verified(self):
        device = self.add_device()
        self.client.force_login(self.user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def test_anonymous_is_sent_to_two_factor_login(self):
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('two_factor:login') + '?next=/', fetch_redirect_response=False)

    def test_owner_decorator_sends_anonymous_to_login(self):
        response = self.client.get(reverse('overview', args=[1]))
        self.assertRedirects(response, reverse('two_factor:login') + '?next=/overview/1/', fetch_redirect_response=False)

    def test_password_only_login_is_redirected(self):
        response = self.client.get('/accounts/login/?next=/profile')
        self.assertRedirects(response, reverse('two_factor:login') + '?next=/profile', fetch_redirect_response=False)

    def test_user_without_device_must_set_up_2fa(self):
        self.client.force_login(self.user)
        for url in [reverse('home'), reverse('profile'), reverse('pgdump', args=[1]), '/admin/']:
            response = self.client.get(url)
            self.assertRedirects(response, reverse('two_factor:setup'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('two_factor:setup')).status_code, 200)

    def test_unverified_session_with_device_is_logged_out(self):
        self.add_device()
        self.client.force_login(self.user)
        response = self.client.get(reverse('profile'))
        self.assertRedirects(response, reverse('two_factor:login') + '?next=/profile', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_verified_user_has_access(self):
        self.login_verified()
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_login_requires_token(self):
        device = self.add_device()
        url = reverse('two_factor:login')
        response = self.client.post(url, {
            'login_view-current_step': 'auth',
            'auth-username': self.user.username,
            'auth-password': self.password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

        response = self.client.post(url, {
            'login_view-current_step': 'token',
            'token-otp_token': '000000' if totp(device.bin_key) != 0 else '111111',
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        device.refresh_from_db()
        device.throttle_reset()  # a failed attempt throttles the device

        response = self.client.post(url, {
            'login_view-current_step': 'token',
            'token-otp_token': f'{totp(device.bin_key):06d}',
        })
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)

    def test_password_reset_is_reachable(self):
        self.assertEqual(self.client.get(reverse('password_reset')).status_code, 200)
