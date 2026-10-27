"""Client policies that enumerate the entire current server boolean array."""
import hashlib
import re
from .client_actions import _mode_reference


def boolean_array_domains(source,answer):
    game=answer.get('game') or {};phase=game.get('nextMode')
    if not isinstance(phase,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]+',phase):return []
    wire=(r'pickAndClickBet\((\w+),(\w+)=!0\)\{const (\w+)=\{selectedIndex:\1\.toString\(\)\},'
        r'(\w+)=\{type:\w+\.APIBetType\.ZERO_BET,bet:"0\.00",playerInteraction:\3\};this\.sendRequest\(\4,!\2\)\}')
    if not re.search(wire,source):return []
    policy=(r'automaticPickGame:\{[^{}]{0,1000}?optionSelection:(\w+)=>\{let (\w+)=\[\];'
        r'for\(let (\w+)=0;\3<\1\.(\w+)\.length;\3\+\+\)0==\1\.\4\[\3\]&&\2\.push\(\3\);'
        r'return \2=[\w$.]+\.shuffleArray\(\2\),\2\[0\]\},type:\w+\.ASBonusPickOptions\.PICK_MODE,'
        r'pickNeededForModes:\[([^\]]{1,1000})\]')
    domains=[]
    for match in re.finditer(policy,source):
        if not re.fullmatch(_mode_reference(source,phase),match[5]):continue
        values=game.get(match[4])
        if not isinstance(values,list) or not 0<len(values)<=32 or any(type(v) is not bool for v in values):continue
        available=[i for i,value in enumerate(values) if value is False]
        if not available:continue
        domains.append({'state':phase,'options':list(range(len(values))),'available':available,
            'ack_field':match[4],'before':list(values),'source':'CLIENT_UNPICKED_BOOLEAN_ARRAY',
            'request_field':'selectedIndex','request_type':'zeroBet',
            'source_sha256':hashlib.sha256(source.encode('utf-8')).hexdigest()})
    return domains


def _members(body):
    from .client_actions import _block
    result={};cursor=1
    while cursor<len(body)-1:
        match=re.match(r'(?:static )?([\w$]+)\(([^)]*)\)\{',body[cursor:])
        if not match:return {}
        value=_block(body,cursor+match.end()-1,len(body))
        if not value or match[1] in result:return {}
        result[match[1]]=(match[2],value[1:-1]);cursor+=match.end()-1+len(value)
    return result


def _reaches(parts,effect):
    """A required direct effect cannot follow a root exit or unknown control flow."""
    if effect not in parts:return False
    return not any(re.match(r'^(?:if|return|throw|switch|for|while|try|do)\b',part)
        for part in parts[:parts.index(effect)])


def nested_boolean_domain(source,answer,ids):
    """Resolve an active pick panel whose same predicate sets and encodes its ack."""
    from .client_actions import _block
    from .static_bindings import class_record
    game=answer.get('game') or {};phase=game.get('nextMode')
    if not isinstance(phase,str):return None
    wire=(r'pickAndClickBet\((\w+),(\w+)=!0\)\{const (\w+)=\{selectedIndex:\1\.toString\(\)\},'
        r'(\w+)=\{type:\w+\.APIBetType\.ZERO_BET,bet:"0\.00",playerInteraction:\3\};this\.sendRequest\(\4,!\2\)\}')
    if not re.search(wire,source):return None
    binding=(r'([\w$]+)\.gameFlowController\.addGameModeFlowStatePresentationMap\('+_mode_reference(source,phase)
        +r',new Map\(\[\[\w+\.FlowState\.IDLE,([\w$]+)\]')
    domains=[]
    for bind in re.finditer(binding,source):
        prefix=source[max(0,bind.start()-16000):bind.start()]
        assigns=list(re.finditer(r'\b'+re.escape(bind[2])+r'=new ([\w$]+\.[\w$]+)(?:\(\))?(?=[,;])',prefix))
        if len(assigns)!=1:continue
        record=class_record(source,bind.start(),assigns[0][1],_block)
        if not record:continue
        available=_members(record[0]);start=available.get('start');complete=available.get('complete')
        if not start or not complete:continue
        live=re.search(r'([\w$]+\.[\w$]+)\.([\w$]+)\.show\((\w+)=>this\.complete\(\3\),\1\.apiPlugin\.isReplay\)',start[1])
        if not live:continue
        # The active completion forwards its argument unchanged to the SDK.
        if not re.fullmatch(r'this\.[\w$]+\.finish\(\),[\w$.]+\.betHandler\.pickAndClickBet\('+re.escape(complete[0])+r',!1\)',complete[1]):continue
        owner_name=live[1].split('.')[1]
        # Resolve the imported owner to its lexical module, preventing a same-name
        # exported class elsewhere from supplying the panel or predicate.
        owner=class_record(source,record[2],live[1],_block)
        if not owner:continue
        headers=list(re.finditer(r'(?:^|[,{])([0-9]+)\(([\w$]+),([\w$]+)(?:,([\w$]+))?\)\{',source))
        contexts=[m for m in headers if m.end()<=owner[2]]
        if not contexts:continue
        context=contexts[-1];content=_block(source,context.end()-1,len(source))
        if not content or not re.search(re.escape(context[3])+r'\.'+re.escape(owner_name)+'='+re.escape(bind[1])+r'(?=[,;}])',content):continue
        creates=list(re.finditer(re.escape(bind[1])+r'\.'+re.escape(live[2])+r'=new ([\w$]+\.[\w$]+)(?=[,;(])',content))
        if len(creates)!=1:continue
        creation=creates[0];view=class_record(source,context.end()-1+creation.start(),creation[1],_block)
        if not view:continue
        members=_members(view[0]);show=members.get('show')
        if not show:continue
        show_arg=show[0].split(',')[0]
        callbacks=re.findall(r'this\.([\w$]+)='+re.escape(show_arg)+r'(?=[,;]|$)',show[1])
        if len(callbacks)!=1:continue
        callback=callbacks[0]
        for handler,(parameter,body) in members.items():
            if not re.fullmatch(r'[\w$]+',parameter):continue
            assignment=re.search(r'([\w$]+\.'+re.escape(owner_name)+r')\.model\.data\.([\w$]+)\.([\w$]+)='+re.escape(parameter)+r'===([\w$]+\.[\w$]+)(?=[,;])',body)
            if not assignment:continue
            from .lifecycle import expressions
            parts=expressions(body)
            if not _reaches(parts,assignment[0]):continue
            ack_owner=class_record(source,view[2],assignment[1],_block)
            if not ack_owner or ack_owner[2]!=owner[2]:continue
            predicate=re.escape(parameter+'==='+assignment[4])
            emitted=re.findall(r'this\.'+re.escape(callback)+r'\('+predicate+r'\?([0-9]+):([0-9]+)\)',body)
            if len(emitted)!=1 or len(re.findall(r'this\.'+re.escape(callback)+r'\(',body))!=1:continue
            yes,no=map(int,emitted[0])
            call='this.'+callback+'('+parameter+'==='+assignment[4]+'?'+str(yes)+':'+str(no)+')'
            reachable=_reaches(parts,call)
            timelines=[]
            for part in parts:
                timeline=re.fullmatch(r'(?:const|let|var) ([\w$]+)=new [\w$.]+\.TimelineLite',part)
                if timeline:timelines.append(timeline[1])
            for timeline in timelines:
                if re.search(re.escape(timeline)+r'\.(?:pause|kill|stop|clear|reverse)\(',body):continue
                for part in parts:
                    callback_part=re.fullmatch(re.escape(timeline)+r'\.add\(\(\)=>\{(.*)\}\)',part,re.S)
                    if not callback_part or not _reaches(parts,part):continue
                    inner=re.sub(r'^if\(null==this\.'+re.escape(callback)+r'\)throw new Error\("[^"\\]{1,100}"\);','',callback_part[1])
                    inner_parts=expressions(inner)
                    if _reaches(inner_parts,call):reachable=True
            if not reachable:continue
            modes=re.findall(re.escape(assignment[1])+r'\.setMode\(([^()]{1,150})\)',body)
            if len(modes)!=1:continue
            mode_call=assignment[1]+'.setMode('+modes[0]+')'
            mode_reachable=_reaches(parts,mode_call)
            for timeline in timelines:
                if re.search(re.escape(timeline)+r'\.(?:pause|kill|stop|clear|reverse)\(',body):continue
                for part in parts:
                    block=re.fullmatch(re.escape(timeline)+r'\.add\(\(\)=>\{(.*)\}\)',part,re.S)
                    if block and _reaches(parts,part) and _reaches(expressions(block[1]),mode_call):mode_reachable=True
            if not mode_reachable:continue
            literal=re.fullmatch(r'["\']([A-Z][A-Z0-9_]+)["\']',modes[0])
            if literal:targets={literal[1]}
            else:
                member=modes[0].split('.')[-1]
                possible=set(re.findall(r'\b[\w$]+\.'+re.escape(member)+r'="([A-Z][A-Z0-9_]+)"',source))
                targets={value for value in possible if re.fullmatch(_mode_reference(source,value),modes[0])}
            if len(targets)!=1:continue
            target=targets.pop()
            if yes==no or set(ids)!={yes,no}:continue
            # Both constructor-installed button callbacks invoke this handler;
            # the predicate's enum member is one of the two distinct arguments.
            calls=re.findall(r'new [\w$.]+\(([\w$]+\.[\w$]+),\(\)=>this\.'+re.escape(handler)+r'\(\1\)\)',view[0])
            if len(calls)!=2 or len(set(calls))!=2 or assignment[4] not in calls:continue
            nested=game.get(assignment[2])
            if not isinstance(nested,dict) or type(nested.get(assignment[3])) is not bool:continue
            domains.append({'state':phase,'options':ids,'available':ids,'ack_field':assignment[2],
                'target_phase':target,'ack_path':[assignment[2],assignment[3]],'ack_values':{str(yes):True,str(no):False},
                'source':'CLIENT_BOUND_NESTED_BOOLEAN','request_field':'selectedIndex',
                'source_sha256':hashlib.sha256(source.encode('utf-8')).hexdigest()})
    return domains[0] if len(domains)==1 else None
