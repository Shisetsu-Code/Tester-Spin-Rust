"""Fresh NGM offline demo client, with observed math and no HAR replay."""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from .ngm_execution import NGMRoundLedger
from .ngm_observation import observation_points, spin_request_contract, spin_action_binding, event_action_binding, continuation_probes
from .ngm_contracts import request_catalog, functional_manifest, passive_request_roles


class NGMDemoSession:
    transport_kind = 'local-client-engine'

    def __init__(self, code, directory, timeout_s, stop_event):
        if not re.fullmatch(r'[A-Za-z0-9_]+', code):
            raise ValueError('NGM_SYMBOL_INVALID')
        self.code = code
        self.directory = Path(directory)
        self.timeout = max(10, float(timeout_s))
        self.stop = stop_event
        self.pw = self.browser = self.context = self.page = self.debug = None
        self.demo_verified = False
        self.balance = self.bet = self.busy = None
        self.keyboard_filter = None
        self.loaded = False
        self.scene = None
        self.popups = {}
        self.contract = None
        self.source_hashes = []
        self.points = []
        self.action_binding = None
        self.continuation_binding = None
        self.errors = []
        self.scripts = []
        self.seen = set()
        self.ledger = None
        self.dispatch_stack = []
        self.capture_directory = None
        self.request_schemas = []
        self.passive_roles = {}
        self.manifest = None
        self.trace = None
        self.event_count = 0
        self.instrumentation_id = None
        self.continuations = []
        self.continuation_state = None
        self.continuation_tokens = set()

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.directory.mkdir(parents=True, exist_ok=True)
        self.trace = (self.directory/'ngm-events.jsonl').open('w', encoding='utf-8')
        try:
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch(headless=True)
            self.context = self.browser.new_context(record_har_path=str(self.directory/'session.har'),
                record_har_content='embed', record_har_url_filter=re.compile(r'\.(?:html|js|jmm)(?:\?|$)'))
            self.context.add_init_script(path=str(Path(__file__).with_name('ngm_hook.js')))
            self.page = self.context.new_page()
            self.page.on('console', self._console)
            self.page.on('response', lambda response: self._resource(response))
            self.debug = self.context.new_cdp_session(self.page)
            self.debug.on('Debugger.scriptParsed', lambda event: self.scripts.append(event))
            self.debug.on('Debugger.paused', lambda event: self._paused(event))
            self.debug.send('Debugger.enable', {'maxScriptsCacheSize': 32*1024*1024})
            self.instrumentation_id = self.debug.send('Debugger.setInstrumentationBreakpoint',
                {'instrumentation': 'beforeScriptExecution'})['breakpointId']
            url = 'https://cachedownload.playtechone.com/ngmdesktop/casinoclient.html?' + urlencode(
                dict(game=self.code, preferedmode='offline', real='0'))
            self.page.goto(url, wait_until='domcontentloaded', timeout=int(self.timeout*1000))
            self.wait(lambda: self.demo_verified and self.contract and len(self.points)>=3 and
                      self.balance is not None and self.bet is not None and self.keyboard_filter is not None and
                      self.loaded and self.scene == 'game',
                      'NGM_BOOTSTRAP_INCOMPLETE')
            if any(key in self.keyboard_filter for key in (32, '32', 'SPACE', 'Space')):
                raise ValueError('NGM_SPIN_KEY_SUPPRESSED')
            if self.popups.get('splash') is True:
                if self.stop.is_set():
                    raise InterruptedError('DETENIDO')
                # A known intro can consume Space without wagering. Wait for its
                # explicit close event before attempting the first paid round.
                self.page.locator('body').press('Space', timeout=int(self.timeout*1000))
                self.wait(lambda: self.popups.get('splash') is False, 'NGM_SPLASH_NOT_CLOSED')
            if any(self.popups.values()):
                raise ValueError('NGM_POPUP_UNBOUND')
            self.wait(lambda: self._action_frame() is not None, 'NGM_SPIN_ACTION_NOT_BOUND')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _trusted(self, url):
        parsed = urlsplit(url)
        return parsed.scheme == 'https' and parsed.hostname == 'cachedownload.playtechone.com'

    def _paused(self, event):
        try:
            # Installation precedes the first client event, avoiding dependence
            # on a later click to expose the live action's closure.
            self._install()
        except Exception as exc:
            self.errors.append('NGM_INSTRUMENTATION_FAILED:'+str(exc)[:300])
        finally:
            self.debug.send('Debugger.resume')

    def _resource(self, response):
        path = urlsplit(response.url).path
        if not self._trusted(response.url) or '/'+self.code+'/' not in path or not path.endswith('.jmm'):
            return
        try:
            if response.status != 200:
                return
            raw = response.body()
            if len(raw) > 8*1024*1024:
                raise ValueError('NGM_MANIFEST_TOO_LARGE')
            document = json.loads(raw)
            if not isinstance(document, dict) or not isinstance(document.get('config'), dict):
                return
            manifest = functional_manifest(document, self.code)
            if self.manifest is not None and self.manifest != manifest:
                raise ValueError('NGM_MANIFEST_AMBIGUOUS')
            self.manifest = manifest
            self._save_contracts()
        except (ValueError, UnicodeError) as exc:
            self.errors.append(str(exc))

    def _save_contracts(self):
        (self.directory/'client-contracts.json').write_text(json.dumps(dict(
            schema='tester-spin/ngm-static-contracts/v1', game_code=self.code,
            source_sha256=self.source_hashes, requests=self.request_schemas,
            request_count=len(self.request_schemas), manifest=self.manifest,
            certifies_game_ok=False), indent=2, ensure_ascii=False), encoding='utf-8')

    def _console(self, message):
        prefix = '__TESTER_NGM__'
        if not message.text.startswith(prefix):
            return
        try:
            row = json.loads(message.text[len(prefix):])
            if not self._trusted(row.get('frame', '')):
                return
            self.event_count += 1
            if self.event_count > 10000:
                raise ValueError('NGM_EVENT_LIMIT')
            if '[CAPTURE_LIMIT]' in message.text:
                raise ValueError('NGM_CAPTURE_LIMIT')
            if self.trace:
                self.trace.write(json.dumps(row, ensure_ascii=False)+'\n')
                self.trace.flush()
            kind, data = row['type'], row['data']
            if kind == 'configuration':
                if data.get('classifier') == 'IUserDataResponse':
                    self.demo_verified = data.get('mode') == 'demo'
                    if not self.demo_verified:
                        raise ValueError('NGM_DEMO_MODE_NOT_CONFIRMED')
                if isinstance(data.get('keyboardFilter'), dict):
                    keys = data['keyboardFilter'].get('suppressedKeys')
                    if isinstance(keys, list):
                        self.keyboard_filter = keys
            elif kind == 'message':
                classifier = data.get('classifier')
                if classifier == 'ISetGameBalanceRequest':
                    self.balance = data.get('amount')
                elif classifier == 'GameBetUpdateNotification':
                    self.bet = data.get('totalBet')
                elif classifier == 'IGameBusyRequest':
                    self.busy = data.get('isBusy')
                elif classifier == 'GameLoadingEndNotification':
                    self.loaded = True
                elif classifier == 'ISetActiveSceneRequest':
                    self.scene = data.get('sceneName')
                elif classifier == 'GamePopupNotification':
                    self.popups[str(data.get('type'))] = data.get('visible') is True
                if self.ledger:
                    self.ledger.accept('message', data)
            elif kind.startswith('offline.'):
                if '/'+self.code+'/' not in urlsplit(row['frame']).path:
                    raise ValueError('NGM_GAME_FRAME_MISMATCH')
                value = data.get('value')
                if kind == 'offline.request':
                    spin = value.get('spin') if isinstance(value, dict) else None
                    request_class = value.get('requestClass') if isinstance(value, dict) else None
                    dispatch_kind = 'spin' if isinstance(spin, dict) else self.passive_roles.get(request_class, 'unknown')
                    if dispatch_kind == 'unhandled_candidate':
                        dispatch_kind = 'round_metadata' if value.get('handlerAbsent') is True else 'unknown'
                    self.dispatch_stack.append((dispatch_kind, self.ledger.spins if dispatch_kind == 'spin' and self.ledger else None))
                    if len(self.dispatch_stack) > 32:
                        raise ValueError('NGM_DISPATCH_DEPTH_LIMIT')
                    if dispatch_kind == 'spin':
                        if not self.ledger:
                            raise ValueError('NGM_UNEXPECTED_SPIN_OUTSIDE_ROUND')
                        self._capture_exchange(self.ledger.spins, 'request', row)
                        self.ledger.accept('spin', spin)
                    elif dispatch_kind in ('continuation', 'round_metadata', 'state_save', 'round_finish'):
                        if not self.ledger or not self.ledger.started or self.ledger.ended or not self.ledger.spins:
                            raise ValueError('NGM_UNEXPECTED_CONTINUATION')
                        if dispatch_kind == 'round_finish' and not (self.ledger.spins == self.ledger.responses == self.ledger.payouts):
                            raise ValueError('NGM_FINISH_BEFORE_PAYOUT')
                    elif dispatch_kind == 'unknown' and self.ledger:
                        self.ledger.errors.append('NGM_COMMAND_UNBOUND')
                elif kind == 'offline.response':
                    if not self.dispatch_stack:
                        raise ValueError('NGM_RESPONSE_WITHOUT_DISPATCH')
                    dispatch_kind, step = self.dispatch_stack.pop()
                    if dispatch_kind == 'spin' and self.ledger:
                        self._capture_exchange(step, 'response', row)
                        self.ledger.accept('response', value)
                elif kind == 'offline.payout' and self.ledger:
                    self.ledger.accept('payout', value if isinstance(value, dict) else {})
            elif kind == 'hook.error':
                raise ValueError('NGM_MESSENGER_HOOK_FAILED')
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.errors.append(str(exc))

    def _capture_exchange(self, step, direction, row):
        if self.capture_directory is None:
            return
        evidence = dict(execution_scope='official-local-demo', server_execution=False,
                        source_sha256=self.source_hashes, event_index=self.event_count, observation=row)
        (Path(self.capture_directory)/f'step-{step}-{direction}.json').write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')

    def _install(self):
        while self.scripts:
            event = self.scripts.pop(0)
            sid, url = event['scriptId'], event.get('url', '')
            if sid in self.seen or not self._trusted(url) or '.cache.js' not in url or '/'+self.code+'/' not in urlsplit(url).path:
                continue
            self.seen.add(sid)
            try:
                source = self.debug.send('Debugger.getScriptSource', {'scriptId': sid})['scriptSource']
            except Exception as exc:
                if 'No script for id' in str(exc):
                    continue
                raise
            if 'OfflineServer' not in source or 'NetworkManager is offline' not in source:
                continue
            contract, points = spin_request_contract(source), observation_points(source)
            action = spin_action_binding(source)
            if not contract or len(points) < 3 or not action:
                raise ValueError('NGM_CONTRACT_UNBOUND')
            digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
            if self.source_hashes:
                raise ValueError('NGM_MULTIPLE_CLIENTS')
            for point in points:
                condition = ('(()=>{try{window.__testerNgmEmit('+json.dumps(point['type'])+
                             ',{value:'+point['expression']+'})}catch(e){}return false})()')
                bound = self.debug.send('Debugger.setBreakpoint', {'location':dict(scriptId=sid,
                    lineNumber=point['lineNumber'], columnNumber=point['columnNumber']), 'condition':condition})
                self.points.append(dict(point, actualLocation=bound['actualLocation']))
            # Capture a reference in the live GWT closure when its event bus runs.
            # This is an official UI action; no HAR JavaScript is evaluated.
            start = event_action_binding(source, 'StartEvent')
            probes = continuation_probes(source)
            start_expression = ''
            if start and len(probes) == 2 and start['function'] == action['function']:
                start_expression = 'window.__testerNgmStart=()=>'+start['function']+'(new '+start['constructor']+');'
            condition = ('(()=>{if(!window.__testerNgmSpin){window.__testerNgmSpin=()=>'+
                         action['function']+'(new '+action['constructor']+');'+start_expression+'}return false})()')
            bound_probes = []
            for probe in probes if start_expression else []:
                probe_condition = ('(()=>{window.__testerNgmState=window.__testerNgmState||{};'+
                    'window.__testerNgmState['+json.dumps(probe['type'])+']='+probe['expression']+';return false})()')
                bound_probe = self.debug.send('Debugger.setBreakpoint', {'location':dict(scriptId=sid,
                    lineNumber=probe['lineNumber'], columnNumber=probe['columnNumber']), 'condition':probe_condition})
                bound_probes.append(dict(probe, actualLocation=bound_probe['actualLocation']))
            bound = self.debug.send('Debugger.setBreakpoint', {'location':dict(scriptId=sid,
                lineNumber=action['lineNumber'], columnNumber=action['columnNumber']), 'condition':condition})
            self.action_binding = dict(action, actualLocation=bound['actualLocation'])
            self.continuation_binding = dict(start_event=start, probes=bound_probes) if start_expression else None
            self.contract = contract
            self.source_hashes.append(digest)
            self.request_schemas = request_catalog(source)
            from .ngm_structured import structured_spin_contract
            structured = structured_spin_contract(source)
            if structured:
                self.contract['structured_entry'] = structured
            self.passive_roles = passive_request_roles(self.request_schemas, structured=structured)
            self._save_contracts()
            if self.instrumentation_id:
                self.debug.send('Debugger.removeBreakpoint', {'breakpointId': self.instrumentation_id})
                self.instrumentation_id = None
            (self.directory/'bootstrap.json').write_text(json.dumps(dict(contract=contract,
                source_sha256=self.source_hashes, points=self.points, fresh_demo=True,
                transport=self.transport_kind, spin_action=self.action_binding, continuation=self.continuation_binding), indent=2), encoding='utf-8')

    def _action_frame(self):
        frames = [frame for frame in self.page.frames if self._trusted(frame.url) and
                  '/'+self.code+'/' in urlsplit(frame.url).path]
        if len(frames) != 1:
            return None
        return frames[0] if frames[0].evaluate("typeof window.__testerNgmSpin==='function'") else None

    def wait(self, predicate, reason):
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            if self.stop.is_set():
                raise InterruptedError('DETENIDO')
            if self.errors:
                raise ValueError(self.errors[0])
            self._install()
            if predicate():
                return
            self.page.wait_for_timeout(100)
        raise TimeoutError(reason)

    def _try_free_continuation(self, frame):
        ledger = self.ledger
        if self.stop.is_set():
            raise InterruptedError('DETENIDO')
        if self.errors or any(self.popups.values()) or not ledger or ledger.errors or not ledger.started or ledger.ended:
            return
        if not ledger.spins or ledger.spins != ledger.responses or ledger.responses != ledger.payouts:
            return
        state = frame.evaluate("""() => {
            const s=window.__testerNgmState;
            if(!s || typeof s.feature!=='function' || typeof s.control!=='function' || typeof window.__testerNgmStart!=='function') return null;
            try { return {feature:s.feature(),control:s.control()}; }
            catch(error) { return {unbound:String(error)}; }
        }""")
        if isinstance(state, dict) and state != self.continuation_state:
            self.continuation_state = state
            (self.directory/'continuation-state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        if not isinstance(state, dict) or not self.manifest:
            return
        control = state.get('control')
        if not isinstance(control, dict) or control.get('id') != 'start' or control.get('ready') is not True:
            return
        feature_state = state.get('feature')
        feature_id = feature_state.get('pending') if isinstance(feature_state, dict) else feature_state
        features = self.manifest.get('configuration', {}).get('features', {})
        feature = features.get(feature_id) if isinstance(feature_id, str) and isinstance(features, dict) else None
        if not isinstance(feature, dict) or feature.get('type') != 'free-spins':
            return
        if feature.get('supported') is False or feature.get('free') is False:
            return
        # Pricing/choice declarations require their own binding; a free-spin
        # label alone cannot authorize a priced extension or a selector.
        if any(key in feature for key in ('cost', 'price', 'choices', 'options', 'buy', 'purchase')):
            return
        if not any(c.get('id') == 'start' and 'button' in str(c.get('type', '')) for c in self.manifest.get('controls', [])):
            return
        token = (ledger.spins, ledger.payouts, feature_id)
        if token in self.continuation_tokens:
            return
        if len(self.continuation_tokens) >= 20:
            raise ValueError('NGM_CONTINUATION_LIMIT')
        # Record before sending. If dispatch fails or is ignored, never retry it.
        self.continuation_tokens.add(token)
        self.continuations.append(dict(feature=feature_id, control='start', after_step=ledger.spins,
            round_event=self.event_count, cost_authority='declared-free-spins', action='StartEvent'))
        (self.directory/'continuations.json').write_text(json.dumps(self.continuations, indent=2), encoding='utf-8')
        frame.evaluate('window.__testerNgmStart()')

    def _round_ready(self, ledger, frame):
        if ledger.errors:
            raise ValueError(ledger.errors[0])
        if ledger.ended and ledger.allowed and self.busy is False:
            return True
        self._try_free_continuation(frame)
        return False

    def spin(self):
        if self.stop.is_set():
            raise InterruptedError('DETENIDO')
        if self.errors:
            raise ValueError(self.errors[0])
        if not self.demo_verified or not self.contract or self.ledger is not None or self.busy is True or any(self.popups.values()):
            raise ValueError('NGM_NOT_READY_FOR_SPIN')
        self.continuation_tokens.clear()
        self.ledger = ledger = NGMRoundLedger(self.balance)
        try:
            frame = self._action_frame()
            if frame is None:
                raise ValueError('NGM_SPIN_ACTION_NOT_BOUND')
            # Exactly one official UI event; never retries an uncertain wager.
            frame.evaluate('window.__testerNgmSpin()')
            self.wait(lambda: self._round_ready(ledger, frame),
                      'NGM_ROUND_NOT_CLOSED_AND_READY')
            if not ledger.verified:
                raise ValueError(';'.join(ledger.issues))
            return ledger.summary()
        finally:
            if self.capture_directory is not None:
                (Path(self.capture_directory)/'wire-events.json').write_text(json.dumps(dict(
                    schema='tester-spin/ngm-ledger/v1', execution_scope='official-local-demo',
                    server_execution=False, balance_before=ledger.before, events=ledger.events),
                    ensure_ascii=False, indent=2), encoding='utf-8')
            (self.directory/('round-'+str(self.event_count)+'.json')).write_text(
                json.dumps(ledger.summary(), indent=2), encoding='utf-8')
            # Failed rounds poison this session; the caller must close it.
            if ledger.verified:
                self.ledger = None

    def __exit__(self, *args):
        try:
            if self.context:
                self.context.close()
        finally:
            try:
                if self.browser:
                    self.browser.close()
            finally:
                if self.pw:
                    self.pw.stop()
                if self.trace:
                    self.trace.close()
