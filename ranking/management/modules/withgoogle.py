#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import json
import os
import re
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime
from html import unescape
from pprint import pprint
from random import choice

import flag
import tqdm

from clist.templatetags.extras import get_country_name
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://codejam.googleapis.com/scoreboard/{id}/poll?p='
    API_ATTEMPTS_URL_FORMAT_ = 'https://codejam.googleapis.com/attempts/{id}/poll?p='
    ARCHIVE_URL_FORMAT_ = 'https://codingcompetitions.withgoogle.com/hashcode/archive/{year}'
    ARCHIVE_DATA_URL_FORMAT_ = 'https://codingcompetitions.withgoogle.com/data/scoreboards/{year}.json'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def _api_get_standings(self, users=None, statistics=None):

        match = re.search('/([0-9a-f]{16})$', self.url)
        if not match:
            raise ExceptionParseStandings(f'Not found id in url = {self.url}')
        self.id = match.group(1)
        standings_url = self.url

        api_ranking_url_format = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        api_attempts_url_format = self.API_ATTEMPTS_URL_FORMAT_.format(**self.__dict__)

        def encode(value):
            ret = base64.b64encode(value.encode()).decode()
            ret = ret.replace('+', '-')
            ret = ret.replace('/', '_')
            return ret

        def decode(code):
            code = code.replace('-', '+')
            code = code.replace('_', '/')
            code = re.sub(r'[^A-Za-z0-9\+\/]', '', code)
            code += '=' * ((4 - len(code) % 4) % 4)
            code = base64.b64decode(code)
            code = code.decode(errors='ignore')
            data = json.loads(code)
            return data

        def get(offset, num):
            query = f'{{"min_rank":{offset},"num_consecutive_users":{num}}}'
            url = api_ranking_url_format + encode(query)
            content = REQ.get(url)
            return decode(content)

        data = get(1, 1)
        problems_info = [
            {
                'url': os.path.join(self.url, task['id']),
                'code': task['id'],
                'name': task['title'],
                'full_score': sum([test['value'] for test in task['tests']])
            }
            for task in data['challenge']['tasks']
        ]
        problems_info.sort(key=lambda t: (t['full_score'], t['name']))
        problems_info = OrderedDict([(t['code'], t) for t in problems_info])

        are_results_final = data['challenge']['are_results_final']

        num_consecutive_users = 200
        n_page = (data['full_scoreboard_size'] - 1) // num_consecutive_users + 1

        def fetch_page(page):
            return get(page * num_consecutive_users + 1, num_consecutive_users)

        def fetch_attempts(handle):
            query = f'{{"nickname":{json.dumps(handle)},"include_non_final_results":true}}'
            url = api_attempts_url_format + encode(query)
            try:
                content = REQ.get(url)
                data = decode(content)
            except FailOnGetResponse:
                data = None
            return handle, data

        result = {}
        with PoolExecutor(max_workers=8) as executor:
            handles_for_getting_attempts = []
            for data in tqdm.tqdm(executor.map(fetch_page, range(n_page)), total=n_page, desc='paging'):
                for row in data['user_scores']:
                    if not row['task_info']:
                        continue
                    handle = row.pop('displayname')
                    if users and handle not in users:
                        continue

                    r = result.setdefault(handle, {})
                    r['member'] = handle
                    r['place'] = row.pop('rank')
                    r['solving'] = row.pop('score_1')
                    r['penalty'] = self.to_time(-row.pop('score_2') / 10**6)
                    if '/round/' in self.url:
                        query = encode(handle)
                        url = self.url.replace('/round/', '/submissions/').rstrip('/') + f'/{query}'
                        r['url'] = url.rstrip('=')

                    country = row.pop('country', None)
                    if country:
                        r['country'] = country

                    solved = 0
                    problems = r.setdefault('problems', {})
                    for task_info in row['task_info']:
                        tid = task_info['task_id']
                        p = problems.setdefault(tid, {})
                        if task_info['penalty_micros'] > 0:
                            p['time'] = self.to_time(task_info['penalty_micros'] / 10**6)
                        p['result'] = task_info['score']
                        if p['result'] and p['result'] != problems_info[tid]['full_score']:
                            p['partial'] = True
                        if task_info['penalty_attempts']:
                            p['penalty'] = task_info['penalty_attempts']
                        solved += task_info['tests_definitely_solved']
                    r['solved'] = {'solving': solved}

                    if statistics and handle in statistics and statistics[handle].get('_with_subscores'):
                        result[handle] = self.merge_dict(r, statistics.pop(handle))
                    else:
                        handles_for_getting_attempts.append(handle)

            if are_results_final:
                for handle, data in tqdm.tqdm(
                    executor.map(fetch_attempts, handles_for_getting_attempts),
                    total=len(handles_for_getting_attempts),
                    desc='attempting'
                ):
                    if data is None:
                        continue
                    challenge = data['challenge']
                    if not challenge.get('are_results_final'):
                        break
                    tasks = {t['id']: t for t in challenge['tasks']}

                    row = result[handle]
                    problems = row['problems']

                    for attempt in sorted(data['attempts'], key=lambda a: a['timestamp_ms']):
                        task_id = attempt['task_id']
                        problem = problems.setdefault(task_id, {})

                        subscores = []
                        score = 0
                        for res, test in zip(attempt['judgement'].pop('results'), tasks[task_id]['tests']):
                            if not test.get('value'):
                                continue
                            subscore = {'status': test['value']}
                            if 'verdict' in res:
                                subscore['result'] = res['verdict'] == 1
                                subscore['verdict'] = res['verdict__str']
                            else:
                                subscore['verdict'] = res['status__str']
                            subscores.append(subscore)
                            if res.get('verdict') == 1:
                                score += test['value']
                        if score != problem.get('result'):
                            continue

                        problem['subscores'] = subscores
                        problem['solution'] = attempt.pop('src_content').replace('\u0000', '')
                        language = attempt.get('src_language__str')
                        if language:
                            problem['language'] = language
                        if 'time' not in problem:
                            delta_ms = attempt['timestamp_ms'] - challenge['start_ms']
                            problem['time'] = self.to_time(delta_ms / 10**3)
                    row['_with_subscores'] = True

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
        }

        if self.start_time.year >= 2020:
            match = re.search(r'\bcode.*jam\b.*\bround\b.*\b(?P<round>[123])[A-Z]?$', self.name, flags=re.I)
            if match:
                r = match.group('round')
                standings.setdefault('info_fields', []).append('advance')
                standings['advance'] = {
                    "title": {
                        "1": "The top 1500 contestants in this round will advance to Round 2",
                        "2": "The top 1000 contestants in this round will win a T-shirt and advance to Round 3",
                        "3": "The top 25 contestants in this round will advance to the World Finals",
                    }[r],
                    "filter": [
                        {
                            "field": "place",
                            "operator": "le",
                            "threshold": {
                                "1": 1500,
                                "2": 1000,
                                "3": 25,
                            }[r],
                        }
                    ]
                }

        return standings

    def _old_get_standings(self, users=None):
        if not self.standings_url:
            self.standings_url = self.url.replace('/dashboard', '/scoreboard')

        result = {}

        page = REQ.get(self.standings_url)

        matches = re.finditer(r'GCJ.(?P<key>[^\s]*)\s*=\s*"?(?P<value>[^";]*)', page)
        vs = {m.group('key'): m.group('value') for m in matches}
        vs['rowsPerPage'] = int(vs['rowsPerPage'])

        matches = re.finditer(r'GCJ.problems.push\((?P<problem>{[^}]*})', page)
        problems_info = OrderedDict([])
        problems = [json.loads(m.group('problem')) for m in matches]

        matches = re.finditer(r'(?P<new>\(\);)?\s*io.push\((?P<subtask>{[^}]*})', page)
        tid = -1
        for idx, m in enumerate(matches):
            subtask = json.loads(m.group('subtask'))
            if m.group('new'):
                tid += 1
            idx = str(idx)
            task = problems[tid].copy()
            task.update(subtask)
            task['name'] = task.pop('title')
            task['code'] = idx
            task['full_score'] = task.pop('points')
            problems_info[idx] = task

        def fetch_page(page_idx):
            nonlocal vs
            params = {
                'cmd': 'GetScoreboard',
                'contest_id': vs['contestId'],
                'show_type': 'all',
                'start_pos': page_idx * vs['rowsPerPage'] + 1,
                'csrfmiddlewaretoken': vs['csrfMiddlewareToken'],
            }
            url = os.path.join(self.standings_url, 'do') + '?' + urllib.parse.urlencode(params)
            page = REQ.get(url)
            data = json.loads(page)
            return data

        data = fetch_page(0)
        n_page = (data['stat']['nrp'] - 1) // vs['rowsPerPage'] + 1

        def time2str(t):
            h = t // 3600
            if h:
                return f'{h}:{t // 60 % 60:02d}:{t % 60:02d}'
            return f'{t // 60}:{t % 60:02d}'

        result = {}
        with PoolExecutor(max_workers=8) as executor:
            for data in tqdm.tqdm(executor.map(fetch_page, range(n_page)), total=n_page):
                for row in data['rows']:
                    handle = row.pop('n')
                    r = result.setdefault(handle, {})
                    r['member'] = handle
                    r['country'] = row.pop('c')
                    r['penalty'] = time2str(row.pop('pen'))
                    r['solving'] = row.pop('pts')
                    r['place'] = row.pop('r')

                    problems = r.setdefault('problems', {})
                    solved = 0
                    for idx, (attempt, time) in enumerate(zip(row.pop('att'), row.pop('ss'))):
                        if attempt:
                            p = problems.setdefault(str(idx), {})
                            if time == -1:
                                p['result'] = -attempt
                            else:
                                solved += 1
                                p['result'] = '+' if attempt == 1 else f'+{attempt - 1}'
                                p['time'] = time2str(time)
                    r['solved'] = {'solving': solved}

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings

    def _hashcode(self, users=None, statistics=None):
        standings_url = None
        is_final_round = self.name.endswith('Final Round')

        data = None
        try:
            page = REQ.get(self.ARCHIVE_DATA_URL_FORMAT_.format(year=self.start_time.year))
            data = json.loads(page)
            names = set()
            for data_round in data['rounds']:
                name = data_round['name']
                if name in names:
                    name = 'Qualification Round'
                if self.name.endswith(name) or name in ['Full ranking', 'Main round'] and is_final_round:
                    data = data_round['data']
                    standings_url = self.ARCHIVE_URL_FORMAT_.format(year=self.start_time.year)
                    break
                names.add(name)
            else:
                data = None
        except FailOnGetResponse as e:
            if e.code != 404:
                raise e

        if not data:
            if 'hashcode_scoreboard' in self.info:
                page = REQ.get(self.info['hashcode_scoreboard'])
                match = re.search('<table[^>]*class="[^"]*Hashcode[^"]*Judge[^"]*Table[^"]*"[^>]*>.*?</table>', page)
                if match:
                    data = parsed_table.ParsedTable(match.group(0))
                    data = [{k: v.value for k, v in row.items()} for row in data]
                else:
                    data = json.loads(page)
            else:
                raise ExceptionParseStandings('Not found data')

        if isinstance(data, dict) and 'columns' in data:
            columns = data['columns']
            data = data['rows']
        else:
            columns = None

        result = {}
        season = self.get_season()
        for rank, row in enumerate(data, start=1):
            if columns is not None:
                row = dict(zip(columns, row))
            row = {k.lower().replace(' ', ''): v for k, v in row.items()}

            name = row.pop('teamname')
            name = unescape(name)

            countries = None

            if 'country' in row:
                countries = re.sub(r',\s+', ',', row.pop('country')).split(',')
            elif 'countries' in row:
                countries = row.pop('countries')
            else:
                match = re.search(r'^(:[A-Z]+:\s)*', flag.dflagize(name))
                if match:
                    countries = []
                    for c in match.group(0).strip().split():
                        c = c.strip(':')
                        countries.append(get_country_name(c))
                    *_, name = name.split(' ', len(countries))
                    name = name.strip()

            member = f'{name}, {season}'

            if users is not None and name not in users:
                continue

            r = result.setdefault(member, {})
            r['name'] = name
            r['member'] = member

            score = row.pop('score', '0')
            score = re.sub(r'[\s,]', '', str(score))
            try:
                float(score)
            except Exception:
                score = '0'
            r['solving'] = score

            if 'rank' in row:
                r['place'] = row.pop('rank')
            else:
                r['place'] = rank

            if countries:
                r['_countries'] = countries

            if 'finalround' in row:
                r['advanced'] = row['finalround']

            stime = row.get('submissiontime', {}).get('iMillis')
            if stime:
                r['time'] = self.to_time(stime / 1000 - self.start_time.timestamp(), 3)

            if 'hubid' in row:
                r['hub_id'] = row.pop('hubid')

        standings = {
            'result': result,
            'hidden_fields': ['hub_id'],
            'problems': [],
        }

        if standings_url:
            standings['url'] = standings_url

        return standings

    def get_standings(self, users=None, statistics=None):
        if 'hashcode_scoreboard' in self.info or re.search(r'\bhash.*code\b.*\(round|final\)$', self.name, re.I):
            ret = self._hashcode(users, statistics)
        elif '/codingcompetitions.withgoogle.com/' in self.url:
            ret = self._api_get_standings(users, statistics)
        elif '/code.google.com/' in self.url or '/codejam.withgoogle.com/' in self.url:
            ret = self._old_get_standings(users)
        else:
            raise InitModuleException(f'url = {self.url}')
        if re.search(r'\bfinal\S*(?:\s+round)?$', self.name, re.I):
            ret['options'] = {'medals': [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]}
        return ret


if __name__ == "__main__":
    statistics = [
        Statistic(
            name='Kick Start. Round H',
            url='https://codejam.withgoogle.com/codejam/contest/3324486/dashboard',
            key='3324486',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Code Jam. AMER Semifinal',
            url='https://code.google.com/codejam/contest/32008/dashboard',
            key='32008',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Code Jam. Round 1A',
            url='https://code.google.com/codejam/contest/32016/dashboard',
            key='32016',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Round 2 2019',
            url='https://codingcompetitions.withgoogle.com/codejam/round/0000000000051679',
            key='0d4dvct96b7cpf0tml4elq0n9r',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Round B 2019',
            url='https://codingcompetitions.withgoogle.com/kickstart/round/0000000000050eda',
            key='0d4dvct96b7cpf0tml4elq0n9r',
            start_time=datetime.now(),
            standings_url=None,
        ),
    ]
    for statictic in statistics:
        standings = statictic.get_standings()
        result = standings.pop('result', None)
        if result:
            scores = [float(r['solving']) for r in result.values()]
            scores.sort()
            score = scores[len(scores) * 9 // 10]
            result = [r for r in result.values() if float(r['solving']) == score]
            pprint(choice(result))
        pprint(standings)
