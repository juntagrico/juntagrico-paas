# Generated by Django 3.2 on 2021-04-30 06:32

import adminconsole.util
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adminconsole', '0007_remove_appenv_google_api_key'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='appenv',
            name='juntagrico_host_email',
        ),
        migrations.AddField(
            model_name='appenv',
            name='juntagrico_secret_key',
            field=models.CharField(default=adminconsole.util.generate_secret_key, help_text='Geheimer Schlüssel (nur im Notfall ändern)', max_length=100, null=True, verbose_name='JUNTAGRICO_SECRET_KEY'),
        ),
        migrations.AlterField(
            model_name='app',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='appenv',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='appenv',
            name='juntagrico_admin_email',
            field=models.EmailField(blank=True, help_text='Hier werden die Error Report hingeschickt', max_length=100, verbose_name='JUNTAGRICO_ADMIN_EMAIL'),
        ),
        migrations.AlterField(
            model_name='appenv',
            name='juntagrico_email_host',
            field=models.CharField(blank=True, help_text='Postausgansserver Url', max_length=100, verbose_name='JUNTAGRICO_EMAIL_HOST'),
        ),
        migrations.AlterField(
            model_name='appenv',
            name='juntagrico_email_password',
            field=models.CharField(blank=True, help_text='Password des Email Kontos', max_length=100, verbose_name='JUNTAGRICO_EMAIL_PASSWORD'),
        ),
        migrations.AlterField(
            model_name='appenv',
            name='juntagrico_email_port',
            field=models.CharField(blank=True, default='25', help_text='Postausgansserver Port', max_length=100, verbose_name='JUNTAGRICO_EMAIL_PORT'),
        ),
        migrations.AlterField(
            model_name='appenv',
            name='juntagrico_email_user',
            field=models.CharField(blank=True, help_text='Benutzername des Email Kontos', max_length=100, verbose_name='JUNTAGRICO_EMAIL_USER'),
        ),
        migrations.AlterField(
            model_name='githubkey',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]