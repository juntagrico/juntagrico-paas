# Generated by Django 2.0.1 on 2018-02-05 21:40

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('adminconsole', '0002_auto_20180202_1256'),
    ]

    operations = [
        migrations.CreateModel(
            name='AppEnv',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('juntagrico_admin_email', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_ADMIN_EMAIL')),
                ('juntagrico_host_email', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_HOST_EMAIL')),
                ('juntagrico_database_host', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_DATABASE_HOST')),
                ('juntagrico_database_name', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_DATABASE_NAME')),
                ('juntagrico_database_password', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_DATABASE_PASSWORD')),
                ('juntagrico_database_port', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_DATABASE_PORT')),
                ('juntagrico_database_user', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_DATABASE_USER')),
                ('juntagrico_email_host', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_EMAIL_HOST')),
                ('juntagrico_email_password', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_EMAIL_PASSWORD')),
                ('juntagrico_email_port', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_EMAIL_PORT')),
                ('juntagrico_email_user', models.CharField(blank=True, max_length=100, null=True, verbose_name='JUNTAGRICO_EMAIL_USER')),
                ('google_api_key', models.CharField(blank=True, max_length=100, null=True, verbose_name='GOOGLE_API_KEY')),
            ],
        ),
        migrations.AlterField(
            model_name='app',
            name='git_clone_url',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='github'),
        ),
        migrations.AddField(
            model_name='appenv',
            name='app',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='env', to='adminconsole.App'),
        ),
    ]
