# Two-factor authentication (2FA)

Two-factor authentication is **optional**. Users who enable it must log in with a password **and** a one-time code from an authenticator app (TOTP). Users who do not set up 2FA can log in with their password alone.

The implementation uses [django-two-factor-auth](https://django-two-factor-auth.readthedocs.io/), which is built on [django-otp](https://django-otp-official.readthedocs.io/).

## For users

### Enabling 2FA

Go to **Profil → Zwei-Faktor-Authentifizierung verwalten** and follow the setup wizard:

1. Scan the QR code with an authenticator app, e.g. Aegis, 2FAS, Google Authenticator, Microsoft Authenticator, 1Password or Bitwarden.
2. Enter the 6-digit code shown in the app to confirm.

From then on, every login asks for a code after the password.

### Disabling 2FA

On the 2FA management page (**Profil → Zwei-Faktor-Authentifizierung verwalten**) you can deactivate 2FA. After that you will log in with your password only.

### Backup codes

Under **Profil → Zwei-Faktor-Authentifizierung verwalten** you can generate backup codes. Each code works once in place of the app code. Store them somewhere safe and separate from your phone, e.g. in a password manager. Generating new codes invalidates the old ones.

### New phone

Move the entry with your authenticator app's transfer or backup function, or: log in, disable 2FA on the 2FA management page and set it up again with the new phone. If the old phone is no longer available, use a backup code, or ask an administrator to reset your 2FA (see below).

## For administrators

### Reset a user's 2FA (lost device, no backup codes)

Verify the user's identity through a separate channel before resetting.

In the Django admin (`/admin/`), delete the user's entries under **TOTP devices** and **Static devices** (the backup codes).

Or in the Django shell on the server:

```python
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

TOTPDevice.objects.filter(user__username='<username>').delete()
StaticDevice.objects.filter(user__username='<username>').delete()
```

On the next login the user is sent through the setup again.

### Locked out superuser

If no superuser can log in anymore, use the Django shell on the server (`python manage.py shell`) and reset the superuser's devices as above.

### Encouraging users to enable 2FA

- Recommend 2FA to all users for improved security.
- Users who enable 2FA are required to verify on each subsequent login.

## For developers

### How it is enforced

`adminconsole.middleware.RequireOTPMiddleware` runs after `django_otp.middleware.OTPMiddleware` and checks every request of a logged-in user:

| State | Result |
|---|---|
| OTP verified | Request goes through |
| No OTP device | Request goes through (2FA is optional) |
| Device exists, session not verified | Logout and redirect to the login |

Anonymous requests are not touched; the existing `@login_required` and `owner_of_*` decorators send them to the login.

Views that must be reachable before 2FA is complete are listed in `RequireOTPMiddleware.ALLOWED_VIEWS` (2FA login and setup, logout, password reset). Add a URL name there only if the page must work for users without a verified session.

The login always routes through `two_factor:login` (`LOGIN_URL`). This view handles both cases: users without a device skip straight to the password step, while users with a device complete the password and OTP steps.

### Templates

The pages of the package are styled through overrides in `adminconsole/templates/two_factor/`:

- `_base.html` renders the 2FA pages inside the console layout (`base.html`).
- `_base_focus.html` renders login and setup without the menu.
- `core/login.html` extends the package's login and adds the "Passwort vergessen" link.

`adminconsole` must come **before** the 2FA apps in `INSTALLED_APPS`, otherwise Django picks the package's templates instead of these overrides.

### Running locally

```bash
python dev_manage.py migrate
python dev_manage.py createsuperuser
python dev_manage.py runserver localhost:8000
python dev_manage.py test adminconsole
```

Open the console at `http://localhost:8000`, not `127.0.0.1` (`ALLOWED_HOSTS` in `dev_settings.py`). `dev_settings.py` uses English (`en-us`); production uses German (`de-ch`).
