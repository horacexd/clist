#!/usr/bin/env python
# -*- coding: utf-8 -*-

from copy import deepcopy
from datetime import timedelta
from logging import getLogger
from smtplib import SMTPResponseException
from traceback import format_exc

import tqdm
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Prefetch, Q
from django.template.loader import render_to_string
from django.utils.timezone import now
from django_print_sql import print_sql_decorator
from telegram.error import Unauthorized
from webpush import send_user_notification
from webpush.utils import WebPushException

from clist.models import Contest
from notification.models import Task
from tg.bot import Bot
from tg.models import Chat

logger = getLogger('notification.sendout.tasks')


class Command(BaseCommand):
    help = 'Send out all unsent tasks'
    TELEGRAM_BOT = Bot()

    def add_arguments(self, parser):
        parser.add_argument('--coders', nargs='+')
        parser.add_argument('--dryrun', action='store_true', default=False)

    def get_message(self, method, data, **kwargs):
        subject_ = kwargs.pop('subject', None)
        message_ = kwargs.pop('message', None)

        if 'contests' in data:
            contests = Contest.objects.filter(pk__in=data['contests'])
            context = deepcopy(data.get('context', {}))
            context.update({
                'contests': contests,
                'domain': settings.HTTPS_HOST_,
            })
            context.update(kwargs)
            subject = render_to_string('subject', context).strip()
            context['subject'] = subject
            method = method.split(':', 1)[0]
            message = render_to_string('message/%s' % method, context).strip()
        else:
            subject = ''
            message = ''
            context = {}

        if subject_:
            subject = subject_ + subject

        if message_:
            message = message_ + message

        return subject, message, context

    def send_message(self, coder, method, data, **kwargs):
        method, *args = method.split(':', 1)
        subject, message, context = self.get_message(method=method, data=data, coder=coder,  **kwargs)
        if method == settings.NOTIFICATION_CONF.TELEGRAM:
            if args:
                self.TELEGRAM_BOT.send_message(message, args[0], reply_markup=False)
            elif coder.chat and coder.chat.chat_id:
                try:
                    if not coder.settings.get('telegram', {}).get('unauthorized', False):
                        self.TELEGRAM_BOT.send_message(message, coder.chat.chat_id, reply_markup=False)
                except Unauthorized as e:
                    if 'bot was blocked by the user' in str(e):
                        coder.chat.delete()
                    else:
                        coder.settings.setdefault('telegram', {})['unauthorized'] = True
                        coder.save()
            elif 'notification' in kwargs:
                kwargs['notification'].delete()
        elif method == settings.NOTIFICATION_CONF.EMAIL:
            send_mail(
                subject,
                message,
                'CLIST <noreply@clist.by>',
                [coder.user.email],
                fail_silently=False,
                html_message=message,
            )
        elif method == settings.NOTIFICATION_CONF.WEBBROWSER:
            payload = {
                'head': subject,
                'body': message,
            }
            contests = list(context.get('contests', []))
            if len(contests) == 1:
                contest = contests[0]
                payload['url'] = contest.url
                payload['icon'] = f'{settings.HTTPS_HOST_}/imagefit/static_resize/64x64/{contest.resource.icon}'

            try:
                send_user_notification(
                    user=coder.user,
                    payload=payload,
                    ttl=300,
                )
            except WebPushException as e:
                if '403 Forbidden' in str(e):
                    if 'notification' in kwargs:
                        delete_info = kwargs['notification'].delete()
                        logger.error(f'{str(e)} = {delete_info}')

    @print_sql_decorator()
    @transaction.atomic
    def handle(self, *args, **options):
        coders = options.get('coders')
        dryrun = options.get('dryrun')

        delete_info = Task.objects.filter(
            Q(is_sent=True, modified__lte=now() - timedelta(days=1)) |
            Q(modified__lte=now() - timedelta(days=7))
        ).delete()
        logger.info(f'Tasks cleared: {delete_info}')

        if dryrun:
            qs = Task.objects.all()
        else:
            qs = Task.unsent.all()
        qs = qs.select_related('notification__coder')
        qs = qs.prefetch_related(
            Prefetch(
                'notification__coder__chat_set',
                queryset=Chat.objects.filter(is_group=False),
                to_attr='cchat',
            )
        )
        if settings.STOP_EMAIL_:
            qs = qs.exclude(notification__method='email')

        if coders:
            qs = qs.filter(notification__coder__username__in=coders)

        if dryrun:
            qs = qs.order_by('-modified')[:1]

        done = 0
        failed = 0
        stop_email = settings.STOP_EMAIL_
        for task in tqdm.tqdm(qs.iterator(), 'sending'):
            if stop_email and task.notification.method == settings.NOTIFICATION_CONF.EMAIL:
                continue

            try:
                task.is_sent = True
                task.save()
                notification = task.notification
                coder = notification.coder
                method = notification.method

                self.send_message(
                    coder,
                    method,
                    task.addition,
                    subject=task.subject,
                    message=task.message,
                    notification=notification,
                )
            except Exception as e:
                logger.error('Exception sendout task:\n%s' % format_exc())
                task.is_sent = False
                task.save()
                if isinstance(e, SMTPResponseException):
                    stop_email = True

            if task.is_sent:
                done += 1
            else:
                failed += 1
        logger.info(f'Done: {done}, failed: {failed}')
