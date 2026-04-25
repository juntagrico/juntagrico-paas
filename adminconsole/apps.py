from django.apps import AppConfig


class JuntagricoPaasAppconfig(AppConfig):
    name = "adminconsole"
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from . import signals  # noqa: F401
