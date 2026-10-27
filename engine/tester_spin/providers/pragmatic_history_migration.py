"""Archive obsolete ordinal obligations only after evidence-based normalization."""
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace


def archive_normalized_menus(root, result, pending, migrations):
    from .pragmatic_bonus_coverage import _canonical_selection, _read
    from .pragmatic_observed_transitions import bonus_choice
    from .pragmatic_preparation_coverage import selection_artifacts
    policies = {'parameterized-menu-actions/v1', 'repeatable-menu-actions/v1', 'hidden-position-structural/v1'}
    current = [m for m in result.discovered_modes if isinstance(m, dict)
               and m.get('coverage_origin') == 'pragmatic_bonus_selection_artifacts'
               and m.get('coverage_policy') in policies and m.get('observed') is True
               and m.get('coverage_required') is True]
    cache = {}
    for key, prior in list(pending.items()):
        if (prior.get('coverage_origin') != 'pragmatic_bonus_selection_artifacts'
                or prior.get('coverage_policy') != 'ordinal-options/v1'):
            continue
        source = Path(prior.get('historical_source') or '')
        if source.name == 'result.json':
            source = source.parent
        try:
            source.resolve().relative_to((Path(root) / 'tests').resolve())
        except ValueError:
            continue
        if source not in cache:
            saved = _read(source / 'result.json')
            evidence = []
            if saved.get('provider') == result.provider and saved.get('slug') == result.slug:
                old_result = SimpleNamespace(symbol=saved.get('symbol', ''))
                for attempt in saved.get('attempts', []):
                    if not isinstance(attempt, dict):
                        continue
                    obj = SimpleNamespace(artifact_dir=attempt.get('artifact_dir'),
                        mode_id=attempt.get('mode_id'),symbol=attempt.get('symbol', ''))
                    for path, origin, phase in selection_artifacts(obj, old_result,
                            'step-*.bonus-selection.json', recursive_attempt=True):
                        raw = _read(path)
                        step = re.match(r'step-([0-9]+)-', path.name)
                        preceding = (list(path.parent.glob(f'step-{int(step[1])-1:03d}-*.response.json'))
                                     if step and int(step[1]) > 0 else [])
                        if len(preceding) != 1:
                            continue
                        try:
                            legacy = bonus_choice(_read(preceding[0]), override=raw.get('selected'))
                        except ValueError:
                            continue
                        normalized = _canonical_selection(path, raw)
                        range_pick = (normalized.get('coverage_policy')=='hidden-position-structural/v1'
                            and re.fullmatch(r'PRAGMATIC:bonus-pick:bgt=69:size=[1-9][0-9]*:level=[0-9]+',
                                             normalized.get('coverage_branch_signature',''))
                            and str(raw.get('branch_signature','')).startswith('PRAGMATIC:range-pick:bgt=69:'))
                        identity = normalized if range_pick else legacy
                        if (not identity or identity.get('branch_signature') != raw.get('branch_signature')
                                or identity.get('domain') != raw.get('domain')):
                            continue
                        if normalized.get('coverage_policy')=='hidden-position-structural/v1' and not range_pick:
                            continue
                        if normalized.get('coverage_policy') in policies:
                            evidence.append((path, origin, raw, normalized))
            cache[source] = evidence
        for path, origin, raw, normalized in cache[source]:
            if (origin != prior.get('origin_mode_id')
                    or raw.get('branch_signature') != prior.get('contract_branch_signature')
                    or raw.get('contract_sha256') != prior.get('contract_sha256')):
                continue
            required = set(map(str, prior.get('required_options', [])))
            mapping = ( {v:'0' for v in normalized.get('domain', [])}
                if normalized.get('coverage_policy')=='hidden-position-structural/v1'
                else normalized.get('coverage_domain_map') or {v:v for v in normalized.get('domain', [])})
            if not required or not required <= set(mapping):
                continue
            classes = {mapping[v] for v in required}
            replacement = next((m for m in current
                if m.get('origin_mode_id') == origin
                and m.get('coverage_policy') == normalized.get('coverage_policy')
                and m.get('contract_branch_signature') == normalized.get('coverage_branch_signature', normalized.get('branch_signature'))
                and m.get('contract_sha256') == normalized.get('contract_sha256')), None)
            if replacement is None:
                continue
            try:
                target = max(1, int(prior.get('required_samples') or 1), int(replacement.get('required_samples') or 1))
                counts = replacement.get('sample_counts', {})
                sufficient = classes <= set(replacement.get('covered_options', [])) and all(int(counts.get(v, 0)) >= target for v in classes)
            except (ValueError, TypeError):
                continue
            if not sufficient:
                continue
            migrations.append({'policy':'pragmatic-ordinal-to-normalized-menu/v1',
                'previous_id':key,'previous':copy.deepcopy(prior),
                'replacement_id':replacement['id'],'replacement_source':result.run_dir,
                'required_samples':target,'normalized_classes':sorted(classes),
                'legacy_artifact':str(path),'normalization_evidence':copy.deepcopy(normalized)})
            del pending[key]
            break
