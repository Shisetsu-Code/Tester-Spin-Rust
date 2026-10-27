"""Small read-only JavaScript input primitives, independent of titles and builds."""
import ast
import warnings
import json
import re

ID = r'[A-Za-z_$][\w$]*'
_TOKEN = re.compile(r'/\*.*?\*/|//[^\r\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`|[A-Za-z_$][\w$]*|[0-9]+(?:\.[0-9]+)?|[^\s]', re.S)
_REGEX = re.compile(r'/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\r\n])+/[dgimsuvy]*')


def canonical_source(source):
    pieces = []
    previous = ''
    index = 0
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        match = None
        if source[index] == '/' and not source.startswith(('//', '/*'), index) and previous in ('=', '(', '[', ',', ':', '!', '?', 'return', 'case', ';', '|', '&'):
            match = _REGEX.match(source, index)
        match = match or _TOKEN.match(source, index)
        if match is None:
            return ''
        token = match[0]
        index = match.end()
        if token.startswith(('/*', '//')):
            continue
        if token.startswith("'"):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', SyntaxWarning)
                    token = json.dumps(ast.literal_eval(token), ensure_ascii=False)
            except (SyntaxError, ValueError):
                pass
        if previous and (previous[-1].isalnum() or previous[-1] in '_$') and (token[0].isalnum() or token[0] in '_$'):
            pieces.append(' ')
        pieces.append(token)
        previous = token
    # Static bracket properties are the same input primitive as dot properties.
    normalized = []
    index = 0
    while index < len(pieces):
        if pieces[index] == '[' and normalized and index+2 < len(pieces) and pieces[index+2] == ']' and (re.fullmatch(ID, normalized[-1]) or normalized[-1] in (']',')')):
            try:
                name = json.loads(pieces[index+1])
            except (ValueError, TypeError):
                name = None
            if isinstance(name,str) and re.fullmatch(ID,name):
                normalized.extend(('.',name))
                index += 3
                continue
        normalized.append(pieces[index])
        index += 1
    return ''.join(normalized)



def block(source, opening):
    depth, index, quote = 1, opening + 1, None
    while index < min(len(source), opening + 8000):
        char = source[index]
        if quote:
            if char == '\\':
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in '\"\'`':
            quote = char
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[opening+1:index]
        index += 1
    return None


def action_handlers(source, symbol):
    pattern = r'\.setActionHandler\((' + ID + r'(?:\.' + ID + r')*\.' + symbol + r'|"' + symbol.lower() + r'"),(?:function\((' + ID + r')\)|\(?(' + ID + r')\)?=>)\{'
    result = []
    for match in re.finditer(pattern, source):
        body = block(source, match.end()-1)
        if body is not None:
            result.append((match[1], match[2] or match[3], body))
    return result


def handler_count(source, symbol):
    return len(re.findall(r'\.setActionHandler\((?:' + ID + r'(?:\.' + ID + r')*\.' + symbol + r'|"' + symbol.lower() + r'"),', source))


def flow_bridge(source):
    if 'params:args||{}' in source and 'EventsGame.play(action)' in source:
        return True
    pattern = r'_act\(('+ID+r'),('+ID+r'),('+ID+r')=null\)\{let ('+ID+r')=\{action:\{name:\1,params:\2\|\|\{\}\},bet:\3\};return '+ID+r'\.EventsGame\.play\(\4\),this\.deferred\.promise\}'
    return bool(re.search(pattern, source))


def flow_parameters(source, symbol):
    if not flow_bridge(source):
        return None
    # A proven prototype replacement supplies the effective middleware, rather
    # than the superseded handler shipped in the same bundle.
    overrides = list(re.finditer(r'Object\.assign\((' + ID + r')\.(default|FlowController)\.prototype,\{initDefaultMiddleware:function[^{}]*\{', source))
    if overrides:
        if len(overrides) != 1:
            return None
        override = overrides[0]
        prefix = source[:override.start()]
        if override[2] == 'default':
            binding = re.search(r'var ' + re.escape(override[1]) + r'=(?:' + ID + r'\()?require\("[^"\n]*controllers/FlowController"\)', prefix)
        else:
            binding = re.search(r'var ' + re.escape(override[1]) + r'=require\("(?:\.\./)*slotscore/core/controllers"\)', prefix)
            if binding:
                between = prefix[binding.end():]
                alias = re.escape(override[1])
                if re.search(alias + r'(?:\.' + ID + r')*=(?!=)|Object\.(?:assign|defineProperty)\(' + alias + r'(?:\.' + ID + r')*,|delete ' + alias + r'\b', between):
                    return None
        body = block(source, override.end()-1)
        if not binding or body is None:
            return None
        following = source[override.end()+len(body)+1:]
        target = re.escape(override[1] + '.' + override[2] + '.prototype')
        if handler_count(following, symbol) or re.search(target + r'\.initDefaultMiddleware=(?!=)|Object\.(?:assign|defineProperty)\(' + target + r',', following):
            return None
        source = body + ';params:args||{};EventsGame.play(action);'
    expression_handlers = []
    for start in re.finditer(r'\.setActionHandler\(('+ID+r'(?:\.'+ID+r')*\.'+symbol+r'),('+ID+r')=>', source):
        action, arg = start[1], start[2]
        model = 'this.app.model.'
        body = '(('+arg+'='+arg+'||{}).bet_per_line="bet_per_line"in '+arg+'?'+arg+'.bet_per_line:'+model+'betPerLine(),'+arg+'.lines="lines"in '+arg+'?'+arg+'.lines:'+model+'gameLines(),'+arg+'.bet_factor="bet_factor"in '+arg+'?'+arg+'.bet_factor:'+model+'betFactor()[0],'+model+'setBetPerLine('+arg+'.bet_per_line),'+model+'setLines('+arg+'.lines),'+model+'setBetFactor('+arg+'.bet_factor),'
        tail = 'this._act('+action+','+arg+','+model+'freespinsBuyingPrice()*'+model+'getRoundBet('+arg+'.bet_per_line,'+arg+'.bet_factor))))'
        optional = arg+'&&"selected_mode"in '+arg+'&&'+model+'setFreespinsBuyingPrice('+model+'getBuyFeatureCostByType('+arg+'.selected_mode)),'
        remaining = source[start.end():]
        if remaining.startswith(body+tail) or remaining.startswith(body+optional+tail):
            expression_handlers.append(start)
    if expression_handlers and len(expression_handlers) == handler_count(source, symbol):
        return ['bet_per_line','lines','bet_factor']
    handlers = action_handlers(source, symbol)
    if not handlers or len(handlers) != handler_count(source, symbol) or 'params:args||{}' not in source or 'EventsGame.play(action)' not in source:
        return None
    signatures = []
    getters = {'bet_per_line':'betPerLine', 'lines':'gameLines', 'bet_factor':'betFactor'}
    for action, argument, body in handlers:
        assigned = re.findall(re.escape(argument)+r'\.('+ID+r')=(?!=)', body)
        if set(assigned) not in ({'bet_per_line','lines'}, {'bet_per_line','lines','bet_factor'}) or len(assigned) != len(set(assigned)):
            return None
        for field in assigned:
            expression = re.escape(argument)+r'\.'+field+r'="'+field+r'"in '+re.escape(argument)+r'\?'+re.escape(argument)+r'\.'+field+r':'+ID+r'(?:\.'+ID+r')*\.'+getters[field]+r'\(\)'+(r'\[0\]' if field=='bet_factor' else '')+r';'
            if not re.search(expression, body):
                return None
        if not re.search(r'\._act\('+re.escape(action)+','+re.escape(argument)+r'(?:,|\))', body):
            return None
        if re.search(re.escape(argument)+r'\[|Object\.assign\('+re.escape(argument)+r'|delete '+re.escape(argument), body):
            return None
        signatures.append([k for k in getters if k in assigned])
    return signatures[0] if all(value == signatures[0] for value in signatures) else None


def empty_flow_actions(source):
    if not flow_bridge(source):
        return {}
    default_dispatch = bool(re.search(r'handlers\[action\]\|\|(?:function\(args\)\{return '+ID+r'\._act\(action,args\)\}|\(?args\)?=>this\._act\(action,args\))', source))
    default_dispatch = default_dispatch or bool(re.search(r'getActionHandler\(('+ID+r')\)\{return this\.handlers\[\1\]\|\|\(('+ID+r')=>this\._act\(\1,\2\)\)\}', source))
    rules = {}
    states = {'BONUS_INIT':('bonus_init','spins'), 'RESPIN':('respin','bonus'),
              'FREESPIN_INIT':('freespin_init','spins'), 'FREESPIN':('freespin','freespins'),
              'FREESPIN_STOP':('freespin_stop','freespins'), 'COLLECT_WIN':('collect_win','spins')}
    for symbol, (name, current) in states.items():
        if not (re.search(r'\.(?:act|actIfPossible)\('+ID+r'(?:\.'+ID+r')*\.'+symbol+r'\)',source) or re.search(r'\.flow\.(?:act|actIfPossible)\("'+name+r'"\)',source)):
            continue
        handlers = action_handlers(source, symbol)
        if len(handlers) == handler_count(source, symbol) and (handlers or default_dispatch) and all(not re.search(re.escape(arg)+r'\s*=|'+re.escape(arg)+r'\.|'+re.escape(arg)+r'\[', body)
               and re.search(r'\._act\('+re.escape(action)+','+re.escape(arg)+r'\)',body)
               for action,arg,body in handlers):
            rules[name]={'current':current}
            if name == 'collect_win':
                rules[name]['currents'] = ['spins','freespins']
            if name == 'respin':
                rules[name]['currents'] = ['spins','freespins','bonus']
    # The client derives the stop action from the advertised bonus origin.
    if ('.bonusOriginState()' in source and ('.BONUS_STOP)' in source or re.search(r'\.flow\.act\("bonus_"\.concat\('+ID+r'(?:\.'+ID+r')*\.bonusOriginState\(\),"_stop"\)\)',source))
            and default_dispatch and not handler_count(source,'BONUS_STOP')):
        for origin in ('spins','freespins'):
            rules['bonus_'+origin+'_stop']={'current':'bonus','back_to':origin}
            if 'this._get("game.bonus.back_to","spins")' in source:
                rules['bonus_'+origin+'_stop']['back_to_default']='spins'
    literal_stop = re.search(r'Object\.defineProperty\(' + ID + r'(?:\.' + ID + r')*\.FLOW_ACTIONS,"BONUS_STOP",\{get:function(?: ' + ID + r')?\(\)\{return"bonus_stop"\}\}\)', source)
    if literal_stop and '.BONUS_STOP)' in source and default_dispatch and not handler_count(source,'BONUS_STOP'):
        rules.pop('bonus_spins_stop', None)
        rules.pop('bonus_freespins_stop', None)
        rules['bonus_stop'] = {'current':'bonus'}
    return rules



def event_spin_parameters(source):
    pattern = r'\.Events\.flow\.play\(\{action:\{name:"spin",params:\{bet_per_line:'+ID+r'(?:\.'+ID+r')*\.betPerLine,lines:'+ID+r'(?:\.'+ID+r')*\.serverData\.settings\.lines\[0\]\}\},bet:'+ID+r'(?:\.'+ID+r')*\.bet\}\)'
    return ['bet_per_line','lines'] if re.search(pattern,source) else None


def flow_purchase_inputs(source, data):
    """Compose UI assignments with a certified flow middleware, never vendor defaults."""
    available = (data or {}).get('context', {}).get('available_buy_bonus', [])
    if not isinstance(available, list):
        available = []
    middleware = flow_parameters(source, 'BUY_SPIN')
    declarations = []
    for match in re.finditer(r'actBuyFeature\(([^)]*)\)\{', source):
        body = block(source, match.end()-1)
        if not body:
            continue
        sent = re.search(r'\.controllers\.flow\.act\('+ID+r'(?:\.'+ID+r')*\.BUY_SPIN,('+ID+r')\)',body)
        optional_controller = False
        if not sent:
            sent = re.search(r'null==\(('+ID+r')='+ID+r'(?:\.'+ID+r')*\.controllers\)\|\|\1\.flow\.act\('+ID+r'(?:\.'+ID+r')*\.BUY_SPIN,('+ID+r')\)', body)
            optional_controller = bool(sent)
        if not sent:
            continue
        variable = sent[2] if optional_controller else sent[1]
        prefix = body[:sent.start()]
        # Resolve only the observed new-module branch, using its actual model
        # predicate and current settings. The legacy serializer remains unknown.
        conditional = re.search(r'if\('+ID+r'(?:\.'+ID+r')*\.isNewModule\(\)\)\{'+re.escape(variable)+r'\.selected_mode=('+ID+r')\}else\{'+re.escape(variable)+r'\.buy_spin_type=\1\}', prefix)
        if conditional:
            predicate = 'isNewModule=function(){return!this._get("settings.freespins_buying_price_by_buy_spin_type.1",0)}'
            pricing = (data or {}).get('settings', {}).get('freespins_buying_price_by_buy_spin_type')
            if predicate not in source or (pricing is not None and not isinstance(pricing, dict)):
                continue
            old_price = (pricing or {}).get('1', 0)
            if old_price is not None and (not isinstance(old_price, (int,float,bool)) or old_price != 0):
                continue
            prefix = prefix[:conditional.start()] + variable + '.selected_mode=' + conditional[1] + ';' + prefix[conditional.end():]
        assignments = re.findall(re.escape(variable)+r'\.('+ID+r')=([^;,]+)[;,]',prefix)
        fields = dict(assignments)
        if len(fields) != len(assignments) or not {'bet_per_line','lines'}.issubset(fields) or set(fields)-{'bet_per_line','lines','selected_mode'}:
            continue
        if not re.fullmatch(ID+r'(?:\.'+ID+r')*\.get\("bet_per_line"\)',fields['bet_per_line']):
            continue
        lines = fields['lines']
        if re.fullmatch(ID+r'(?:\.'+ID+r')*\.gameLines\(\)',lines):
            line_source = 'current_lines'
        elif re.fullmatch(ID+r'(?:\.'+ID+r')*\.settingsLines\(\)\[0\]',lines):
            line_source = 'settings_lines_first'
        elif re.fullmatch(ID+r'(?:\.'+ID+r')*\.betFactor\(\)\[0\]',lines):
            line_source = 'bet_factor_first'
        else:
            continue
        selector = fields.get('selected_mode')
        selector_type = None
        if selector is None:
            modes = available if len(available)==1 else []
        elif re.fullmatch(ID+r'\.toString\(\)',selector):
            selector_type, modes = 'string', available
        elif re.fullmatch(ID,selector) and selector in match[1].split(','):
            selector_type, modes = 'preserve', available
        elif re.fullmatch(ID+r'(?:\.'+ID+r')*\.isNewModel\(\)\?('+ID+r'):\1\.toString\(\)',selector):
            mapping = 'isNewModel=function(){return this._get("settings.buy_bonus_prices.1",null)>0}'
            if mapping not in source:
                continue
            price = (data or {}).get('settings',{}).get('buy_bonus_prices',{}).get('1')
            selector_type = 'preserve' if isinstance(price,(int,float)) and price>0 else 'string'
            modes = available
        else:
            continue
        params = list(middleware or [])
        if selector is not None:
            params.append('selected_mode')
        declarations.append({'purchase_ui_observed':True, 'purchase_modes':modes if middleware else [],
                             'purchase_selector_type':selector_type,
                             'purchase_params':{str(mode):params for mode in modes} if middleware else {},
                             'purchase_value_sources':{'lines':line_source}})
    from .special_inputs import transformed_purchase_inputs
    transformed = transformed_purchase_inputs(source, data, middleware)
    if transformed:
        return transformed
    return declarations[0] if declarations and all(row==declarations[0] for row in declarations) else None


def runner_spin_contract(runner_source, init_source):
    """Certify the active shared spin button independently of unused client middleware."""
    source = canonical_source(runner_source)
    init = canonical_source(init_source)
    declaration = re.search(r'window\._PROVIDER\.game=\{name:"[^"\\]+",use:\[([^\]]*)\]', init)
    if not declaration:
        return None
    uses = re.findall(r'"([^"\\]+)"', declaration[1])
    if 'protocol' not in uses or any(value.split('|')[0] == 'custom_play' for value in uses):
        return None
    normal = r'action:\{name:"spin",params:\{bet_per_line:this\.model\.get\("bet_per_line"\),lines:this\.model\.get\("lines"\)\}\},bet:this\.model\.get\("bet"\)'
    if not re.search(normal, source) or '.onGamePlay({data:' not in source or '._getPlayParams()}' not in source:
        return None
    forwarding = r'\.use\.custom_play\|\|'+ID+r'(?:\.'+ID+r')*\.flow\.play\.on\((?P<wrapper>\()?function\(('+ID+r')\)\{return '+ID+r'(?:\.'+ID+r')*\.game\.play\(\2\.data\)\}(?(wrapper)\))\)'
    if not re.search(forwarding, source):
        return None
    return {'spin_params':['bet_per_line','lines'], 'spin_route':'shared-runner-button',
            'evidence':'Current init enables protocol without custom_play; current GameRunner button forwards bet_per_line/lines directly'}
