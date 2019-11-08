#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import logging
import coloredlogs
import yaml
import hashlib


from tg.bot import Bot
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Notify errors'

    def handle(self, *args, **options):
        logger = logging.getLogger('notify.error')
        coloredlogs.install(logger=logger)

        bot = Bot()

        cache_filepath = os.path.join(os.path.dirname(__file__), 'cache.yaml')
        if os.path.exists(cache_filepath):
            with open(cache_filepath, 'r') as fo:
                cache = yaml.load(fo)
        else:
            cache = {}

        filepath = './legacy/logs/update/index.txt'
        if os.path.exists(filepath):
            with open(filepath) as fo:
                errors = []
                for m in re.finditer('php.* in [^ ]* on line [0-9]+$', fo.read(), re.MULTILINE | re.IGNORECASE):
                    errors.append(m.group(0))
                if errors:
                    errors = '\n'.join(errors)
                    msg = f'https://legacy.clist.by/logs/update/: ```\n{errors}\n```'

                    h = hashlib.md5(msg.encode('utf8')).hexdigest()
                    k = 'update-file-error-hash'
                    if cache.get(k) != h:
                        cache[k] = h
                        bot.admin_message(msg)

        cache = yaml.dump(cache, default_flow_style=False)
        with open(cache_filepath, 'w') as fo:
            fo.write(cache)