import datetime
from pathlib import Path

import docker
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator

from adminconsole.util import generate_secret_key


class GitHubKey(models.Model):
    user = models.OneToOneField(User, related_name='githubkey', null=True, blank=True, on_delete=models.CASCADE)
    key = models.CharField(max_length=500)

    def __str__(self):
        return str(self.user)


class App(models.Model):
    PYTHON_VERSION = [
        ("3.9", "3.9 (Nur mit Juntagrico < 2.0)"),
        ("3.10", "3.10"),
        ("3.11", "3.11"),
        ("3.12", "3.12"),
        ("3.13", "3.13 (Nur mit Juntagrico >= 2.0)"),
    ]

    user = models.ForeignKey(User, related_name='app', null=True, blank=True, on_delete=models.CASCADE)
    git_clone_url = models.CharField('github', max_length=100, blank=True)
    name = models.CharField('name', max_length=100, unique=True, validators=[RegexValidator(regex='^[a-z0-9-]+$')])
    port = models.IntegerField('port', unique=True)
    wsgi = models.CharField('wsgi', max_length=100, blank=True)
    python_version = models.CharField('python', max_length=100, blank=True, choices=PYTHON_VERSION)
    managed = models.BooleanField('Managed', default=True)
    version = models.PositiveIntegerField('version', default=1)
    staging_of = models.ForeignKey('App', null=True, blank=True, on_delete=models.CASCADE, related_name='stagings')

    def __str__(self):
        return self.name

    @property
    def dir(self):
        return Path('/var/django/projects') / self.name

    @property
    def log_file(self):
        return str(self.dir) + '.txt'

    @property
    def wsgi_path(self):
        return self.wsgi or self.name.partition('-')[0] + '.wsgi'

    @property
    def container(self):
        return docker.from_env().containers.get(self.name)

    def run_until(self):
        if self.staging_of:
            file = self.dir / 'Dockerfile'
            modified_time = datetime.datetime.fromtimestamp(file.stat().st_mtime, tz=datetime.timezone.utc)
            return modified_time + datetime.timedelta(1)
        return None


class AppEnv(models.Model):
    app = models.OneToOneField(App, related_name='env', on_delete=models.CASCADE)
    juntagrico_admin_email = models.EmailField('JUNTAGRICO_ADMIN_EMAIL', max_length=100, blank=True, help_text='Hier werden die Error Report hingeschickt')
    juntagrico_database_host = models.CharField('JUNTAGRICO_DATABASE_HOST', max_length=100, blank=True)
    juntagrico_database_name = models.CharField('JUNTAGRICO_DATABASE_NAME', max_length=100, blank=True)
    juntagrico_database_password = models.CharField('JUNTAGRICO_DATABASE_PASSWORD', max_length=100, blank=True)
    juntagrico_database_port = models.CharField('JUNTAGRICO_DATABASE_PORT', max_length=100, blank=True)
    juntagrico_database_user = models.CharField('JUNTAGRICO_DATABASE_USER', max_length=100, blank=True)
    juntagrico_email_host = models.CharField('JUNTAGRICO_EMAIL_HOST', max_length=100, blank=True, help_text='Postausgansserver Url')
    juntagrico_email_password = models.CharField('JUNTAGRICO_EMAIL_PASSWORD', max_length=100, blank=True, help_text='Password des Email Kontos')
    juntagrico_email_port = models.CharField('JUNTAGRICO_EMAIL_PORT', max_length=100, default='25', blank=True, help_text='Postausgansserver Port')
    juntagrico_email_user = models.CharField('JUNTAGRICO_EMAIL_USER', max_length=100, blank=True, help_text='Benutzername des Email Kontos')
    juntagrico_email_tls = models.BooleanField('JUNTAGRICO_EMAIL_TLS', default=False)
    juntagrico_email_ssl = models.BooleanField('JUNTAGRICO_EMAIL_SSL', default=False)
    juntagrico_secret_key = models.CharField('JUNTAGRICO_SECRET_KEY', null=True, max_length=100, help_text='Geheimer Schlüssel (nur im Notfall ändern)', default=generate_secret_key)
    various = models.TextField('VARIOUS', blank=True)

    def __str__(self):
        return self.app.name

    def get_lines(self):
        yield 'JUNTAGRICO_DEBUG=False'
        yield 'JUNTAGRICO_DATABASE_ENGINE=django.db.backends.postgresql'
        if self.app.staging_of:
            yield 'JUNTAGRICO_STAGING=1'
        for field in self._meta.get_fields():
            if field.name.startswith('juntagrico'):
                yield f'{field.verbose_name}={getattr(self, field.name)}'
        for line in self.various.splitlines():
            if clean_line := line.strip():
                yield clean_line
