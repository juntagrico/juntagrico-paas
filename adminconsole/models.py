import datetime
from pathlib import Path
from functools import cached_property

import docker
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator, validate_domain_name
from django.urls import reverse
from django.utils import timezone
from docker.errors import NotFound
from docker.types import Mount

from adminconsole.util import generate_secret_key


def get_cronjob_definition(cronjob_id):
    """Look up a cronjob definition from settings.CRONJOBS by id."""
    for cj in settings.CRONJOBS:
        if cj['id'] == cronjob_id:
            return cj
    return None


def get_available_cronjobs(app_name=None):
    """Return cronjob definitions filtered by app availability.
    If app_name is provided, only return cronjobs where apps is not set or app_name is in the list.
    """
    results = []
    for cj in settings.CRONJOBS:
        apps = cj.get('apps')
        if apps is None or app_name in apps:
            results.append(cj)
    return results


def get_python_version_choices():
    """Return Python version choices with an automatic (default) option prepended."""
    fixed = [
        ('3.10', '3.10'),
        ('3.11', '3.11'),
        ('3.12', '3.12 (Nur mit Juntagrico >= 2.0)'),
        ('3.13', '3.13 (Nur mit Juntagrico >= 2.0)'),
        ('3.14', '3.14 (Nur mit Juntagrico >= 2.0)'),
    ]
    default_label = f'Automatisch ({settings.DEFAULT_PYTHON_VERSION})'
    return [('', default_label)] + fixed


class GitHubKey(models.Model):
    user = models.OneToOneField(
        User, related_name='githubkey', null=True, blank=True, on_delete=models.CASCADE
    )
    installation_id = models.CharField('GitHub App installation ID', max_length=50)

    def __str__(self):
        return str(self.user)


class App(models.Model):
    STATIC_DIR = 'static'
    MEDIA_DIR = 'media'
    # paths inside container
    INTERNAL_ROOT = '/code/internal_files/'
    STATIC_ROOT = '/code/static/'
    MEDIA_ROOT = '/code/media/'

    user = models.ForeignKey(
        User, related_name='app', null=True, blank=True, on_delete=models.CASCADE
    )
    git_clone_url = models.CharField('github', max_length=500, blank=True)
    git_branch = models.CharField('branch', max_length=100, blank=True, default='main')
    name = models.CharField(
        'name',
        max_length=100,
        unique=True,
        validators=[RegexValidator(regex='^[a-z0-9-]+$')],
    )
    port = models.IntegerField('port', unique=True)
    wsgi = models.CharField('wsgi', max_length=100, blank=True)
    python_version = models.CharField(
        'python', max_length=100, blank=True, choices=get_python_version_choices
    )
    juntagrico_version = models.CharField('juntagrico', max_length=50, blank=True)
    managed = models.BooleanField('Managed', default=True)
    version = models.PositiveIntegerField('version', default=2)
    staging_of = models.ForeignKey(
        'App', null=True, blank=True, on_delete=models.CASCADE, related_name='stagings'
    )
    run_until = models.DateTimeField('run until', null=True, blank=True, default=None)
    isolated_network = models.BooleanField(
        'network isolation',
        default=False,
        help_text='Run the app in its own Docker network instead of the host network. '
        'Takes effect at the next restart (manage.py restart), see README "App network isolation".',
    )
    creation_pending = models.BooleanField('creation pending', default=False)
    installation_pending = models.BooleanField('installation pending', default=False)

    def __str__(self):
        return self.name

    @property
    def dir(self):
        return Path(settings.PROJECTS_DIR) / self.name

    @property
    def work_dir(self):
        return Path(settings.WORK_DIR) / self.name

    @property
    def uid(self):
        # user id for app user
        return str(10000 + self.port)

    @property
    def code_dir(self):
        return self.work_dir / 'code'

    @property
    def static_dir(self):
        return self.dir / 'static'

    def get_mount(self, path, target, read_only=False):
        common = dict(target=target, read_only=read_only)
        if settings.APP_VOLUME is not None:
            # mount static files from volume
            return Mount(
                source=settings.APP_VOLUME,
                type='volume',
                subpath=self.name + '/' + path,
                **common,
            )
        return Mount(source=str(self.dir / path), type='bind', **common)

    def static_files_mount(self, read_only=True):
        return self.get_mount(self.STATIC_DIR, self.STATIC_ROOT, read_only=read_only)

    def media_mount(self):
        return self.get_mount(self.MEDIA_DIR, self.MEDIA_ROOT)

    def internal_mount(self):
        # internal is always a volume
        return Mount(
            target=self.INTERNAL_ROOT,
            source=f'{self.name}-internal',
            read_only=False,
        )

    @property
    def log_file(self):
        return str(self.dir) + '.txt'

    @property
    def wsgi_path(self):
        return self.wsgi or self.name.partition('-')[0] + '.wsgi'

    @property
    def image_tag(self):
        return f'{self.name}:{self.version}'

    @property
    def container(self):
        return docker.from_env().containers.get(self.name)

    @cached_property
    def running(self):
        """Return True if the Docker container is running, False otherwise."""
        try:
            return docker.from_env().containers.get(self.name).status in (
                'running',
                'created',
                'restarting',
            )
        except NotFound:
            return False

    def set_branch(self, branch_name):
        self.git_branch = branch_name
        self.save()

    def renew(self):
        self.run_until = timezone.now() + datetime.timedelta(days=1)
        self.save()

    def get_absolute_url(self):
        return reverse('overview', args=[self.id])

    def get_installation_token(self) -> str | None:
        """Get a GitHub App installation access token for this app's owner.

        Looks up the app owner's GitHubKey to find the installation_id, then
        generates an installation access token. Returns None if no installation
        is configured for this app's owner.
        """
        try:
            github_key = GitHubKey.objects.get(user=self.user)
            installation_id = int(github_key.installation_id)
        except (GitHubKey.DoesNotExist, ValueError, TypeError):
            return None

        from adminconsole.util.git import get_installation_access_token

        return get_installation_access_token(installation_id)


class AppEnv(models.Model):
    app = models.OneToOneField(App, related_name='env', on_delete=models.CASCADE)
    juntagrico_admin_email = models.EmailField(
        'JUNTAGRICO_ADMIN_EMAIL',
        max_length=100,
        blank=True,
        help_text='Hier werden die Error Report hingeschickt',
    )
    juntagrico_database_host = models.CharField(
        'JUNTAGRICO_DATABASE_HOST', max_length=100, blank=True
    )
    juntagrico_database_name = models.CharField(
        'JUNTAGRICO_DATABASE_NAME', max_length=100, blank=True
    )
    juntagrico_database_password = models.CharField(
        'JUNTAGRICO_DATABASE_PASSWORD', max_length=100, blank=True
    )
    juntagrico_database_port = models.CharField(
        'JUNTAGRICO_DATABASE_PORT', max_length=100, blank=True
    )
    juntagrico_database_user = models.CharField(
        'JUNTAGRICO_DATABASE_USER', max_length=100, blank=True
    )
    juntagrico_email_host = models.CharField(
        'JUNTAGRICO_EMAIL_HOST',
        max_length=100,
        blank=True,
        help_text='Postausgansserver Url',
    )
    juntagrico_email_password = models.CharField(
        'JUNTAGRICO_EMAIL_PASSWORD',
        max_length=100,
        blank=True,
        help_text='Password des Email Kontos',
    )
    juntagrico_email_port = models.CharField(
        'JUNTAGRICO_EMAIL_PORT',
        max_length=100,
        default='25',
        blank=True,
        help_text='Postausgansserver Port',
    )
    juntagrico_email_user = models.CharField(
        'JUNTAGRICO_EMAIL_USER',
        max_length=100,
        blank=True,
        help_text='Benutzername des Email Kontos',
    )
    juntagrico_email_tls = models.BooleanField('JUNTAGRICO_EMAIL_TLS', default=False)
    juntagrico_email_ssl = models.BooleanField('JUNTAGRICO_EMAIL_SSL', default=False)
    juntagrico_secret_key = models.CharField(
        'JUNTAGRICO_SECRET_KEY',
        blank=True,
        max_length=100,
        help_text='Geheimer Schlüssel (nur im Notfall ändern)',
        default=generate_secret_key,
    )

    def __str__(self):
        return self.app.name

    def get_lines(self):
        yield 'JUNTAGRICO_DEBUG=False'
        yield 'JUNTAGRICO_DATABASE_ENGINE=django.db.backends.postgresql'
        yield 'JUNTAGRICO_STATIC_ROOT=' + self.app.STATIC_ROOT
        yield 'JUNTAGRICO_MEDIA_ROOT=' + self.app.MEDIA_ROOT
        yield 'JUNTAGRICO_DOMAINS=' + ','.join(
            self.app.domains.values_list('name', flat=True)
        )
        if self.app.staging_of:
            yield 'JUNTAGRICO_STAGING=1'
        for field in self._meta.get_fields():
            if field.name.startswith('juntagrico'):
                yield f'{field.verbose_name}={getattr(self, field.name)}'
        for var in self.env_vars.all():
            yield f'{var.key}={var.value}'


class AppEnvVar(models.Model):
    """Individual key-value environment variable entry for an AppEnv."""

    env = models.ForeignKey(AppEnv, related_name='env_vars', on_delete=models.CASCADE)
    key = models.CharField(max_length=200)
    value = models.TextField(blank=True, default='')
    secret = models.BooleanField(default=False)

    class Meta:
        unique_together = ('env', 'key')
        ordering = ['key']

    def __str__(self):
        if self.secret and self.value:
            return f'{self.key}=****'
        return f'{self.key}={self.value}'


class AppCronjob(models.Model):
    app = models.ForeignKey(App, related_name='cronjobs', on_delete=models.CASCADE)
    cronjob_id = models.CharField(max_length=100)
    minute = models.PositiveIntegerField(
        null=True, blank=True, help_text='Minute (0-59)'
    )
    hour = models.PositiveIntegerField(null=True, blank=True, help_text='Hour (0-23)')

    class Meta:
        unique_together = ('app', 'cronjob_id')

    def __str__(self):
        return f'{self.app.name}: {self.cronjob_id}'


class Domain(models.Model):
    app = models.ForeignKey(App, related_name='domains', on_delete=models.CASCADE)
    name = models.CharField(
        'name', max_length=100, unique=True, validators=[validate_domain_name]
    )

    def clean(self):
        # nginx and certbot treat domain names case-insensitively and ignore a trailing dot
        self.name = self.name.lower().rstrip('.')
        for platform_domain in settings.ALLOWED_HOSTS:
            platform_domain = '.'.join(platform_domain.rsplit('.', 2)[-2:])
            if self.name == platform_domain or self.name.endswith(
                '.' + platform_domain
            ):
                # platform subdomains are reserved: an app may only use its own
                if not self.app_id or self.name != f'{self.app.name}.{platform_domain}':
                    raise ValidationError({'name': 'ungültige Domain'})
