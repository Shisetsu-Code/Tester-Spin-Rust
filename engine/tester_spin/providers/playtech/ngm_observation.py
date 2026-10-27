"""Static observation bindings for NGM offline clients; never evaluates source.

Bindings describe non-pausing logpoints in a freshly loaded official demo.
They do not authorize wagers or certify the purchase inventory/round closure.
"""
import re
import json
from .client_sources import _function_bodies
from .ngm_contracts import request_catalog, _constants

NAME = r"[A-Za-z_$][\w$]*"


def event_action_binding(source, label):
    """Find the declared UI SpinEvent and its unique live event dispatcher."""
    declarations = list(re.finditer(
        r"\b"+NAME+r"\([^;()]*['\"]"+re.escape(label)+r"['\"],(\d+),[^;()]*\)", source))
    if len(declarations) != 1:
        return None
    registrations = list(re.finditer(NAME+r"\("+declarations[0][1]+
        r",\d+,(?:\{[^{}]*\}|"+NAME+r"),("+NAME+r")\)", source))
    if len(registrations) != 1:
        return None
    constructor = registrations[0][1]
    dispatchers = set(re.findall(r"\b("+NAME+r")\(new "+re.escape(constructor)+r"(?:\(\))?\)", source))
    if len(dispatchers) != 1:
        return None
    dispatcher = dispatchers.pop()
    args, body = _function_bodies(source).get(dispatcher, ([], ''))
    if len(args) != 1 or not re.fullmatch(NAME+r"\("+NAME+","+re.escape(args[0])+r"\)", body):
        return None
    header = re.search(r"function "+re.escape(dispatcher)+r"\([^)]*\)\{", source)
    if not header:
        return None
    offset = header.end()
    return dict(constructor=constructor, function=dispatcher,
                lineNumber=source.count('\n', 0, offset),
                columnNumber=offset-source.rfind('\n', 0, offset)-1)


def spin_action_binding(source):
    return event_action_binding(source, 'SpinEvent')


def continuation_probes(source):
    """Read live feature/action state through unambiguous client declarations.

    These getters authorize no action. Runtime additionally requires a declared
    free feature, an open settled round, and one-shot continuation accounting.
    """
    functions, constants = _function_bodies(source), _constants(source)
    spin = list(re.finditer(NAME+r"\([^;()]*['\"]SpinRequest['\"],(\d+),[^;()]*\)", source))
    control = list(re.finditer(NAME+r"\([^;()]*['\"]DesktopRoundButtons['\"],(\d+),[^;()]*\)", source))
    if len(spin) != 1 or len(control) != 1:
        return []
    registration = list(re.finditer(NAME+r'\('+spin[0][1]+r',\d+,(?:\{[^{}]*\}|'+NAME+r'),('+NAME+r')\)', source))
    if len(registration) != 1:
        return []
    ctor = registration[0][1]
    senders = [name for name, (_, body) in functions.items() if re.search(r'new '+re.escape(ctor)+r'(?![\w$])', body)]
    if len(senders) != 1:
        return []
    features = []
    for name, (_, body) in functions.items():
        if not re.search(r'(?<![\w$])'+re.escape(senders[0])+r'\(', body):
            continue
        for match in re.finditer(NAME+r'\(('+NAME+r'\('+NAME+r'(?:\.'+NAME+r')*,null\)\.'+NAME+r'),('+NAME+r')\)', body):
            if constants.get(match[2]) == {'free-spins'}:
                access = re.fullmatch(r'('+NAME+r')\(('+NAME+r'(?:\.'+NAME+r')*),null\)\.('+NAME+r')', match[1])
                accessor_args, accessor_body = functions.get(access[1], ([], ''))
                if len(accessor_args) != 2:
                    continue
                stacks = re.findall(r'new ('+NAME+r')\('+re.escape(accessor_args[0])+r'\.('+NAME+r')\)', accessor_body)
                if len(stacks) != 1:
                    continue
                iterator, stack_field = stacks[0]
                pending = [fn for fn, (fn_args, fn_body) in functions.items()
                    if len(fn_args) == 1 and re.fullmatch(
                        r'var '+NAME+r'(?:,'+NAME+r')*;for\(('+NAME+r')=new '+re.escape(iterator)+
                        r'\('+re.escape(fn_args[0])+r'\.'+re.escape(stack_field)+r'\);[^;{}]+;\)\{('+NAME+r')='+
                        NAME+r'\(\1(?:\.'+NAME+r')*\);return \2\}return null', fn_body)]
                if len(pending) != 1:
                    continue
                features.append((name, '()=>({current:'+match[1]+',pending:('+pending[0]+'('+access[2]+')||{}).'+access[3]+'})'))
    # Restrict the model declaration to this concrete class's registration block.
    reg = list(re.finditer(NAME+r'\('+control[0][1]+r',\d+,(?:\{[^{}]*\}|'+NAME+r'),'+NAME+r'\)', source))
    if len(reg) != 1:
        return []
    block = source[reg[0].end():control[0].start()]
    models = []
    for match in re.finditer(r'('+NAME+r')\(this\.('+NAME+r'),('+NAME+r'),null\)', block):
        if constants.get(match[3]) == {'spin'}:
            models.append((match[1], match[2]))
    if len(features) != 1 or len(models) != 1:
        return []
    writer, field = models[0]
    args, body = functions.get(writer, ([], ''))
    if len(args) != 3:
        return []
    slots = re.findall(r'='+re.escape(args[0])+r'\.('+NAME+r');'+re.escape(args[0])+r'\.'+NAME+r'\('+re.escape(args[1])+r'\)', body)
    if len(slots) != 1:
        return []
    disabled = set(re.findall(r"this\.("+NAME+r")\|\|this\.("+NAME+r")\?['\"]:disabled['\"]", source))
    if len(disabled) != 1:
        return []
    inherited_disabled, own_disabled = next(iter(disabled))
    available = [match[1] for _, (_, body) in functions.items() if (match := re.fullmatch(
        r'return this\.('+NAME+r')&&\!\(this\.'+re.escape(inherited_disabled)+r'\|\|this\.'+re.escape(own_disabled)+r'\)', body))]
    current = [name for name, (args, body) in functions.items() if len(args) == 1 and re.fullmatch(
        r'return '+NAME+r'\('+re.escape(args[0])+','+re.escape(args[0])+r'\.'+re.escape(field)+r'\.'+re.escape(slots[0])+r'\)', body)]
    if len(available) != 1 or len(current) != 1:
        return []
    setters = []
    for name, (args, body) in functions.items():
        if len(args) == 2 and body == writer+'('+args[0]+'.'+field+','+args[1]+',null)':
            setters.append((name, '(()=>{const owner='+args[0]+',model='+args[0]+'.'+field+';return ()=>{const button='+current[0]+'(owner);return {id:model.'+slots[0]+',ready:!!button&&'+'button.'+available[0]+'&&!(button.'+inherited_disabled+'||button.'+own_disabled+')&&!(owner.'+inherited_disabled+'||owner.'+own_disabled+')}}})()'))
    if len(setters) != 1:
        return []
    result = []
    for kind, (name, expression) in [('feature', features[0]), ('control', setters[0])]:
        header = re.search(r'function '+re.escape(name)+r'\([^)]*\)\{', source)
        if header is None:
            return []
        offset = header.end()
        result.append(dict(type=kind, expression=expression, function=name,
            lineNumber=source.count('\n', 0, offset), columnNumber=offset-source.rfind('\n', 0, offset)-1))
    return result


def spin_request_contract(source):
    """Use the same complete semantic serializer as the HAR analyzer."""
    rows = [row for row in request_catalog(source) if row['name'] == 'SpinRequest']
    if len(rows) != 1 or rows[0]['unresolved_fields']:
        return None
    row = rows[0]
    names = ('bet', 'numCoins', 'spinType')
    if not all(name in row['fields'] for name in names):
        return None
    fields = {name:row['fields'][name] for name in names}
    if len(set(fields.values())) != len(names):
        return None
    return dict(constructor=row['constructor'], message_id=row['message_id'], fields=fields)


def observation_points(source):
    functions = _function_bodies(source)
    points = []

    def point(kind, name, offset, expression):
        header = re.search(r"function " + re.escape(name) + r"\([^)]*\)\{", source)
        if header is None:
            return
        position = header.end() + offset
        points.append(dict(type=kind, function=name,
                           lineNumber=source.count("\n", 0, position),
                           columnNumber=position-source.rfind("\n", 0, position)-1,
                           expression=expression))

    dispatchers = []
    for name, (args, body) in functions.items():
        if len(args) != 2 or "for(" not in body:
            continue
        returns = list(re.finditer(r"return (" + NAME + r")", body))
        if not returns:
            continue
        result = returns[-1][1]
        if not re.search(re.escape(result)+r"=new "+NAME+r"(?:\(\))?;", body):
            continue
        calls = list(re.finditer(r"("+NAME+r")="+NAME+r"\."+NAME+r"\("+re.escape(args[1])+r"\)", body))
        if len(calls) == 1 and re.search(NAME+r"\("+re.escape(result)+","+re.escape(calls[0][1])+r"\)", body):
            dispatchers.append((name, args[1], returns))
    if len(dispatchers) == 1:
        name, request, returns = dispatchers[0]
        expression = request
        contract = spin_request_contract(source)
        if contract:
            fields = ",".join(key+":"+request+"."+value
                              for key, value in contract['fields'].items())
            normalized = request+' instanceof '+contract['constructor']+'?{'+fields+'}:null'
            from .ngm_structured import structured_spin_contract, observation_expression
            structured = structured_spin_contract(source)
            if structured:
                normalized = '('+observation_expression(structured, request)+'||('+normalized+'))'
            expression = '({raw:'+request+',spin:'+normalized+',requestClass:'
            expression += ''.join(request+' instanceof '+row['constructor']+'?'+json.dumps(row['name'])+':'
                                  for row in request_catalog(source))+'null})'
        body = functions[name][1]
        lookup = re.search(r'('+NAME+r')='+NAME+r'\('+NAME+r'\.'+NAME+r','+re.escape(request)+r'\.'+NAME+r'\);(?=if\(!\1\)return '+re.escape(returns[-1][1])+r';)', body)
        offset = 0
        if lookup:
            offset = lookup.end()
            expression = (expression[:-2]+',handlerAbsent:!'+lookup[1]+'})' if contract else
                          '({raw:'+request+',handlerAbsent:!'+lookup[1]+'})')
        point("offline.request", name, offset, expression)
        for returned in returns:
            point("offline.response", name, returned.start(), returned[1])

    # Require a linked payout sum -> credit wrapper -> result construction.
    # A balance delta alone is deliberately insufficient evidence.
    sums = set()
    for name, (args, body) in functions.items():
        if len(args) != 1 or "for(" not in body:
            continue
        match = re.search(r"("+NAME+r")\+=("+NAME+r")\.("+NAME+r")\}", body)
        if match and re.search(re.escape(match[1])+r"=0;", body):
            sums.add(name)
    candidates = []
    for name, (args, body) in functions.items():
        if len(args) != 2:
            continue
        last = re.search(r"return ("+NAME+r")$", body)
        if not last:
            continue
        paid = last[1]
        if not any(re.search(re.escape(total)+r"\("+re.escape(args[1])+r"\)", body) for total in sums):
            continue
        if not re.search(re.escape(paid)+r"="+NAME+r"\(", body):
            continue
        # The credited value and payout collection must flow together into
        # a result constructor; merely finding an unrelated sum is not enough.
        for outer, (_, outer_body) in functions.items():
            call = re.search(r"("+NAME+r")="+re.escape(name)+r"\(("+NAME+r"(?:\."+NAME+r")*),("+NAME+r")\)", outer_body)
            if call and re.search(r"new "+NAME+r"\("+re.escape(call[2])+","+re.escape(call[1])+","+re.escape(call[3])+r"\)", outer_body):
                candidates.append((name, last, paid))
                break
    if len(candidates) == 1:
        name, last, paid = candidates[0]
        point("offline.payout", name, last.start(), "({calculatedWin:"+paid+"})")
    return points
