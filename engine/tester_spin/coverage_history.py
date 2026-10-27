"""Keep unresolved, explicitly announced branches across short audit runs."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_lock = threading.RLock()


@contextmanager
def _history_lock(root):
    """Use a stable lock file for the entire read/merge/replace transaction."""
    with _lock:
        root.mkdir(parents=True, exist_ok=True)
        # Never unlink the lock: waiters must all synchronize on the same file.
        with (root / '.coverage-history.lock').open('a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b'\0')
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def _archive_structural_replacements(pending, modes, migrations, source):
    for mode in modes:
        if (not isinstance(mode, dict) or mode.get('observed') is not True
                or mode.get('coverage_required') is not True
                or mode.get('coverage_policy') != 'hidden-position-structural/v1'
                or mode.get('coverage_origin') != 'pragmatic_bonus_selection_artifacts'
                or mode.get('required_options') != ['0'] or mode.get('covered_options') != ['0']):
            continue
        signature = str(mode.get('contract_branch_signature', ''))
        digest = str(mode.get('contract_sha256', ''))
        if (not re.fullmatch(r'PRAGMATIC:bonus-grid:bg_0:bgt=69:size=[1-9][0-9]*:level=[0-9]+', signature)
                or not re.fullmatch(r'[a-f0-9]{64}', digest) or not mode.get('origin_mode_id')):
            continue
        counts = mode.get('sample_counts')
        if not isinstance(counts, dict):
            continue
        for key, prior in list(pending.items()):
            if (prior.get('coverage_policy') != 'ordinal-options/v1'
                    or any(prior.get(field) != mode.get(field) for field in
                           ('coverage_origin', 'origin_mode_id', 'contract_branch_signature', 'contract_sha256'))
                    or not prior.get('required_options')
                    or any(not str(option).isdecimal() for option in prior['required_options'])):
                continue
            target = max(1, int(prior.get('required_samples') or 1), int(mode.get('required_samples') or 1))
            if int(counts.get('0', 0)) < target:
                continue
            migrations.append({'policy': 'ordinal-to-hidden-position/v1', 'previous_id': key,
                               'previous': copy.deepcopy(prior), 'replacement_id': mode['id'],
                               'replacement_source': source, 'contract_sha256': digest,
                               'contract_branch_signature': signature, 'required_samples': target})
            del pending[key]


def _archive_recurring_choice_replacements(pending, modes, migrations, source):
    """Replace depth-expanded obligations only with current complete loop evidence."""
    for marker in modes:
        if (not isinstance(marker, dict) or marker.get('kind') != 'DIAGNOSTIC'
                or marker.get('observed') is not True or marker.get('coverage_required') is not False
                or marker.get('source') != 'choice_transition.gameData.progress.level'
                or marker.get('coverage_scope') != 'available_actions_not_all_repeat_counts'):
            continue
        parent, anchor = marker.get('parent'), marker.get('entry_prefix')
        options, repeats = marker.get('options'), marker.get('repeat_actions')
        if (not isinstance(anchor, list) or not isinstance(options, list) or not options
                or not isinstance(repeats, list) or not repeats
                or not all(isinstance(v,str) and v for v in anchor + options + repeats)
                or not set(repeats).issubset(options)):
            continue
        replacement = next((mode for mode in modes if isinstance(mode,dict)
            and mode.get('kind') == 'CHOICE_BRANCH' and mode.get('parent') == parent
            and mode.get('prefix') == anchor and mode.get('observed') is True
            and mode.get('coverage_required') is True
            and set(mode.get('required_options', [])) == set(options)
            and set(options).issubset(mode.get('covered_options', []))), None)
        if replacement is None:
            continue
        counts = replacement.get('sample_counts')
        if not isinstance(counts,dict):
            continue
        for key, prior in list(pending.items()):
            prefix = prior.get('prefix')
            required = prior.get('required_options')
            if (prior.get('kind') != 'CHOICE_BRANCH' or prior.get('parent') != parent
                    or not isinstance(prefix,list) or len(prefix) <= len(anchor)
                    or prefix[:len(anchor)] != anchor
                    or not all(action in repeats for action in prefix[len(anchor):])
                    or not isinstance(required,list) or not required
                    or not set(required).issubset(options)):
                continue
            try:
                target = max(1,int(prior.get('required_samples') or 1),int(replacement.get('required_samples') or 1))
                if any(int(counts.get(option,0)) < target for option in required):
                    continue
            except (TypeError, ValueError):
                continue
            migrations.append({'policy':'redtiger-depth-to-recurring-actions/v1',
                'previous_id':key, 'previous':copy.deepcopy(prior),
                'replacement_id':replacement['id'], 'replacement_source':source,
                'required_samples':target, 'evidence':copy.deepcopy(marker)})
            del pending[key]


def _archive_classified_selector_replacements(pending, result, migrations, source):
    """Resolve previously unknown selectors only with current same-quote execution."""
    if result.provider != 'nolimit_city':return
    for mode in result.discovered_modes:
        if (mode.get('kind') not in ('PURCHASE','FEATURE_SPIN') or mode.get('validated') is not True
                or mode.get('observed') is not True or mode.get('evidence_level')!='REMOTE_EXECUTION'
                or mode.get('monetary_contract')!='nolimit-city/round-ledger/v1'):continue
        if any(set(d.get('options',[]))-set(d.get('covered',[])) for d in mode.get('choice_domains',[])):continue
        for key,prior in list(pending.items()):
            if (prior.get('kind')!='UNKNOWN_FEATURE' or any(prior.get(field)!=mode.get(field)
                    for field in ('selector','server_type','stake','price_multiplier'))
                    or not mode.get('selector') or set(prior.get('required_options',[]))!={mode['selector']}):continue
            target=max(1,int(prior.get('required_samples') or 1),int(mode.get('required_samples') or 1))
            if int(mode.get('sample_counts',{}).get(mode['selector'],0))<target:continue
            migrations.append({'policy':'nolimit-unknown-selector-to-verified-kind/v1','previous_id':key,
                'previous':copy.deepcopy(prior),'replacement_id':mode['id'],'replacement_source':source,
                'required_samples':target})
            del pending[key]


def retain_pending_branches(directory, result):
    if directory is None:
        return
    root = Path(directory)
    path = root / 'coverage-history.json'

    def absorb(pending, modes, source):
        for mode in modes:
            if not isinstance(mode, dict) or mode.get('coverage_required') is not True:
                continue
            key = str(mode.get('id') or '')
            if not key:
                continue
            prior = pending.get(key, {})
            required = {str(x) for x in mode.get('required_options', [])}
            covered = {str(x) for x in mode.get('covered_options', [])}
            old = set(prior.get('required_options', []))
            if required and 'DOMAIN_UNRESOLVED' not in required:
                old.discard('DOMAIN_UNRESOLVED')
            target = max(1, int(prior.get('required_samples') or 1), int(mode.get('required_samples') or 1))
            counts = mode.get('sample_counts')
            missing = (old | required) - covered
            if isinstance(counts, dict):
                missing |= {option for option in old | required if int(counts.get(option, 0)) < target}
            elif target > 1:
                missing |= old | required
            if not missing:
                pending.pop(key, None)
                continue
            item = copy.deepcopy(mode)
            item.update(required_options=sorted(missing), covered_options=[],
                        required_samples=target,
                        historical_source=prior.get('historical_source') or source)
            pending[key] = item

    with _history_lock(root):
        pending = {}
        migrations = []
        if path.exists():
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved.get('provider') != result.provider or saved.get('slug') != result.slug:
                # A stale directory must not turn an otherwise valid game run into
                # an ERROR. Preserve the foreign history for inspection and start a
                # fresh history for this game.
                suffix = 1
                archived = root / f"coverage-history.foreign-{suffix}.json"
                while archived.exists():
                    suffix += 1
                    archived = root / f"coverage-history.foreign-{suffix}.json"
                path.replace(archived)
            else:
                pending = saved.get('pending', {})
                migrations = saved.get('policy_migrations', [])
        else:
            # One-time migration; never mistake other games or arbitrary JSON for history.
            files = sorted((root/'tests').glob('*/result.json'), key=lambda p:p.stat().st_mtime_ns)
            for previous in files:
                if result.run_dir and previous.parent.resolve() == Path(result.run_dir).resolve():
                    continue
                try:
                    record = json.loads(previous.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if record.get('provider') == result.provider and record.get('slug') == result.slug:
                    absorb(pending, record.get('discovered_modes', []), str(previous))
        _archive_classified_selector_replacements(pending, result, migrations, result.run_dir)
        _archive_structural_replacements(pending, result.discovered_modes, migrations, result.run_dir)
        if result.provider == 'pragmatic':
            from tester_spin.providers.pragmatic_history_migration import archive_normalized_menus
            archive_normalized_menus(root, result, pending, migrations)
        if result.provider == 'redtiger':
            _archive_recurring_choice_replacements(pending, result.discovered_modes, migrations, result.run_dir)
        if result.provider == 'yggdrasil':
            from tester_spin.providers.yggdrasil.discounted_purchase import archive_price_variants
            archive_price_variants(result, pending, migrations, result.run_dir)
        absorb(pending, result.discovered_modes, result.run_dir)
        current = {str(m.get('id')):m for m in result.discovered_modes if isinstance(m, dict)}
        for key, item in pending.items():
            if key in current:
                mode = current[key]
                # Current evidence can explicitly exclude a mode from required coverage.
                # Preserve prior history for inspection without overriding that decision.
                if mode.get('coverage_required') is False:
                    continue
                mode['coverage_required'] = True
                mode.setdefault('branch_signature', item.get('branch_signature', key))
                mode['required_samples'] = max(int(mode.get('required_samples') or 1), int(item.get('required_samples') or 1))
                mode['required_options'] = sorted(set(map(str, mode.get('required_options', []))) | set(item['required_options']))
                mode['historical_source'] = item['historical_source']
            else:
                inherited = copy.deepcopy(item)
                inherited.update(observed=False, historical_pending=True)
                inherited['reason'] = 'Pendiente de una corrida anterior; no se volvió a demostrar su cobertura.'
                result.discovered_modes.append(inherited)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    prefix='.coverage-history-', suffix='.tmp', dir=root, delete=False) as output:
                temporary = Path(output.name)
                json.dump({'schema':'tester-spin/coverage-history/v1',
                    'provider':result.provider,'slug':result.slug,'pending':pending,
                    'policy_migrations':migrations}, output, ensure_ascii=False, indent=2)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
