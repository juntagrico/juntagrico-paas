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
    user = models.ForeignKey(User, related_name='app', null=True, blank=True, on_delete=models.CASCADE)
    git_clone_url = models.CharField('github', max_length=100)
    name = models.CharField('name', max_length=100, unique=True, validators=[RegexValidator(regex='^[a-z0-9]+$')])
    port = models.IntegerField('port', unique=True)
    managed = models.BooleanField('Managed', default=True)

    def __str__(self):
        return self.name


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

    




