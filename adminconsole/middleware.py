from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.urls import Resolver404, resolve
from django_otp import user_has_device


class RequireOTPMiddleware:
    """
    Enforces two-factor authentication for users who have configured an OTP device.

    2FA is optional: users without an OTP device can access the console with
    password-only login. Users who have set up 2FA must complete OTP verification
    on each login; unverified sessions with a device are logged out.
    """

    ALLOWED_VIEWS = {
        'two_factor:login',
        'two_factor:setup',
        'two_factor:qr',
        'two_factor:setup_complete',
        'logout',
        'password_reset',
        'password_reset_done',
        'password_reset_confirm',
        'password_reset_complete',
        'login',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and user_has_device(user) and not user.is_verified() and not self.is_allowed(request):
            logout(request)
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)

    def is_allowed(self, request):
        try:
            return resolve(request.path_info).view_name in self.ALLOWED_VIEWS
        except Resolver404:
            return True
