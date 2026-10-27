"""Conservative normalization of client lifecycle effects.

Only root expressions and known callback lifecycles are traversed. An effect
inside a condition, ternary, paused timeline or unknown callback is not proof.
This is a recognizer, not a JavaScript interpreter.
"""
import re


def expressions(text):
    """Split root comma/semicolon expressions, respecting strings and ternaries."""
    stack=[];quote=None;escaped=False;ternary=0;start=0;out=[];i=0
    while i<len(text):
        char=text[i]
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
        elif char in ('"',"'",'`'):quote=char
        elif text.startswith('//',i):return []
        elif text.startswith('/*',i):return []
        elif char in '([{':stack.append(char)
        elif char in ')]}':
            if not stack or '([{'.index(stack.pop())!=')]}'.index(char):return []
        elif not stack:
            if char=='?' and text[i:i+2] not in ('?.','??') and text[max(0,i-1):i+1]!='??':ternary+=1
            elif char==':' and ternary:ternary-=1
            elif char==';' or char==',' and not ternary:
                out.append(text[start:i].strip());start=i+1
                if char==';':ternary=0
        i+=1
    if quote or stack or ternary:return []
    out.append(text[start:].strip())
    return [part for part in out if part]


def conditional_arms(text):
    """Find both arms of one root ternary without evaluating its condition."""
    stack=[];quote=None;escaped=False;question=None;nested=0
    for i,char in enumerate(text):
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
        elif char in ('"',"'",'`'):quote=char
        elif char in '([{':stack.append(char)
        elif char in ')]}':
            if not stack or '([{'.index(stack.pop())!=')]}'.index(char):return None
        elif not stack:
            if text[i:i+2]=='=>':return None
            if char=='?' and text[i:i+2] not in ('?.','??') and text[max(0,i-1):i+1]!='??':
                if question is None:question=i
                else:nested+=1
            elif char==':' and question is not None:
                if nested:nested-=1
                else:return text[question+1:i].strip(),text[i+1:].strip()
    return None


def methods(body,block):
    result={};i=1
    while i<len(body)-1:
        match=re.match(r'(\w+)\(([^)]*)\)\{',body[i:])
        if not match:return {}
        value=block(body,i+match.end()-1)
        if not value:return {}
        if match[1] in result:return {}
        result[match[1]]=(match[2],value[1:-1]);i+=match.end()-1+len(value)
    return result


def _paren_end(text,start):
    stack=[];quote=None;escaped=False
    for index in range(start,len(text)):
        char=text[index]
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
        elif char in ('"',"'",'`'):quote=char
        elif char in '([{':stack.append(char)
        elif char in ')]}':
            if not stack or '([{'.index(stack.pop())!=')]}'.index(char):return None
            if not stack:return index
    return None


def _without_shadowed_arrows(text,name):
    """Ignore lexical uses of a callback parameter that shadows an outer alias."""
    pattern=re.compile(r'(?<![\w$.])(?:'+re.escape(name)+r'|\('+re.escape(name)+r'\))=>')
    out=[];cursor=0;quote=None;escaped=False;i=0
    while i<len(text):
        char=text[i]
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
            i+=1;continue
        if char in ('"',"'",'`'):quote=char;i+=1;continue
        match=pattern.match(text,i)
        loop=re.match(r'for\(let '+re.escape(name)+r'=[0-9]+;'+re.escape(name)+r'<=[0-9]+;'+re.escape(name)+r'\+\+\)',text[i:])
        if not match and not loop:i+=1;continue
        start=match.end() if match else i+loop.end()
        if start<len(text) and text[start]=='{':
            end=_paren_end(text,start)
            if end is None:return text
            end+=1
        else:
            end=start;stack=[];inner_quote=None;inner_escaped=False
            while end<len(text):
                value=text[end]
                if inner_quote:
                    if inner_escaped:inner_escaped=False
                    elif value=='\\':inner_escaped=True
                    elif value==inner_quote:inner_quote=None
                elif value in ('"',"'",'`'):inner_quote=value
                elif value in '([{':stack.append(value)
                elif value in ')]}':
                    if not stack:break
                    if '([{'.index(stack.pop())!=')]}'.index(value):return text
                elif value in ',;' and not stack:break
                end+=1
        out.extend([text[cursor:i],'__shadowed_callback']);cursor=end;i=end
    return ''.join(out)+text[cursor:]


def expanded_expressions(text):
    """Separate self-returning GSAP chains without swallowing unknown methods."""
    result=[]
    for part in expressions(text):
        prefix=re.match(r'(?:(?:const|let|var) (\w+)=|return )((?:\w+\.(?:gsap|default)\.timeline|new \w+\.TimelineLite)\()',part)
        if not prefix:
            root=re.match(r'(\w+)\.(add|addLabel|to|from|fromTo|set)\(',part)
            if not root:result.append(part);continue
            end=_paren_end(part,root.end()-1)
            if end is None:return None
            tail=part[end+1:]
            if not tail:result.append(part);continue
            calls=[part[:end+1]];cursor=0
            while cursor<len(tail):
                method=re.match(r'\.(add|addLabel|to|from|fromTo|set)\(',tail[cursor:])
                if not method:return None
                close=_paren_end(tail,cursor+method.end()-1)
                if close is None:return None
                calls.append(root[1]+tail[cursor:close+1]);cursor=close+1
            result.extend(calls);continue
        end=_paren_end(part,prefix.end()-1)
        if end is None:return None
        tail=part[end+1:]
        if not tail:result.append(part);continue
        name=prefix[1]
        if name is None:
            index=0
            while '__returned_timeline_'+str(index) in text:index+=1
            name='__returned_timeline_'+str(index)
        declaration='const '+name+'='+part[prefix.start(2):end+1]
        calls=[];cursor=0
        while cursor<len(tail):
            method=re.match(r'\.(add|addLabel|to|from|fromTo|set|totalProgress|timeScale|duration)\(',tail[cursor:])
            if not method:return None
            close=_paren_end(tail,cursor+method.end()-1)
            if close is None:return None
            arguments=tail[cursor+method.end():close]
            if method[1]=='timeScale' and (not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',arguments) or float(arguments)<=0):return None
            calls.append(name+tail[cursor:close+1]);cursor=close+1
        result.extend([declaration,*calls])
        if prefix[1] is None:result.append('return '+name)
    return result


def proves_zero_bet(body,block,*,entry="start"):
    available=methods(body,block)
    if not available:return False
    zero=r'[\w$.]+\.betHandler\.zeroBet\(\)'

    def callback(value,depth):
        match=re.fullmatch(r'\(\)=>\{(.*)\}',value,re.S)
        if match:return effects(match[1],depth+1)
        match=re.fullmatch(r'(?:\(\w*\)|\w+)=>(.*)',value,re.S)
        return bool(match and effects(match[1],depth+1))

    def effects(text,depth=0,known_timelines=()):
        if depth>8:return False
        while text.startswith('(') and text.endswith(')') and expressions(text[1:-1]):text=text[1:-1].strip()
        timelines=set(known_timelines);arrays={};parts=expanded_expressions(text)
        if parts is None:return False
        for part in parts:
            if part.startswith('if('):
                end=_paren_end(part,2)
                if end is not None and effects(part[3:end],depth+1,timelines):return True
                return False
            if re.match(r'^(else|for|while|switch|try|do)\b',part):return False
            direct=part.removeprefix('return ').strip()
            if re.fullmatch(zero,direct):return True
            arms=conditional_arms(direct)
            if arms and all(effects(arm,depth+1) for arm in arms):return True
            # An unassigned, playing timeline completes through its declared
            # callback. A paused/cancelled timeline cannot authorize an action.
            completion=re.fullmatch(r'\w+\.gsap\.timeline\(\{(.*)\}\)',direct,re.S)
            config=expressions(completion[1]) if completion else []
            if (len(config)==1 and config[0].startswith('onComplete:')
                    and callback(config[0][len('onComplete:'):],depth)):return True
            # Known methods invoked unconditionally by the active lifecycle.
            invoked=re.fullmatch(r'this\.(\w+)\([^()]*\)',direct)
            if invoked and invoked[1] in available and invoked[1] not in ('start','getAnimation'):
                if effects(available[invoked[1]][1],depth+1):return True
            array=re.fullmatch(r'(?:const|let|var) (\w+)=\[(.*)\]',part,re.S)
            if array:
                name=re.escape(array[1])
                mutated=bool(re.search(r'\b'+name+r'\b',array[2]))
                for other in parts:
                    if other==part or not re.search(r'\b'+name+r'\b',other):continue
                    use=re.fullmatch(r'\w+\.SimplePresentationRunner\.run\('+name+r',(.*)\)',other.removeprefix('return '),re.S)
                    if not use:mutated=True;break
                    for argument in expressions(use[1]):
                        shadow=re.match(r'(?:'+name+r'|\('+name+r'\))=>',argument)
                        if not shadow and re.search(r'\b'+name+r'\b',argument):mutated=True;break
                    if mutated:break
                if not mutated:arrays[array[1]]=expressions(array[2])
                continue
            timeline=re.fullmatch(r'(?:const|let|var) (\w+)=(?:\w+\.(?:gsap|default)\.timeline\((.*)\)|new \w+\.TimelineLite(?:\((.*)\))?)',part,re.S)
            if timeline:
                config=timeline[2] if timeline[2] is not None else timeline[3] or ''
                name=re.escape(timeline[1])
                mutated=any(other!=part and re.search(r'\b'+name+r'(?:\s*=(?![=>])|\.(?:pause|kill|stop|clear|reverse|reversed)\()',_without_shadowed_arrows(other,timeline[1])) for other in parts)
                for other in parts:
                    other=_without_shadowed_arrows(other,timeline[1])
                    if other!=part and re.search(r'\b'+name+r'\b',other):
                        known=re.sub(r'\b'+name+r'\.(?:add|addLabel|to|from|fromTo|set|totalProgress|timeScale|duration)\b','__known_timeline',other)
                        if re.search(r'\b'+name+r'\b',known):mutated=True
                        for call in re.finditer(r'\b'+name+r'\.\w+\(',other):
                            end=_paren_end(other,call.end()-1)
                            if end is None or re.match(r'\s*(?:\?\.|\.|\[)',other[end+1:]):mutated=True
                    for speed in re.finditer(r'\b'+name+r'\.timeScale\(',other):
                        value=re.match(r'([0-9]+(?:\.[0-9]+)?)\)',other[speed.end():])
                        if value is None or float(value[1])<=0:mutated=True

                if not mutated and 'paused' not in config and not re.search(r'\bon(?:Start|Update|Repeat)\b',config):
                    timelines.add(timeline[1])
                    properties=expressions(config[1:-1]) if config.startswith('{') and config.endswith('}') else []
                    if (not re.search(r'\b'+name+r'\b',config) and len(properties)==1 and properties[0].startswith('onComplete:')
                            and callback(properties[0][len('onComplete:'):],depth)):return True
                continue
            added=re.fullmatch(r'(\w+)\.add\((.*)\)',direct,re.S)
            if added and added[1] in timelines:
                args=expressions(added[2])
                if args and callback(args[0],depth):return True
            runner=re.fullmatch(r'\w+\.SimplePresentationRunner\.run\((.*)\)',direct,re.S)
            if runner:
                args=expressions(runner[1])
                if len(args)>=2 and callback(args[1],depth):return True
                if args and args[0] in arrays:
                    for item in arrays[args[0]]:
                        local=re.fullmatch(r'new \w+\.LocalPresentation\((.*)\)',item,re.S)
                        values=expressions(local[1]) if local else []
                        if (len(values)==3 and values[1] in ('()=>!0','()=>true')
                                and re.fullmatch(r'["\'][^"\']*["\']',values[2])
                                and callback(values[0],depth)):return True
                        if local:break # Earlier unknown LocalPresentation may never finish.


            # An earlier return, throw or branch that can exit invalidates later
            # root calls. Conditional UI work without exits does not grant action.
            if re.search(r'\b(return|throw|break|continue)\b',part):return False
        return False

    return entry in available and effects(available[entry][1])
