"""Source-bound recognition of a synchronous prefix in a TS async lifecycle.

Only the canonical awaiter is recognized. Restore is removed only after tracing
GAME -> model.onGame -> an explicit reset, never from a missing wire field.
An unresolved yield, callback, override or Action Spins branch stays unresolved.
"""
import re
from .static_bindings import IDENT,class_record,inherited_methods,module_id,_module_headers
from .direct_demo import members
from .lifecycle import expressions,conditional_arms,proves_zero_bet,_paren_end


def _owner(source,position,block):
    headers=_module_headers(source)
    candidates=[item for item in headers if item.end()<=position]
    if not candidates:return None
    header=candidates[-1];body=block(source,header.end()-1,len(source))
    if not body or position>=header.end()-1+len(body):return None
    return header,body,headers


def _import(source,position,reference,block):
    owner=_owner(source,position,block)
    if not owner or not owner[0][4] or '.' not in reference:return None
    header,body,headers=owner;alias,name=reference.split('.',1)
    prefix=body[:position-header.end()+1]
    writes=list(re.finditer(r'(?<![\w$.])'+re.escape(alias)+r'\s*=(?!=)',prefix))
    imports=list(re.finditer(r'(?<![\w$.])'+re.escape(alias)+'='+re.escape(header[4])+r'\(([0-9]+(?:e[0-9]{1,3})?)\)',prefix))
    if len(writes)!=1 or len(imports)!=1:return None
    targets=[item for item in headers if module_id(item[1])==module_id(imports[0][1])]
    if len(targets)!=1:return None
    target=targets[0];content=block(source,target.end()-1,len(source))
    return (target,content,name) if content else None


def _aliases(text,seeds):
    result=set(seeds)
    while True:
        references='(?:'+'|'.join(re.escape(value) for value in result)+')'
        found={match[1] for match in re.finditer(r'(?<![\w$.])('+IDENT+r')='+references+r'(?=[,;}])',text)}
        if found<=result:return result
        result.update(found)
        if len(result)>64:return None


def _writes(text,references,field):
    names='(?:'+'|'.join(re.escape(value) for value in references)+')'
    property_name=r'(?:\.'+re.escape(field)+r'|\[["\']'+re.escape(field)+r'["\']\])'
    return list(re.finditer(r'(?<![\w$.])'+names+property_name+r'\s*(?:[+*/&|?^\-]?=(?!=)|\+\+|--)',text))


def _game_event(source,position,reference,block):
    imported=_import(source,position,reference,block)
    if not imported:return False
    header,body,name=imported;export=re.escape(header[3])+r'\.'+re.escape(name)
    initialized=re.search(r'\(('+IDENT+r')='+export+r'\|\|\('+export+r'=\{\}\)\)',body)
    if not initialized:return False
    normalized=body[:initialized.start()]+initialized[1]+body[initialized.end():]
    names=_aliases(normalized,{initialized[1],header[3]+'.'+name})
    if names is None:return False
    writes=_writes(normalized,names,'GAME')
    return len(writes)==1 and bool(re.match(r'"game"(?=[,;}]|$)',normalized[writes[0].end():]))


def _canonical_awaiter(body):
    identifier=IDENT
    # Named backreferences describe the actual control flow, independent of
    # minifier identifiers. The helper must eagerly call generator.next(), and
    # all continuation and rejection paths must preserve the standard driver.
    pattern=(r'\{return new\((?P<p>'+identifier+r')\|\|\((?P=p)=Promise\)\)\(function\((?P<ok>'+identifier+r'),(?P<err>'+identifier+r')\)\{'
        r'function (?P<yes>'+identifier+r')\((?P<a>'+identifier+r')\)\{try\{(?P<step>'+identifier+r')\((?P<gen>'+identifier+r')\.next\((?P=a)\)\)\}catch\((?P<ae>'+identifier+r')\)\{(?P=err)\((?P=ae)\)\}\}'
        r'function (?P<no>'+identifier+r')\((?P<b>'+identifier+r')\)\{try\{(?P=step)\((?P=gen)\.throw\((?P=b)\)\)\}catch\((?P<be>'+identifier+r')\)\{(?P=err)\((?P=be)\)\}\}'
        r'function (?P=step)\((?P<result>'+identifier+r')\)\{var (?P<temp>'+identifier+r');(?P=result)\.done\?(?P=ok)\((?P=result)\.value\):\((?P=temp)=(?P=result)\.value,(?P=temp) instanceof (?P=p)\?(?P=temp):new (?P=p)\(function\((?P<adopt>'+identifier+r')\)\{(?P=adopt)\((?P=temp)\)\}\)\)\.then\((?P=yes),(?P=no)\)\}'
        r'(?P=step)\(\((?P=gen)=(?P=gen)\.apply\((?P<self>'+identifier+r'),(?P<args>'+identifier+r')\|\|\[\]\)\)\.next\(\)\)\}\)\}')
    match=re.fullmatch(pattern,body)
    if not match:return None
    outer=[match[name] for name in ('self','args','p','gen','ok','err','yes','no','step')]
    if len(set(outer))!=len(outer):return None
    if any(match[name] in (match['step'],match['gen'],match['err']) for name in ('a','b')):return None
    if any(match[name]==match['err'] for name in ('ae','be')):return None
    if any(match[name] in (match['p'],match['ok'],match['yes'],match['no']) for name in ('result','temp')):return None
    if match['temp']==match['result'] or match['adopt']==match['temp']:return None
    return match


def _awaiter(source,position,name,block,generator):
    owner=_owner(source,position,block)
    if not owner:return False
    header,body,_=owner;prefix=body
    matches=list(re.finditer(r'var '+re.escape(name)+r'=this&&this\.__awaiter\|\|function\(('+IDENT+r'),('+IDENT+r'),('+IDENT+r'),('+IDENT+r')\)\{',prefix))
    if len(matches)!=1:return False
    match=matches[0]
    if not re.fullmatch(r'\{(?:[\"\']use strict[\"\'];)?',prefix[:match.start()]):return False
    if header.end()-1+match.start()>=position:return False
    implementation=block(prefix,match.end()-1,len(prefix))
    recognized=_canonical_awaiter(implementation or '')
    if not recognized:return False
    if tuple(match.groups())!=(recognized['self'],recognized['args'],recognized['p'],recognized['gen']):return False
    # The fallback declaration and its internals are a single validated unit.
    residual=prefix[:match.start()]+prefix[match.end()-1+len(implementation):]
    callback='function*()'+generator
    if residual.count(callback)!=1:return False
    residual=residual.replace(callback,'__bound_callback',1)
    return not re.search(r'(?<![\w$.])'+re.escape(name)+r'\s*=(?!=)|\.__awaiter\s*=(?!=)',residual)


def _same_class(source,position,reference,target,block):
    record=class_record(source,position,reference,block)
    return bool(record and record[2]==target[2])


def _class_unmodified(source,record,block,*,methods=(),statics=()):
    """Check the actual defining module for late class/prototype overrides."""
    owner=_owner(source,record[2],block)
    if not owner:return False
    header,module,_=owner
    prefix=source[max(0,record[2]-200):record[2]]
    named=re.search(r'class ('+IDENT+r')(?: extends '+IDENT+r'\.'+IDENT+r')?$',prefix)
    anonymous=re.search(r'('+IDENT+r'\.'+IDENT+r')=class$',prefix)
    if named:
        seeds={named[1]}
        seeds.update(match[1] for match in re.finditer(r'('+re.escape(header[3])+r'\.'+IDENT+r')='+re.escape(named[1])+r'(?=[,;}])',module))
        start=record[2]-(header.end()-1)
        lexical=module[:start]+'__class_body'+module[start+len(record[0]):]
        if re.search(r'(?<![\w$.])'+re.escape(named[1])+r'\s*=(?!=)',lexical):return False
    elif anonymous:seeds={anonymous[1]}
    else:return False
    aliases=_aliases(module,seeds)
    if aliases is None or _writes(module,aliases,'prototype'):return False
    prototypes=_aliases(module,{alias+'.prototype' for alias in aliases})
    if prototypes is None:return False
    for name in methods:
        if _writes(module,prototypes,name):return False
    for name in statics:
        if _writes(module,aliases,name):return False
    # Reflection-based overrides do not have the ordinary assignment shape.
    targets='(?:'+'|'.join(re.escape(value) for value in aliases|prototypes)+')'
    if re.search(r'Object\.(?:assign|defineProperty|defineProperties|setPrototypeOf)\('+targets+r'(?=[,)])',module):return False
    return True


def _model(source,position,game_reference,block):
    game=class_record(source,position,game_reference,block)
    if not game or not _class_unmodified(source,game,block,statics=('getParsedData',)):return None
    prefix=source[max(0,game[2]-200):game[2]]
    name=re.search(r'class ('+IDENT+r')(?: extends '+IDENT+r'\.'+IDENT+r')?$',prefix)
    if not name:return None
    instances=list(re.finditer(re.escape(name[1])+r'\.model=new ('+IDENT+r'\.'+IDENT+r')\(',game[0]))
    if len(instances)!=1:return None
    owner=_owner(source,game[2],block)
    if not owner:return None
    aliases=[name[1]]+[match[1] for match in re.finditer(r'('+re.escape(owner[0][3])+r'\.'+IDENT+r')='+re.escape(name[1])+r'(?=[,;}])',owner[1])]
    aliases=_aliases(owner[1],aliases)
    if aliases is None:return None
    writes=_writes(owner[1],aliases,'model')
    if len(writes)!=1:return None
    model=class_record(source,game[2]+instances[0].start(),instances[0][1],block)
    return (game,model) if model else None


def _processed_model(source,position,game_reference,block,action_spins_active):
    resolved=_model(source,position,game_reference,block)
    if not resolved:return None
    game,model=resolved
    if not _class_unmodified(source,model,block,methods=('onGame','isRestore','parsedGameData')):return None
    available=members(model[0],block)
    if not available or 'onGame' not in available or not model[1]:return None
    parent=class_record(source,model[2],model[1],block)
    if not parent or parent[1] or not _class_unmodified(source,parent,block,methods=('onGame','isRestore','parsedGameData')):return None
    base=members(parent[0],block)
    if not base or 'constructor' not in base:return None
    if any(name in candidate for name in ('get isRestore','set isRestore','get parsedGameData','set parsedGameData') for candidate in (available,base)):return None
    args,constructor=base['constructor'];parameter=args.split(',')[0]
    event=None
    for part in expressions(constructor):
        event=re.fullmatch(re.escape(parameter)+r'\.events\.on\(('+IDENT+r'\.'+IDENT+r')\.GAME,('+IDENT+r')=>this\.onGame\(\2\)\)',part)
        if event:break
    if not event or not _game_event(source,parent[2],event[1],block):return None
    for candidate in (constructor,available.get('constructor',('', ''))[1]):
        aliases=_aliases(candidate,{'this'})
        if aliases is None or _writes(candidate,aliases,'onGame'):return None
    args,on_game=available['onGame'];parameter=args
    if not re.fullmatch(IDENT,parameter):return None
    # Two observed Action Spins variants. Neither is assumed inactive merely
    # because the wire response omitted an Action Spins property.
    early=re.match(r'if\(('+IDENT+r'\.'+IDENT+r')\.isActionSpinsActive\)return ',on_game)
    if early:
        if action_spins_active is not False or not _same_class(source,model[2],early[1],game,block):return None
        end=on_game.find(';',early.end())
        if end<0:return None
        on_game=on_game[end+1:]
    disjunction=re.fullmatch(r'('+IDENT+r'\.'+IDENT+r')\.isActionSpinsActive\|\|\((.*)\)',on_game,re.S)
    if disjunction:
        if action_spins_active is not False or not _same_class(source,model[2],disjunction[1],game,block):return None
        on_game=disjunction[2]
    parts=expressions(on_game)
    reset='this.isRestore=!1';parsed=None
    if reset not in parts or not any(part=='super.onGame('+parameter+')' for part in parts):return None
    aliases=_aliases(on_game,{'this'})
    if aliases is None:return None
    restore_writes=_writes(on_game,aliases,'isRestore')
    parsed_writes=_writes(on_game,aliases,'parsedGameData')
    if len(restore_writes)!=1 or not on_game[restore_writes[0].end():].startswith('!1,') or len(parsed_writes)!=1:return None
    if re.search(r'\b(if|return|throw|yield)\b',on_game):return None
    for part in parts[:parts.index(reset)]:
        match=re.fullmatch(r'this\.parsedGameData=new ('+IDENT+r'\.'+IDENT+r')\('+re.escape(parameter)+r'(?:,this\.\w+)?\)',part)
        if match:parsed=class_record(source,model[2],match[1],block)
    if not parsed:return None
    return game,model,parsed


def _false_flag(source,position,expression,block,action_spins_active,aliases):
    direct=re.fullmatch(r'('+IDENT+r'\.'+IDENT+r')\.model\.isRestore',expression)
    if direct:return bool(_processed_model(source,position,direct[1],block,action_spins_active))
    alias=re.fullmatch(r'('+IDENT+r')\.isRestoreState',expression)
    if not alias or alias[1] not in aliases:return False
    reference=aliases[alias[1]]
    resolved=_processed_model(source,position,reference,block,action_spins_active)
    if not resolved:return False
    game,model,parsed=resolved
    getter=re.search(r'static getParsedData\(\)\{',game[0])
    if not getter:return False
    value=block(game[0],getter.end()-1,len(game[0]))
    prefix=source[max(0,game[2]-200):game[2]];named=re.search(r'class ('+IDENT+r')(?: extends '+IDENT+r'\.'+IDENT+r')?$',prefix)
    if not named or value!='{return '+named[1]+'.model.parsedGameData?'+named[1]+'.model.parsedGameData:'+named[1]+'.model.parsedInitData}':return False
    if not _class_unmodified(source,parsed,block,methods=('isRestoreState',)):return False
    available=members(parsed[0],block)
    if available and any(name in available for name in ('get isRestoreState','set isRestoreState')):return False
    constructor=available.get('constructor') if available else None
    if not constructor:return False
    aliases=_aliases(constructor[1],{'this'})
    if aliases is None:return False
    writes=_writes(constructor[1],aliases,'isRestoreState')
    return len(writes)==1 and bool(re.match(r'!1(?=[,;}]|$)',constructor[1][writes[0].end():]))


def _declarations(text):
    """Keep the declaration kind on each root comma-separated binding."""
    output=[]
    # expressions() splits commas and semicolons; each subsequent bare binding
    # is promoted only when a declaration has already introduced its local name.
    declaration=None
    for part in expressions(text):
        match=re.match(r'(const|let|var) ',part)
        if match:declaration=match[1]
        elif declaration and re.match(IDENT+r'=(?:new '+IDENT+r'\.TimelineLite)',part):part=declaration+' '+part
        output.append(part)
    return ';'.join(output)


def proves_async_zero_bet(source,position,reference,answer,block,*,action_spins_active=None,direct_demo_transport=False):
    """Prove one bound async start; optional context must come from the caller."""
    game=answer.get('game') if isinstance(answer,dict) else None
    if not isinstance(game,dict) or not all(isinstance(game.get(field),str) for field in ('mode','nextMode')):return False
    available=inherited_methods(source,position,reference,block)
    if not available or 'start' not in available:return False
    # The recognized async presentations have no construction-time effects.
    # Unknown constructors could replace a module-local helper before start.
    constructor=available.get('constructor')
    if constructor and constructor[1]:return False
    args,start,offset=available['start']
    prefix=re.match(r'return ('+IDENT+r')\(this,void 0,void 0,function\*\(\)\{',start)
    if not prefix:return False
    generator=block(start,prefix.end()-1,len(start))
    if not generator or start[prefix.end()-1+len(generator):]!=')':return False
    if not _awaiter(source,offset,prefix[1],block,generator):return False
    body=generator[1:-1];aliases={}
    model_refs={match[1] for match in re.finditer(r'('+IDENT+r'\.'+IDENT+r'\.model)\.isRestore\b',body)}
    if any(_writes(body,{reference},'isRestore') for reference in model_refs):return False
    for item in expressions(body):
        alias=re.match(r'(?:const|let|var) ('+IDENT+r')=('+IDENT+r'\.'+IDENT+r')\.getParsedData\(\)$',item)
        if alias:
            name=alias[1]
            if len(re.findall(r'(?<![\w$.])'+re.escape(name)+r'\s*=(?!=)',body))!=1:return False
            if _writes(body,{name},'isRestoreState'):return False
            residual=body.replace(item,'',1)
            residual=re.sub(r'(?<![\w$.])'+re.escape(name)+r'\.'+IDENT,'__read',residual)
            if re.search(r'(?<![\w$.])'+re.escape(name)+r'(?![\w$])',residual):return False
            aliases[name]=alias[2]
    if action_spins_active is None and direct_demo_transport is True:
        from .action_spins_context import proves_action_spins_inactive
        owners={value.rsplit('.model',1)[0] for value in model_refs}|set(aliases.values())
        if len(owners)==1 and proves_action_spins_inactive(source,offset,next(iter(owners)),block,direct_demo_transport=True):
            action_spins_active=False
    normalized=[]
    for part in expressions(_declarations(body)):
        guard=re.match(r'('+IDENT+r'\.'+IDENT+r'\.model\.isRestore|'+IDENT+r'\.isRestoreState)(?=&&|\?)',part)
        if guard and _false_flag(source,offset,guard[1],block,action_spins_active,aliases):
            rest=part[guard.end():]
            if rest.startswith('&&'):continue
            arms=conditional_arms(part)
            if not arms:return False
            normalized.append(arms[1]);continue
        normalized.append(part)
    text=';'.join(normalized)
    if re.search(r'\byield\b',text):return False
    synthetic='{start('+args+'){'+text+'}}'
    return proves_zero_bet(synthetic,block)
