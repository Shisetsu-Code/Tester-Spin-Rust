"""Turn complete NGM client declarations into an auditable execution plan.

This grammar describes client protocols, never game names or captured outcomes.
Unrecognized features, prices, wire fields and registrations remain unknown.
"""
import hashlib
import json
import re
from .client_sources import _function_bodies
from .ngm_contracts import NAME, STRING, _constants

METADATA = {'ID', 'windowId', 'umid'}
REQUEST_FIELDS = {
    'SpinRequest': METADATA | {'bet', 'numCoins', 'lines', 'spinType'},
    'StartBonusGameRequest': METADATA,
    'SlotGameLoginRequest': METADATA | {'coinAge', 'gameShortName', 'gameTechnology', 'version', 'maxBet', 'maxPosBet', 'minBet', 'minPosBet'},
    'ReserveBrokenGamesRequest': METADATA | {'brokenGameString'},
    'BrokenGamesListRequest': METADATA,
    'ChatRequest': METADATA | {'chatMessage'},
    'JackpotUpdatesSubscribeRequest': METADATA,
    'SmartGameLimitsRequest': METADATA | {'gameShortName', 'lastUsedCoins'},
    'FreeSpinsBonusRequest': METADATA | {'fsbSpin'},
    'FreeSpinsBonusCoinsizeRequest': METADATA,
    'LogUserPreferencesRequest': METADATA | {'value', 'preferences'},
}
FEATURE_FIELDS = {
    'type', 'free', 'supported', 'auto-spin', 'single-game-feature', 'skip-outro',
    'keep-last-win', 'reels-set', 'reels-config', 'auto-start-more-spins',
    'show-total-win', 'include-game-win', 'symbol', 'spins-count', 'restore-reels',
    'retrigger', 'cumulative-win', 'more-spins-count', 'show-cp-buttons',
}
CONFIG_FIELDS = {
    'game_code','maxfps','reels.rotation.default','reels.rotation.turbo','side_buttons','btn_hold_delay',
    'promo_messages','animations','features','win_ranges.default','allow_debug','supported_orientation',
    'server_type','show_paytable_as_scene','combined_symbols_supported','turbo_mode_supported','fixed_lines',
    'hide_animated_symbols','free_spins_bonus_supported','engine','coin_sizes','win_ranges','display_height',
    'display_width','enlargement_sounds','lines','symbols_list','stack_symbols_sequences','symbols',
    'reels.rotation','sound','symbols.wildId','symbols.bandit','symbols.sheriff','wild.shift.delta',
    'symbol_animations','paytable','reels','fs_sequences_weights','wild_state_to_reel_weights',
    'coins_per_line','max_coins_per_line','selected_lines','auto_adjust_lines','total_bet_multiplier',
    'anticipation','base_reel_width','demo_max_win','fg_fake_symbol_ids','locked_reels_ids',
    'jackpot_supported','supported_help_brands','symbols.scatterId',
}
FEATURE_KINDS = {'regular': ('reels-spin', 'SPIN'), 'autoplay': ('reels-spin', 'BASE_AUTOPLAY'),
                 'free-spins': ('free-spins', 'NATURAL_BONUS'), 'fsb': ('reels-spin', 'PROMOTIONAL_SPINS')}


def _feature_loader(functions, source):
    matches = []
    constants = _constants(source)
    for name, (args, body) in functions.items():
        if len(args) != 2:
            continue
        read = re.search(r'('+NAME+r')='+re.escape(args[0])+r'\.'+NAME+r'\.'+NAME+r'\(('+STRING+'|'+NAME+r')\)', body)
        target = re.search(re.escape(args[1])+r'\.('+NAME+r')=('+NAME+r')$', body)
        if not read or not target:
            continue
        if read[2] not in ("'features'", '"features"') and constants.get(read[2]) != {'features'}:
            continue
        rows, table = read[1], target[2]
        loop = re.search(r'for\(('+NAME+r')='+re.escape(rows)+r'\.'+NAME+r'\(\)\.'+NAME+r'\(\);\1\.'+NAME+r'\(\);\)\{('+NAME+r')=\1\.'+NAME+r'\(\);', body)
        if not loop or not re.search(re.escape(rows)+r'\.'+NAME+r'\('+re.escape(loop[2])+r'\)', body):
            continue
        if not re.search(NAME+r'\('+re.escape(table)+r'\.'+NAME+r','+re.escape(loop[2])+','+NAME+r'\)', body):
            continue
        matches.append(dict(function=name, table_field=target[1], authority='configured-feature-map'))
    return matches[0] if len(matches) == 1 else None


def _registered_handlers(source, functions):
    """Bind registrations to the same map read by the offline dispatcher."""
    dispatch = []
    for name, (args, body) in functions.items():
        if len(args) != 2:
            continue
        match = re.search(r'('+NAME+r')=('+NAME+r')\('+re.escape(args[0])+r'\.('+NAME+r'),'+re.escape(args[1])+r'\.'+NAME+r'\);if\(!\1\)return '+NAME+r';', body)
        if match:
            dispatch.append((name, match[2], match[3]))
    if len(dispatch) != 1:
        return None
    dispatcher, lookup, field = dispatch[0]
    setters = []
    for name, (args, body) in functions.items():
        if len(args) == 3 and re.search(re.escape(lookup)+r'\('+re.escape(args[0])+r'\.'+re.escape(field)+','+re.escape(args[1])+r'\)', body):
            if re.search(NAME+r'\('+re.escape(args[0])+r'\.'+re.escape(field)+','+re.escape(args[1])+','+NAME+r'\)', body) and re.search(r'\.'+NAME+r'\('+re.escape(args[2])+r'\)$', body):
                setters.append(name)
    if len(setters) != 1:
        return None
    setter = setters[0]
    # Count every call, rejecting dynamic class expressions rather than dropping them.
    calls = list(re.finditer(r'(?<![\w$])'+re.escape(setter)+r'\(', source))
    flat = list(re.finditer(r'(?<![\w$])'+re.escape(setter)+r'\(('+NAME+r'),('+NAME+r'),', source))
    # One occurrence is the setter declaration itself; its formal args are not registrations.
    registrations = [m for m in flat if not source[max(0,m.start()-9):m.start()].endswith('function ')]
    if len(calls) != len(registrations)+1 or not registrations:
        return None
    descriptors = {}
    for m in re.finditer(r'var ('+NAME+r')='+NAME+r"\([^;()]*['\"]([^'\"]+)['\"],(?:\d+|null),[^;()]*\)", source):
        descriptors.setdefault(m[1], set()).add(m[2])
    names = []
    for m in registrations:
        candidates = descriptors.get(m[2], set())
        if len(candidates) != 1:
            return None
        names.append(next(iter(candidates)))
    return dict(dispatcher=dispatcher, registration=setter, names=sorted(set(names)))



def _call_arguments(body, start):
    """Bounded lexical split only; never evaluates captured expressions."""
    values, begin, depth, quote, escaped = [], start, 0, None, False
    for index in range(start, min(len(body), start+8192)):
        char = body[index]
        if quote:
            if escaped: escaped = False
            elif char == chr(92): escaped = True
            elif char == quote: quote = None
            continue
        if char in ("'", '"'): quote = char
        elif char in '([{': depth += 1
        elif char in ')]}':
            if char == ')' and depth == 0:
                return values+[body[begin:index]]
            depth -= 1
        elif char == ',' and depth == 0:
            values.append(body[begin:index]); begin = index+1
    return None


def _enum_fields(functions, constructor):
    seen = set()
    while constructor not in seen and len(seen) < 4:
        seen.add(constructor)
        args, body = functions.get(constructor, ([], ''))
        if len(args) != 2:
            return None
        parent = re.fullmatch(r'('+NAME+r')\.call\(this,'+re.escape(args[0])+','+re.escape(args[1])+r'\)', body)
        if parent:
            constructor = parent[1]
            continue
        assignments = list(re.finditer(r'this\.('+NAME+r')=('+NAME+r')(?:;|$)', body))
        if len(assignments) != 2 or len({m[1] for m in assignments}) != 2 or ''.join(m[0] for m in assignments) != body:
            return None
        fields = {m[2]:m[1] for m in assignments}
        return [fields.get(arg) for arg in args] if set(fields) == set(args) else None
    return None


def _spin_values(source, functions, schemas):
    spin = [r for r in schemas if r['name'] == 'SpinRequest']
    if len(spin) != 1 or not {'bet','numCoins','spinType'} <= set(spin[0]['fields']):
        return None
    constructor, field = spin[0]['constructor'], spin[0]['fields']['spinType']
    senders = []
    for name, (args, body) in functions.items():
        create = re.search(r'('+NAME+r')=new '+re.escape(constructor)+r'(?:\(\))?(?![\w$])', body)
        if create:
            if body[:create.start()] != 'var '+create[1]+';':
                return None
            model = re.escape(create[1])
            selector = model+r'\.'+re.escape(field)
            assignment = re.findall(selector+r'=('+NAME+r');', body)
            # Reject extra dot/bracket writes, even when their RHS is not a name.
            if len(assignment) != 1 or assignment[0] not in args or len(re.findall(selector+r'(?![\w$])', body)) != 1:
                return None
            if re.search(model+r'\[', body):
                return None
            # The sender may initialize fields from arguments/null, then submit.
            # Any additional expression touching the selector is unbound.
            before_send = body[create.end():]
            prefix = before_send.split('try{', 1)[0] if 'try{' in before_send else before_send.rsplit(';', 1)[0]+';'
            assignments = re.findall(model+r'\.'+NAME+r'=(?:'+NAME+r'|null);', prefix)
            if prefix != ';'+''.join(assignments):
                return None
            initializations = re.findall(model+r'\.('+NAME+r')=('+NAME+r'|null);', prefix)
            if len({field for field, _ in initializations}) != len(initializations):
                return None
            if any(key not in set(spin[0]['fields'].values()) or value not in set(args)|{'null'} for key, value in initializations):
                return None
            tail = before_send[len(prefix):]
            submit = NAME+r'\('+re.escape(args[0])+r'(?:\.'+NAME+r')*,'+model+r'\)'
            caught = r'catch\(('+NAME+r')\)\{\1='+NAME+r'\(\1\);if\(!'+NAME+r'\(\1,\d+\)\)throw '+NAME+r'\(\1\)\}'
            if not (re.fullmatch(submit, tail) or re.fullmatch(r'try\{'+submit+r'\}'+caught, tail)):
                return None
            senders.append((name, args.index(assignment[0])))
    if len(senders) != 1:
        return None
    sender, position = senders[0]
    calls = []
    for name, (_, body) in functions.items():
        for match in re.finditer(r'(?<![\w$])'+re.escape(sender)+r'\(', body):
            args = _call_arguments(body, match.end())
            if args is None or len(args) <= position:
                return None
            calls.append((name, args[position]))
    if len(calls) != 1 or len(re.findall(r'(?<![\w$])'+re.escape(sender)+r'\(', source)) != 2:
        return None
    owner, phase = calls[0]
    literal = re.fullmatch(r"['\"](regular|free|re)['\"]", phase)
    if literal:
        return dict(sender=sender, caller=owner, values=[literal[1]])
    selections = list(re.finditer(r'('+NAME+r')=\(('+NAME+r')\(\),('+NAME+r')\)', phase))
    if len(selections) != 3 or len({(m[1], m[2]) for m in selections}) != 1 or '.toLowerCase()' not in phase:
        return None
    variable, initializer = selections[0][1], selections[0][2]
    v, init = re.escape(variable), re.escape(initializer)
    members = [re.escape(m[3]) for m in selections]
    condition = NAME+r'\('+NAME+r'\('+NAME+r'(?:\.'+NAME+r')*,null\)\.'+NAME+r','+NAME+r'\)'
    respin = NAME+r'\('+NAME+r'(?:\.'+NAME+r')*,[\"\']re-spin[\"\']\)'
    branch = lambda member: r'\('+v+r'=\('+init+r'\(\),'+member+r'\)\)'
    projection = r'\('+v+r'\.('+NAME+r')!=null\?'+v+r'\.\1:[\"\'][\"\']\+'+v+r'\.('+NAME+r')\)\.toLowerCase\(\)'
    projected = re.fullmatch(r'\('+condition+r'\?'+branch(members[0])+':'+respin+r'\?'+branch(members[1])+':'+branch(members[2])+','+projection+r'\)', phase)
    if not projected:
        return None
    if len(re.findall(r'(?<![\w$.])'+re.escape(variable)+r'=(?![=])', phase)) != len(selections):
        return None
    enum_body = functions.get(initializer, ([], ''))[1]
    definitions = list(re.finditer(r'('+NAME+r')=new ('+NAME+r')'+r"\(['\"](REGULAR|FREE|RE)['\"],\d+\)", enum_body))
    if len({m[2] for m in definitions}) != 1:
        return None
    fields = _enum_fields(functions, definitions[0][2]) if definitions else None
    if fields is None or fields != list(projected.groups()):
        return None
    declared = {m[1]:m[3].lower() for m in definitions}
    for member in declared:
        if len(re.findall(r'(?<![\w$.])'+re.escape(member)+r'=(?![=])', source)) != 1:
            return None
        if re.search(r'(?<![\w$])'+re.escape(member)+r'(?:\.'+NAME+r'|\[[^;]{1,64}\])\s*(?:[+*/-]?=(?!=)|\+\+|--)', source):
            return None
    selected = {m[3] for m in selections}
    if len(declared) != 3 or selected != set(declared):
        return None
    return dict(sender=sender, caller=owner, values=sorted(declared.values()))


def _economic_declarations(value, path='$'):
    if isinstance(value, dict):
        if value.get('supported') is False:
            return
        for key, child in value.items():
            here = path+'/'+str(key)
            fixed_base_factor = key == 'total_bet_multiplier' and type(child) in (int, float) and child > 0
            if not fixed_base_factor and re.search(r'buy|ante|cost|price|purchase|extra.?bet|feature.?bet|bet.?option|bet.?mode|bet.?type|bet.?multiplier|stake', str(key), re.I):
                yield here
            yield from _economic_declarations(child, here)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _economic_declarations(child, path+'/'+str(i))


def _unbound_controls(manifest, source):
    known = {'scrollbar.knob_button','button.yes','button.no','fsb.info.btn','fsb.btn','fsb.close.btn',
        'btn.close','info.btn','coin_size.minus','coin_size.plus','btn','autoplay.btn','auto_play_stop.btn',
        'turbo.on','turbo.off','buttons.container','spin','start','stop','lines.minus','lines.plus','btn.continue','paytable.prev','paytable.next','paytable.back'}
    templates = {'/ui/debug.btn','/ui/cursor_btn','/ui/play_btn','/ui/imgBtn','/ui/msg.btn'}
    attributes = {'ref','template_refs','@P','@S','@O','id','type','cursor','props','layout','text','label','border','ratio','shortcut','group','propagative','enabled','visible'}
    for control in manifest.get('controls', []):
        ref, identity = control.get('ref', ''), control.get('id')
        if identity is not None and not isinstance(identity, str):
            yield ref; continue
        if set(control)-attributes or any(key in control for key in ('action','command','choices','options')):
            yield ref; continue
        if identity in {'yesButton','noButton','okButton'}:
            # These reviewed configuration confirmations are attached by the
            # official view's event binder, not inferred from their images.
            if not re.search(NAME+r'\('+NAME+r'\('+NAME+r'(?:\.'+NAME+r')*,[\"\']'+re.escape(identity)+r'[\"\'],0\),'+NAME+r',', source):
                yield ref
        elif identity in known:
            continue
        elif ref in templates or ref.startswith('/scenes/interp-select-scene/'):
            continue
        else:
            yield ref


def build_execution_plan(report, source):
    manifest = report.get('manifest') or {}
    config = manifest.get('configuration') or {}
    issues = list(report.get('unresolved', []))
    functions = _function_bodies(source)
    loader = _feature_loader(functions, source)
    registry = _registered_handlers(source, functions)
    if not loader:
        issues.append('NGM_FEATURE_MAP_AUTHORITY_UNBOUND')
    if not registry:
        issues.append('NGM_HANDLER_REGISTRY_UNBOUND')
    if manifest.get('unresolved_templates'):
        issues.append('NGM_CONTROL_TEMPLATE_UNBOUND')
    features, planned = config.get('features'), []
    math_fields = set()
    def weighted(value):
        if not isinstance(value, list) or not value:
            return False
        return all(isinstance(row, dict) and (type(row.get('weight')) in (int,float) and row['weight']>=0
            or weighted(row.get('weights'))) for row in value)
    for key, value in config.items():
        if key.endswith(('_weight','_weights')) and weighted(value):
            math_fields.add(key)
        if key=='cheats' and config.get('allow_debug') in (False,'false') and isinstance(value,dict) and all(isinstance(v,str) for v in value.values()):
            math_fields.add(key)
    issues.extend('NGM_CONFIG_FIELD_UNBOUND:'+str(key) for key in set(config)-CONFIG_FIELDS-math_fields)
    schemas = report.get('requests') or []
    from .ngm_structured import structured_spin_contract
    structured = structured_spin_contract(source)
    spin_values = _spin_values(source, functions, schemas)
    if structured:
        classic_active = False
        for row in schemas:
            if row.get('name')!='SpinRequest':continue
            money={row.get('fields',{}).get(key) for key in ('bet','numCoins')}-{None}
            setters={name for name,(args,body) in functions.items() if args and any(re.search(re.escape(args[0])+r'\.'+re.escape(field)+r'(?![\w$])',body) for field in money)}
            for producer,(_,body) in functions.items():
                for create in re.finditer(r'('+NAME+r')=new '+re.escape(row['constructor'])+r'(?![\w$])',body):
                    model=re.escape(create[1])
                    selector=row.get('fields',{}).get('spinType')
                    safe_setters={name for name,(args,code) in functions.items() if len(args)==2 and selector and code==args[0]+'.'+selector+'='+args[1]}
                    safe_calls=sum(len(re.findall(re.escape(name)+r'\('+model+r',',body)) for name in safe_setters)
                    returns=len(re.findall(r'\breturn '+model+r'(?![\w$])',body))
                    uses=len(re.findall(r'(?<![\w$.])'+model+r'(?![\w$])',body))
                    if uses!=2+safe_calls+returns:classic_active=True
                    if returns:
                        for consumer,(_,consumer_body) in functions.items():
                            for call in re.finditer(r'(?<![\w$])'+re.escape(producer)+r'\(',consumer_body):
                                params=_call_arguments(consumer_body,call.end())
                                if params is None:
                                    classic_active=True;continue
                                end=call.end();depth=1
                                while end<len(consumer_body) and depth:
                                    if consumer_body[end]=='(':depth+=1
                                    elif consumer_body[end]==')':depth-=1
                                    end+=1
                                stack=[]
                                for pos,char in enumerate(consumer_body[:call.start()]):
                                    if char=='(':stack.append(pos)
                                    elif char==')' and stack:stack.pop()
                                opening=stack[-1] if stack else -1
                                # A non-final comma expression discards the returned object.
                                if (opening<0 or (opening and re.match(r'[\w$)\]]',consumer_body[opening-1]))
                                    or '=' not in consumer_body[opening+1:call.start()]
                                    or consumer_body[call.start()-1:call.start()]!=',' or consumer_body[end:end+1]!=','):
                                    classic_active=True
                    if (re.search(model+r'\[',body) or any(re.search(model+r'\.'+re.escape(field)+r'(?![\w$])',body) for field in money)
                        or any(re.search(re.escape(setter)+r'\('+model+r'[,)]',body) for setter in setters)):
                        classic_active=True

        if classic_active:
            issues.append('NGM_MULTIPLE_ENTRY_DOMAINS_UNBOUND')
        else:
            spin_values = dict(wager_format='structured-line', **structured)
    if not spin_values:
        issues.append('NGM_SPIN_SELECTOR_DOMAIN_UNBOUND')
    issues.extend('NGM_CONTROL_EFFECT_UNBOUND:'+ref for ref in _unbound_controls(manifest, source))
    issues.extend('NGM_ECONOMIC_DECLARATION_UNBOUND:'+ref for ref in _economic_declarations(config, '/config'))
    issues.extend('NGM_ECONOMIC_DECLARATION_UNBOUND:'+ref for ref in _economic_declarations(manifest.get('controls', []), '/controls'))
    calculators = config.get('engine', {}).get('calculators', {}) if isinstance(config.get('engine'), dict) else {}
    reviewed_calculators = {'default','display-win','hotf-expanding-wild','hotf-display-feature','hotf-enlargement','display-feature','waves'}
    if not calculators or not isinstance(calculators, dict) or any(not isinstance(c, dict) or not isinstance(c.get('type'), str) or c.get('type') not in reviewed_calculators for c in calculators.values()):
        issues.append('NGM_ENGINE_CALCULATORS_UNBOUND')
    if not isinstance(features, dict) or not features or not isinstance(features.get('regular'), dict):
        issues.append('NGM_FEATURE_DECLARATION_MISSING')
        features = {}
    for calculator in calculators.values() if isinstance(calculators, dict) else []:
        if not isinstance(calculator, dict):
            continue
        if calculator.get('type') in ('hotf-display-feature','display-feature','waves'):
            target = calculator.get('feature')
            target_config = features.get(target) if isinstance(target,str) else None
            if isinstance(target_config,dict) and target_config.get('supported') is False:
                continue
            if calculator.get('type')=='waves':
                valid=False
            else:
                required = {'type','feature','mode'}
                valid = (required<=set(calculator)<=required|{'trigger-count'} and target=='free-spins'
                    and calculator.get('mode')=={'type':'free-spins'}
                    and ('trigger-count' not in calculator or type(calculator['trigger-count']) is int and calculator['trigger-count']>0))
        elif calculator.get('type')=='default':
            valid = (set(calculator)<={'type','wilds'} and
                ('wilds' not in calculator or isinstance(calculator['wilds'],list) and all(type(n) is int and n>=0 for n in calculator['wilds'])))
        else:
            valid = set(calculator)=={'type'}
        if not valid:
            issues.append('NGM_CALCULATOR_FIELDS_UNBOUND')
    for identity, feature in features.items():
        if not isinstance(feature, dict):
            issues.append('NGM_FEATURE_INVALID:'+str(identity)); continue
        if feature.get('supported') is False:
            planned.append(dict(id=identity, kind='DISABLED', declaration=feature)); continue
        spec = FEATURE_KINDS.get(identity)
        if not spec or feature.get('type') != spec[0] or set(feature)-FEATURE_FIELDS:
            issues.append('NGM_FEATURE_UNBOUND:'+str(identity)); continue
        for key, value in feature.items():
            if key in ('type','reels-set','reels-config'):
                valid = isinstance(value, str) and bool(value)
            elif key in ('spins-count','more-spins-count','symbol'):
                valid = type(value) is int and value >= 0
            else:
                valid = type(value) is bool
            if not valid:
                issues.append('NGM_FEATURE_VALUE_UNBOUND:'+identity+':'+key)
        if identity in ('regular', 'autoplay') and feature.get('free') is not False:
            issues.append('NGM_BASE_COST_UNBOUND:'+identity)
        if identity == 'free-spins' and (feature.get('free') is False or 'spins-count' in feature and (type(feature['spins-count']) is not int or feature['spins-count'] <= 0)):
            issues.append('NGM_FREE_SPINS_DECLARATION_INVALID')
        planned.append(dict(id=identity, kind=spec[1], declaration=feature))
    # Other economic declarations cannot hide outside the feature map.
    for key in config:
        if re.search(r'buy|ante|cost|purchase|bet.?option|bet.?mode|bet.?type|stake', key, re.I):
            issues.append('NGM_ECONOMIC_CONFIG_UNBOUND:'+key)
    schemas = report.get('requests') or []
    if not any(r['name']=='SpinRequest' for r in schemas):
        issues.append('NGM_SPIN_CONTRACT_MISSING')
    registered = set(registry['names']) if registry else set()
    lifecycle = structured.get('lifecycle_roles', {}) if structured else {}
    for row in schemas:
        name, fields = row['name'], set(row.get('declared_fields', []))
        allowed = REQUEST_FIELDS.get(name)
        if row.get('unresolved_fields') or fields != set(row.get('fields', {})):
            issues.append('NGM_SERIALIZER_UNBOUND:'+name)
        elif structured and (name==structured['name'] or name in lifecycle):
            continue
        elif allowed is not None:
            if not fields or not fields <= allowed:
                issues.append('NGM_COMMAND_FIELDS_UNBOUND:'+name)
        elif not (registry and row.get('wire_message') and fields == METADATA and name not in registered):
            issues.append('NGM_COMMAND_EFFECT_UNBOUND:'+name)
    abstract = {r['name'] for r in report.get('source_declarations', []) if r.get('concrete') is False}
    if registered-{r['name'] for r in schemas}-abstract:
        issues.append('NGM_REGISTERED_HANDLER_CONTRACT_MISSING')
    issues = sorted(set(issues))
    complete = not issues
    domains = {key:dict(complete=complete, declaration_state='DECLARED_EMPTY' if complete else 'UNKNOWN',
                       options=[], source='ngm-client.feature-map+wire-contracts+handler-registry',
                       evidence=dict(source_sha256=report.get('source_sha256'), source_ref=report.get('source_ref'), manifest_ref=report.get('manifest_ref')))
               for key in ('purchase', 'ante')}
    return dict(schema='tester-spin/ngm-execution-plan/v1', complete=complete,
                source_sha256=report.get('source_sha256'), manifest_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                authority=loader, handler_registry=registry, spin_selector=spin_values, features=planned, domains=domains, unresolved=issues)
