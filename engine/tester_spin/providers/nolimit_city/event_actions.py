"""Source-bound legacy idle animation -> timeline -> event -> bare zeroBet.

Only a fresh direct transport can exclude the SDK's Action Spins UI path. The
counter carried by the event is proved to reach the keypad, never betHandler.
"""
import re
from functools import lru_cache
from .protocol import MAX_BODY,_money
from .static_bindings import IDENT,class_record,module_id,inherited_methods,_module_headers
from .async_lifecycle import _owner,_import,_writes,_aliases,_class_unmodified
from .action_spins_context import _members,_event,_ui_activation,_game_modules
from .lifecycle import expressions,proves_zero_bet


_REF=IDENT+r'\.'+IDENT


def _root_position(module,position):
    stack=[];quote=None;escaped=False
    for index,char in enumerate(module[:position]):
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
        elif char in ('"',"'",'`'):quote=char
        elif module.startswith(('//','/*'),index):return False
        elif char in '([{':stack.append(char)
        elif char in ')]}':
            if not stack or '([{'.index(stack.pop())!=')]}'.index(char):return False
    return not quote and stack==['{']


def _class_at(source,position,block):
    owner=_owner(source,position,block)
    if not owner:return None
    header,module,_=owner;found=[]
    for match in re.finditer(r'\bclass(?: ('+IDENT+r'))?(?: extends '+_REF+r')?\{',module):
        body=block(module,match.end()-1,len(module));offset=header.end()-1+match.end()-1
        if body and offset<position<offset+len(body):found.append((body,offset,match[1]))
    return min(found,key=lambda record:len(record[0])) if found else None


def _method_map(body,offset,block):
    available=_members(body,offset,block)
    if available is None:return None
    result={}
    for name,args,value,start,kind in available:
        key=(kind+' ' if kind else '')+name
        if key in result:return None
        result[key]=(args,value[1:-1],start)
    return result


def _same(source,position,reference,target,block):
    record=class_record(source,position,reference,block)
    return bool(record and record[2]==target[2])


def _constant(source,position,reference,block):
    record=class_record(source,position,reference,block)
    imported=_import(source,position,reference,block)
    if not record or not imported or record[0]!='{}' or not _class_unmodified(source,record,block):return None
    modules=_game_modules(source,record,imported[2],block)
    if not modules:return None
    writes=[]
    for header,module,refs,aliases in modules:
        for write in _writes(module,aliases,'ZERO_BET'):
            if module_id(header[1])!=module_id(imported[0][1]) or not _root_position(module,write.start()):return None
            if not re.match(r'"balanceEvent_zeroBet"(?=[,;}]|$)',module[write.end():]):return None
            writes.append(write)
    return record if len(writes)==1 else None


def _quiet_actions(source,event_identity,block):
    if len(re.findall(r'["\']actionSpinsActive["\']',source))!=1:return False
    if re.search(r'\[["\']ACTION_SPINS_IS_ACTIVE["\']\]',source):return False
    enabled=0
    for match in re.finditer(r'('+_REF+r')\.ACTION_SPINS_IS_ACTIVE\b',source):
        if _event(source,match.start(),match[1],block)!=event_identity:return False
        before=source[max(0,match.start()-200):match.start()]
        call=re.search(r'[\w$.]+\.events\.(on|once|trigger)\($',before)
        if not call:return False
        if call[1]!='trigger':continue
        after=source[match.end():]
        if after.startswith(',!1)'):continue
        if not after.startswith(',!0)') or not _ui_activation(source,match.start(),match[1],block):return False
        enabled+=1
    return enabled>0


def _dispatcher(source,position,reference,block):
    record=class_record(source,position,reference,block)
    if not record or not _class_unmodified(source,record,block,methods=('dispatchEvent','addEventListener','hasEventHandler')):return False
    methods=_method_map(record[0],record[2],block)
    if not methods or not all(key in methods for key in ('dispatchEvent','addEventListener','hasEventHandler')):return False
    args,body,_=methods['dispatchEvent']
    if not re.fullmatch(IDENT,args):return False
    event=re.escape(args)
    pattern=(r'let (?P<first>'+IDENT+r')=this\._firstListeners\['+event+r'\.type\];if\((?P=first)&&(?P=first)\.callback\.call\(this,'+event+r',(?P=first)\.params\),this\._listeners\['+event+r'\.type\]\)for\(let (?P<index>'+IDENT+r')=this\._listeners\['+event+r'\.type\]\.length-1;(?P=index)>=0;(?P=index)--\)\{const (?P<item>'+IDENT+r')=this\._listeners\['+event+r'\.type\]\[(?P=index)\];(?P=item)\.callback\.call\(this,'+event+r',(?P=item)\.params\)\}let (?P<last>'+IDENT+r')=this\._lastListeners\['+event+r'\.type\];(?P=last)&&(?P=last)\.callback\.call\(this,'+event+r',(?P=last)\.params\)')
    if not re.fullmatch(pattern,body):return False
    params=methods['addEventListener'][0].split(',')
    if len(params)!=4 or not all(re.fullmatch(IDENT,value) for value in params):return False
    owner,kind,callback,extra=map(re.escape,params)
    expected=(r'this\.hasEventHandler\('+owner+','+kind+r'\)\|\|\(this\._listeners\['+kind+r'\]=this\._listeners\['+kind+r'\]\|\|\[\],this\._listeners\['+kind+r'\]\.push\(\{source:'+owner+',type:'+kind+',callback:'+callback+',params:'+extra+r'\}\)\)')
    if not re.fullmatch(expected,methods['addEventListener'][1]):return False
    params=methods['hasEventHandler'][0].split(',')
    if len(params)!=2 or len(set(params))!=2:return False
    owner,kind=map(re.escape,params)
    expected=(r'return!!this\._listeners\['+kind+r'\]&&this\._listeners\['+kind+r'\]\.some\(\(('+IDENT+r'),'+IDENT+','+IDENT+r'\)=>\1\.source==='+owner+r'\)')
    match=re.fullmatch(expected,methods['hasEventHandler'][1])
    return bool(match and match[1]!=params[0])


def _enabled_bus(source,position,reference,block,bridge,action_member):
    bus=class_record(source,position,reference,block);imported=_import(source,position,reference,block)
    if not bus or not imported or not _class_unmodified(source,bus,block,statics=('dispatchEvent','addEventListener','enabled')):return False
    methods=_method_map(bus[0],bus[2],block)
    if not methods or not all(name in methods for name in ('dispatchEvent','addEventListener','get enabled','set enabled')):return False
    prefix=source[max(0,bus[2]-200):bus[2]];named=re.search(r'class ('+IDENT+r')$',prefix)
    if not named:return False
    arg=methods['dispatchEvent'][0]
    if arg==named[1] or methods['dispatchEvent'][1]!=named[1]+'._enabled&&this._eventDispatcher.dispatchEvent('+arg+')':return False
    if methods['get enabled'][:2]!=('', 'return this._enabled'):return False
    setter=methods['set enabled']
    if setter[1]!='this._enabled='+setter[0]:return False
    for key,member in methods.items():
        if key!='set enabled' and _writes(member[1],{'this'},'_enabled'):return False
        if _writes(member[1],{'this'},'_eventDispatcher'):return False
    params=methods['addEventListener'][0].split(',')
    if len(params)!=4 or not params[3].startswith('...'):return False
    normal=params[:3]+[params[3][3:]]
    if methods['addEventListener'][1]!='this._eventDispatcher.addEventListener('+','.join(normal)+')':return False
    modules=_game_modules(source,bus,imported[2],block)
    if not modules:return False
    initial=[];dispatchers=[];controlled=[]
    for header,module,refs,aliases in modules:
        for write in _writes(module,aliases,'_enabled'):
            if module_id(header[1])!=module_id(imported[0][1]) or not _root_position(module,write.start()):return False
            if not re.match(r'!0(?=[,;}]|$)',module[write.end():]):return False
            initial.append(write)
        for write in _writes(module,aliases,'enabled'):
            absolute=header.end()-1+write.start()
            if not action_member[2]<absolute<action_member[2]+len(action_member[1])+2:return False
            controlled.append(write)
        for write in _writes(module,aliases,'_eventDispatcher'):
            if module_id(header[1])!=module_id(imported[0][1]) or not _root_position(module,write.start()):return False
            value=re.match(r'new ('+_REF+r')(?=[,;}]|$)',module[write.end():])
            if not value or not _dispatcher(source,header.end()-1+write.start(),value[1],block):return False
            dispatchers.append(write)
        for name in ('dispatchEvent','addEventListener'):
            if _writes(module,aliases,name):return False
        names='(?:'+'|'.join(re.escape(value) for value in aliases)+')'
        if re.search(r'(?<![\w$.])'+names+r'\._eventDispatcher(?!=)',module):return False
        if re.search(r'Object\.(?:assign|defineProperty|defineProperties|setPrototypeOf)\('+names+r'(?=[,)])|'+names+r'\[[^\]]+\]\s*=(?!=)',module):return False
    return len(initial)==1 and len(dispatchers)==1 and len(controlled)==1


@lru_cache(maxsize=2)
def _bridge(source,bus_reference,event_reference,position,block):
    bus=class_record(source,position,bus_reference,block)
    balance=_constant(source,position,event_reference,block)
    if not bus or not balance:return False
    subscription=(r'('+_REF+r')\.addEventListener\(this,('+_REF+r')\.ZERO_BET,('+IDENT+r')=>this\.onZeroBet\(\3\.params\[0\]\)\)')
    valid=0
    for match in re.finditer(subscription,source):
        if not _same(source,match.start(),match[1],bus,block) or not _same(source,match.start(),match[2],balance,block):continue
        containing=_class_at(source,match.start(),block)
        if not containing:return False
        body,offset,_=containing
        if not _class_unmodified(source,(body,None,offset),block,methods=('onZeroBet','onActionSpins','initGameEvents','initSlotApiEvents','_slotApi')):return False
        methods=_method_map(body,offset,block)
        if not methods or not all(name in methods for name in ('constructor','initGameEvents','initSlotApiEvents','onZeroBet','onActionSpins')):return False
        handler=methods['onZeroBet'];parameter=re.escape(handler[0])
        shape=(r'this\._slotApi\.betHandler\.zeroBet\(\),null=='+parameter+r'&&\('+parameter+r'=-1\),[\w$.]+\.keypad\.setZeroBetSpinCounter\('+parameter+r'\)')
        if not re.fullmatch(shape,handler[1]):return False
        if match[0] not in expressions(methods['initGameEvents'][1]):return False
        constructor=methods['constructor'];parts=expressions(constructor[1])
        if len(_writes(body,{'this'},'_slotApi'))!=1:return False
        for key in ('onZeroBet','onActionSpins','initGameEvents','initSlotApiEvents'):
            if _writes(body,{'this'},key):return False
        if 'this._slotApi='+constructor[0] not in parts or not all('this.'+name+'()' in parts for name in ('initGameEvents','initSlotApiEvents')):return False
        action=methods['onActionSpins'];assignment=re.fullmatch(r'('+_REF+r')\.enabled=!'+re.escape(action[0]),action[1])
        if not assignment or not _same(source,action[2],assignment[1],bus,block):return False
        events=methods['initSlotApiEvents'];active=re.search(r'this\._slotApi\.events\.on\(('+_REF+r')\.ACTION_SPINS_IS_ACTIVE,('+IDENT+r')=>this\.onActionSpins\(\2\)\)',events[1])
        if not active or active[0] not in expressions(events[1]):return False
        identity=_event(source,events[2],active[1],block)
        if identity is None or not _quiet_actions(source,identity,block):return False
        if not _enabled_bus(source,position,bus_reference,block,containing,action):return False
        valid+=1
    return valid==1


def _event_type(source,position,reference,block):
    record=class_record(source,position,reference,block)
    if not record or record[1] or not _class_unmodified(source,record,block,methods=('type','params')):return False
    methods=_method_map(record[0],record[2],block)
    if not methods or methods.get('get type',())[:2]!=('', 'return this._type') or methods.get('get params',())[:2]!=('', 'return this._params'):return False
    constructor=methods.get('constructor')
    if not constructor:return False
    args=constructor[0].split(',')
    return len(args)==2 and args[1].startswith('...') and constructor[1]=='this._type='+args[0]+',this._params='+args[1][3:]


def _animation(source,position,reference,block):
    record=class_record(source,position,reference,block)
    if not record or not _class_unmodified(source,record,block,methods=('getAnimation','prepare')):return None
    available=inherited_methods(source,position,reference,block)
    if not available or 'getAnimation' not in available:return None
    if 'shouldRun' in available and available['shouldRun'][:2] not in (('', 'return!0'),('', 'return true')):return None
    methods=_method_map(record[0],record[2],block)
    return methods.get('getAnimation') if methods else None


def _finite_animation(method):
    args,body,offset=method
    declared=re.search(r'(?:^|;)const ('+IDENT+r')=new '+IDENT+r'\.TimelineLite;',body)
    if not declared:return False
    name=declared[1];parts=expressions(body)
    if not parts or parts[-1] not in (name,'return '+name):return False
    if re.search(r'\b'+re.escape(name)+r'\.(?:pause|kill|repeat|stop|eventCallback|timeScale|clear|reverse)\b|\byield\b',body):return False
    residual=body.replace(declared[0],'',1)
    residual=re.sub(r'\b'+re.escape(name)+r'\.(?:add|addLabel|to|from|fromTo|set)\b','__timeline',residual)
    residual=re.sub(r'(?:return )?'+re.escape(name)+r'$','',residual)
    return not re.search(r'\b'+re.escape(name)+r'\b',residual)


def _bound_config(source,config,block):
    owner=_owner(source,config.start(),block)
    if not owner:return False
    header,module,_=owner
    factory=list(re.finditer(r'this\.GAME_ROUND_CONFIG=\(\)=>\(\{',module))
    matching=[]
    for value in factory:
        body=block(module,value.end()-1,len(module));absolute=header.end()-1+value.end()-1
        if body and absolute<config.start()<absolute+len(body):matching.append(value)
    if len(matching)!=1:return False
    containing=_class_at(source,config.start(),block)
    if not containing or not containing[2]:return False
    name=containing[2]
    exports=re.findall(re.escape(header[3])+r'\.('+IDENT+r')='+re.escape(name)+r'(?=[,;}])',module)
    if len(exports)!=1 or len(re.findall(re.escape(name)+r'\.instance=new '+re.escape(name)+r'(?=[,;}]|$)',module))!=1:return False
    config_record=(containing[0],None,containing[1])
    if not _class_unmodified(source,config_record,block,methods=('GAME_ROUND_CONFIG',)):return False
    members=_method_map(containing[0],containing[1],block)
    if not members or any(key in members for key in ('get GAME_ROUND_CONFIG','set GAME_ROUND_CONFIG')):return False
    if len(_writes(containing[0],{'this'},'GAME_ROUND_CONFIG'))!=1:return False
    configurations=_game_modules(source,config_record,exports[0],block)
    if not configurations:return False
    singleton_writes=0
    for module_header,content,refs,aliases in configurations:
        for write in _writes(content,aliases,'instance'):
            if module_id(module_header[1])!=module_id(header[1]) or not _root_position(content,write.start()):return False
            if not re.match(r'new '+re.escape(name)+r'(?=[,;}]|$)',content[write.end():]):return False
            singleton_writes+=1
        instances=_aliases(content,{reference+'.instance' for reference in aliases})
        if instances is None or _writes(content,instances,'GAME_ROUND_CONFIG'):return False
    if singleton_writes!=1:return False
    # A game constructor must actually consume this exact exported singleton.
    consumed=0
    for match in re.finditer(r'constructor\(\)\{super\(('+_REF+r')\.instance\)\}',source):
        imported=_import(source,match.start(),match[1],block)
        if imported and module_id(imported[0][1])==module_id(header[1]) and imported[2]==exports[0]:consumed+=1
    return consumed==1


def automatic_event_command(source,answer,block,*,direct_demo_transport=False):
    if direct_demo_transport is not True or not isinstance(source,str) or len(source)>MAX_BODY:return None
    game=answer.get('game') or {};mode=game.get('nextMode')
    if not isinstance(mode,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]+',mode) or mode=='NORMAL':return None
    try:
        if 'extraSpinCost' in game and _money(game['extraSpinCost'])!=0:return None
    except ValueError:return None
    if any(field in game and game[field] is not False for field in ('wasExtraSpin','isExtraSpin')):return None
    if _event_action_proven(source,mode,block):return {'type':'zeroBet','bet':'0.00'}
    return None


@lru_cache(maxsize=16)
def _event_action_proven(source,mode,block):
    """Cache only immutable source/phase proof; answer guards stay per call."""
    configurations=list(re.finditer(r'\b'+re.escape(mode)+r':\{idle:\[([^\]]{1,1600})\]',source))
    if len(configurations)!=1 or not _bound_config(source,configurations[0],block):return False
    config=configurations[0]
    for item in config[1].split(','):
        match=re.fullmatch(r'new ('+_REF+r')(?:\(\))?',item)
        if not match:return False
        method=_animation(source,config.start(),match[1],block)
        if not method:return False
        args,body,offset=method
        dispatch=(r'('+_REF+r')\.dispatchEvent\(new ('+_REF+r')\(('+_REF+r')\.ZERO_BET(?:,((?:this|'+re.escape(args)+r')\.'+IDENT+r'(?:-[0-9]+)?))?\)\)')
        replacements=[]
        for event in re.finditer(dispatch,body):
            if _event_type(source,offset,event[2],block) and _bridge(source,event[1],event[3],offset,block):replacements.append(event)
        normalized=body
        for event in reversed(replacements):normalized=normalized[:event.start()]+'known.betHandler.zeroBet()'+normalized[event.end():]
        parts=expressions(normalized)
        if parts and re.fullmatch(IDENT,parts[-1]) and re.search(r'(?:^|;)const '+re.escape(parts[-1])+r'=new '+IDENT+r'\.TimelineLite;',normalized):
            normalized=';'.join(parts[:-1])
        if replacements and proves_zero_bet('{start('+args+'){'+normalized+'}}',block):return True
        if not _finite_animation(method):return False
    return False
