"""Resolve bounded CommonJS webpack bindings without executing client code."""
import re
from functools import lru_cache

IDENT = r"[A-Za-z_$][\w$]*"


@lru_cache(maxsize=2)
def _module_headers(source):
    # Immutable source indexes may be reused across hundreds of free spins.
    # Retain only the current and previous client, not a catalog of bundles.
    return tuple(re.finditer(r"(?:^|[,{])([0-9]+(?:e[0-9]{1,3})?)(?::function|:)?\(("+IDENT+r"),("+IDENT+r")(?:,("+IDENT+r"))?\)(?:=>)?\{",source))


def module_id(value):
    coefficient,separator,exponent=value.partition('e')
    return int(coefficient)*10**int(exponent or '0')


def bound_class(source, position, reference, block):
    """Resolve an imported class only inside the containing webpack module."""
    headers=_module_headers(source)
    owners=[m for m in headers if m.end()<=position]
    if not owners:return None
    owner=owners[-1]; body=block(source,owner.end()-1,len(source))
    if not body or position>=owner.end()-1+len(body):return None
    if not owner[4]:return None
    alias,name=reference.split('.',1)
    prefix=body[:position-owner.end()+1]
    imports=list(re.finditer(r"(?<![\w$.])"+re.escape(alias)+r"="+re.escape(owner[4])+r"\(([0-9]+(?:e[0-9]{1,3})?)\)",body[:position-owner.end()+1]))
    if len(imports)!=1:return None
    if len(re.findall(r"(?<![\w$.])"+re.escape(alias)+r"\s*=(?!=)",prefix))!=1:return None
    targets=[m for m in headers if module_id(m[1])==module_id(imports[0][1])]
    if len(targets)!=1:return None
    target=targets[0]; content=block(source,target.end()-1,len(source))
    if not content:return None
    exported=re.escape(target[3])+r"\."+re.escape(name)
    effective=re.sub(r"(?:"+re.escape(target[3])+r"\."+IDENT+r"=)+void 0(?=[,;])", "", content)
    if len(re.findall(exported+r"=(?!=)",effective))!=1:return None
    direct=list(re.finditer(exported+r"=class\{",content))
    if len(direct)==1:return block(content,direct[0].end()-1)
    aliases=list(re.finditer(exported+r"=("+IDENT+r")(?=[,;}])",content))
    if len(aliases)!=1:return None
    definitions=list(re.finditer(r"class "+re.escape(aliases[0][1])+r"\{",content[:aliases[0].start()]))
    if len(definitions)!=1:return None
    return block(content,definitions[0].end()-1)


def proves_wrapped_flow(source,position,wrapper,items,block):
    from .lifecycle import methods,proves_zero_bet
    implementation=bound_class(source,position,wrapper,block)
    if not implementation:return False
    # Exact synchronous wrapper: running its input is its active start action.
    shape=(r"\{static createFlow\((\w+)\)\{return\{start:(\w+)=>\w+\.SimplePresentationRunner\.run\(\1,\(\)=>\2\.finish\(\),(\w+)=>\2\.setSkipCallback\(\3\)\)\}\}\}")
    if not re.fullmatch(shape,implementation):return False
    # Only a sole presentation is accepted. Earlier unknown presentations could
    # stall, and conditional shouldRun must never authorize a zero bet.
    item=re.fullmatch(r"new ("+IDENT+r"\."+IDENT+r")(?:\(\))?",items)
    if not item:return False
    implementation=bound_class(source,position,item[1],block)
    if not implementation:return False
    available=methods(implementation,block)
    if available.get('shouldRun') not in (('', 'return!0'),('', 'return true')):return False
    return proves_zero_bet(implementation,block)


def class_record(source,position,reference,block):
    """Return class body, parent reference and its lexical definition offset."""
    headers=_module_headers(source)
    owners=[m for m in headers if m.end()<=position]
    if not owners:return None
    owner=owners[-1];content=block(source,owner.end()-1,len(source))
    if not content or position>=owner.end()-1+len(content):return None
    if '.' in reference:
        if not owner[4]:return None
        alias,name=reference.split('.',1);prefix=content[:position-owner.end()+1]
        imports=list(re.finditer(r"(?<![\w$.])"+re.escape(alias)+r"="+re.escape(owner[4])+r"\(([0-9]+(?:e[0-9]{1,3})?)\)",prefix))
        if len(imports)!=1 or len(re.findall(r"(?<![\w$.])"+re.escape(alias)+r"\s*=(?!=)",prefix))!=1:return None
        targets=[m for m in headers if module_id(m[1])==module_id(imports[0][1])]
        if len(targets)!=1:return None
        owner=targets[0];content=block(source,owner.end()-1,len(source))
        if not content:return None
        export=re.escape(owner[3])+r"\."+re.escape(name)
        effective=re.sub(r"(?:"+re.escape(owner[3])+r"\."+IDENT+r"=)+void 0(?=[,;])", "", content)
        if len(re.findall(export+r"=(?!=)",effective))!=1:return None
        definitions=list(re.finditer(export+r"=class(?: extends ("+IDENT+r"\."+IDENT+r"))?\{",content))
        if definitions:
            if len(definitions)!=1:return None
            definition=definitions[0];offset=owner.end()-1+definition.end()-1
            return block(source,offset,len(source)),definition[1],offset
        aliases=list(re.finditer(export+r"=("+IDENT+r")(?=[,;}])",content))
        if len(aliases)!=1:return None
        reference=aliases[0][1]
    definitions=list(re.finditer(r"class "+re.escape(reference)+r"(?: extends ("+IDENT+r"\."+IDENT+r"))?\{",content))
    if len(definitions)!=1:return None
    definition=definitions[0];offset=owner.end()-1+definition.end()-1
    return block(source,offset,len(source)),definition[1],offset


def inherited_methods(source,position,reference,block,depth=0):
    from .lifecycle import methods
    if depth>5:return None
    record=class_record(source,position,reference,block)
    if not record or not record[0]:return None
    body=record[0];accessors=[]
    # Preserve accessor override information while presenting ordinary methods
    # to the lifecycle recognizer. A getter is never treated as a method call.
    pieces=[];cursor=1
    while cursor<len(body)-1:
        member=re.match(r'(?:(get|set) )?([\w$]+)\(([^)]*)\)\{',body[cursor:])
        if not member:return None
        value=block(body,cursor+member.end()-1)
        if not value:return None
        if member[1]:accessors.append(member[2])
        else:pieces.append(body[cursor:cursor+member.end()-1+len(value)])
        cursor+=member.end()-1+len(value)
    own=methods('{'+''.join(pieces)+'}',block)
    if not own and not accessors:return None
    inherited={}
    if record[1]:
        inherited=inherited_methods(source,record[2],record[1],block,depth+1)
        if inherited is None:return None
    for name in accessors:
        if name in inherited or name in ('start','shouldRun','buildTimeline'):return None
    inherited.update({name:(args,body,record[2]) for name,(args,body) in own.items()})
    constructor=inherited.get("constructor")
    if constructor:
        for name in inherited:
            if re.search(r"this\."+re.escape(name)+r"\s*=(?!=)",constructor[1]):return None
    return inherited


def enum_literal(source,position,reference,block,depth=0):
    if depth>5:return None
    owner,field=reference.rsplit('.',1)
    record=class_record(source,position,owner,block)
    if not record:return None
    # Static assignments are read only in this exact defining module.
    prefix=source[max(0,record[2]-150):record[2]]
    named=re.search(r'class ('+IDENT+r')(?: extends '+IDENT+r'\.'+IDENT+r')?$',prefix)
    if not named:return None
    headers=_module_headers(source)
    enclosing=[m for m in headers if m.end()<=record[2]]
    if not enclosing:return None
    content=block(source,enclosing[-1].end()-1,len(source))
    if not content:return None
    writes=list(re.finditer(r'(?<![\w$])'+re.escape(named[1])+r'\.'+re.escape(field)+r'=(?!=)([^,;}]+)',content))
    if writes:
        if len(writes)!=1:return None
        literal=re.fullmatch(r'"([A-Z_]+)"',writes[0][1])
        return literal[1] if literal else None
    if record[1]:return enum_literal(source,record[2],record[1]+'.'+field,block,depth+1)
    return None


def inactive_guard(body,game,source=None,position=None,block=None):
    """Prove a false, side effect free conjunction over server fields."""
    if not body.startswith('return '):return False
    values=[]
    model=r'[\w$.]+\.model\.(?:data\.)?'
    for clause in body[7:].split('&&'):
        match=re.fullmatch(model+r'(mode|nextMode)(?:\.toString\(\))?\.includes\(([^()]+)\)',clause)
        if match:
            literal=re.fullmatch(r'"([A-Z_]+)"',match[2])
            value=literal[1] if literal else enum_literal(source,position,match[2],block) if source else None
            if value is None or not isinstance(game.get(match[1]),str):return False
            values.append(value in game[match[1]]);continue
        equality=re.fullmatch(r'([\w$]+\.[\w$]+\.[\w$]+)==='+model+r'(mode|nextMode)',clause)
        if equality and source:
            value=enum_literal(source,position,equality[1],block)
            if value is None or not isinstance(game.get(equality[2]),str):return False
            values.append(value==game[equality[2]]);continue
        boolean=re.fullmatch(r'!'+model+r'(\w+)',clause)
        if boolean:
            value=game.get(boolean[1]);values.append(not value if type(value) is bool else None);continue
        return False
    return bool(values) and False in values


def proves_bound_action(source,position,reference,answer,block,depth=0,*,direct_demo_transport=False):
    from .lifecycle import proves_zero_bet
    if depth>3:return False
    available=inherited_methods(source,position,reference,block)
    if not available:return False
    guard=available.get('shouldRun')
    if guard and guard[:2] not in (('', 'return!0'),('', 'return true')):return False
    bound_available=available
    normalized={}
    runner_shape=(r'\{static run\((\w+),(\w+),(\w+)\)\{const (\w+)=\1\.concat\(\),(\w+)=\4\.shift\(\);null==\5\?\2\(\):\5\.shouldRun\(\)\?\5\.start\(\{finish:\(\)=>(\w+)\.run\(\4,\2,\3\),setSkipCallback:\3\}\):\6\.run\(\4,\2,\3\)\}\}')
    for name,(args,body,offset) in available.items():
        for call in list(re.finditer(r'([\w$]+\.[\w$]+)\.run\(',body)):
            implementation=bound_class(source,offset,call[1],block)
            if implementation and re.fullmatch(runner_shape,implementation):
                body=body.replace(call[1]+'.run(', 'known.SimplePresentationRunner.run(')
        normalized[name]=(args,body,offset)
    available=normalized
    flattened='{'+''.join(name+'('+args+'){'+body+'}' for name,(args,body,offset) in available.items())+'}' 
    if proves_zero_bet(flattened,block):return True
    from .async_lifecycle import proves_async_zero_bet
    if proves_async_zero_bet(source,position,reference,answer,block,direct_demo_transport=direct_demo_transport):return True
    # This exact inherited start creates and plays this.tl, then invokes the
    # active buildTimeline override. No phase or class name grants permission.
    start=available.get('start');build=available.get('buildTimeline')
    base=(r'this\.controller=(\w+),this\.tl=\w+\.gsap\.timeline\(\{onComplete:\(\)=>\{\1\.setSkipCallback\(\),\1\.finish\(\)\}\}\),this\.createSkipCallback&&this\.tl\.add\(\(\)=>\{this\.controller\.setSkipCallback\(\(\)=>\{this\.skip\(\)\}\)\},\.1\),this\.buildTimeline\(\)')
    from .presentation_progression import active_timeline_body
    body=active_timeline_body(available)
    if body is not None and proves_zero_bet('{start(){'+body+'}}',block):return True
    from .presentation_progression import proves_presentation_progression
    if proves_presentation_progression(source,bound_available,answer,block,depth):return True
    if not start:return False
    runner=re.fullmatch(r'(?:this\.\w+=\w+,)?\w+\.SimplePresentationRunner\.run\(this\.(\w+),\(\)=>[^;]+\)',start[1])
    constructor=available.get('constructor')
    if not runner or not constructor:return False
    assignments=list(re.finditer(r'this\.'+re.escape(runner[1])+r'=\[([^\]]{1,1600})\]',constructor[1]))
    if not assignments:return False
    residual=re.sub(r'this\.'+re.escape(runner[1])+r'=\[[^\]]{0,1600}\]','__array_assignment',constructor[1])
    if re.search(r'this\.'+re.escape(runner[1])+r'\b',residual):return False
    for item in assignments[-1][1].split(','):
        match=re.fullmatch(r'new ('+IDENT+r'(?:\.'+IDENT+r')?)(?:\(\))?',item)
        if not match:return False
        child=inherited_methods(source,constructor[2],match[1],block)
        if not child:return False
        condition=child.get('shouldRun')
        if condition and inactive_guard(condition[1],answer.get('game') or {},source,condition[2],block):continue
        return proves_bound_action(source,constructor[2],match[1],answer,block,depth+1,direct_demo_transport=direct_demo_transport)
    return False
