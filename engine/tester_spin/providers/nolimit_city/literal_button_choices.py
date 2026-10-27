"""Finite UI buttons whose receipt is a consumed phase result, not an index echo."""
import hashlib,re
from .client_actions import _block,_mode_reference
from .static_bindings import class_record
from .fixed_signals import _members
from .finite_choices import _reaches
from .lifecycle import expressions,conditional_arms
from .async_lifecycle import _class_unmodified,_owner,_aliases,_writes
from .presentation_progression import _runner_proven


def _record(source,position,reference):
    record=class_record(source,position,reference,_block)
    if not record:return None
    members=_members(record[0],_block)
    if not members or not _class_unmodified(source,record,_block,methods=tuple(members)):return None
    return record,members


def _constructed_parts(members,name='constructor',seen=()):
    if name in seen or len(seen)>4:return []
    method=members.get(name)
    if not method:return []
    parts=expressions(method[1]);output=[]
    for part in parts:
        if not _reaches(parts,part):continue
        output.append(part)
        call=re.fullmatch(r'this\.(\w+)\(\)',part)
        if call:output.extend(_constructed_parts(members,call[1],seen+(name,)))
    return output


def _button_callback(source,position,reference,arguments):
    resolved=_record(source,position,reference)
    if not resolved:return False
    record,members=resolved;constructor=members.get('constructor')
    if not constructor or not record[1]:return False
    formal=constructor[0].split(',');actual=expressions(arguments)
    if len(formal)!=len(actual) or len(set(formal))!=len(formal):return False
    parts=expressions(constructor[1])
    if not parts:return False
    forwarded=re.fullmatch(r'super\(\w+,'+re.escape(formal[-1])+r'\)',parts[0])
    if not forwarded:return False
    # A subclass may style pointer state, but may not replace dispatch.
    if any(name in members for name in ('onClick','onPointerTap','addClickCallback','bindEvents')):return False
    parent=_record(source,record[2],record[1])
    if not parent:return False
    _,base=parent;constructor=base.get('constructor');add=base.get('addClickCallback');click=base.get('onClick');bind=base.get('bindEvents');enable=base.get('enable')
    if not constructor or not add or not click or not bind or not enable:return False
    inherited_enable=members.get('enable')
    if inherited_enable and inherited_enable[1]!='super.enable('+inherited_enable[0]+')':return False
    enable_parts=expressions(enable[1])
    flag=re.fullmatch(r'this\.(\w+)\|\|\(this\.bindEvents\(\),this\.\1=!0\)',enable_parts[0]) if enable_parts else None
    if not flag or not _reaches(expressions(constructor[1]),'this.'+flag[1]+'=!1'):return False
    if 'this.interactive='+enable[0] not in enable_parts:return False
    parameters=constructor[0].split(',')
    if len(parameters)!=2:return False
    array=re.fullmatch(r'this\.(\w+)\.push\('+re.escape(add[0])+r'\)',add[1])
    if not array:return False
    field=array[1];parts=expressions(constructor[1])
    empty='this.'+field+'=[]';registration='null!='+parameters[1]+'&&this.addClickCallback('+parameters[1]+')'
    if not _reaches(parts,empty) or not _reaches(parts,registration):return False
    if len(_writes(constructor[1],{'this'},field))!=1:return False
    loop=r'for\(let (\w+) of this\.'+re.escape(field)+r'\)\1\(\);'
    if not re.match(r'^if\(this\.interactive&&null!=this\.parent\)\{'+loop,click[1]):return False
    pointer=re.search(r'this\.(\w+)=(\w+)=>\{\2\.stopPropagation\(\),this\.onClick\(\2\)\}',constructor[1])
    return bool(pointer and 'this.on("pointertap",this.'+pointer[1]+')' in expressions(bind[1]))


def _phase_children(source,phase,flow):
    binding=r'addGameModeFlowStatePresentationMap\('+_mode_reference(source,phase)+r',new Map\(\[([^;]{1,1800})\]\)'
    for match in re.finditer(binding,source):
        state=re.search(r'\[\w+\.FlowState\.'+flow+r',(\w+)\]',match[1])
        if not state:continue
        owner=_owner(source,match.start(),_block)
        if not owner:continue
        prefix=source[owner[0].end()-1:match.start()]
        assigned=list(re.finditer(r'\b'+re.escape(state[1])+r'=new (\w+\.\w+)(?:\(\))?(?=[,;])',prefix))
        if len(assigned)!=1:continue
        resolved=_record(source,match.start(),assigned[0][1])
        if not resolved:continue
        record,members=resolved;start=members.get('start')
        if not start:continue
        parts=expressions(start[1])
        runners=[m for part in parts if (m:=re.match(r'(\w+\.\w+)\.run\(this\.(\w+),',part)) and _reaches(parts,part)]
        if len(runners)!=1:continue
        runner=runners[0]
        if not _runner_proven(source,record[2],runner[1],_block):continue
        implementation=class_record(source,record[2],runner[1],_block)
        if not implementation or not _class_unmodified(source,implementation,_block,statics=('run','log')):continue
        constructors=_constructed_parts(members)
        arrays=[m[1] for part in constructors if (m:=re.fullmatch(r'this\.'+re.escape(runner[2])+r'=\[([^\]]+)\]',part))]
        if len(arrays)!=1:continue
        for item in expressions(arrays[0]):
            child=re.fullmatch(r'new (\w+\.\w+)(?:\(\))?',item)
            if child:
                value=_record(source,record[2],child[1])
                if value:yield value


def _guard(body,mode,next_mode,source):
    return bool(re.fullmatch(r'return \w+\.\w+\.model\.data\.mode=='+_mode_reference(source,mode)
        +r'&&\w+\.\w+\.model\.data\.nextMode=='+_mode_reference(source,next_mode),body))


def _result_path(source,phase,ids):
    # Bind the phase-specific result to the same promo parser that lists IDs.
    for match in re.finditer(r'\b\w+\.\w+=class\{',source):
        body=_block(source,match.end()-1)
        if not body:continue
        members=_members(body,_block);options=members.get('getActionSpinOptions')
        if not _class_unmodified(source,(body,None,match.end()-1),_block,methods=tuple(members)):continue
        if not options:continue
        policy=re.search(r'options:\[([^\]]+)\],type:\w+\.ASBonusPickOptions\.PICK_MODE,pickNeededForModes:\[([^\]]+)\]',options[1])
        if not policy or not re.fullmatch(_mode_reference(source,phase),policy[2]):continue
        if [int(v) for v in re.findall(r'\bid:(\d+)',policy[1])]!=ids:continue
        parser=re.search(r'getParsedData:\((\w+),(\w+),(\w+)\)=>\(',options[1])
        if not parser:continue
        getter=re.search(r'totalSpinWinnings:this\.(\w+)\('+','.join(map(re.escape,parser.groups()))+r'\)',options[1])
        if not getter or getter[1] not in members:continue
        args,text=members[getter[1]]
        if args!=','.join(parser.groups()) or not text.startswith('return '):continue
        expression=text[7:]
        for _ in range(6):
            arms=conditional_arms(expression)
            if not arms:break
            question=expression.find('?');condition=expression[:question]
            if re.fullmatch(re.escape(parser[1])+r'\.mode==='+_mode_reference(source,phase),condition):
                path=re.fullmatch(re.escape(parser[1])+r'\.([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)',arms[0])
                if path:return list(path.groups())
                break
            expression=arms[1]
    return None


def literal_button_domain(source,answer,ids):
    game=answer.get('game') or {};phase=game.get('nextMode');mode=game.get('mode')
    wire=(r'pickAndClickBet\((\w+),(\w+)=!0\)\{const (\w+)=\{selectedIndex:\1\.toString\(\)\},'
        r'(\w+)=\{type:\w+\.APIBetType\.ZERO_BET,bet:"0\.00",playerInteraction:\3\};this\.sendRequest\(\4,!\2\)\}')
    if not re.search(wire,source):return None
    if not isinstance(phase,str) or not isinstance(mode,str):return None
    path=_result_path(source,phase,ids)
    if path is None:return None
    result_children=list(_phase_children(source,phase,'RESULT'))
    if not any(_guard(m.get('shouldRun',('',''))[1],phase,'NORMAL',source) for _,m in result_children):return None
    domains=[]
    for child,members in _phase_children(source,phase,'IDLE'):
        if not _guard(members.get('shouldRun',('',''))[1],mode,phase,source):continue
        start=members.get('start')
        if not start:continue
        call=re.fullmatch(r'this\.\w+=\w+,(\w+\.\w+)\.(\w+)\.start\(\(\)=>this\.(\w+)\(\)\)',start[1])
        if not call or members.get(call[3],('',''))[1]!='this._controller.finish()':continue
        owner=class_record(source,child[2],call[1],_block)
        if not owner:continue
        prefix=source[max(0,owner[2]-180):owner[2]];named=re.search(r'class (\w+)(?: extends [\w.]+)?$',prefix)
        if not named:continue
        defining=_owner(source,owner[2],_block)
        if not defining:continue
        header,module,_=defining
        seeds={named[1]}
        seeds.update(m[1] for m in re.finditer(r'('+re.escape(header[3])+r'\.\w+)='+re.escape(named[1])+r'(?=[,;}])',module))
        aliases=_aliases(module,seeds)
        if aliases is None or len(_writes(module,aliases,call[2]))!=1:continue
        creation=list(re.finditer(re.escape(named[1])+r'\.'+re.escape(call[2])+r'=new (\w+\.\w+)',owner[0]))
        if len(creation)!=1:continue
        view=_record(source,owner[2]+creation[0].start(),creation[0][1])
        if not view:continue
        vr,vm=view
        view_start=vm.get('start')
        if not view_start or not re.fullmatch(r'this\.\w+=\w+,this\.\w+\(\)',view_start[1]):continue
        for part in _constructed_parts(vm):
            panel=re.fullmatch(r'this\.\w+=new (\w+\.\w+)\((\w+)=>this\.(\w+)\(\2\)\)',part)
            if not panel:continue
            selected=vm.get(panel[3]);parameter=selected[0] if selected else ''
            if not re.fullmatch(r'\w+',parameter):continue
            if re.search(r'(?<![\w$.])'+re.escape(parameter)+r'\s*(?:[+*/-]?=(?![=>])|\+\+|--)',selected[1]):continue
            selected_parts=expressions(selected[1])
            wire=[part for part in selected_parts if re.fullmatch(r'\w+\.\w+\.apiPlugin\.betHandler\.pickAndClickBet\('+re.escape(parameter)+r',!1\)',part)]
            if len(wire)!=1 or not _reaches(selected_parts,wire[0]):continue
            container=_record(source,vr[2],panel[1])
            if not container:continue
            cr,cm=container;ctor=cm.get('constructor')
            if not ctor or not re.fullmatch(r'\w+',ctor[0]):continue
            callback=[m[1] for p in _constructed_parts(cm) if (m:=re.fullmatch(r'this\.(\w+)='+re.escape(ctor[0]),p))]
            if len(callback)!=1:continue
            if len(_writes(cr[0],{'this'},callback[0]))!=1:continue
            if re.search(r'this\[[^\]]+\]\s*=(?!=)',cr[0]):continue
            callbacks=[]
            for p in _constructed_parts(cm):
                m=re.search(r',\w+=>this\.(\w+)\((\d+)\)\)$',p)
                construction=re.fullmatch(r'this\.(\w+)=new (\w+\.\w+)\((.*)\)',p)
                enabled=False
                if construction:
                    enabling='this.'+construction[1]+'.enable(!0)'
                    for enabled_part in _constructed_parts(cm):
                        gate=re.fullmatch(r'0==\w+\.\w+\.apiPlugin\.isReplay&&\((.*)\)',enabled_part)
                        if gate and enabling in expressions(gate[1]):enabled=True
                if (m and construction and enabled and _button_callback(source,cr[2],construction[2],construction[3])):
                    callbacks.append((m[1],int(m[2])))
            if len(callbacks)!=len(ids) or [value for _,value in callbacks]!=ids or len({name for name,_ in callbacks})!=1:continue
            clicked=cm.get(callbacks[0][0])
            if not clicked:continue
            pattern=(r'1!=\w+\.\w+\.apiPlugin\.isReplay&&1!=this\.(\w+)&&\(this\.\1=!0,this\.(\w+)\('+re.escape(clicked[0])+r'\)\)')
            guard=re.fullmatch(pattern,clicked[1])
            if not guard:continue
            forwarded=cm.get(guard[2])
            if not forwarded:continue
            effect='this.'+callback[0]+'('+forwarded[0]+')'
            if re.search(r'(?<![\w$.])'+re.escape(forwarded[0])+r'\s*(?:[+*/-]?=(?![=>])|\+\+|--)',forwarded[1].split(effect,1)[0]):continue
            if not _reaches(expressions(forwarded[1]),effect):continue
            domains.append({'state':phase,'options':ids,'available':ids,'ack_field':path[0],
                'result_path':path,'target_phase':'NORMAL','source':'CLIENT_BOUND_LITERAL_BUTTONS',
                'request_field':'selectedIndex','request_type':'zeroBet',
                'source_sha256':hashlib.sha256(source.encode('utf-8')).hexdigest()})
    return domains[0] if len(domains)==1 else None
