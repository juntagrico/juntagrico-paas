# Migration to replace GitHubKey.key with installation_id and extend git_clone_url.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('adminconsole', '0019_alter_app_python_version_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='githubkey',
            name='key',
        ),
        migrations.AddField(
            model_name='githubkey',
            name='installation_id',
            field=models.CharField(
                default='',
                max_length=50,
                verbose_name='GitHub App installation ID',
            ),
        ),
        migrations.AlterField(
            model_name='app',
            name='git_clone_url',
            field=models.CharField(blank=True, max_length=500, verbose_name='github'),
        ),
    ]
