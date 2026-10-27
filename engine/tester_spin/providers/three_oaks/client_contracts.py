"""Client-backed input contracts, never inferred from game names or vendor labels."""
import hashlib
import json
import re
from pathlib import Path



def handler_fingerprint(source):
    """Bind HAR evidence to unchanged action handlers and the purchase UI caller."""
    if 'params:args||{}' not in source:
        return None
    handlers = []
    pattern = r'(?:setActionHandler\([^,{}]{1,100},function\([^)]{0,100}\)|function actBuyFeature\([^)]{0,100}\))\{'
    for match in re.finditer(pattern, source):
        start = match.end() - 1
        depth, index, quote = 1, start + 1, None
        while index < min(len(source), start + 4000) and depth:
            char = source[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
            elif char in "\"'`":
                quote = char
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
            index += 1
        if depth:
            return None
        handlers.append(source[match.start():index])
    if not handlers or not any('function actBuyFeature(' in h for h in handlers):
        return None
    from .runtime import source_continuation_rules
    content = {'handlers': handlers, 'continuations': source_continuation_rules(source)}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

def _client_contract(source, data=None):
    registry=json.loads(Path(__file__).with_name('observed_client_contracts.json').read_text(encoding='utf-8'))
    if registry.get('schema')!='three-oaks/observed-client-contracts/v1':
        raise ValueError('3 Oaks: invalid client contract schema')
    digest=hashlib.sha256(source.encode('utf-8')).hexdigest()
    contract=registry.get('clients',{}).get(digest)
    contract_source = 'accepted-official-client-har'
    if contract is None:
        signature = handler_fingerprint(source)
        matches = [value for value in registry.get('clients', {}).values()
                   if signature and value.get('handler_sha256') == signature]
        if matches:
            # Only identical input/continuation contracts can share a handler signature.
            unique = {json.dumps(value, sort_keys=True) for value in matches}
            if len(unique) == 1:
                contract = matches[0]
                contract_source = 'accepted-har-with-current-client-handlers'
    if contract is not None:
        if contract.get('spin_params')!=['bet_per_line','lines'] or not contract.get('evidence'):
            raise ValueError('3 Oaks: invalid observed client contract')
        return {**contract,'client_sha256':digest,'contract_source':contract_source}
    from .source_inputs import source_purchase_contract
    active = source_purchase_contract(source, data=data)
    if active and active.get('spin_params'):
        active['client_sha256'] = digest
        return active
    # Legacy public serializer: explicit assignments and the actual wire bridge.
    compact=re.sub(r'\s+','',source)
    match=re.search(r'setActionHandler\("spin",function\(args\)\{([^{}]*(?:\{\}[^{}]*)*)\}\)',compact)
    if match and 'params:args||{}' in compact:
        body=match[1]
        assigned=set(re.findall(r'args\.([a-z_]+)=',body))
        if (assigned=={'bet_per_line','lines'} and '._act("spin",args,' in body
                and 'args[' not in body and 'Object.assign' not in body):
            return {'spin_params':['bet_per_line','lines'],'purchase_modes':[],
                    'purchase_params':{},'continuations':{},'client_sha256':digest,
                    'evidence':'Active client spin handler sets bet_per_line/lines and transports args unchanged',
                    'contract_source':'current-client-serializer', **(active or {})}
    if active:
        return {**active, 'client_sha256': digest}
    return None


def client_contract(source, data=None, *, runner_source=None, init_source=None):
    profile = _client_contract(source, data=data)
    from .special_inputs import antebet_input_contract
    from .code_primitives import canonical_source, empty_flow_actions
    continuations = empty_flow_actions(canonical_source(source))
    if profile and continuations:
        profile['continuations'] = {**profile.get('continuations', {}), **continuations}
    ante = antebet_input_contract(source, data)
    if ante:
        profile = {**(profile or {}), **ante}
    if runner_source is not None and init_source is not None:
        from .code_primitives import runner_spin_contract
        runner = runner_spin_contract(runner_source, init_source)
        if runner:
            profile = {**(profile or {'purchase_modes':[], 'purchase_params':{}, 'continuations':{}}), **runner}
            profile['contract_source'] = 'current-client-and-shared-runner'
            profile['runner_sha256'] = hashlib.sha256(runner_source.encode()).hexdigest()
            profile['init_sha256'] = hashlib.sha256(init_source.encode()).hexdigest()
            from .code_primitives import canonical_source
            if (profile.get('antebet_ui_observed') and re.search(r'Object\.assign\(' + r'[A-Za-z_$][\w$]*' + r'\.action\.params,\{ante_bet:this\.model\.get\("ante_bet"\)\}\)', canonical_source(runner_source))):
                profile['antebet_executable'] = True
    return profile
