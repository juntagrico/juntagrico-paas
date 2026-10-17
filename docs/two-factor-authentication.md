# Two-factor authentication (2FA)

Every user of the admin console has to log in with a password **and** a one-time code from an authenticator app (TOTP). There is no way to opt out.

The implementation uses [django-two-factor-auth](https://django-two-factor-auth.readthedocs.io/), which is built on [django-otp](https://django-otp-official.readthedocs.io/).

## For users

### First login

1. Log in with username and password as usual.
2. You are sent to the 2FA setup. Until it is finished, no other page of the console can be opened.
3. Scan the QR code with an authenticator app, e.g. Aegis, 2FAS, Google Authenticator, Microsoft Authenticator, 1Password or Bitwarden.
4. Enter the 6-digit code shown in the app to confirm.

From then on, every login asks for a code after the password.

### Backup codes

Under **Profil → Zwei-Faktor-Authentifizierung verwalten** you can generate backup codes. Each code works once in place of the app code. Store them somewhere safe and separate from your phone, e.g. in a password manager. Generating new codes invalidates the old ones.

### New phone

Move the entry with your authenticator app's transfer or backup function, or: log in on the old phone, disable 2FA on the 2FA management page and set it up again with the new phone. If the old phone is no longer available, use a backup code, or ask an administrator to reset your 2FA (see below).

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

### Rolling out to existing users

- Announce the change before deploying: on the next login, every user has to set up an authenticator app.
- Until a user has set up a device, the password alone still logs them in once and leads straight into the setup. Anyone who knows that password could enroll their own device. Ask users to set up 2FA soon after the deployment.
- Sessions that were logged in before the deployment are sent to the setup (no device yet) or logged out (device exists, session not verified).

## For developers

### How it is enforced

`adminconsole.middleware.RequireOTPMiddleware` runs after `django_otp.middleware.OTPMiddleware` and checks every request of a logged-in user:

| State | Result |
|---|---|
| OTP verified | Request goes through |
| No OTP device | Redirect to the setup (`two_factor:setup`) |
| Device exists, session not verified | Logout and redirect to the login |

Anonymous requests are not touched; the existing `@login_required` and `owner_of_*` decorators send them to the login.

Views that must be reachable before 2FA is complete are listed in `RequireOTPMiddleware.ALLOWED_VIEWS` (2FA login and setup, logout, password reset). Add a URL name there only if the page must work for users without a verified session.

Further safeguards:

- `/accounts/login/` (Django's password-only login) redirects to the 2FA login (`adminconsole/urls.py`).
- The Django admin uses `AdminSiteOTPRequired`.

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
