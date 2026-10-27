"""Bounded static script-loader expressions. No JavaScript is executed."""
import ast
import hashlib
import re

_TOKEN=re.compile(r"\s*(?:((?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'))|([A-Za-z_$][\w$]*)|([+?:()]))")

def _value(expression, values):
    tokens=[];pos=0
    while pos<len(expression):
        m=_TOKEN.match(expression,pos)
        if not m:raise ValueError('dynamic expression')
        tokens.append(m.groups());pos=m.end()
    index=0
    def atom():
        nonlocal index
        if index>=len(tokens):raise ValueError('truncated expression')
        string,name,symbol=tokens[index];index+=1
        if string:return ast.literal_eval(string)
        if name:
            if name not in values:raise ValueError('unknown variable')
            return values[name]
        if symbol=='(':
            result=ternary()
            if index>=len(tokens) or tokens[index][2]!=')':raise ValueError('parenthesis')
            index+=1;return result
        raise ValueError('unsupported expression')
    def concat():
        nonlocal index
        result=atom()
        while index<len(tokens) and tokens[index][2]=='+':
            index+=1;other=atom()
            if not isinstance(result,str) or not isinstance(other,str):raise ValueError('non-string concatenation')
            result+=other
            if len(result)>2048:raise ValueError('loader expression limit')
        return result
    def ternary():
        nonlocal index
        result=concat()
        if index<len(tokens) and tokens[index][2]=='?':
            index+=1;yes=concat()
            if index>=len(tokens) or tokens[index][2]!=':':raise ValueError('ternary')
            index+=1;no=concat()
            if type(result) is not bool:raise ValueError('non-boolean condition')
            result=yes if result else no
        return result
    result=ternary()
    if index!=len(tokens):raise ValueError('trailing expression')
    return result

def script_dependencies(source):
    # Large bundles are not interpreted as global assignment environments.
    literals=re.findall(r"setAttribute\([\"']src[\"'],\s*[\"']([^\"']+\.js)[\"']\)",source)
    for created in re.finditer(r'\b([A-Za-z_$][\w$]*)\s*=\s*document\.createElement\(["\']script["\']\)',source):
        for assigned in re.finditer(r'(?<![\w$.])'+re.escape(created[1])+r'\.src\s*=\s*(["\'])([^"\'\n]{1,2048}\.js)\1\s*(?=[,;})])',source):
            literals.append(assigned[2])
    if len(source)>32768:return list(dict.fromkeys(literals))
    values={'true':True,'false':False}
    for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*=\s*[\"']noModule[\"']\s*in\s+HTMLScriptElement\.prototype",source):
        values[match[1]]=True  # Select the declared modern build; no query override.
    for match in list(re.finditer(r"\b([A-Za-z_$][\w$]*)\s*=([^,;\n]{1,1024})",source))[:256]:
        try:values[match[1]]=_value(match[2].strip(),values)
        except (ValueError,SyntaxError):pass
    result=list(literals)
    for match in re.finditer(r"setAttribute\([\"']src[\"'],\s*([A-Za-z_$][\w$]*)\)",source):
        path=values.get(match[1])
        if isinstance(path,str) and path.endswith('.js'):result.append(path)
    return list(dict.fromkeys(result))


def _function_bodies(source):
    functions={}
    for m in re.finditer(r"function ([A-Za-z_$][\w$]*)\(([^)]*)\)\{",source):
        depth=1;quote=None;escape=False;end=m.end()
        while end<len(source) and end-m.end()<8192 and depth:
            char=source[end];end+=1
            if quote:
                if escape:escape=False
                elif char=='\\':escape=True
                elif char==quote:quote=None
            elif char in ('\"',"'",'`'):quote=char
            elif char=='{':depth+=1
            elif char=='}':depth-=1
        if depth==0:functions[m[1]]=(m[2].split(','),source[m.end():end-1])
    return functions

def compiled_pick_binding(source):
    """Recognize a bounded key-builder -> continuation -> playOut chain.

    Function/property names are captured from source, never tied to a title/build.
    Unknown or longer chains remain unbound.
    """
    aliases=set(re.findall(r"\b([A-Za-z_$][\w$]*)=[\"']pick[\"']",source))
    functions=_function_bodies(source)
    sinks=[name for name,(args,body) in functions.items() if 'GLU.game.playOut' in body and re.search(r'parameters\s*:\s*JSON\.parse\(',body)]
    wrappers=set()
    for name,(args,body) in functions.items():
        for sink in sinks:
            for call in re.finditer(re.escape(sink)+r"\([^,;]+,[A-Za-z_$][\w$]*\.([A-Za-z_$][\w$]*),",body):
                if re.search(r"\."+re.escape(call[1])+r"=48775\b",source):wrappers.add(name)
    literal_wrappers=set(wrappers)
    for _ in range(3):
        for name,(args,body) in functions.items():
            if len(args)<2 or len(re.findall(r'(?<![\w$.])'+re.escape(args[1])+r'(?![\w$])',body))!=1:continue
            if any(re.search(re.escape(wrapper)+r'\([A-Za-z_$][\w$.]*,'+re.escape(args[1])+r'(?:,|\))',body) for wrapper in literal_wrappers):
                literal_wrappers.add(name)
    ident=r'[A-Za-z_$][\w$]*'
    for _,(args,body) in functions.items():
        for call in re.finditer(r'('+ident+r')\(('+ident+r')\.('+ident+r'),["\']pick["\'],('+ident+r')\)',body):
            helper=functions.get(call[1])
            if not helper or len(helper[0])!=3:continue
            owner,key,value=helper[0]
            setter=re.escape(owner)+r'\.'+ident+r'\.set\('+re.escape(key)+r',void 0==='+re.escape(value)+r'\?null:'+re.escape(value)+r'\)'
            if not re.search(setter,helper[1]):continue
            model=call[2]
            if not re.search(re.escape(model)+r'=new '+ident,body):continue
            # Container is constructed, populated once, then forwarded unchanged.
            if len(re.findall(r'(?<![\w$.])'+re.escape(model)+r'(?![\w$])',body))!=4:continue
            if any(re.search(re.escape(wrapper)+r'\('+ident+r','+re.escape(model)+r'(?:,|\))',body) for wrapper in literal_wrappers):return True
    for name,(args,body) in functions.items():
        for alias in aliases:
            for call in re.finditer(r"([A-Za-z_$][\w$]*)\(([A-Za-z_$][\w$]*),"+re.escape(alias)+r",",body):
                helper=functions.get(call[1])
                if helper is None or len(helper[0])!=3:continue
                _,key,value=helper[0]
                if not re.search(r","+re.escape(key)+","+re.escape(value)+r"\)",helper[1]):continue
                for wrapper in wrappers:
                    if re.search(re.escape(wrapper)+r"\([A-Za-z_$][\w$.]*,"+re.escape(call[2])+r"\)",body):return True
    return False


def compiled_default_cost_binding(source):
    """Bind the compiled regular-spin selector to decoded CostCfg.name.

    Recognize the observed default -> selected cost name -> task -> playMoney
    chain with captured identifiers, without running client code. A caller must
    still require a unique current cost row; this proof is not a mode catalog.
    """
    ident = r'[A-Za-z_$][\w$]*'
    functions = _function_bodies(source)
    defaults = set(re.findall(r'\b(' + ident + r')=["\']default["\']', source))
    names = set(re.findall(r'\b(' + ident + r')=["\']name["\']', source))
    if not defaults or not names:
        return {}
    name_properties = set()
    decoder_pattern = (r'\.Qd=function\((' + ident + r')\)\{([^{}]{1,2000})\};var '
                       + ident + r'=' + ident + r'\([^;]{0,200}["\']Serializer_TS/CostCfg_DI["\']')
    for decoder in re.finditer(decoder_pattern, source):
        argument, body = decoder.groups()
        if not all('"' + key + '"' in body or "'" + key + "'" in body for key in ('cost', 'uuid')):
            continue
        for alias in names:
            read = (r'(' + ident + r')=' + ident + r'\(' + re.escape(argument) + ',' + re.escape(alias)
                    + r'\),(' + ident + r')\(' + ident + ',' + ident + r'\(\1\)\)')
            for match in re.finditer(read, body):
                setter = functions.get(match[2])
                if setter is None or len(setter[0]) != 2:
                    continue
                owner, value = setter[0]
                assignment = re.fullmatch(re.escape(owner) + r'\.(' + ident + ')=' + re.escape(value), setter[1])
                if assignment:
                    name_properties.add(assignment[1])
    if not name_properties:
        return {}
    for sink, (args, body) in functions.items():
        if len(args) != 5:
            continue
        command = re.search(r'var (' + ident + r')=\{ID:' + re.escape(args[1]) + r'\}', body)
        if command is None or ('$wnd.GLU.game.playMoney(' + args[0] + ',' + command[1] + ',' + args[2] + ')') not in body:
            continue
        callback_pattern = (r'\(' + r'[^;{}]{0,100},(' + ident + r')\),_\.' + ident + r'=function\(\)\{'
            + re.escape(sink) + r'\(this\.(' + ident + r')\.(' + ident + r'),this\.\2\.(' + ident
            + r'),this\.(' + ident + r'),null,' + ident + r'\(this\.\2\)\)\}')
        for callback in re.finditer(callback_pattern, source):
            constructor, owner_property, _, entry_property, selector_property = callback.groups()
            if not re.search(r'\.' + re.escape(entry_property) + r'=40021\b', source):
                continue
            constructor_data = functions.get(constructor)
            if constructor_data is None or len(constructor_data[0]) != 2:
                continue
            owner, selector = constructor_data[0]
            expected = 'this.' + owner_property + '=' + owner + ',this.' + selector_property + '=' + selector
            if constructor_data[1] != expected:
                continue
            for dispatch, (dispatch_args, dispatch_body) in functions.items():
                if len(dispatch_args) != 2:
                    continue
                adapter, mode = map(re.escape, dispatch_args)
                transfer = re.fullmatch(r'var (' + ident + r');\1=(' + ident + r')\(' + adapter
                    + r'\.' + ident + ',' + mode + r'\),' + ident + r'\(' + adapter + r'\.' + ident
                    + ',new ' + re.escape(constructor) + r'\(' + adapter + r',\1\)\)', dispatch_body)
                if transfer is None:
                    continue
                resolver = functions.get(transfer[2])
                if resolver is None or len(resolver[0]) != 2:
                    continue
                context, selected = map(re.escape, resolver[0])
                for default in defaults:
                    resolved = re.fullmatch(r'var (' + ident + r');return ' + ident + r'\(' + re.escape(default)
                        + ',' + selected + r'\)&&\(\1=(' + ident + r')\(' + context + r'\),\1\?'
                        + selected + r'=\1\.(' + ident + r'):[\s\S]{1,1000}\),' + selected, resolver[1])
                    if resolved is None or resolved[3] not in name_properties:
                        continue
                    lookup = functions.get(resolved[2])
                    if lookup is None or lookup[1].count('.vd(') != 2:
                        continue
                    # The regular spin model initializes this field to default
                    # and forwards it unchanged into the bound dispatcher.
                    for _, (_, init_body) in functions.items():
                        for initialized in re.finditer(r'this\.(' + ident + r')=' + re.escape(default) + r'(?=[,;]|$)', init_body):
                            forwarded = any(len(a) >= 1 and re.search(re.escape(dispatch) + r'\('
                                + re.escape(a[0]) + r'\.' + ident + ',' + re.escape(a[0]) + r'\.'
                                + re.escape(initialized[1]) + r'\)', b) for a, b in functions.values())
                            if forwarded:
                                return {'profile': 'compiled-default-cost-name/v1',
                                        'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
                                        'cost_name_property': resolved[3]}
    return {}
