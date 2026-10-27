"""Bounded static script-loader expressions. No JavaScript is executed."""
import ast
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
