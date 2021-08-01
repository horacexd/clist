# Generated by Django 3.1.12 on 2021-07-03 11:28

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0058_auto_20210308_1449'),
        ('true_coders', '0038_auto_20210703_0011'),
    ]

    operations = [
        migrations.CreateModel(
            name='ListValue',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('group_id', models.PositiveIntegerField()),
                ('account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='ranking.account')),
                ('coder', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='true_coders.coder')),
                ('coder_list', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='values', to='true_coders.list')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]