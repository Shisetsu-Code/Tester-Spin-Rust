"""Recognize a bound UI acknowledgment with one constant, zero-stake wire signal."""
import re
from .protocol import MAX_BODY
from .client_actions import _mode_reference
from .static_bindings import class_record,_module_headers
from .lifecycle import expressions
from .finite_choices import _reaches


def _members(body,block):
    result={};cursor=1
    while cursor<len(body)-1:
        member=re.match(r'(?:(get|set|static) )?([\w$]+)\(([^)]*)\)\{',body[cursor:])
        if not member:return {}
        value=block(body,cursor+member.end()-1,len(body))
        if not value:return {}
        if member[1] not in ('get','set'):
            if member[2] in result:return {}
            result[member[2]]=(member[3],value[1:-1])
        cursor+=member.end()-1+len(value)
    return result


def _installed_button(members,clicked,name='constructor',seen=()):
    if name in seen or len(seen)>8 or name not in members:return False
    parts=expressions(members[name][1])
    button=r'this\.[\w$]+=new [\w$.]+\("[^"\\]{1,100}",\(\)=>this\.'+re.escape(clicked)+r'\(\)\)'
    for part in parts:
        if not _reaches(parts,part):continue
        if re.fullmatch(button,part):return True
        call=re.fullmatch(r'this\.([\w$]+)\(\)',part)
        if call and _installed_button(members,clicked,call[1],seen+(name,)):return True
    return False


def fixed_signal_command(source,answer,block):
    if not isinstance(source,str) or len(source)>MAX_BODY:return None
    phase=(answer.get('game') or {}).get('nextMode')
    if not isinstance(phase,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]+',phase) or phase=='NORMAL':return None
    policy=(r'automaticPickGame:\{[^{}]{0,1000}optionSelection:\w+=>([0-9]{1,2}),'
        r'type:\w+\.ASBonusPickOptions\.PICK_MODE,pickNeededForModes:\[([^\]]{1,1000})\]')
    constants=[m[1] for m in re.finditer(policy,source) if re.fullmatch(_mode_reference(source,phase),m[2])]
    if len(constants)!=1:return None
    value=constants[0]
    wire=(r'pickAndClickBet\((\w+),(\w+)=!0\)\{const (\w+)=\{selectedIndex:\1\.toString\(\)\},'
        r'(\w+)=\{type:\w+\.APIBetType\.ZERO_BET,bet:"0\.00",playerInteraction:\3\};this\.sendRequest\(\4,!\2\)\}')
    if not re.search(wire,source):return None
    binding=(r'([\w$]+)\.gameFlowController\.addGameModeFlowStatePresentationMap\('+_mode_reference(source,phase)
        +r',new Map\(\[\[\w+\.FlowState\.IDLE,([\w$]+)\]')
    proven=[]
    for bind in re.finditer(binding,source):
        contexts=[h for h in _module_headers(source) if h.end()<=bind.start()]
        if not contexts:continue
        context=contexts[-1];prefix=source[context.end()-1:bind.start()]
        assignments=list(re.finditer(r'\b'+re.escape(bind[2])+r'=new ([\w$]+\.[\w$]+)(?:\(\))?(?=[,;])',prefix))
        if len(assignments)!=1:continue
        presentation=class_record(source,bind.start(),assignments[0][1],block)
        if not presentation:continue
        methods=_members(presentation[0],block);start=methods.get('start')
        if not start:continue
        body=start[1]
        idle=re.match(r'if\(this\.([\w$]+)='+re.escape(start[0])+r',this\.\1\.state===\w+\.FlowState\.IDLE\)\{',body)
        if idle:
            branch=block(body,idle.end()-1,len(body))
            if not branch:continue
            body=branch[1:-1]
        parts=expressions(body)
        live=(r'(?:[\w$]+=)?([\w$]+\.[\w$]+)\.([\w$]+)\.([\w$]+)\((\w+)=>\{?this\.([\w$]+)\(\4\)\}?,\1\.apiPlugin\.isReplay\)')
        found=[(part,m) for part in parts if (m:=re.fullmatch(live,part)) and _reaches(parts,part)]
        if len(found)!=1:continue
        call=found[0][1];done=methods.get(call[5])
        if not done or not re.fullmatch(r'this\.[\w$]+\.finish\(\),'+re.escape(call[1])+r'\.apiPlugin\.betHandler\.pickAndClickBet\('+re.escape(done[0])+r',!1\)',done[1]):continue
        owner=class_record(source,presentation[2],call[1],block)
        if not owner:continue
        owner_name=call[1].split('.')[1]
        module=block(source,context.end()-1,len(source))
        if not module or not context.end()-1<=owner[2]<context.end()-1+len(module):continue
        if not re.search(re.escape(context[3])+r'\.'+re.escape(owner_name)+'='+re.escape(bind[1])+r'(?=[,;}])',module):continue
        creates=list(re.finditer(re.escape(bind[1])+r'\.'+re.escape(call[2])+r'=new ([\w$]+\.[\w$]+)(?=[,;(])',module))
        if len(creates)!=1:continue
        aliases={bind[1]}
        for _ in range(8):
            discovered=set()
            for alias in aliases:discovered.update(re.findall(r'(?<![\w$.])([\w$]+(?:\.[\w$]+){0,3})='+re.escape(alias)+r'(?=[,;)}\]])',module))
            if discovered<=aliases:break
            aliases.update(discovered)
        else:continue
        panel_property=r'(?:\.'+re.escape(call[2])+r'|\[\s*["\']'+re.escape(call[2])+r'["\']\s*\])'
        if sum(len(re.findall(r'(?<![\w$.])'+re.escape(alias)+panel_property+r'=(?![=>])',module)) for alias in aliases)!=1:continue
        creation=creates[0];view=class_record(source,context.end()-1+creation.start(),creation[1],block)
        if not view:continue
        members=_members(view[0],block);show=members.get(call[3])
        if not show:continue
        parameter=show[0].split(',')[0];show_parts=expressions(show[1])
        callbacks=[m[1] for part in show_parts if (m:=re.fullmatch(r'this\.([\w$]+)='+re.escape(parameter),part)) and _reaches(show_parts,part)]
        if len(callbacks)!=1:continue
        callback=callbacks[0]
        if len(re.findall(r'this\.'+re.escape(callback)+r'=(?!=)',view[0]))!=2:continue
        if re.search(r'this\[\s*["\']'+re.escape(callback)+r'["\']\s*\]',view[0]):continue
        if re.findall(r'this\.'+re.escape(callback)+r'\(([^()]*)\)',view[0])!=[value]:continue
        for method,(args,text) in members.items():
            if args:continue
            signal=(r'^const ([\w$]+)=[\w$.]+\.gsap\.timeline\(\{onStart:\(\)=>\{if\(!([\w$]+\.[\w$]+)\.apiPlugin\.isReplay\)\{'
                r'if\(null==this\.'+re.escape(callback)+r'\)throw new Error\("[^"\\]{1,100}"\);this\.'+re.escape(callback)+r'\('+value+r'\),this\.'+re.escape(callback)+r'=void 0\}\}\}\)')
            signal_match=re.match(signal,text)
            if not signal_match:continue
            signal_owner=class_record(source,view[2],signal_match[2],block)
            if not signal_owner or signal_owner[2]!=owner[2]:continue
            if re.search(re.escape(signal_match[1])+r'\.(?:pause|kill|stop|clear|reverse)\(',text):continue
            clicks=[name for name,(arg,content) in members.items() if not arg and expressions(content)[-1:]==['this.'+method+'()'] and not re.search(r'\b(?:return|throw|if)\b',content)]
            if len(clicks)!=1 or not _installed_button(members,clicks[0]):continue
            proven.append({'type':'zeroBet','bet':'0.00','playerInteraction':{'selectedIndex':value}})
    return proven[0] if len(proven)==1 else None
