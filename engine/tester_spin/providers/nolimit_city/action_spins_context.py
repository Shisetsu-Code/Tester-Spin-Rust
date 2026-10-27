"""Inactive Action Spins state for an independently trusted fresh demo transport.

The proof binds the game field, imported event constant, its only update callback
and every event producer. Raw response fields cannot supply caller context.
"""
import re
from functools import lru_cache
from .static_bindings import IDENT,class_record,module_id,_module_headers
from .async_lifecycle import _owner,_import,_aliases,_writes


_FIELD='isActionSpinsActive'
_EVENT='ACTION_SPINS_IS_ACTIVE'


def _event(source,position,reference,block):
    imported=_import(source,position,reference,block)
    if not imported:return None
    header,body,name=imported;export=re.escape(header[3])+r'\.'+re.escape(name)
    initialized=re.search(r'\(('+IDENT+r')='+export+r'\|\|\('+export+r'=\{\}\)\)',body)
    if not initialized:return None
    residual=body[:initialized.start()]+body[initialized.end():]
    residual=re.sub(export+r'=void 0(?=[,;])','',residual)
    if _writes(residual,{header[3]},name) or re.search(r'(?<![\w$.])'+re.escape(initialized[1])+r'\s*=(?!=)',residual):return None
    normalized=body[:initialized.start()]+initialized[1]+body[initialized.end():]
    aliases=_aliases(normalized,{initialized[1],header[3]+'.'+name})
    if aliases is None:return None
    writes=_writes(normalized,aliases,_EVENT)
    if len(writes)!=1 or not re.match(r'"actionSpinsActive"(?=[,;}]|$)',normalized[writes[0].end():]):return None
    return module_id(header[1]),name


def _members(body,offset,block):
    result=[];cursor=1
    while cursor<len(body)-1:
        match=re.match(r'(?:(static) )?(?:(get|set) )?('+IDENT+r')\(([^)]*)\)\{',body[cursor:])
        if not match:return None
        value=block(body,cursor+match.end()-1,len(body))
        if not value:return None
        start=offset+cursor+match.end()-1
        result.append((match[3],match[4],value,start,match[2]))
        cursor+=match.end()-1+len(value)
    return result


def _ui_activation(source,position,event_reference,block):
    owner=_owner(source,position,block)
    if not owner:return False
    header,module,_=owner;class_candidates=[]
    for match in re.finditer(r'\bclass(?: ('+IDENT+r'))?(?: extends '+IDENT+r'(?:\.'+IDENT+r')?)?\{',module):
        body=block(module,match.end()-1,len(module))
        absolute=header.end()-1+match.end()-1
        if body and absolute<position<absolute+len(body):class_candidates.append((body,absolute,match[1]))
    if not class_candidates:return False
    body,offset,class_name=min(class_candidates,key=lambda record:len(record[0]))
    available=_members(body,offset,block)
    if not available:return False
    selected=[member for member in available if member[3]<position<member[3]+len(member[2])]
    if len(selected)!=1 or selected[0][0]=='constructor':return False
    name,args,method,_,_=selected[0]
    # Enabling methods are UI-only SDK operations. No class-local path may
    # call or pass them during construction or any automatic lifecycle.
    if re.search(r'this\.'+re.escape(name)+r'\b|this\s*\[[^\]]+\]',body):return False
    if class_name and re.search(r'(?<![\w$.])'+re.escape(class_name)+r'\.'+re.escape(name)+r'\b',body):return False
    if class_name:
        aliases={class_name}
        aliases.update(match[1] for match in re.finditer(r'('+re.escape(header[3])+r'\.'+IDENT+r')='+re.escape(class_name)+r'(?=[,;}])',module))
        references='(?:'+'|'.join(re.escape(value) for value in aliases)+')'
        if re.search(r'new '+references+r'(?:\([^()]*\))?(?:\.'+re.escape(name)+r'\b|\s*\[[^\]]+\])',module):return False
        instances={match[1] for match in re.finditer(r'(?<![\w$.])('+IDENT+r')=new '+references+r'(?:\([^()]*\))?(?=[,;}])',module)}
        instances=_aliases(module,instances) if instances else set()
        if instances is None:return False
        if instances and re.search(r'(?<![\w$.])(?:'+'|'.join(re.escape(value) for value in instances)+r')(?:\.'+re.escape(name)+r'\b|\s*\[[^\]]+\])',module):return False
    event=re.escape(event_reference)+r'\.'+_EVENT
    maximize=(r'\{this\.newView\.visible=!0,'+IDENT+r'\.NolimitApplication\.addDialog\(this\.newView,!0\),'
        +IDENT+r'\.IS_MINIMIZED=!1,'+IDENT+r'\.apiPlugIn\.events\.trigger\('+event+r',!0\),'
        +IDENT+r'\.apiPlugIn\.events\.trigger\('+IDENT+r'\.PromoPanelEvents\.PROMO_PANEL_MAXIMIZED\)\}')
    opened=(r'\{this\._isOpen=!0,(?P<plugin>'+IDENT+r'\.'+IDENT+r')\.apiPlugIn\.events\.trigger\('+event+r',!0\),'
        r'this\.accumulatedBet=0,this\.accumulatedWin=0,this\.fsCount=0,this\.isPlaying=!0,this\._view\.reset\(\),this\._view\.setNetPosition\(0\),this\._view\.setFreeBetMode\((?P<arg>'+IDENT+r')\),'
        r'(?P=arg)&&\(this\.accumulatedWin=(?P=plugin)\.apiPlugIn\.promotionHandler\.getCurrentWinnings\(\)\|\|0\),this\._asController\.promotionPlugin\.newView\.addChild\(this\._view\),this\._view\.show\(\)\}')
    return bool(re.fullmatch(maximize,method) or re.fullmatch(opened,method))


def _game_modules(source,game,export_name,block):
    defining=_owner(source,game[2],block)
    if not defining:return None
    target=module_id(defining[0][1]);prefix=source[max(0,game[2]-200):game[2]]
    named=re.search(r'class ('+IDENT+r')(?: extends '+IDENT+r'\.'+IDENT+r')?$',prefix)
    if not named:return None
    result=[]
    for header in _module_headers(source):
        module=block(source,header.end()-1,len(source))
        if not module:continue
        references=set()
        if module_id(header[1])==target:references.update((named[1],header[3]+'.'+export_name))
        if header[4]:
            for imported in re.finditer(r'(?<![\w$.])('+IDENT+r')='+re.escape(header[4])+r'\(([0-9]+(?:e[0-9]{1,3})?)\)',module):
                if module_id(imported[2])==target:
                    references.update((imported[1]+'.'+export_name,imported[1]+'["'+export_name+'"]',imported[1]+"['"+export_name+"']"))
        if not references:continue
        aliases=_aliases(module,references)
        if aliases is None:return None
        result.append((header,module,references,aliases))
    return result


def _flag_callback(source,position,text,reference,block,game):
    target=re.escape(reference)+r'\.'+_FIELD
    simple=re.fullmatch(target+r'=!0===('+IDENT+r')',text)
    ternary=re.fullmatch(r'!0===('+IDENT+r')\?\('+target+r'=!0,[\w$.]+\.stop\(\)\):'+target+r'=!1',text)
    match=simple or ternary
    resolved=class_record(source,position,reference,block)
    return match[1] if match and resolved and resolved[2]==game[2] else None


def proves_action_spins_inactive(source,position,game_reference,block,*,direct_demo_transport=False):
    """Return True only with fresh caller context and a complete SDK contract."""
    if direct_demo_transport is not True:return False
    from .protocol import MAX_BODY
    if not isinstance(source,str) or len(source)>MAX_BODY:return False
    return _inactive_binding(source,position,game_reference,block)


@lru_cache(maxsize=2)
def _inactive_binding(source,position,game_reference,block):
    game=class_record(source,position,game_reference,block)
    imported=_import(source,position,game_reference,block)
    if not game or not imported:return False
    modules=_game_modules(source,game,imported[2],block)
    if not modules:return False
    initialized=[];event_identity=None;callbacks=0
    for header,module,references,aliases in modules:
        covered=[]
        # The callback must be the immediate argument of a real subscription;
        # unrelated same-named handlers cannot authorize a state assumption.
        for match in re.finditer(r'[\w$.]+\.events\.on\(('+IDENT+r'\.'+IDENT+r')\.'+_EVENT+r',('+IDENT+r')=>\{',module):
            value=block(module,match.end()-1,len(module))
            if not value:continue
            identity=_event(source,header.end()-1+match.start(),match[1],block)
            if identity is None:continue
            for reference in references:
                parameter=_flag_callback(source,header.end()-1+match.start(),value[1:-1],reference,block,game)
                if parameter!=match[2]:continue
                if event_identity is not None and identity!=event_identity:return False
                event_identity=identity;callbacks+=1
                covered.append((match.end()-1,match.end()-1+len(value)))
        for write in _writes(module,aliases,_FIELD):
            if any(start<=write.start()<end for start,end in covered):continue
            absolute=header.end()-1+write.start()
            if game[2]<=absolute<game[2]+len(game[0]):return False
            if not re.match(r'!1(?=[,;}]|$)',module[write.end():]):return False
            # Initial state belongs to the class's own defining module.
            defining=_owner(source,game[2],block)
            if not defining or module_id(defining[0][1])!=module_id(header[1]):return False
            initialized.append(absolute)
        names='(?:'+'|'.join(re.escape(value) for value in aliases)+')'
        if re.search(r'Object\.(?:assign|defineProperty|defineProperties|setPrototypeOf)\('+names+r'(?=[,)])',module):return False
        # Computed writes can replace the flag without spelling its name.
        if re.search(names+r'\[[^\]]+\]\s*=(?!=)',module):return False
    if len(initialized)!=1 or callbacks!=1 or event_identity is None:return False
    # Exactly one literal definition is allowed. A raw-string emitter or alias
    # producer outside the bound SDK event schema remains unresolved.
    if len(re.findall(r'["\']actionSpinsActive["\']',source))!=1:return False
    if re.search(r'\[["\']'+_EVENT+r'["\']\]',source):return False
    producers=0
    for match in re.finditer(r'('+IDENT+r'\.'+IDENT+r')\.'+_EVENT+r'\b',source):
        identity=_event(source,match.start(),match[1],block)
        if identity!=event_identity:return False
        before=source[max(0,match.start()-200):match.start()]
        call=re.search(r'[\w$.]+\.events\.(on|once|trigger)\($',before)
        if not call:return False
        if call[1]!='trigger':continue
        after=source[match.end():]
        if after.startswith(',!1)'):continue
        if not after.startswith(',!0)') or not _ui_activation(source,match.start(),match[1],block):return False
        producers+=1
    return producers>0
