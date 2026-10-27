"""Read active public UI input calls; no game names or bundle allowlists."""
import re

_ID = r'[A-Za-z_$][\w$]*'



def _numeric_map(selector, prefix):
    match = re.fullmatch('(' + _ID + r')\[' + _ID + r'\]', selector)
    if not match:
        return None
    variable = match[1]
    alias = re.search(re.escape(variable) + '=('+_ID+r'),$', prefix)
    if alias:
        target = alias[1]
        calls = re.search(r'(' + _ID + r')\(' + re.escape(target) + r'=\{\},' + _ID + r'(?:\.'+_ID+r')?,[0-9]+\)((?:,\1\('+re.escape(target)+','+_ID+r'(?:\.'+_ID+r')?,[0-9]+\))*)$' , prefix[:alias.start()].rstrip(','))
        return [int(v) for v in re.findall(r',([0-9]+)\)', calls[0])] if calls else None
    assignment = re.search(re.escape(variable) + r'=([^;]{1,300}),$', prefix)
    if not assignment:
        return None
    expression = assignment[1]
    values = []
    while expression != '{}':
        call = re.search(_ID + r'\(\{\},'+_ID+r'(?:\.'+_ID+r')?,([0-9]+)\)', expression)
        if not call:
            return None
        values.append(int(call[1]))
        expression = expression[:call.start()] + '{}' + expression[call.end():]
    return values


def _selector_policy(source, selector, prefix, data):
    if re.fullmatch(r'(?:' + _ID + r'|\(' + _ID + r'\+1\))\.toString\(\)', selector):
        return 'string', None
    if re.fullmatch(_ID + r'\+1', selector):
        variable = selector[:-2]
        guard = re.search(r'if\(\[([0-9]+(?:,[0-9]+)*)\]\.includes\(' + re.escape(variable) + r'\)&&', prefix)
        if guard:
            from .code_primitives import block
            opening = prefix.find('{', guard.end())
            if opening >= 0 and block(prefix, opening) is None:
                return 'number', [int(value)+1 for value in guard[1].split(',')]
        return 'number', None
    domain = _numeric_map(selector, prefix)
    if domain is not None:
        return 'number', domain
    if re.fullmatch(_ID, selector):
        condition = re.search(re.escape(selector) + '=' + _ID + r'\.serverData\.get\("version"\)\?Number\((' + _ID + r')\):String\(\1\);$', prefix)
        mapping = re.search(r'\.set\("version",(?P<wrapper>\()?function\((?P<data>'+_ID+r')\)\{var (?P<temporary>'+_ID+r');return null!==\((?P=temporary)=(?P=data)\.settings\.version\)&&void 0!==(?P=temporary)\?(?P=temporary):null\}(?(wrapper)\))\)', source)
        if condition and mapping:
            version = (data or {}).get('settings', {}).get('version')
            return ('number' if version else 'string'), None
    return None, None

def source_purchase_contract(source, data=None):
    from .code_primitives import canonical_source, flow_parameters, empty_flow_actions, event_spin_parameters, flow_purchase_inputs
    source = canonical_source(source)
    flow_spin = flow_parameters(source, 'SPIN')
    event_spin = event_spin_parameters(source)
    flow_purchase = flow_purchase_inputs(source, data)
    context = (data or {}).get('context', {})
    available = context.get('available_buy_bonus', [])
    if not isinstance(available, list):
        available = []
    available = [v for v in available if isinstance(v, (int, str)) and not isinstance(v, bool)]
    modern_bridge = re.search(r'sendPlayAsync:function\((' + _ID + r'),(' + _ID + r')\)\{return[^{};]{1,100}\.bus\.play\(\1,\2\)\}', source)
    modern_buy = bool(modern_bridge and re.search(r'\.bus\.sendPlayAsync\(\{name:"buy_spin",params:\{', source))
    legacy_buy = bool('BUY_SPIN:"buy_spin"' in source and re.search(r'function actBuyFeature\([^)]*\)\{[^{}]{0,500}\{\}[^{}]{0,1300}\.controllers\.flow\.act\([^,]+\.BUY_SPIN,params\)', source))
    if not modern_bridge and not legacy_buy and not flow_spin and not event_spin and not flow_purchase:
        return None
    profile = {'purchase_modes': [], 'purchase_params': {}, 'purchase_ui_observed': bool(modern_buy or legacy_buy or flow_purchase),
               'continuations': {}, 'evidence': 'Active UI emits buy_spin through the client play bridge',
               'contract_source': 'current-client-input-calls'}
    if flow_spin or event_spin:
        profile['spin_params'] = event_spin or flow_spin
        if event_spin:
            profile['spin_value_sources'] = {'lines':'settings_lines_first'}
        profile['continuations'] = empty_flow_actions(source)
    calls = re.finditer(r'\.sendPlayAsync\(\{name:"(spin|buy_spin)",params:\{([^{}]{1,500})\}\},', source)
    signatures = {}
    prefixes = {}
    selectors = []
    for call in calls:
        action, body = call.groups()
        prefixes.setdefault(action, []).append(re.sub(_ID + r'\.bus$', '', source[max(0, call.start()-450):call.start()]))
        match = re.fullmatch(r'bet_per_line:' + _ID + r'\.bus\.getUI\("bet_per_line"\),lines:' + _ID + r'\.(?:bus\.getUI\("lines"\)|serverData\.get\("settingsLines"\)\[(?:0|' + _ID + r'\.bus\.setUI\("lines",' + _ID + r'\.value\))\])(?:,selected_mode:(.+))?', body)
        if match:
            signatures.setdefault(action, set()).add(match.group(1) or '')
            if action == 'buy_spin':
                selectors.append((match.group(1) or '', prefixes[action][-1]))
        else:
            signatures.setdefault(action, set()).add('UNSUPPORTED')
    if signatures.get('spin') == {''}:
        profile['spin_params'] = ['bet_per_line', 'lines']
    purchases = signatures.get('buy_spin', set())
    params = ['bet_per_line', 'lines']
    if purchases == {''} and len(available) == 1:
        profile['purchase_modes'] = available
    elif purchases and 'UNSUPPORTED' not in purchases:
        policies = [_selector_policy(source, selector, prefix, data) for selector, prefix in selectors]
        known = [policy for policy in policies if policy[0]]
        unresolved = len(known) != len(policies)
        # An unresolved alternative cannot invalidate a separately proven finite route,
        # nor can it extend that route to other server-advertised selectors.
        profile['purchase_input_routes'] = [{'selector':selector, 'type':policy[0], 'domain':policy[1]}
                                           for (selector, _), policy in zip(selectors, policies)]
        if unresolved and known and all(policy[1] is not None for policy in known):
            policies = known
        if policies and all(policy[0] and policy[0] == policies[0][0] for policy in policies):
            selector_type = policies[0][0]
            domain = None if any(policy[1] is None for policy in policies) else set(value for _, values in policies for value in values)
            if selector_type:
                profile['purchase_selector_type'] = selector_type
                profile['purchase_modes'] = [mode for mode in available if domain is None or mode in domain]
                if domain is not None:
                    profile['purchase_ui_modes'] = list(profile['purchase_modes'])
                params.append('selected_mode')
    profile['purchase_params'] = {str(mode): list(params) for mode in profile['purchase_modes']}
    if modern_bridge:
        paid_calls = list(re.finditer(r'\.sendPlayAsync\(\{name:"buy_spin",params:\{bet_per_line:'+_ID+r'\.bus\.getUI\("bet_per_line"\),lines:'+_ID+r'\.bus\.getUI\("lines"\),paid_feature:\{([^{}]+)\}\[('+_ID+r')\]\}\},', source))
        if len(paid_calls) == 1:
            body = paid_calls[0][1]
            pairs = re.findall(r'([0-9]+):"([a-z_]+)"', body)
            if pairs and ','.join(k+':"'+v+'"' for k,v in pairs) == body and len({k for k,v in pairs}) == len(pairs):
                mapping = {k:{'paid_feature':v} for k,v in pairs}
                profile['purchase_modes'] = [v for v in available if str(v) in mapping]
                profile['purchase_params'] = {str(v):['bet_per_line','lines','paid_feature'] for v in profile['purchase_modes']}
                profile['purchase_wire_values'] = mapping
    if re.search(r'\.sendPlayAsync\(\{name:' + _ID + r'\.serverData\.get\("actions"\)\.last\(\),params:\{\}\},null\)', source):
        profile['continuations'] = {'bonus_init': {'current': 'spins'},
                                    'respin': {'current': 'bonus'},
                                    'bonus_spins_stop': {'current': 'bonus'},
                                    'freespin_init': {'current': 'spins'},
                                    'freespin': {'current': 'freespins'},
                                    'freespin_stop': {'current': 'freespins'}}
    if flow_purchase:
        profile.update(flow_purchase)
    return profile if profile.get('spin_params') or profile['purchase_ui_observed'] else None
