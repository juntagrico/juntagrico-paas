# Migration to add creation_pending and installation_pending flags to App model.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('adminconsole', '0020_githubkey_installation_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='app',
            name='creation_pending',
            field=models.BooleanField('creation pending', default=False),
        ),
        migrations.AddField(
            model_name='app',
            name='installation_pending',
            field=models.BooleanField('installation pending', default=False),
        ),
    ]
