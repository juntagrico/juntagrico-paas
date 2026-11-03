# Generated migration to separate branch from git_clone_url into its own field.

from django.db import migrations, models


def migrate_branch(apps, schema_editor):
    """Extract branch from git_clone_url and strip it from the URL."""
    App = apps.get_model('adminconsole', 'App')
    for app in App.objects.all():
        url, _, branch = app.git_clone_url.partition('@')
        if branch:
            app.git_branch = branch
            app.git_clone_url = url
        else:
            app.git_branch = 'main'
            app.git_clone_url = url
        app.save(update_fields=['git_clone_url', 'git_branch'])


def reverse_migrate_branch(apps, schema_editor):
    """Recombine git_clone_url and git_branch into the old format."""
    App = apps.get_model('adminconsole', 'App')
    for app in App.objects.all():
        if app.git_branch:
            app.git_clone_url = f'{app.git_clone_url}@{app.git_branch}'
        app.save(update_fields=['git_clone_url'])


class Migration(migrations.Migration):

    dependencies = [
        ('adminconsole', '0017_app_isolated_network'),
    ]

    operations = [
        migrations.AddField(
            model_name='app',
            name='git_branch',
            field=models.CharField(blank=True, default='main', max_length=100, verbose_name='branch'),
        ),
        migrations.RunPython(migrate_branch, reverse_migrate_branch),
    ]
