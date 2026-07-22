import subprocess

from django.conf import settings
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from adminconsole.models import Domain


@receiver(pre_delete, sender=Domain)
def on_domain_delete(sender, instance, **kwargs):
    # remove related nginx config file
    subprocess.run(
        [settings.PYTHON_BIN, '-m', 'manage', 'remove_domain', instance.name],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
