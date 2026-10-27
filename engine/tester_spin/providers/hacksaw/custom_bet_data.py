"""Conservative source evidence for SDK custom bet data; never executes JavaScript."""
import json
import math
import re

_ID = r"[A-Za-z_$][\w$]*"


def _balanced(source, start, opening="{", closing="}"):
    if start >= len(source) or source[start] != opening:
        return None
    depth = 0
    quote = None
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
        elif char in ('"', "'"): quote = char
        elif char == "`": return None
        elif char == opening: depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0: return source[start:index + 1], index + 1
    return None


def _literal(raw):
    # Quoting property identifiers is sufficient only for the strict JSON subset.
    raw = re.sub(r'([,{]\s*)(' + _ID + r')\s*:', r'\1"\2":', raw)
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return None
    def safe(item):
        if isinstance(item, dict):
            return 'betAmount' not in item and all(safe(v) for v in item.values())
        if isinstance(item, list): return all(safe(v) for v in item)
        if type(item) is float:return math.isfinite(item)
        return item is None or isinstance(item, (str, bool, int, float))
    return value if isinstance(value, dict) and value and safe(value) else None


def client_custom_bet_data(source, casino_source):
    """Return proven default and selector payloads, leaving unknowns unresolved.

    ``proven`` certifies SDK transport only; absent per-selector entries are not
    evidence that the default applies to that selector. Price overrides reject.
    """
    result = {'default': None, 'by_selector': {}, 'proven': False}
    subscriber = re.search(r'"updateCustomBetData",function\((' + _ID + r')\)\{', casino_source)
    if not subscriber: return result
    body = _balanced(casino_source, subscriber.end() - 1)
    if not body or not re.search(r'\._gameState\.customBetData=' + re.escape(subscriber[1]) + r'(?=[,;}])', body[0]): return result
    transport = re.search(r'(' + _ID + r')\.customData=this\._gameState\.customBetData', casino_source)
    if not transport or not re.search(r'\bbets:\[' + re.escape(transport[1]) + r'\]', casino_source[transport.end():transport.end()+2000]): return result
    result['proven'] = True
    defaults = []
    initializers = []
    for init in re.finditer(r'init:function\([^)]*\)\{', source):
        body = _balanced(source, init.end()-1)
        if body: initializers.append(body[0])
    initial = ';'.join(initializers)
    for match in re.finditer(r'\.publish\("updateCustomBetData",(?=\{)', initial):
        obj = _balanced(initial, match.end())
        if not obj or not initial[obj[1]:].startswith(')'): return result
        value = _literal(obj[0])
        if value is None: return result
        defaults.append(value)
    if defaults and all(v == defaults[0] for v in defaults): result['default'] = defaults[0]

    registration = re.search(r'\["hacksaw\.common\.types\.FeatureBuyItem"\]=(' + _ID + r')', source)
    if not registration: return result

    # A single method must bind both the data branch and the menu argument to
    # the identical flag. No matching by selector spelling or identifier suffix.
    for method in re.finditer(_ID + r':function\([^)]*\)\{', source):
        part = _balanced(source, method.end()-1)
        if not part: continue
        text = part[0]
        for binding in re.finditer(r'(' + _ID + r')=(' + _ID + r'\.' + _ID + r')\?(?=\{)', text):
            high = _balanced(text, binding.end())
            if not high or text[high[1]:high[1]+2] != ':{': continue
            low = _balanced(text, high[1]+1)
            if not low: continue
            publish = re.search(r'\.publish\("updateCustomBetData",' + re.escape(binding[1]) + r'\.(' + _ID + r')\)', text[low[1]:])
            menu_call = re.search(r'\.publish\("updateFeatureBuyContent",', text[low[1]:])
            if not publish or not menu_call: continue
            # Any intervening use may rebind, mutate or leak the object to an
            # unknown function. Only an untouched local reaches this publish.
            before_publish = text[low[1]:low[1]+publish.start()]
            if re.search(r'(?<![\w$])' + re.escape(binding[1]) + r'(?![\w$])', before_publish):
                continue
            menu_tail = text[low[1]:]
            direct = re.search(r'\.publish\("updateFeatureBuyContent",new ' + _ID + r'\(this\.getFeatureBuyItems\(' + re.escape(binding[2]) + r'\)', menu_tail)
            alias_bound = False
            menu_end = direct.end() if direct else None
            for alias in re.finditer(r'(' + _ID + r')=new ' + _ID + r'\(this\.getFeatureBuyItems\(' + re.escape(binding[2]) + r'\)', menu_tail):
                opening = menu_tail.index('(', alias.start())
                args = _balanced(menu_tail, opening, '(', ')')
                if args and re.match(r';this\._uiChannel\.publish\("updateFeatureBuyContent",' + re.escape(alias[1]) + r'\)', menu_tail[args[1]:]):
                    alias_bound = True
                    menu_end = min(menu_end, args[1]) if menu_end is not None else args[1]
            if not direct and not alias_bound: continue
            # The flag owner must stay a read-only scalar-property source until
            # the menu consumes it. Rebinding, mutation and object escape make
            # identical flag spelling insufficient to prove identical value.
            owner = binding[2].split('.')[0]
            stable = True
            interval = menu_tail[:menu_end]
            for use in re.finditer(r'(?<![\w$])' + re.escape(owner) + r'(?![\w$])', interval):
                member = re.match(r'\.(' + _ID + r')', interval[use.end():])
                suffix = interval[use.end()+member.end():].lstrip() if member else ''
                prefix = interval[:use.start()].rstrip()
                if (not member or re.match(r'(?:=(?!=)|(?:&&|\|\||\?\?)=|[+*/%&|^?-]=|\+\+|--|\(|\[|\.)', suffix)
                        or re.search(r'(?:\+\+|--|\bdelete)\s*$', prefix)):
                    stable = False
                    break
            if not stable: continue
            values = []
            for raw in (high[0], low[0]):
                prop = re.search(r'(?:[,{])' + re.escape(publish[1]) + r':(?=\{)', raw)
                obj = _balanced(raw, prop.end()) if prop else None
                values.append(_literal(obj[0]) if obj else None)
            if any(value is None for value in values): continue
            for menu in re.finditer(r'getFeatureBuyItems:function\((' + _ID + r')\)\{', source):
                branch = _balanced(source, menu.end()-1)
                param = re.escape(menu[1])
                pattern = r'^\{return(?:' + param + r'|\(' + param + r'=null==' + param + r'\?!1:' + param + r'\))\?'
                conditional = re.match(pattern, branch[0]) if branch else None
                if not conditional: continue
                a = _balanced(branch[0], conditional.end(), '[', ']')
                b = _balanced(branch[0], a[1]+1, '[', ']') if a and branch[0][a[1]:a[1]+1] == ':' else None
                if not a or not b or branch[0][b[1]:] != '}': continue
                mapping = {}
                for array, value in zip((a[0], b[0]), values):
                    calls = re.findall(r'new ' + re.escape(registration[1]) + r'\("((?:\\.|[^"\\])*)"[,)]', array)
                    if not calls: break
                    for identifier in calls:
                        if identifier in mapping and mapping[identifier] != value: break
                        mapping[identifier] = value
                    else: continue
                    break
                else:
                    if any(k in result['by_selector'] and result['by_selector'][k] != v for k,v in mapping.items()):
                        result['by_selector'] = {}; return result
                    result['by_selector'].update(mapping)
    return result
