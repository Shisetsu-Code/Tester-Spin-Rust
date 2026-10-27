"""Financial and lifecycle checks for observed NGM offline rounds."""


def _amount(value):
    # NGM stores currency in integer minor units. Never accept bool/NaN/coercion.
    return type(value) is int and 0 <= value <= 2**53-1


class NGMRoundLedger:
    def __init__(self, before):
        if not _amount(before):
            raise ValueError('BALANCE_UNKNOWN')
        self.before = self.balance = before
        self.started = self.ended = self.allowed = False
        self.spins = self.responses = self.payouts = 0
        self.stake = self.win = 0
        self.errors = []
        self.debit_balances = []
        self.events = []

    def accept(self, kind, value):
        from copy import deepcopy
        self.events.append(dict(kind=kind, value=deepcopy(value)))
        if kind == 'message':
            classifier = value.get('classifier')
            if classifier == 'GameRoundStartNotification':
                if self.started:
                    self.errors.append('OVERLAPPING_ROUND')
                self.started = True
            elif classifier == 'ISetGameBalanceRequest':
                if _amount(value.get('amount')):
                    if self.responses and value['amount'] < self.balance:
                        self.errors.append('UNDECLARED_CONTINUATION_DEBIT')
                    self.balance = value['amount']
                    if self.started and not self.responses:
                        self.debit_balances.append(self.balance)
                else:
                    self.errors.append('INVALID_BALANCE')
            elif classifier == 'GameRoundEndNotification':
                if not self.started or self.ended:
                    self.errors.append('ROUND_END_OUT_OF_ORDER')
                self.ended = True
            elif classifier == 'NextGameRoundAllowed':
                if self.ended:
                    self.allowed = True
        elif kind == 'spin':
            if not self.started or self.ended or self.spins != self.payouts:
                self.errors.append('SPIN_OUT_OF_ORDER')
            structured = value.get('wager_format') == 'structured-line' and value.get('bet_type') == 'line'
            if not _amount(value.get('bet')) or (not structured and (not _amount(value.get('numCoins')) or not value.get('numCoins'))):
                self.errors.append('INVALID_WAGER')
            elif (value.get('spinType') == 'regular' or structured) and self.spins == 0 and value['bet'] > 0:
                self.stake += value['bet']
            elif value.get('spinType') != 'free' or self.spins == 0:
                self.errors.append('SPIN_TYPE_UNSUPPORTED')
            self.spins += 1
        elif kind == 'response':
            if not self.started or self.ended or self.responses >= self.spins:
                self.errors.append('RESPONSE_OUT_OF_ORDER')
            self.responses += 1
        elif kind == 'payout':
            if not self.started or self.ended or self.payouts >= self.responses:
                self.errors.append('PAYOUT_OUT_OF_ORDER')
            if _amount(value.get('calculatedWin')):
                self.win += value['calculatedWin']
            else:
                self.errors.append('INVALID_PAYOUT')
            self.payouts += 1

    @property
    def issues(self):
        errors = list(self.errors)
        if not self.started or not self.ended or not self.allowed:
            errors.append('ROUND_NOT_CLOSED_AND_READY')
        if not self.spins or self.responses != self.spins:
            errors.append('RESPONSE_COUNT_MISMATCH')
        if self.payouts != self.spins:
            errors.append('PAYOUT_COUNT_MISMATCH')
        if self.before-self.stake+self.win != self.balance:
            errors.append('BALANCE_NOT_RECONCILED')
        if not self.stake or self.before-self.stake not in self.debit_balances:
            errors.append('WAGER_DEBIT_NOT_OBSERVED')
        return list(dict.fromkeys(errors))

    @property
    def verified(self):
        return not self.issues

    def summary(self):
        return dict(verified=self.verified, stake=self.stake, win=self.win,
                    balance_before=self.before, balance_after=self.balance,
                    steps=self.spins, issues=self.issues, local_demo=True)


def test_ngm_game(provider, game, *, spins, timeout_s, stop_event, progress):
    """Execute observed rounds and consume the current captured client plan."""
    import json
    import time
    import uuid
    from tester_spin.models import GameTestResult, SpinAttempt, utc_now_iso

    clock = time.monotonic()
    run = provider.har_artifact_dir(game)/'runs'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    count = max(1, int(spins))+1
    result = GameTestResult(provider.key, game.slug, game.name, game.url, count, 0, 0,
                            'PARCIAL', symbol=game.symbol, run_dir=str(run))
    result.feature_domains = {key:dict(declaration_state='UNKNOWN', options=[])
                              for key in ('purchase', 'ante')}
    issues = ['NGM_FEATURE_INVENTORY_UNKNOWN']
    result.structural_map['playtech_protocol'] = dict(variant='ngm-offline',
        transport='local-client-engine', fresh_demo=False, server_execution=False)
    try:
        if stop_event.is_set():
            raise InterruptedError('DETENIDO')
        with provider.ngm_session_factory(game.symbol, run, timeout_s, stop_event) as session:
            result.structural_map['playtech_protocol'].update(
                contract=session.contract, source_sha256=session.source_hashes,
                fresh_demo=getattr(session, 'demo_verified', False),
                request_schemas=getattr(session, 'request_schemas', []),
                functional_manifest=getattr(session, 'manifest', None))
            mode = dict(id='NGM_REGULAR', kind='SPIN', name='Giro normal demo local', validated=False)
            result.discovered_modes = [mode]
            for index in range(1, count+1):
                if stop_event.is_set():
                    raise InterruptedError('DETENIDO')
                directory = run/f'attempt-{index}'
                directory.mkdir()
                attempt = SpinAttempt(index, False, mode_id=mode['id'], symbol=game.symbol,
                                      artifact_dir=str(directory))
                result.attempts.append(attempt)
                started = time.monotonic()
                try:
                    session.capture_directory = directory
                    summary = session.spin()
                    if summary.get('verified') is not True:
                        raise ValueError('NGM_ROUND_NOT_VERIFIED')
                    evidence = dict(summary, execution_scope='official-local-demo',
                        server_execution=False, source_sha256=session.source_hashes, event_trace='wire-events.json', session_trace='../ngm-events.jsonl')
                    (directory/'summary.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
                    attempt.ok = attempt.terminal = True
                    attempt.wire_steps = summary['steps']
                    mode['execution_scope'] = 'official-local-demo'
                    result.successful_spins += 1
                    mode['validated'] = True
                    if index == count:
                        result.structural_map['return_to_base_verified'] = True
                    progress(f'[{game.name}] NGM demo local: ronda cerrada, coste {summary["stake"]}, premio {summary["win"]}.')
                except Exception as exc:
                    attempt.error = str(exc)
                    raise
                finally:
                    session.capture_directory = None
                    attempt.elapsed_ms = (time.monotonic()-started)*1000
            issues.extend(session.errors)
    except Exception as exc:
        issues.append(type(exc).__name__+': '+str(exc))
    # The recorder finishes writing on context close. Analyze only afterwards;
    # this path reads evidence and never reuses a captured session for execution.
    har_path = run/'session.har'
    if har_path.is_file():
        try:
            from .ngm_contracts import analyze_har
            if har_path.stat().st_size > 256*1024*1024:
                raise ValueError('NGM_HAR_TOO_LARGE')
            report = analyze_har(json.loads(har_path.read_text(encoding='utf-8-sig')), game.symbol)
            (run/'ngm-har-contracts.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
            protocol = result.structural_map['playtech_protocol']
            matches = report.get('source_sha256') in protocol.get('source_sha256', [])
            protocol['har_analysis'] = dict(path=str(run/'ngm-har-contracts.json'),
                request_count=report['request_count'], source_matches_session=matches, unresolved=report['unresolved'],
                capture_diagnostics=report['capture_diagnostics'])
            result.structural_map['capture_next_steps'] = report['capture_diagnostics']['next_steps']
            issues.extend(code for code in report['capture_diagnostics']['issues'] if code == 'HAR_EMPTY_CAPTURE')
            if protocol.get('source_sha256') and not matches:
                issues.append('NGM_HAR_SOURCE_MISMATCH')
            manifest_matches = protocol.get('functional_manifest') == report.get('manifest') and report.get('manifest') is not None
            protocol['har_analysis']['manifest_matches_session'] = manifest_matches
            plan = report['execution_plan']
            protocol['execution_plan'] = plan
            (run/'execution-plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
            if not manifest_matches:
                issues.append('NGM_HAR_MANIFEST_MISMATCH')
            if not protocol.get('fresh_demo'):
                issues.append('NGM_DEMO_MODE_NOT_CONFIRMED')
            if matches and manifest_matches and protocol.get('fresh_demo') and plan['complete']:
                result.feature_domains = plan['domains']
                issues.remove('NGM_FEATURE_INVENTORY_UNKNOWN')
                result.structural_map['ngm_features'] = plan['features']
            else:
                issues.extend(plan['unresolved'])
        except (OSError, ValueError, TypeError) as exc:
            issues.append('NGM_HAR_ANALYSIS_FAILED:'+str(exc))
    else:
        issues.append('NGM_HAR_MISSING')
        result.structural_map['capture_next_steps'] = ['No se guardó session.har. Revisá el error de arranque/cierre del navegador y repetí la prueba demo con captura completa.']
    result.failed_spins = sum(not attempt.ok for attempt in result.attempts)
    result.status = 'OK' if (not issues and result.successful_spins == count
        and len(result.attempts) == count and all(a.ok and a.terminal for a in result.attempts)
        and result.structural_map.get('return_to_base_verified')) else 'PARCIAL'
    result.error = '; '.join(dict.fromkeys(issues))
    result.structural_map['execution_issues'] = list(dict.fromkeys(issues))
    result.finished_at = utc_now_iso()
    result.elapsed_ms = (time.monotonic()-clock)*1000
    (run/'result.json').write_text(json.dumps(result.to_dict(), indent=2), encoding='utf-8')
    if result.status == 'PARCIAL':
        for step in result.structural_map.get('capture_next_steps', []):
            progress(f'[{game.name}] Captura: {step}')
    progress(f'[{game.name}] {result.status}: {result.successful_spins} rondas demo locales verificadas. '+result.error)
    return result
