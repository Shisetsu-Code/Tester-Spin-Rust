"""Execute and audit certified manual reel choices without title-specific paths."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
from tester_spin.providers.pragmatic_modes import discover_modes
from tester_spin.providers.pragmatic_protocol import server_error
from tester_spin.providers.pragmatic_preparation_coverage import selection_artifacts


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def collect_reel_coverage(result):
    groups = {}
    for attempt in result.attempts:
        directory = Path(attempt.artifact_dir)
        proof = _read(directory/'return-to-base.json')
        valid = (attempt.ok and attempt.terminal and proof.get('status') == 'CONFIRMED'
                 and proof.get('consecutive_base', 0) >= 2)
        accepted = {}
        for path, origin_mode, phase in selection_artifacts(attempt, result, 'step-*.reel-selection.json'):
            record = _read(path)
            if not record.get('domain'):
                continue
            signature = str(record.get('branch_signature') or 'manual-reel-selection')
            source_hash = str(record.get('contract_sha256') or '')
            key = (origin_mode, signature, source_hash)
            group = groups.setdefault(key, {'mode_id':origin_mode, 'signature':signature,
                'required':set(), 'covered':set(), 'counts':{}, 'source':record, 'source_phases':set()})
            group['source_phases'].add(phase)
            group['required'].update(map(str, record['domain']))
            response = _read(path.with_name(path.name.replace('.reel-selection.json','.response.json')))
            if phase == 'attempt' and valid and response and not server_error(response):
                accepted.setdefault(key, set()).add(str(record['selected']))
        for key, options in accepted.items():
            group = groups[key]
            group['covered'].update(options)
            for option in options:
                group['counts'][option] = group['counts'].get(option, 0) + 1
    return groups


def expand_reel_choices(provider, game, result, *, spins, timeout_s, stop_event, progress):
    groups = collect_reel_coverage(result)
    if not groups or result.status in {'ERROR','CANCELADO'}:
        return result
    root = Path(result.run_dir)
    catalog = discover_modes(_read(root/'discovery/doInit.response.json'), requested_base_bet=provider.base_bet)
    modes = {mode.id:mode for mode in catalog.enabled()}
    target = max(1, int(spins))
    initial_status, initial_error = result.status, result.error
    errors = []
    for group_key, group in groups.items():
        mode_id = group['mode_id']
        if mode_id not in modes or len(group['required']) > 64:
            continue
        mode = modes[mode_id]
        existing = [int(p.name.split('-')[-1]) for p in (root/mode_id).glob('attempt-*') if p.name.split('-')[-1].isdigit()]
        repetition = max(existing, default=0)
        for option in sorted(group['required'], key=int):
            deficit = max(0, target-group['counts'].get(option,0))
            for _ in range(deficit * 3):
                if stop_event.is_set():
                    break
                current = collect_reel_coverage(result).get(group_key, {})
                if current.get('counts',{}).get(option,0) >= target:
                    break
                repetition += 1
                progress(f'{mode_id}: selección de carretes {option}; muestra adicional.')
                result.requested_spins += 1
                attempt = provider._test_mode_once(game, symbol=result.symbol, cver=None,
                    mode=mode, catalog=catalog, attempt_number=max((a.number for a in result.attempts),default=0)+1,
                    repetition=repetition, run_root=root, timeout_s=timeout_s, reel_selection_index=option)
                result.attempts.append(attempt)
                if not attempt.ok:
                    errors.append(attempt.error)
                    break
    groups = collect_reel_coverage(result)
    missing = False
    for group in groups.values():
        mode_id = group['mode_id']
        fingerprint = hashlib.sha256((group['signature']+group['source'].get('contract_sha256','')).encode()).hexdigest()[:10]
        missing |= any(group['counts'].get(option,0) < target for option in group['required'])
        multiple = sum(item['mode_id'] == mode_id for item in groups.values()) > 1
        result.discovered_modes.append({'id':mode_id+'_REEL_SELECTION'+('_'+fingerprint if multiple else ''),'kind':'CHOICE_BRANCH',
            'origin_mode_id':mode_id,'source_phases':sorted(group['source_phases']),'observed':True,'executable':True,'coverage_required':True,
            'branch_signature':mode_id+':'+group['signature']+':'+fingerprint,
            'required_options':sorted(group['required'],key=int),'covered_options':sorted(group['covered'],key=int),
            'required_samples':target,'sample_counts':group['counts'],
            'contract_source':group['source'].get('contract_source',''),
            'contract_sha256':group['source'].get('contract_sha256',''),
            'reason':'Selección de carretes anunciada por el cliente; cada opción requiere una ronda terminal y dos tiradas normales.'})
    result.successful_spins = sum(a.ok and a.terminal for a in result.attempts)
    result.failed_spins = sum(not a.ok for a in result.attempts)
    if stop_event.is_set():
        result.status='CANCELADO'
    elif missing or any(not a.ok or not a.terminal for a in result.attempts) or errors:
        result.status='PARCIAL' if result.successful_spins else 'ERROR'
    else:
        result.status=initial_status
    result.error='; '.join([initial_error]+errors).strip('; ')
    if missing:
        result.error = (result.error+' Cobertura pendiente de selecciones de carretes; ver path-coverage.json.').strip()
    provider._write_json(root/'result.json',result.to_dict())
    return result
