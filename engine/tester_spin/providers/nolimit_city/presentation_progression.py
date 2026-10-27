"""Source-bound progression through noninteractive presentation callbacks."""
import re


def active_timeline_body(available):
    start=available.get('start');build=available.get('buildTimeline')
    if not start or not build:return None
    arg=re.escape(start[0])
    complete=r'onComplete:\(\)=>\{'+arg+r'\.setSkipCallback\(\),'+arg+r'\.finish\(\)\}'
    skip=r'onStart:\(\)=>\{'+arg+r'\.setSkipCallback\(\(\)=>\{this\.skip\(\)\}\)\}'
    shape=(r'this\.controller='+arg+r',(?:'+arg+r'\.setSkipCallback\(\(\)=>\{this\.skip\(\)\}\),)?'
        r'this\.tl=\w+\.gsap\.timeline\(\{'+complete+r'(?:,'+skip+r')?\}\),'
        r'(?:this\.createSkipCallback&&this\.tl\.add\(\(\)=>\{this\.controller\.setSkipCallback\(\(\)=>\{this\.skip\(\)\}\)\},\.1\),)?this\.buildTimeline\(\)')
    if not re.fullmatch(shape,start[1]):return None
    body=build[1]
    alias=re.match(r'^(const|let|var) (\w+)=this\.tl(?=[,;])',body)
    if alias:
        body=alias[1]+' '+alias[2]+'=known.gsap.timeline()'+body[alias.end():]
        return re.sub(r'this\.tl\b',alias[2],body)
    if '__active_member_timeline' in body:return None
    body=re.sub(r'this\.tl\b','__active_member_timeline',body)
    return 'const __active_member_timeline=known.gsap.timeline();'+body


def _runner_proven(source,position,reference,block):
    from .static_bindings import class_record
    from .fixed_signals import _members
    record=class_record(source,position,reference,block)
    if not record:return False
    members=_members(record[0],block);run=members.get('run')
    if not run:return False
    args=run[0].split(',')
    if len(args)==3:
        pattern=(r'const (\w+)='+re.escape(args[0])+r'\.concat\(\),(\w+)=\1\.shift\(\);null==\2\?'+re.escape(args[1])+r'\(\):\2\.shouldRun\(\)\?\2\.start\(\{finish:\(\)=>(\w+)\.run\(\1,'+re.escape(args[1])+','+re.escape(args[2])+r'\),setSkipCallback:'+re.escape(args[2])+r'\}\):\3\.run\(\1,'+re.escape(args[1])+','+re.escape(args[2])+r'\)')
        return bool(re.fullmatch(pattern,run[1]))
    if len(args)!=4:return False
    named=re.search(r'class (\w+)$',source[max(0,record[2]-100):record[2]])
    if not named:return False
    a,b,c,d=args;head=re.match(r'const (\w+)='+a+r'\.concat\(\),(\w+)=\1\.shift\(\);if\(null==\2\)'+b+r'\(\);else\{const (\w+)=\2\.name\?\2\.name:"unnamed presentation";',run[1])
    if not head:return False
    x,y,label=head.groups();owner=named[1]
    expected=(head[0]+y+'.shouldRun()?('+owner+'.log('+d+',"starting: "+'+label+'),'+y+'.start({finish:()=>{'+owner+'.log('+d+',"finishing: "+'+label+'),'+owner+'.run('+x+','+b+','+c+','+d+')},setSkipCallback:'+c+'})):('+owner+'.log('+d+',"skipping: "+'+label+'),'+owner+'.run('+x+','+b+','+c+','+d+'))}')
    log=members.get('log')
    if not log or run[1]!=expected:return False
    left,right=map(re.escape,log[0].split(','))
    direct=r'null!='+left+r'&&\w+\.Logger\.logDev\('+left+r'\+'+right+r'\)'
    concatenated=r'const (\w+)='+left+r'\?'+left+r'\+'+right+':'+right+r';\w+\.Logger\.logDev\(\1\)'
    return bool(re.fullmatch(direct,log[1]) or re.fullmatch(concatenated,log[1]))


def _bound_view(source,position,owner,property_name,block):
    from .static_bindings import class_record,_module_headers
    record=class_record(source,position,owner,block)
    if not record:return None
    named=re.search(r'class (\w+)(?: extends [\w$.]+)?$',source[max(0,record[2]-180):record[2]])
    contexts=[h for h in _module_headers(source) if h.end()<=record[2]]
    if not named or not contexts:return None
    context=contexts[-1];module=block(source,context.end()-1,len(source))
    if not module:return None
    aliases={named[1]}
    for _ in range(8):
        discovered=set()
        for alias in aliases:discovered.update(re.findall(r'(?<![\w$.])([\w$]+(?:\.[\w$]+){0,3})='+re.escape(alias)+r'(?=[,;)}\]])',module))
        if discovered<=aliases:break
        aliases.update(discovered)
    else:return None
    if sum(len(re.findall(r'(?<![\w$.])'+re.escape(alias)+r'\.'+re.escape(property_name)+r'=(?![=>])',module)) for alias in aliases)!=1:return None
    creates=list(re.finditer(r'(?<![\w$.])'+re.escape(named[1])+r'\.'+re.escape(property_name)+r'=new ([\w$]+\.[\w$]+)(?=[,;(])',module))
    if len(creates)!=1:return None
    return class_record(source,context.end()-1+creates[0].start(),creates[0][1],block)


def _button_reachable(members,clicked,name='constructor',seen=()):
    from .lifecycle import expressions
    from .finite_choices import _reaches
    if name in seen or len(seen)>8 or name not in members:return False
    body=members[name][1]
    # A bounded literal glyph initializer only creates and positions PIXI text;
    # it cannot gate or replace the subsequent ContinueButton callback.
    from .client_actions import _block
    for loop in reversed(list(re.finditer(r'for\(const (\w+) of"[^"\\]{1,64}"\)\{',body))):
        value=_block(body,loop.end()-1,len(body))
        if not value:continue
        glyph=(r'const (\w+)=new PIXI\.BitmapText\('+re.escape(loop[1])+r',\{[^{}]{1,1000}\}\);\1\.position\.x=this\.(\w+)\.width,this\.\2\.addChild\(\1\)')
        if re.fullmatch(glyph,value[1:-1]):body=body[:loop.start()]+body[loop.end()-1+len(value):]
    parts=expressions(body)
    for part in parts:
        if not _reaches(parts,part):continue
        if re.fullmatch(r'this\.\w+\.addClickCallback\(\(\)=>this\.'+re.escape(clicked)+r'\(\)\)',part):return True
        call=re.fullmatch(r'this\.(\w+)\(\)',part)
        if call and _button_reachable(members,clicked,call[1],seen+(name,)):return True
    return False


def _ui_switches(body,block):
    from .lifecycle import _paren_end
    for match in reversed(list(re.finditer(r'\bswitch\([\w$.]+\)\{',body))):
        value=block(body,match.end()-1,len(body))
        if not value:continue
        cases=re.split(r'case [\w$.]+:',value[1:-1])
        assignments=[re.fullmatch(r'(\w+)=[\w$.]+(?:;break;?)?',case) for case in cases[1:]]
        if cases[0] or not assignments or any(m is None for m in assignments):continue
        names={m[1] for m in assignments}
        if len(names)!=1 or not re.search(r'(?:let|var) '+re.escape(next(iter(names)))+r'=[0-9]+;$',body[:match.start()]):continue
        body=body[:match.start()]+body[match.end()-1+len(value):]
    return body


def _ui_completion(source,available,block):
    from .lifecycle import proves_zero_bet,expressions,expanded_expressions,_paren_end
    from .fixed_signals import _members
    if any(re.search(r'betHandler|sendRequest|selectedIndex|playerInteraction',body) for _,body,_ in available.values()):return False
    body=active_timeline_body(available)
    if body is None:return False
    body=re.sub(r'\b\w+\.eventCallback\("onComplete",\(\)=>\{this\.controller\.setSkipCallback\(\)\}\),?','',body)
    body=_ui_switches(body,block)
    build=available['buildTimeline']
    for call in re.finditer(r'([\w$]+\.[\w$]+)\.(\w+)\.(\w+)\(\(\)=>\{?this\.(\w+)\(\)\}?\)',body):
        handler=available.get(call[4])
        if not handler or handler[0]:continue
        projected=body[:call.start()]+'known.api.betHandler.zeroBet()'+body[call.end():]
        if not proves_zero_bet('{start(){'+projected+'}}',block):continue
        flattened='{'+''.join(name+'('+args+'){'+text.replace('this.controller.finish()','known.api.betHandler.zeroBet()')+'}' for name,(args,text,_) in available.items())+'}'
        if not proves_zero_bet(flattened,block,entry=call[4]):continue
        view=_bound_view(source,build[2],call[1],call[2],block)
        if not view or re.search(r'betHandler|sendRequest|selectedIndex|playerInteraction',view[0]):continue
        members=_members(view[0],block);register=members.get(call[3])
        if not register or not re.fullmatch(r'\w+',register[0]):continue
        stores=list(re.finditer(r'this\.(\w+)='+re.escape(register[0])+r'(?=[,;])',register[1]))
        if len(stores)!=1:continue
        store=stores[0];field=store[1]
        registration=register[1][:store.start()]+'known.api.betHandler.zeroBet()'+register[1][store.end():]
        registration_parts=expanded_expressions(registration)
        if registration_parts is None:continue
        if registration_parts and re.fullmatch(r'(?:return )?\w+',registration_parts[-1]):registration_parts.pop()
        if not proves_zero_bet('{start(){'+';'.join(registration_parts)+'}}',block):continue
        if len(re.findall(r'this\.'+re.escape(field)+r'=(?!=)',view[0]))!=1:continue
        if re.findall(r'this\.'+re.escape(field)+r'\(([^()]*)\)',view[0])!=['']:continue
        for name,(args,text) in members.items():
            if args or not _button_reachable(members,name):continue
            if text.startswith('if('):
                end=_paren_end(text,2);condition=expressions(text[3:end]) if end else []
                guard=re.match(r'throw new Error\("[^"\\]{1,100}"\);',text[end+1:]) if end else None
                if not condition or condition[-1]!='null==this.'+field or not guard:continue
                text=','.join(condition[:-1])+';'+text[end+1+guard.end():]
            text=text.replace('this.'+field+'()','known.api.betHandler.zeroBet()')
            if proves_zero_bet('{start(){'+text+'}}',block):return True
    return False


def proves_presentation_progression(source,available,answer,block,depth):
    from .lifecycle import expressions
    from .finite_choices import _reaches
    from .static_bindings import inherited_methods,proves_bound_action,inactive_guard,IDENT
    start=available.get('start');constructor=available.get('constructor')
    if not start or not constructor:return False
    parts=expressions(start[1])
    calls=[(part,m) for part in parts if (m:=re.fullmatch(r'([\w$]+\.[\w$]+)\.run\(this\.(\w+),(.*)\)',part)) and _reaches(parts,part)]
    if len(calls)!=1:return False
    call=calls[0][1]
    if not _runner_proven(source,start[2],call[1],block):return False
    assignments=[part for part in expressions(constructor[1]) if re.fullmatch(r'this\.'+re.escape(call[2])+r'=\[[^\]]{1,1600}\]',part)]
    if len(assignments)!=1 or not _reaches(expressions(constructor[1]),assignments[0]):return False
    residual=constructor[1].replace(assignments[0],'')
    if re.search(r'this\.'+re.escape(call[2])+r'\b',residual):return False
    items=expressions(assignments[0].split('=',1)[1][1:-1])
    if not items or len(items)>32:return False
    for item in items:
        match=re.fullmatch(r'new ('+IDENT+r'(?:\.'+IDENT+r')?)(?:\(\))?',item)
        if not match:return False
        child=inherited_methods(source,constructor[2],match[1],block)
        if not child:return False
        condition=child.get('shouldRun')
        if condition and inactive_guard(condition[1],answer.get('game') or {},source,condition[2],block):continue
        if proves_bound_action(source,constructor[2],match[1],answer,block,depth+1):return True
        if not _ui_completion(source,child,block):return False
    return False
