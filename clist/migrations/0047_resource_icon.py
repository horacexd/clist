# Generated by Django 2.2.13 on 2020-07-19 11:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0046_auto_20200712_2220'),
    ]

    operations = [
        migrations.AddField(
            model_name='resource',
            name='icon',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
