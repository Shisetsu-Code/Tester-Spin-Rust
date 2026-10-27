"""Provider-specific closure callbacks. No cross-provider protocol inference."""
from tester_spin.return_to_base import save_exchange, verify_return_to_base


def rubyplay_check(runtime, directory, timeout_s, stop_event):
    from tester_spin.providers.rubyplay.runtime import post_action, validate_action_response

    def play(target):
        captures = []
        action = 'spin'
        had_event = False
        for step in range(1, 129):
            if stop_event.is_set():
                raise InterruptedError('Detención solicitada')
            response, request, data, previous_an = post_action(runtime, action, timeout_s=timeout_s, bet=runtime.default_bet)
            captures.append(save_exchange(target, request, data, step))
            warnings = validate_action_response(data, action=action, previous_an=previous_an)
            if warnings or response.status_code >= 400:
                return dict(ok=False, base=False, known=False, captures=captures, warnings=warnings)
            action = runtime.next_action
            if action == 'spin':
                return dict(ok=True, base=not had_event, known=True, captures=captures)
            had_event = True
            from tester_spin.providers.rubyplay.runtime_contracts import STATE_CONTINUATIONS, INDEX_CONTINUATIONS
            if action not in STATE_CONTINUATIONS - INDEX_CONTINUATIONS:
                return dict(ok=True, base=False, known=False, captures=captures, next_action=action)
        return dict(ok=True, base=False, known=False, captures=captures, reason='continuation limit')
    return verify_return_to_base(directory, play, stop_event=stop_event)


def redtiger_check(runtime, directory, timeout_s, stop_event, *, initial_response=None):
    from tester_spin.providers.redtiger.execution import _post_spin, _post_choice
    from tester_spin.providers.redtiger.runtime import response_summary, pending_choice_from_response, choice_transition

    previous_response = initial_response

    def play(target):
        nonlocal previous_response
        status, request, data, warnings = _post_spin(runtime, stake=runtime.default_stake, feature_buy=None, timeout_s=timeout_s, stop_event=stop_event)
        captures = [save_exchange(target, request, data)]
        entry = data
        from tester_spin.providers.redtiger.base_state import _choice_round_components_normal
        entry_game = entry.get('result', {}).get('game', {})
        normal_probe = (entry_game.get('spinMode') == 'Normal' and type(entry_game.get('gameMode')) is int
                        and entry_game['gameMode'] == 0 and entry_game.get('features') == []
                        and _choice_round_components_normal(entry_game))
        steps, transitions = [], []
        for step in range(1, 65):
            prompt = pending_choice_from_response(data)
            if prompt is None or warnings or not normal_probe:
                break
            selected = 'collect' if 'collect' in prompt.available else prompt.available[0]
            code, endpoint, command, reply, extra_warnings = _post_choice(runtime, prompt=prompt, choice=selected, timeout_s=timeout_s, stop_event=stop_event)
            captures.append(save_exchange(target, command, reply, step+1))
            steps.append((command, reply))
            transitions.append(choice_transition(prompt, selected, reply))
            warnings.extend(extra_warnings)
            status, data = code, reply
        if normal_probe and pending_choice_from_response(data) is not None:
            warnings.append('selector pendiente durante comprobación de regreso al base')
        summary = response_summary(data)
        summary['choice_continuations'] = transitions
        from tester_spin.providers.redtiger.base_state import classify_base_state, settled_paid_choice_round
        if steps:
            base = settled_paid_choice_round(request, entry, steps, previous_response)
            classification = {'base':base, 'known':base, 'reason':'settled_paid_normal_round_with_choices' if base else 'unverified_choice_round'}
        else:
            classification = classify_base_state(data, request=request, previous=previous_response)
        previous_response = data
        return dict(ok=status < 400 and not warnings, base=classification['base'],
                    known=classification['known'], classification=classification,
                    captures=captures, summary=summary)
    return verify_return_to_base(directory, play, stop_event=stop_event)


def bgaming_check(send, base_options, directory, stop_event, *, extra_data=None, legacy=False, initial_balance=None):
    from tester_spin.providers.bgaming.runtime import (
        legacy_safe_terminal_command, provider_error_envelope, flow_continuation_command,
    )

    previous_balance = initial_balance

    def play(target):
        nonlocal previous_balance
        response, request, data = send('spin', options_payload=dict(base_options), extra_data_payload=extra_data)
        captures = []
        had_event = False
        for step in range(1, 257):
            capture = save_exchange(target, request, data, step)
            from tester_spin.providers.bgaming.runtime import balance_total, infer_observed_debit
            capture['observed_debit'] = infer_observed_debit(data, previous_balance)
            capture['balance_before'] = previous_balance
            capture['balance_after'] = balance_total(data)
            previous_balance = balance_total(data)
            captures.append(capture)
            if response.status_code >= 400 or provider_error_envelope(data) is not None or data.get('error'):
                return dict(ok=False, base=False, known=False, captures=captures)
            if stop_event.is_set():
                raise InterruptedError('Detención solicitada')
            if legacy:
                flow = {'state': (data.get('game') or {}).get('state'), 'available_actions': data.get('available_commands')}
                command = legacy_safe_terminal_command(data)
            else:
                flow = data.get('flow') or {}
                command = flow_continuation_command(data)
            closed = flow.get('state') == 'closed' and 'spin' in (flow.get('available_actions') or [])
            modifier = (flow.get('purchased_feature') or {})
            modifier_name = str(modifier.get('name') or '') if isinstance(modifier, dict) else ''
            if closed:
                return dict(ok=True, base=not had_event and not modifier_name, known=True,
                            captures=captures, active_purchase=modifier_name)
            # These commands have a demonstrated parameter-free continuation.
            # Advertised choices do not become executable just by being listed.
            if not command:
                return dict(ok=True, base=False, known=False, captures=captures,
                            pending_state=flow.get('state'), available_actions=flow.get('available_actions'))
            if step == 256:
                break
            had_event = had_event or not legacy
            response, request, data = send(command)
        return dict(ok=True, base=False, known=False, captures=captures, reason='continuation limit')
    return verify_return_to_base(directory, play, stop_event=stop_event)


def belatra_check(provider, state, directory, timeout_s, stop_event=None):
    def play(target):
        ok, terminal, steps, current, following = provider._execute_direct_spin(state, timeout_s=timeout_s, attempt_dir=target)
        import json
        captures = []
        labels = ['start'] + sorted(path.name.removesuffix('.request.json') for path in target.glob('continue-*.request.json')) + ['finish']
        had_feature = False
        for step, label in enumerate(labels, 1):
            req = target/f'{label}-request.json'
            resp = target/f'{label}-response.json'
            # Canonical Belatra filenames use a dot.
            if not req.exists():
                req, resp = target/f'{label}.request.json', target/f'{label}.response.json'
            if req.exists() and resp.exists():
                request = json.loads(req.read_text(encoding='utf-8'))
                response = json.loads(resp.read_text(encoding='utf-8'))
                captures.append({'step': step, 'request': request, 'response': response})
                gs = response.get('gs') or {}
                current_phase, next_phase = str(gs.get('phaseCur') or ''), str(gs.get('phaseNext') or '')
                had_feature = had_feature or current_phase.startswith(('free', 'Bonus')) or next_phase.startswith(('toNextFG', 'toBonus'))
        return dict(ok=ok, base=terminal and not had_feature, known=terminal, captures=captures, state=[current, following])
    return verify_return_to_base(directory, play, stop_event=stop_event)


def pragmatic_check(provider, bootstrap, last, base_fields, directory, timeout_s):
    current = dict(last)

    def play(target):
        nonlocal current
        captures = []
        had_event = False
        had_manual = False
        ordinary_cascade_seen = False
        in_bonus = False
        action = 'doSpin'
        for step in range(128):
            from tester_spin.return_to_base import audit_stop_event
            stop = audit_stop_event()
            if stop is not None and stop.is_set():
                raise InterruptedError('Detención solicitada')
            fields = dict(base_fields)
            if action in {'doCollect', 'doBonus', 'doCollectBonus', 'doFSOption'}:
                fields = {key: fields[key] for key in ('symbol', 'repeat', 'mgckey') if key in fields}
            fields['action'] = action
            if action == 'doFSOption':
                fields['ind'] = str(selected_fs_option)
            if action == 'doSpin':
                fields['bl'] = '0'
            fields.pop('pur', None)
            for key in ('index', 'counter'):
                fields[key] = str(int(current.get(key) or fields.get(key) or 0)+1)
            status, _, data, _ = provider._post_and_store(bootstrap, fields, target, step=step, label='base-check', timeout_s=timeout_s)
            captures.append(save_exchange(target, fields, data, step+1))
            current = data
            from tester_spin.providers.pragmatic_protocol import server_error
            err = server_error(data)
            if status >= 400 or err not in (None, '', '0'):
                return dict(ok=False, base=False, known=False, captures=captures)
            from tester_spin.providers.pragmatic_observed_transitions import observed_next_action
            na = observed_next_action(data,getattr(bootstrap,'symbol',''))
            from tester_spin.providers.pragmatic_observed_transitions import observed_continuation
            declared=observed_continuation(data,getattr(bootstrap,'symbol',''))
            if declared:
                # Free cards belong to a feature, not a normal paid base cycle.
                had_event = had_event or data.get('na') == 'm' or data.get('fs_left') not in (None, '', '0')
                action=declared
                continue
            from tester_spin.providers.pragmatic_observed_transitions import observed_paid_base
            active_data = {k:v for k,v in data.items() if k != 'rs_c'} if observed_paid_base(data, getattr(bootstrap,'symbol','')) else data
            active = provider._feature_active(active_data)
            from tester_spin.providers.pragmatic_reel_contract import reel_selection
            from tester_spin.providers.pragmatic_observed_transitions import automatic_fs_respin
            automatic_cascade = automatic_fs_respin(data, symbol=getattr(bootstrap, "symbol", ""))
            manual = None if automatic_cascade else reel_selection(data, getattr(bootstrap, 'reel_contract', None))
            had_manual = had_manual or manual is not None
            # A certified manual reel choice is part of the ordinary paid round.
            # Other features still reset consecutive normal-round confirmation.
            other_features = provider._feature_active({key:value for key,value in active_data.items()
                if key not in {'rs','rs_p','rs_c','rs_m','rs_t','rs_more'}})
            ordinary_cascade = automatic_cascade and 'fs' not in data and 'fsmax' not in data
            ordinary_cascade_seen = ordinary_cascade_seen or ordinary_cascade
            ordinary_finish = ordinary_cascade_seen and not other_features and (
                'rs_t' in data or (not data.get('rs') and all(key in data for key in ('rs_p','rs_c','rs_m'))))
            had_event = had_event or (active and ((manual is None and not ordinary_cascade and not ordinary_finish) or other_features))
            if na == 'fso':
                from tester_spin.providers.pragmatic_har_states import parse_fs_options, choose_fs_option_index
                options = parse_fs_options(data)
                if not options:
                    return dict(ok=True, base=False, known=False, captures=captures, next_action=na)
                selected_fs_option = choose_fs_option_index(options, repetition=1)
                provider._write_json(target / f'base-fs-option-{step:03d}.json', {
                    'schema': 'tester-spin/pragmatic-fso-selection/v1',
                    'source': 'HAR-grounded doFSOption', 'phase': 'base_probe',
                    'option_count': len(options), 'option_indices': [item['index'] for item in options],
                    'selected_index': selected_fs_option, 'options': options,
                    'fs_opt_mask': data.get('fs_opt_mask', ''), 'fs_opt': data.get('fs_opt', ''),
                })
                had_event = True
                action = 'doFSOption'
            elif na == 'b':
                had_event = True
                from tester_spin.providers.pragmatic_observed_transitions import bonus_transition
                in_bonus = bonus_transition(data) is None
                action = 'doBonus'
            elif na in {'cb', 'bc'}:
                action = 'doCollectBonus'
            elif na == 'c':
                action = 'doCollect'
            elif na == 's' and active:
                action = 'doSpin'
            elif (na == 's' or (not na and action in {'doCollect', 'doCollectBonus'})) and not active:
                return dict(ok=True, base=not had_event, known=True, captures=captures, manual_phase_observed=had_manual)
            else:
                return dict(ok=True, base=False, known=False, captures=captures, next_action=na)
        return dict(ok=True, base=False, known=False, captures=captures)
    return verify_return_to_base(directory, play)


def d1_check(provider, ws, frames, lines, bet_index, initial_state, directory, timeout_s, *, initial_terminal=False):
    import time
    from tester_spin.return_to_base import audit_stop_event

    def play(target):
        nonlocal lines, bet_index
        captures = []
        had_event = False
        for step in range(1, 129):
            stop = audit_stop_event()
            if stop is not None and stop.is_set():
                raise InterruptedError('Detención solicitada')
            wire = provider._wire_message('1', f'{lines},{bet_index},0')
            ws.send(wire)
            frames.append({'direction': 'sent', 'classification': 'return-to-base' if step == 1 else 'return-continuation', 'payload': provider._frame_preview(wire)})
            deadline = time.monotonic()+max(2.0, timeout_s)
            payload = None
            while time.monotonic() < deadline:
                candidate = provider._recv_protocol_json(ws, deadline=deadline, frames=frames)
                message_type = provider._int_field(candidate.get('type'), -1)
                if message_type in {2, 3}:
                    payload = candidate
                    break
            if payload is None:
                raise TimeoutError('D1: sin respuesta a comprobación de regreso')
            captures.append(save_exchange(target, {'type': 1, 'lines': lines, 'bet_index': bet_index}, payload, step))
            if message_type == 2:
                return dict(ok=False, base=False, known=False, captures=captures)
            active = provider._d1_feature_active(payload)
            if active:
                had_event = True
                if payload.get('l') is not None:
                    lines = provider._int_field(payload['l'], lines)
                if payload.get('b3') is not None:
                    bet_index = provider._int_field(payload['b3'], bet_index)
                continue
            # Operational return is distinct from proving the st contract.
            same_state = payload.get('st') == initial_state and initial_state is not None
            terminal = getattr(provider, '_d1_result_terminal', lambda value: value.get('st') == 0)(payload)
            return dict(ok=True, base=(terminal or same_state) and not had_event,
                        known=terminal or same_state,
                        captures=captures, terminal_contract_proven=terminal)
        return dict(ok=True, base=False, known=False, captures=captures, reason='continuation limit')
    return verify_return_to_base(directory, play, observed_only=not initial_terminal and initial_state not in getattr(provider, 'D1_TERMINAL_STATES', {0}))
