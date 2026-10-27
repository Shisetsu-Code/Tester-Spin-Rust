"""Purchase declarations from the matching game constructor and proven serializer."""
import re


def _code(source):
    # Keep offsets while excluding strings and comments from structural parsing.
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|//[^\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda m: ' ' * len(m.group()), source)


def _block(code, opening):
    depth = 1
    for index in range(opening + 1, min(len(code), opening + 200000)):
        if code[index] == '{': depth += 1
        elif code[index] == '}':
            depth -= 1
            if depth == 0: return code[opening + 1:index]
    return None


def _top_level(body):
    braces = parentheses = brackets = 0
    output = []
    for char in body:
        if char == '{': braces += 1
        elif char == '(': parentheses += 1
        elif char == '[': brackets += 1
        nested = braces or parentheses or brackets
        output.append(char if not nested and char not in '})]' else ' ')
        if char == '}': braces -= 1
        elif char == ')': parentheses -= 1
        elif char == ']': brackets -= 1
    return ''.join(output)


def _value(body, name):
    # A direct chain assigns the same literal to each property, right to left.
    value = None
    for match in re.finditer(r'(?:^|[;,])\s*((?:this\.[A-Za-z_$][\w$]*\s*=\s*)+)([^;,}]*)',body):
        names = re.findall(r'this\.([A-Za-z_$][\w$]*)\s*=',match[1])
        if name in names: value = match[2].strip()
    return value


def _constructor(source, name):
    code = _code(source)
    legacy = re.search(r'\b' + re.escape(name) + r'View\s*=\s*function\([^)]*\)\s*\{', code)
    if legacy:
        body = _block(code, legacy.end() - 1)
        return (_top_level(body), 'BasicSlotView.call(this)' in re.sub(r'\s+', '', body)) if body is not None else (None, False)
    modern = re.search(r'\bclass\s+' + re.escape(name) + r'View\s+extends\s+BasicSlotView\s*\{', code)
    if modern:
        class_body = _block(code, modern.end() - 1)
        ctor = next((m for m in re.finditer(r'\bconstructor\([^)]*\)\s*\{', class_body or '') if _at_top(class_body,m.start())),None)
        if ctor:
            body = _block(class_body, ctor.end() - 1)
            return (_top_level(body), 'super()' in re.sub(r'\s+', '', body)) if body is not None else (None, False)
    return None, False


def _at_top(code, index):
    prefix = code[:index]
    return prefix.count('{') == prefix.count('}')


def _methods(code, owner):
    result = []
    pattern = r'\b' + re.escape(owner) + r'\.prototype\.([A-Za-z_$][\w$]*)\s*=\s*function\([^)]*\)\s*\{'
    for match in re.finditer(pattern, code):
        body = _block(code, match.end() - 1)
        if body is not None: result.append((match[1],body))
    legacy = re.search(r'\b' + re.escape(owner) + r'\s*=\s*function\([^)]*\)\s*\{', code)
    if legacy:
        body = _block(code, legacy.end() - 1)
        if body is not None: result.append(('constructor',body))
    for cls in re.finditer(r'\bclass\s+' + re.escape(owner) + r'(?:\s+extends\s+[A-Za-z_$][\w$]*)?\s*\{', code):
        class_body = _block(code,cls.end()-1)
        for match in re.finditer(r'\b([A-Za-z_$][\w$]*)\([^)]*\)\s*\{',class_body or ''):
            if _at_top(class_body,match.start()):
                body = _block(class_body,match.end()-1)
                if body is not None: result.append((match[1],body))
    return result


def discover_purchase_modes(sources: list[str], game_name: str) -> list[dict]:
    if not re.fullmatch(r'[A-Za-z0-9_]+', game_name): return []
    code = _code('\n'.join(sources))
    compact = re.sub(r'\s+', '', ''.join(body for _,body in _methods(code,'BasicSlotView')))
    plays = {re.sub(r'\s+','',body) for name,body in _methods(code,'SlotNetworkController') if name=='play'}
    play = next(iter(plays)) if len(plays)==1 else ''
    shared_buy = all(token in compact for token in (
        '0==this.buyFeatureToPlayActionIndex?this.sideBet=2',
        'this.sideBetPercent=this.sideBet=0',
        'this.buyFeaturePlayIndex=this.sideBetPlayIndex=this.buyFeatureToPlayActionIndex=this.sideBetToPlayActionIndex=this.extraAnimationState=0',
    ))
    serializer = '(Game.game.sideBet-1).toString()' in play and 'this.sendData(' in play
    configured_serializer = all(token in play for token in (
        'if(Game.game.useBuyFeature&&0<Game.game.sideBetPercent)',
        'e=Game.game.buyFeaturePlayIndex,Game.game.buyFeaturePlayIndex=0',
        '+e.toString()',
    )) and 'this.buyFeaturePlayIndex=this.buyFeatureToPlayActionIndex' in compact
    for source in sources:
        body, inherited = _constructor(source, game_name)
        if body is None: continue
        if _value(body, 'useBuyFeature') not in {'!0', 'true'}: return []
        multiplier = _value(body, 'buyFeatureMult')
        multiplier = float(multiplier) if multiplier and re.fullmatch(r'\d+(?:\.\d+)?', multiplier) else None
        selector = None; reason = 'PURCHASE_WS_REQUEST_AND_TERMINAL_RESPONSE_REQUIRED'
        changes = any(re.search(r'\bthis\.' + name + r'\s*=', body) for name in ('sideBet','buyFeatureToPlayActionIndex','buyFeaturePlayIndex','sideBetPercent'))
        if shared_buy and serializer and inherited and not changes:
            selector = 1; reason = 'CLIENT_DEFAULT_BUY_SELECTOR'
        elif shared_buy and serializer and inherited and configured_serializer:
            action = _value(body, 'buyFeatureToPlayActionIndex')
            percent = _value(body, 'sideBetPercent')
            if (action and re.fullmatch(r'[1-9][0-9]{0,3}', action)
                    and percent and re.fullmatch(r'\d+(?:\.\d+)?', percent) and float(percent) > 0
                    and _value(body, 'buyFeaturePlayIndex') is None):
                selector = int(action); reason = 'CLIENT_CONFIGURED_BUY_SELECTOR'
        return [{
            'id':'D1_BUY_FEATURE', 'kind':'PURCHASE', 'observed':True,
            'coverage_required':True, 'executable':selector is not None, 'validated':False,
            'feature_selector':selector, 'cost_multiplier':multiplier,
            'contract_source':'matching_game_client_constructor', 'reason':reason,
            'required_options':['D1_BUY_FEATURE'], 'covered_options':[],
        }]
    return []


def discover_antebet_modes(sources: list[str], game_name: str) -> list[dict]:
    purchases = discover_purchase_modes(sources,game_name)
    purchase_selector = purchases[0].get('feature_selector') if purchases else None
    code = _code('\n'.join(sources))
    base = _methods(code,'BasicSlotView')
    base_code = re.sub(r'\s+','',''.join(body for _,body in base))
    plays = {re.sub(r'\s+','',body) for name,body in _methods(code,'SlotNetworkController') if name=='play'}
    if len(plays)!=1: return []
    play = next(iter(plays))
    if not all(token in play for token in ('e=Game.game.sideBetPlayIndex','0<Game.game.sideBetPlayIndex','+e.toString()')): return []
    if 'this.sideBetPlayIndex=this.sideBetToPlayActionIndex' not in base_code: return []
    value_method = next((body for name,body in base if name=='getSidebetValue'), '')
    if not re.search(r'Math\.round\(\s*[A-Za-z_$][\w$]*\s*\*\s*this\.sideBetPercent\s*\)',value_method): return []
    for source in sources:
        body,inherited = _constructor(source,game_name)
        if body is None: continue
        action,percent = _value(body,'sideBetToPlayActionIndex'),_value(body,'sideBetPercent')
        if (not inherited or _value(body,'sideBet')!='1' or _value(body,'sideBetPlayIndex') is not None
                or not action or not re.fullmatch(r'[1-9][0-9]{0,3}',action)
                or not percent or not re.fullmatch(r'\d+(?:\.\d+)?',percent) or float(percent)<=0
                or int(action)==purchase_selector): return []
        return [{'id':'D1_ANTE_BET','kind':'ANTE_BET','observed':True,'coverage_required':True,
                 'executable':_value(body,'useBuyFeature') in {'!0','true'},'validated':False,'feature_selector':int(action),
                 'cost_multiplier':1+float(percent),'contract_source':'matching_game_client_side_bet_chain',
                 'reason':'CLIENT_CONFIGURED_SIDE_BET_SELECTOR','required_options':['D1_ANTE_BET'],'covered_options':[]}]
    return []


def apply_purchase_coverage(result, modes: list[dict]) -> None:
    known = {mode.get('id') for mode in result.discovered_modes}
    for mode in modes:
        if mode.get('id') not in known:
            result.discovered_modes.append(mode)
            known.add(mode.get('id'))
    if any(not mode.get('validated') for mode in modes) and result.status == 'OK':
        result.status = 'PARCIAL'
        result.error = 'D1: tirada base completa; compra detectada pendiente de validar con mensajes WebSocket y cierre.'


def purchase_modes_for_init(modes: list[dict], payload: dict) -> list[dict]:
    # Official client disables its buy UI when the init response has bf="f".
    return [] if payload.get("bf") == "f" else modes

def classify_spin_message(payload: dict, *, purchase_selectors=(), side_bet_selectors=()):
    """Shape identifies a variant; game-specific selector evidence supplies its meaning."""
    if not isinstance(payload, dict) or isinstance(payload.get('type'), bool) or str(payload.get('type')) != '1':
        return None
    data = payload.get('data')
    if not isinstance(data, str) or len(data) > 128:
        return None
    fields = data.split(',')
    if len(fields) not in {3, 4} or any(not re.fullmatch(r'\d{1,10}', field) for field in fields):
        return None
    values = list(map(int, fields))
    if values[0] <= 0:
        return None
    result = {'operation': 'SPIN', 'variant': 'normal', 'lines':values[0],
              'bet_index':values[1], 'playmode':values[2]}
    if len(values) == 4:
        selector = values[3]
        result['feature_selector'] = selector
        result['variant'] = ('bonus_buy' if selector in purchase_selectors and selector not in side_bet_selectors
                             else 'side_bet' if selector in side_bet_selectors and selector not in purchase_selectors
                             else 'feature_variant')
    return result


def purchase_response_evidence(request, response, *, base_bet=None, cost_multiplier=None, observed_debit=None):
    """Acceptance evidence is separate from a completed bonus/return-to-base contract.

    observed_debit must be an independently verified debit, not a raw balance
    difference that might include wins or other operations.
    """
    import math
    def number(value):
        if isinstance(value, bool):
            return None
        try:
            value = float(value)
        except (ValueError, TypeError, OverflowError):
            return None
        return value if math.isfinite(value) and value >= 0 else None
    result = {'purchase_accepted':False, 'terminal':False, 'bonus_spins':None, 'cost_matches':False}
    if not isinstance(request, dict) or not isinstance(response, dict):
        return result
    bet, multiplier, debit = map(number, (base_bet, cost_multiplier, observed_debit))
    if bet and multiplier and debit is not None:
        expected = bet * multiplier
        result['cost_matches'] = math.isfinite(expected) and math.isclose(debit, expected, rel_tol=1e-6, abs_tol=1e-6)
    current, total = number(response.get('b8')), number(response.get('b9'))
    in_bonus = (response.get('type') == 3 and type(response.get('st')) is int and response.get('st') in {5,6,11,12}
                and current is not None and total is not None and total > 0
                and current.is_integer() and total.is_integer() and current <= total)
    if in_bonus:
        result['bonus_spins'] = int(total)
    result['purchase_accepted'] = bool(request.get('variant') == 'bonus_buy' and in_bonus and result['cost_matches'])
    return result
