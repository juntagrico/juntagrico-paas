# Generated by Django 2.0.2 on 2019-06-16 06:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adminconsole', '0005_auto_20181105_1517'),
    ]

    operations = [
        migrations.AddField(
            model_name='appenv',
            name='various',
            field=models.TextField(blank=True, verbose_name='VARIOUS'),
        ),
    ]
