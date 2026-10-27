"""Shared paid-option declarations. Reuse parsers, never another game's OK."""
from collections import Counter
import hashlib
import json
from pathlib import Path

SCHEMA = 'tester-spin/paid-options/v1'


def write_paid_option_inventory(result, *, primitive, source, options, complete,
                               evidence_files=(), unresolved=()):
    issues = list(unresolved)
    root = Path(result.run_dir).resolve() if result.run_dir else None
    proofs = []
    for filename in evidence_files:
        try:
            if root is None:
                raise ValueError('RUN_DIRECTORY_MISSING')
            file = (root / filename).resolve()
            relative = file.relative_to(root).as_posix()
            proofs.append({'path':relative, 'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        except (OSError, ValueError, TypeError):
            issues.append('PAID_INVENTORY_EVIDENCE_UNAVAILABLE')
    if not proofs:
        issues.append('PAID_INVENTORY_EVIDENCE_MISSING')
    known = complete is True and not issues
    declaration = {
        'schema':SCHEMA, 'provider':result.provider, 'game':result.slug,
        'symbol':result.symbol, 'primitive':primitive, 'source':source,
        'complete':known, 'state':'DECLARED' if known else 'UNKNOWN',
        'options':options, 'count':len(options) if known else None,
        'counts_by_category':dict(Counter(o.get('category','unknown') for o in options)) if known else None,
        'unresolved':list(dict.fromkeys(issues)), 'evidence':proofs,
    }
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        (root/'paid-option-inventory.json').write_text(json.dumps(declaration,ensure_ascii=False,indent=2),encoding='utf-8')
    result.structural_map['paid_option_inventory'] = dict(declaration,evidence_files=['paid-option-inventory.json'] if root else [])
    return result.structural_map['paid_option_inventory']


def ensure_paid_option_declaration(result):
    """Unsupported primitives declare unknown, including unverified zero."""
    if 'paid_option_inventory' not in result.structural_map:
        from tester_spin.providers.paid_declarations import declare_adapter_paid_options
        if declare_adapter_paid_options(result):
            return
        write_paid_option_inventory(result,primitive={'id':'unresolved','version':1},
            source='provider_primitive_unavailable',options=[],complete=False,
            unresolved=['PAID_OPTION_DECLARATION_NOT_IMPLEMENTED'])
