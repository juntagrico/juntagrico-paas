# Remove the 'various' field from AppEnv after data migration to AppEnvVar

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('adminconsole', '0015_remove_appenv_various_appenvvar'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='appenv',
            name='various',
        ),
    ]
