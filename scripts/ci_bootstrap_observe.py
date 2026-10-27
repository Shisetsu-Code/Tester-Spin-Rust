#!/usr/bin/env python3
"""Observe fresh public demo bootstraps; never click gameplay controls.

Only sanitized JSON is persisted. This is discovery evidence, not a game test.
Unknown request/frame dialects are recorded as unknown and are not claimed safe
or silently converted into a known protocol. No private browser state is loaded.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from ci_capture_evidence import clean

PROVIDERS = ('elk', 'relax', 'playson', 'playngo', 'games_global')
MAX_PROVIDER = 80 * 1024 * 1024
MAX_BODY = 12 * 1024 * 1024
MAX_RECORDS = 1500
EXTRA_SECRET = re.compile(r'(?i)^(?:user_?id|playerguid|client_?id|auth|username|password|sessionkey|launchToken|loginToken|extsession|exttoken|ticket)$')
DEMO = re.compile(r'^\s*(?:play\s+(?:demo|for\s+fun)|try\s+(?:demo|for\s+free|game)|demo|free\s+play)\s*[!›»→]*\s*$', re.I)
CONSENT = re.compile(r'^\s*(?:accept\s+(?:all\s+)?cookies|allow\s+all\s+cookies|(?:i\s+am|i.m)\s+(?:over\s+18|18\s*(?:\+|or\s+older))|yes,?\s+i\s+am\s+18\s+or\s+older)\s*[.!]*\s*$', re.I)
GAME_ACTIONS = {'spin', 'dospin', 'bet', 'buy', 'buy_feature', 'purchase', 'play', 'gamble', 'dobonus', 'docollectbonus'}
INIT_ACTIONS = {'init', 'connect', 'reconnect', 'login', 'funmoneylogin', 'register', 'authenticate', 'getsettings'}


def sanitized(value):
    """Exporter redaction plus identifiers carried by demo launch/bootstrap APIs."""
    if isinstance(value, dict):
        value = {key: '[REDACTED]' if EXTRA_SECRET.fullmatch(str(key)) and child not in (None, '', False) else sanitized(child)
                 for key, child in value.items()}
    elif isinstance(value, list):
        value = [sanitized(child) for child in value]
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return clean(sanitized(parsed))
        value = re.sub(r'(?i)((?:userid|user_id|playerguid|clientid|client_id|extsession|exttoken|ticket)\s*[=:]\s*["\']?)[^\s&<>"\']+', r'\1[REDACTED]', value)
    return clean(value)


def classify(provider, url, body):
    """Block only exact observed action keys/endpoints, never substring guesses."""
    path = urlsplit(url).path.rstrip('/').lower()
    if provider == 'relax' and path.endswith('/engine1/game/play'):
        return 'GAMEPLAY_BLOCKED', 'relax.engine1.play'
    if provider == 'elk' and path.endswith('/play/purchase'):
        return 'GAMEPLAY_BLOCKED', 'elk.capi.purchase'
    if provider == 'playson' and path.endswith('/bet'):
        return 'GAMEPLAY_BLOCKED', 'playson.bet'
    actions = []
    query = parse_qs(urlsplit(url).query)
    for key in ('action', 'command'):
        actions.extend(query.get(key, []))
    if body:
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError, UnicodeError):
            parsed = None
        if isinstance(parsed, dict):
            for key in ('action', 'command'):
                if isinstance(parsed.get(key), str):
                    actions.append(parsed[key])
            if provider == 'games_global':
                packet = parsed.get('packet')
                if isinstance(packet, dict) and isinstance(packet.get('payload'), str):
                    try:
                        request = ET.fromstring(packet['payload']).find('Request')
                        if request is not None and request.get('verbex') == 'Spin':
                            return 'GAMEPLAY_BLOCKED', 'games_global.AdvSlot.Spin'
                        if request is not None and request.get('verbex') == 'Refresh':
                            return 'BOOTSTRAP_ACTION', 'games_global.AdvSlot.Refresh'
                    except ET.ParseError:
                        pass
        elif isinstance(body, str) and body.lstrip().startswith('<'):
            try:
                node = ET.fromstring(body)
                actions.extend(node.attrib[key] for key in ('action', 'command') if key in node.attrib)
            except ET.ParseError:
                pass
        elif isinstance(body, str):
            form = parse_qs(body)
            for key in ('action', 'command'):
                actions.extend(form.get(key, []))
    for action in actions:
        if str(action).lower() in GAME_ACTIONS:
            return 'GAMEPLAY_BLOCKED', str(action)
    if actions and all(str(action).lower() in INIT_ACTIONS for action in actions):
        return 'BOOTSTRAP_ACTION', ','.join(actions)
    return 'UNKNOWN', ''


class Evidence:
    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.size = 0
        self.records = []
        self.skipped = 0

    def save(self, relative, value):
        encoded = json.dumps(sanitized(value), ensure_ascii=False).encode('utf-8')
        if self.size + len(encoded) > MAX_PROVIDER or len(self.records) >= MAX_RECORDS:
            self.skipped += 1
            return False
        target = self.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        self.size += len(encoded)
        self.records.append({'file': str(relative), 'bytes': len(encoded), 'sanitized': True,
                             'export_sha256': hashlib.sha256(encoded).hexdigest()})
        return True


async def first_visible(scope, role, pattern):
    matches = scope.get_by_role(role, name=pattern)
    for index in range(min(await matches.count(), 12)):
        item = matches.nth(index)
        if await item.is_visible() and await item.is_enabled():
            return item
    return None


async def demo_control(page, game):
    for frame in page.frames:
        scopes = [frame]
        if game['provider'] == 'games_global':
            # Products is shared by every title. Never click another card's demo.
            title = re.sub('[™®©]', '', game['name']).strip()
            target = frame.get_by_text(re.compile(re.escape(title), re.I))
            scopes = []
            if await target.count() == 1 and await target.is_visible():
                ancestor = target
                for _ in range(4):
                    ancestor = ancestor.locator('xpath=..')
                    scopes.append(ancestor)
        for scope in scopes:
            if game['provider'] == 'games_global':
                count = sum([await scope.get_by_role(role, name=DEMO).count() for role in ('button', 'link')])
                if count != 1:
                    continue
            for role in ('button', 'link'):
                item = await first_visible(scope, role, DEMO)
                if item is not None:
                    return item
    return None


async def observe_game(browser, game, evidence, seconds, number):
    from playwright.async_api import Error as PlaywrightError
    context = await browser.new_context(service_workers='block')
    context.set_default_timeout(1200)
    prefix = f'{number:02d}-{game["slug"]}'
    started = time.monotonic()
    tasks = set()
    counters = {'http': 0, 'blocked_gameplay': 0, 'unknown_mutations': 0, 'unknown_websocket_messages': 0}
    events = []

    def spawn(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.add(task)
        def finished(done):
            tasks.discard(done)
            if not done.cancelled() and done.exception() is not None and len(events) < 200:
                events.append({'kind': 'capture_task_error', 'error': type(done.exception()).__name__})
        task.add_done_callback(finished)

    async def route_http(route):
        request = route.request
        try:
            body = request.post_data
        except (PlaywrightError, UnicodeError):
            body = None
        state, reason = classify(game['provider'], request.url, body)
        if state == 'GAMEPLAY_BLOCKED':
            counters['blocked_gameplay'] += 1
            evidence.save(f'{prefix}/blocked-{counters["blocked_gameplay"]:04d}.json',
                          {'url': request.url, 'method': request.method, 'classification': state, 'reason': reason})
            await route.abort('blockedbyclient')
            return
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and state == 'UNKNOWN':
            counters['unknown_mutations'] += 1
        await route.continue_()

    async def capture_response(response):
        request = response.request
        content_type = response.headers.get('content-type', '')
        if not any(value in content_type.lower() for value in ('json', 'html', 'javascript', 'text/xml', 'application/xml', 'text/plain')):
            return
        counters['http'] += 1
        index = counters['http']
        item = {'url': response.url, 'status': response.status, 'content_type': content_type,
                'method': request.method, 'resource_type': request.resource_type}
        try:
            body = request.post_data
            item['classification'], item['action'] = classify(game['provider'], request.url, body)
            if body:
                item['request_body'] = body
            length = response.headers.get('content-length', '')
            if length.isdigit() and int(length) > MAX_BODY:
                item['body_omitted'] = 'size_bound'
            elif evidence.size < MAX_PROVIDER:
                raw = await asyncio.wait_for(response.body(), timeout=5)
                item['source_sha256'] = hashlib.sha256(raw).hexdigest()
                item['source_bytes'] = len(raw)
                if len(raw) <= MAX_BODY:
                    item['response_body'] = raw.decode('utf-8', errors='replace')
                else:
                    item['body_omitted'] = 'size_bound'
        except (PlaywrightError, asyncio.TimeoutError) as exc:
            item['capture_error'] = type(exc).__name__
        evidence.save(f'{prefix}/http-{index:04d}.json', item)

    def route_socket(ws):
        server = ws.connect_to_server()

        def outgoing(message):
            text = message if isinstance(message, str) else None
            state, action = classify(game['provider'], ws.url, text)
            if state == 'GAMEPLAY_BLOCKED':
                counters['blocked_gameplay'] += 1
                if len(events) < 200:
                    events.append({'kind': 'websocket_gameplay_blocked', 'url': ws.url, 'action': action})
                return
            if state == 'UNKNOWN':
                counters['unknown_websocket_messages'] += 1
            if len(events) < 200:
                events.append({'kind': 'websocket_sent', 'url': ws.url, 'classification': state,
                               'text': text[:4096] if text is not None else '[BINARY DIALECT UNKNOWN]',
                               'text_truncated': text is not None and len(text) > 4096,
                               'bytes': len(message)})
            server.send(message)

        ws.on_message(outgoing)
        # Incoming frames continue to the page unchanged; bodies of opaque
        # binary messages are not written to disk.

    await context.route('**/*', route_http)
    await context.route_web_socket('**/*', route_socket)
    on_response = lambda response: spawn(capture_response(response))
    context.on('response', on_response)
    page = await context.new_page()
    summary = {'game': game, 'scope': 'bootstrap_observation_only', 'game_success_assessed': False,
               'controls': [], 'errors': [], 'unknowns_are_not_certified_safe': True}
    try:
        await page.goto(game['url'], wait_until='domcontentloaded', timeout=min(20000, int(seconds*1000)))
    except PlaywrightError as exc:
        summary['errors'].append('navigation:' + type(exc).__name__)
    demo_clicked = False
    consent_labels = set()
    while time.monotonic() - started < seconds:
        for current in list(context.pages):
            if current.is_closed():
                continue
            try:
                for frame in current.frames:
                    control = await first_visible(frame, 'button', CONSENT)
                    if control is not None:
                        label = (await control.inner_text()).strip()
                        if label not in consent_labels:
                            await control.click(timeout=1500, no_wait_after=True)
                            consent_labels.add(label)
                            summary['controls'].append({'kind': 'consent_or_age', 'label': label})
                if not demo_clicked:
                    control = await demo_control(current, game)
                    if control is not None:
                        label = (await control.inner_text()).strip()
                        await control.click(timeout=1500, no_wait_after=True)
                        demo_clicked = True
                        summary['controls'].append({'kind': 'explicit_demo', 'label': label})
            except PlaywrightError as exc:
                if len(summary['errors']) < 20:
                    summary['errors'].append('control:' + type(exc).__name__)
        await asyncio.sleep(.5)
    context.remove_listener('response', on_response)
    await context.set_offline(True)  # End external observation at the time bound.
    summary['frames'] = []
    for page_number, current in enumerate(context.pages):
        if current.is_closed():
            continue
        for frame_number, frame in enumerate(current.frames):
            summary['frames'].append({'page': page_number, 'frame': frame_number, 'url': frame.url})
            try:
                html = await asyncio.wait_for(frame.content(), timeout=2)
                evidence.save(f'{prefix}/page-{page_number}-frame-{frame_number}.json', {'url': frame.url, 'html': html})
            except (PlaywrightError, asyncio.TimeoutError):
                pass
    if tasks:
        _, pending = await asyncio.wait(list(tasks), timeout=5)
        for task in pending:
            task.cancel()
    await context.close()
    summary.update(counters)
    summary['elapsed_s'] = round(time.monotonic() - started, 2)
    summary['socket_events'] = events
    evidence.save(f'{prefix}/summary.json', summary)
    return sanitized(summary)


async def run(args):
    from playwright.async_api import async_playwright
    report = json.loads((ROOT/'reports/2026-10-27-actions/games.json').read_text())
    games = [game for game in report['games'] if game['provider'] == args.provider][:3]
    if len(games) != 3:
        raise ValueError('Expected exactly three previously selected public games')
    evidence = Evidence(args.output)
    summaries = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for number, game in enumerate(games):
                # Use only selection identity, not historic result/error payloads.
                identity = {key: game[key] for key in ('provider', 'slug', 'name', 'url')}
                try:
                    summaries.append(await observe_game(browser, identity, evidence, args.seconds, number))
                except Exception as exc:
                    summaries.append({'game': identity, 'error': type(exc).__name__, 'game_success_assessed': False})
                finally:
                    for context in list(browser.contexts):
                        await context.close()
        finally:
            await browser.close()
    index = dict(schema='tester-spin/bootstrap-observation/v1', provider=args.provider,
                 scope='Fresh public entry/demo initialization only; no gameplay controls clicked',
                 maximum_bytes=MAX_PROVIDER, exported_bytes=evidence.size, skipped=evidence.skipped,
                 games=summaries, files=evidence.records)
    # Index has metadata only and is also sanitized; reserve within 80 MiB budget.
    encoded = json.dumps(sanitized(index), ensure_ascii=False, indent=2).encode()
    while evidence.size + len(encoded) > MAX_PROVIDER and index['files']:
        record = index['files'].pop()
        target = evidence.output / record['file']
        if target.exists():
            evidence.size -= target.stat().st_size
            target.unlink()
        index['skipped'] += 1
        index['exported_bytes'] = evidence.size
        encoded = json.dumps(sanitized(index), ensure_ascii=False, indent=2).encode()
    (evidence.output/'index.json').write_bytes(encoded)
    print(json.dumps({'provider': args.provider, 'games_observed': len(summaries), 'game_success_assessed': False,
                      'exported_bytes': evidence.size + len(encoded)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=PROVIDERS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=45)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 45:
        parser.error('--seconds must be between 1 and 45')
    asyncio.run(run(args))
