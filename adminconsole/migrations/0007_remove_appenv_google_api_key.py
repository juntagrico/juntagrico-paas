# Generated by Django 3.1.7 on 2021-03-24 20:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('adminconsole', '0006_appenv_various'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='appenv',
            name='google_api_key',
        ),
    ]
