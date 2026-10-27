"""Annotate certified bonus picks without equating one choice with all coverage."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from tester_spin.providers.pragmatic_protocol import server_error
from tester_spin.providers.pragmatic_preparation_coverage import selection_artifacts

_ORIGIN = 'pragmatic_bonus_selection_artifacts'


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _integer(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _canonical_selection(path, record):
    # Re-evaluate legacy artifacts from their preceding RAW state; preserve files.
    signature=str(record.get('branch_signature',''))
    if not (signature.startswith('PRAGMATIC:range-pick:bgt=69:') or (signature.startswith('PRAGMATIC:bonus-choice:bgt=69:') and any(family in signature for family in ('family=gambling:','family=bg:')))):
        return record
    match=re.match(r'step-([0-9]+)-',path.name)
    if not match or int(match[1])==0:return record
    previous=list(path.parent.glob(f'step-{int(match[1])-1:03d}-*.response.json'))
    if len(previous)!=1:return record
    from tester_spin.providers.pragmatic_observed_transitions import bonus_transition
    try:normalized=bonus_transition(_read(previous[0]),override=record.get('selected'))
    except ValueError:return record
    return normalized if normalized and normalized.get("coverage_policy") in {"parameterized-menu-actions/v1","repeatable-menu-actions/v1","hidden-position-structural/v1"} else record


def annotate_bonus_coverage(result):
    """Refresh per-mode/state/source coverage from attempts and their base probes.

    A sample is an independent terminal attempt with two confirmed base cycles,
    not another pick or probe in the same attempt. Linked bootstrap observations add SPIN obligations but never count as samples.
    A later verified SPIN with the same contract and state can satisfy them.
    """
    groups = {}
    target = max(1, _integer(getattr(result, 'samples_per_path', 1), 1))
    for attempt in result.attempts:
        if not attempt.artifact_dir:
            continue
        directory = Path(attempt.artifact_dir)
        proof = _read(directory / 'return-to-base.json')
        valid_attempt = (attempt.ok and attempt.terminal and proof.get('status') == 'CONFIRMED'
                         and _integer(proof.get('consecutive_base')) >= 2)
        accepted = defaultdict(set)
        for path, origin_mode, phase in selection_artifacts(attempt, result, 'step-*.bonus-selection.json', recursive_attempt=True):
            record = _canonical_selection(path, _read(path))
            raw_domain = record.get('domain')
            if not isinstance(raw_domain, list) or not raw_domain:
                continue
            domain = {str(value) for value in raw_domain}
            if any(not value.isdecimal() for value in domain):
                continue
            signature = str(record.get('coverage_branch_signature') or record.get('branch_signature') or '')
            structural = (record.get('coverage_policy') == 'hidden-position-structural/v1'
                and re.fullmatch(r'PRAGMATIC:(?:bonus-grid:bg_0:bgt=69:size=[0-9]+:level=[0-9]+|bonus-pick:bgt=69:size=[0-9]+:level=[0-9]+|progressive-grid:flat:size=[0-9]+:level=0)', signature))
            parameterized = (record.get('coverage_policy') == 'parameterized-menu-actions/v1'
                and signature == 'PRAGMATIC:parameterized-gamble:bgt=69:play-sm-sp')
            repeatable = (record.get('coverage_policy') == 'repeatable-menu-actions/v1'
                and signature == 'PRAGMATIC:repeatable-menu:bgt=69:family=bg:labels=y,n'
                and domain == {'0', '1'})
            domain_map = record.get('coverage_domain_map', {}) if parameterized else {}
            if parameterized and (set(domain_map) != domain or not set(domain_map.values()) <= {'0','1','2'}):continue
            coverage_domain = {'0'} if structural else set(domain_map.values()) if parameterized else domain
            policy = ('hidden-position-structural/v1' if structural else
                      'parameterized-menu-actions/v1' if parameterized else
                      'repeatable-menu-actions/v1' if repeatable else 'ordinal-options/v1')
            source_hash = str(record.get('contract_sha256') or '')
            key = (origin_mode, signature, source_hash, policy)
            group = groups.setdefault(key, {'required': set(), 'counts': defaultdict(int), 'record': record, 'source_phases': set(), 'observed_domain':set()})
            group['source_phases'].add(phase)
            group['required'].update(coverage_domain)
            group['observed_domain'].update(domain)
            selected = str(record.get('selected'))
            response = _read(path.with_name(path.name.replace('.bonus-selection.json', '.response.json')))
            http = _read(path.with_name(path.name.replace('.bonus-selection.json', '.http.json')))
            valid_response = bool(response) and not server_error(response) and _integer(http.get('status'), 200) < 400
            if parameterized:
                from tester_spin.providers.pragmatic_observed_transitions import parameterized_gamble_acknowledged
                valid_response = valid_response and parameterized_gamble_acknowledged(record,response)
            if record.get('coverage_policy')=='repeatable-menu-actions/v1':
                from tester_spin.providers.pragmatic_observed_transitions import repeatable_yes_no_acknowledged
                valid_response=valid_response and repeatable_yes_no_acknowledged(record,response)
            if structural and signature.startswith('PRAGMATIC:bonus-pick:bgt=69:'):
                from tester_spin.providers.pragmatic_observed_transitions import range_pick_acknowledged
                valid_response=valid_response and range_pick_acknowledged(record,response)
            if signature.startswith('PRAGMATIC:progressive-grid:flat:'):
                statuses = str(response.get('status','')).split(',')
                valid_response = (valid_response and selected in domain
                    and len(statuses) == len(domain)
                    and all(value == ('1' if str(i) == selected else '0') for i,value in enumerate(statuses))
                    and response.get('na') in {'cb','bc'} and response.get('end') == '1'
                    and response.get('level') == '1' and response.get('lifes') == '0')
            if signature.startswith('PRAGMATIC:mystery-choice:vs10bookfallen:'):
                valid_response = (valid_response and selected in domain
                    and response.get('ms') == str(int(selected)+3)
                    and response.get('ch') == 'ind~'+selected)
            if phase in {'attempt', 'base_probe'} and valid_attempt and valid_response and signature and source_hash and selected in domain:
                accepted[key].add('0' if structural else domain_map.get(selected,selected))
        for key, choices in accepted.items():
            for selected in choices:
                groups[key]['counts'][selected] += 1

    shared_counts = defaultdict(int)
    shared_modes = defaultdict(set)
    for (mode_id, signature, source_hash, policy), group in groups.items():
        if policy == 'hidden-position-structural/v1':
            shared_key = (signature, source_hash)
            shared_counts[shared_key] += group['counts'].get('0', 0)
            if group['counts'].get('0', 0):shared_modes[shared_key].add(mode_id)
    result.discovered_modes = [row for row in result.discovered_modes if row.get('coverage_origin') != _ORIGIN]
    pending = False
    for (mode_id, signature, source_hash, policy), group in sorted(groups.items()):
        required = sorted(group['required'], key=int)
        counts = ({'0':shared_counts[(signature, source_hash)]} if policy=='hidden-position-structural/v1'
                  else dict(sorted(group['counts'].items(), key=lambda pair: int(pair[0]))))
        covered = [option for option in required if counts.get(option, 0) >= target]
        pending = pending or len(covered) < len(required)
        identity_data = [mode_id, signature, source_hash] + ([policy] if policy=='hidden-position-structural/v1' else [])
        identity = hashlib.sha256(json.dumps(identity_data).encode('utf-8')).hexdigest()[:16]
        record = group['record']
        result.discovered_modes.append({
            'id': f'{mode_id}_BONUS_PICK_{identity}', 'kind': 'CHOICE_BRANCH',
            'origin_mode_id': mode_id, 'coverage_origin': _ORIGIN, 'source_phases': sorted(group['source_phases']),
            'observed': True, 'executable': bool(signature and source_hash), 'coverage_required': True,
            'branch_signature': f'{mode_id}:{signature}:{source_hash}' + (f':{policy}' if policy=='hidden-position-structural/v1' else ''),
            'coverage_policy':policy,
            'coverage_class_labels':{'0':'hidden_position'} if policy=='hidden-position-structural/v1' else record.get('coverage_class_labels',{}),
            'handler_sample_modes':sorted(shared_modes[(signature,source_hash)]) if policy=='hidden-position-structural/v1' else [mode_id],
            'observed_position_domain':sorted(group['observed_domain'],key=int),
            'contract_branch_signature': signature,
            'required_options': required, 'covered_options': covered,
            'required_samples': target, 'sample_counts': counts,
            'contract_source': record.get('contract_source', ''), 'contract_sha256': source_hash,
            'reason': ('Clase de posición oculta: mismo selector status<=0 y doBonus(ind); no acredita todos los índices ni premios. '
                       if policy=='hidden-position-structural/v1' else 'Cada opción de menú requiere su muestra. ')
                      + 'Exige respuesta válida, ronda terminal y dos ciclos base; muestras por intento independiente.',
        })
    if pending and result.status == 'OK':
        result.status = 'PARCIAL'
    return result


def expand_observed_bonus_choices(provider, game, result, *, spins, timeout_s, stop_event, progress):
    """Explore only HAR-confirmed bgt=69 choices, using bounded fresh sessions.

    The existing wire selector reserves least-attempted choices per symbol.
    A choice counts only after terminal proof and two completed base rounds.
    """
    if not result.run_dir or result.status in {'ERROR','CANCELADO'}: return result
    from tester_spin.providers.pragmatic_modes import discover_modes
    root=Path(result.run_dir)
    catalog=discover_modes(_read(root/'discovery/doInit.response.json'),requested_base_bet=provider.base_bet)
    modes={mode.id:mode for mode in catalog.enabled()}
    original_status=result.status
    result.samples_per_path=max(1,int(spins))
    annotate_bonus_coverage(result)
    def observed():
        def supported_grid(row):
            match=re.fullmatch(r'PRAGMATIC:(?:bonus-grid:bg_0:bgt=69|bonus-pick:bgt=[0-9]+):size=([0-9]+):level=([0-9]+)',row.get('contract_branch_signature',''))
            return bool(match and 1<=int(match[1])<=14)
        return [row for row in result.discovered_modes if row.get('coverage_origin')==_ORIGIN
                and (row.get('contract_branch_signature','').startswith('PRAGMATIC:bonus-choice:bgt=69:')
                     or row.get('contract_branch_signature','').startswith('PRAGMATIC:mystery-choice:vs10bookfallen:')
                     or row.get('contract_branch_signature') in {'PRAGMATIC:parameterized-gamble:bgt=69:play-sm-sp','PRAGMATIC:repeatable-menu:bgt=69:family=bg:labels=y,n'}
                     or supported_grid(row))]
    if not observed(): return result
    explored_modes=set()
    for initial in list(observed()):
        mode_id=initial['origin_mode_id']
        if mode_id not in modes or mode_id in explored_modes: continue
        domain=initial['required_options']
        grid=initial['contract_branch_signature'].startswith(('PRAGMATIC:bonus-grid:','PRAGMATIC:bonus-pick:'))
        if len(domain)>14: continue
        explored_modes.add(mode_id)
        repetitions=[int(p.name.split('-')[-1]) for p in (root/mode_id).glob('attempt-*') if p.name.split('-')[-1].isdigit()]
        repetition=max(repetitions,default=0)
        for _ in range(min(64 if grid else 24,len(domain)*result.samples_per_path*(4 if grid else 3))):
            if stop_event.is_set(): break
            pending_rows=[row for row in observed() if row['origin_mode_id']==mode_id
                          and set(row['required_options'])-set(row['covered_options'])]
            if not pending_rows: break
            repetition+=1
            progress(f'{mode_id}: cobertura automática de elección de free spins; muestra adicional {repetition}.')
            result.requested_spins+=1
            attempt=provider._test_mode_once(game,symbol=result.symbol,cver=None,mode=modes[mode_id],catalog=catalog,
                attempt_number=max((a.number for a in result.attempts),default=0)+1,repetition=repetition,
                run_root=root,timeout_s=timeout_s)
            result.attempts.append(attempt)
            annotate_bonus_coverage(result)
            if not attempt.ok or not attempt.terminal: break
    result.successful_spins=sum(a.ok and a.terminal for a in result.attempts)
    result.failed_spins=sum(not a.ok for a in result.attempts)
    pending=any(set(row['required_options'])-set(row['covered_options']) for row in result.discovered_modes if row.get('coverage_origin')==_ORIGIN)
    if stop_event.is_set(): result.status='CANCELADO'
    elif pending or any(not a.ok or not a.terminal for a in result.attempts): result.status='PARCIAL'
    elif original_status=='OK': result.status='OK'
    provider._write_json(root/'result.json',result.to_dict())
    return result
