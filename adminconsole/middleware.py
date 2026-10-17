from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django_otp import user_has_device


class RequireOTPMiddleware:
    """
    Requires every authenticated user to complete two-factor authentication.

    Users without an OTP device are sent to the setup wizard. Sessions that are
    authenticated but not OTP verified (e.g. created before 2FA was enforced) are
    logged out, so the user has to log in again with a token.
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
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not user.is_verified() and not self.is_allowed(request):
            if not user_has_device(user):
                return redirect('two_factor:setup')
            logout(request)
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)

    def is_allowed(self, request):
        try:
            return resolve(request.path_info).view_name in self.ALLOWED_VIEWS
        except Resolver404:
            return True
