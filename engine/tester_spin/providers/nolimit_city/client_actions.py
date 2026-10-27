"""Read bounded client action bindings. Never execute downloaded JavaScript.

Only the observed unconditional flow and zero-bet controller shapes are accepted.
Unknown/conditional call shapes stay unresolved; names of games are immaterial.
"""
import re
from .protocol import MAX_BODY,_money


def _block(source,start,limit=16000):
    """Balanced JS block, skipping quoted strings and comments."""
    depth=0;quote=None;escaped=False;i=start;end=min(len(source),start+limit)
    while i<end:
        char=source[i]
        if quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=None
        elif char in ('"',"'",'`'):quote=char
        elif source.startswith('//',i):
            newline=source.find('\n',i+2,end)
            if newline<0:return None
            i=newline
        elif source.startswith('/*',i):
            close=source.find('*/',i+2,end)
            if close<0:return None
            i=close+1
        elif char=='{':depth+=1
        elif char=='}':
            depth-=1
            if depth==0:return source[start:i+1]
        i+=1
    return None


def _exported_class(source,name):
    matches=list(re.finditer(r'\b\w+\.'+re.escape(name)+r'=class\{',source))
    if len(matches)==1:return _block(source,matches[0].end()-1)
    if matches:return None
    found=[]
    for export in re.finditer(r'\b\w+\.'+re.escape(name)+r'=(\w+)(?=[},;])',source):
        start=max(0,export.start()-16000)
        for definition in re.finditer(r'class '+re.escape(export[1])+r'(?: extends [\w.]+)?\{',source[start:export.start()]):
            offset=start+definition.end()-1;body=_block(source,offset)
            if body and offset+len(body)==export.start():found.append(body)
    return found[0] if len(found)==1 else None


def _event_bridge(source):
    subscription=r'BalanceEvent\.ZERO_BET,\(?(\w+)=>this\.onZeroBet\(\1\.params\[0\]\)'
    handler=r'onZeroBet\(\w+\)\{this\._slotApi\.betHandler\.zeroBet\(\),'
    return bool(re.search(subscription,source) and re.search(handler,source))


def _mode_reference(source,mode):
    """Match an exact wire phase as a static enum reference or JS literal."""
    references=[r'\w+\.\w+\.'+re.escape(mode),
                re.escape('"'+mode+'"'), re.escape("'"+mode+"'")]
    enum=r'class (\w+) extends \w+\.GameMode\{\}\w+\.(\w+)=\1,([^;}]{1,4000})'
    for match in re.finditer(enum,source):
        for value in re.finditer(r'\b'+re.escape(match[1])+r'\.(\w+)="'+re.escape(mode)+r'"(?=[,;]|$)',match[3]):
            references.append(r'\w+\.'+re.escape(match[2])+r'\.'+re.escape(value[1]))
    return '(?:'+'|'.join(references)+')'


def automatic_command(source,answer,*,direct_demo_transport=False):
    if not isinstance(source,str) or len(source)>MAX_BODY:return None
    if direct_demo_transport is True:
        from .direct_demo import direct_demo_source
        source=direct_demo_source(source,_block)
    game=answer.get('game') or {};mode=game.get('nextMode')
    if not isinstance(mode,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]+',mode) or mode=='NORMAL':return None
    # A paid quote/decision never becomes a bare zeroBet.
    try:
        if 'extraSpinCost' in game and _money(game['extraSpinCost'])!=0:return None
    except ValueError:return None
    if any(field in game and game[field] is not False for field in ('wasExtraSpin','isExtraSpin')):return None
    result={'type':'zeroBet','bet':'0.00'}
    reference=_mode_reference(source,mode)
    binding=(r'addGameModeFlowStatePresentationMap\('+reference
             +r',new Map\(\[\[\w+\.FlowState\.IDLE,(\w+)\]')
    inline=(r'addGameModeFlowStatePresentationMap\('+reference
        +r',new Map\(\[\[\w+\.FlowState\.IDLE,\{start:(\w+)=>\{\w+\.apiPlugin\.betHandler\.zeroBet\(\),\1\.finish\(\)\}\}\]')
    if re.search(inline,source):return result
    wrapped=(r'addGameModeFlowStatePresentationMap\('+reference
        +r',new Map\(\[\[\w+\.FlowState\.IDLE,([\w$]+\.[\w$]+)\.createFlow\(\[([^\]]{1,1600})\]\)')
    for match in re.finditer(wrapped,source):
        from .static_bindings import proves_wrapped_flow
        if proves_wrapped_flow(source,match.start(),match[1],match[2],_block):return result
    direct=(r'addGameModeFlowStatePresentationMap\('+reference
        +r',new Map\(\[\[\w+\.FlowState\.IDLE,new \w+\.(\w+)(?:\(\))?\]')
    for match in re.finditer(direct,source):
        from .static_bindings import proves_bound_action
        owner=re.search(r'new ([\w$]+\.[\w$]+)',match[0])
        if owner and proves_bound_action(source,match.start(),owner[1],answer,_block,**({'direct_demo_transport':True} if direct_demo_transport is True else {})):return result
        body=_exported_class(source,match[1])
        if body:
            from .lifecycle import proves_zero_bet
            if proves_zero_bet(body,_block):return result
    for match in re.finditer(binding,source):
        prefix=source[max(0,match.start()-12000):match.start()]
        constructor=r'new \w+\.(\w+)(?:\(\))?'
        comma=r'\((?:new \w+\.\w+(?:\(\))?,)*new \w+\.(\w+)(?:\(\))?\)'
        assignments=list(re.finditer(r'\b'+re.escape(match[1])+r'=(?:'+constructor+'|'+comma+r')(?=[,;)])',prefix))
        if not assignments:continue
        assignment=assignments[-1]
        if re.search(r'\b'+re.escape(match[1])+r'\s*=',prefix[assignment.end():]):continue
        from .static_bindings import proves_bound_action
        owner=re.search(r'new ([\w$]+\.[\w$]+)',assignment[0])
        if owner and proves_bound_action(source,match.start(),owner[1],answer,_block,**({'direct_demo_transport':True} if direct_demo_transport is True else {})):return result
        body=_exported_class(source,assignment[1] or assignment[2])
        if not body:continue
        from .lifecycle import proves_zero_bet
        if proves_zero_bet(body,_block):return result
    # Legacy animation lists can include a conditional pick presentation. Only
    # its explicit argument-free ELSE branch is automatic in other bound modes.
    for config in re.finditer(r'\b'+re.escape(mode)+r':\{idle:\[([^\]]{0,1600})\]',source):
        for name in re.findall(r'new \w+\.(\w+)',config[1]):
            body=_exported_class(source,name)
            if not body:continue
            from .lifecycle import proves_zero_bet
            if proves_zero_bet(body,_block,entry='getAnimation'):return result
            branch=re.search(r'^\{getAnimation\((\w+)\)\{const \w+=new \w+\.TimelineLite,\w+=\1\.nextMode===\w+\.\w+\.[A-Z_]+\|\|\w+\.\w+\.[A-Z_]+\?\1\.freespinsLeft-1:-1;return \w+\.add\(\(\)=>\{if\(\1\.nextMode===\w+\.\w+\.([A-Z_]+)\)\{const (\w+)=\{selectedIndex:[\w.]+\};\w+\.\w+\.api\.betHandler\.zeroBet\(\3\)\}else \w+\.\w+\.api\.betHandler\.zeroBet\(\);',body)
            left=game.get('freespinsLeft',answer.get('remainingFreeSpins'))
            if branch and mode!=branch[2] and type(left) is int and left>0:return result
    from .event_actions import automatic_event_command
    event=automatic_event_command(source,answer,_block,direct_demo_transport=direct_demo_transport)
    if event is not None:return event
    from .fixed_signals import fixed_signal_command
    fixed=fixed_signal_command(source,answer,_block)
    if fixed is not None:return fixed
    if not _event_bridge(source):return None
    # Older registered controllers: exact trigger expression, no win threshold.
    for match in re.finditer(r'class (\w+) extends \w+\.(ZeroBetController|FreespinZeroBetController)\{',source):
        body=_block(source,match.end()-1,4000)
        if not body:continue
        if match[2]=='FreespinZeroBetController':
            left=game.get('freespinsLeft',answer.get('remainingFreeSpins'))
            if type(left) is not int or left<=0:continue
        trigger=re.search(r'calculateIsTriggered\((\w+)\)\{return ([^{};]+)\}',body)
        if not trigger:continue
        expression=re.sub(r'^this\.\w+='+re.escape(trigger[1])+r'\.nextMode,','',trigger[2])
        clauses=expression.split('||');phases=[]
        for clause in clauses:
            condition=re.fullmatch(re.escape(trigger[1])+r'\.nextMode=={1,2}\w+\.\w+\.([A-Z][A-Z0-9_]+)',clause)
            if condition is None:break
            phases.append(condition[1])
        if len(phases)!=len(clauses) or mode not in phases:continue
        export=re.match(r'\w+\.(\w+)='+re.escape(match[1])+r'(?=[};,])',source[match.end()-1+len(body):])
        if not export:continue
        if re.search(r'ZERO_BETS=\[[^\]]{0,1500}?\(\)=>new \w+\.'+re.escape(export[1])+r'(?=[,\]])',source):return result
    # Nested free respins: bind the configured idle class and its dispatch branch
    # to the same server modes. The event argument controls only the UI counter.
    idle=re.finditer(r'\b'+re.escape(mode)+r':\{idle:\[([^\]]{0,1600})\]',source)
    left=game.get('freespinsLeft',answer.get('remainingFreeSpins'))
    if game.get('respinActive') is not True or type(left) is not int or left<0:return None
    for config in idle:
        for name in re.findall(r'new \w+\.(\w+)',config[1]):
            body=_exported_class(source,name)
            if not body:continue
            # Both arms of the exact callback dispatch zeroBet. Match them
            # contiguously so an unknown enclosing guard cannot be skipped.
            base_branch=(r'\.add\(\[\(\)=>\{if\(\(this\._inRespinFS\|\|this\._intoRespinFS\)&&"FREESPIN"!==this\._data\.nextMode\)'
                r'\w+\.EventHandler\.dispatchEvent\(new \w+\.GameEvent\(\w+\.BalanceEvent\.ZERO_BET,this\._freespinsLeft\)\);else\{'
                r'let (\w+)=-1;if\(this\._wildOverlays\.forEach\(\((\w+),(\w+)\)=>\{\2&&\(\1=\3\)\}\),'
                r'\1>1&&this\._inRespin\|\|this\._intoRespin\|\|"'+re.escape(mode)+r'"===this\._data\.nextMode\)\{'
                r'let (\w+)=-1;this\._wildOverlays\.forEach\(\((\w+),(\w+)\)=>\{\5&&\(\4=\6\)\}\),'
                r'\w+\.EventHandler\.dispatchEvent\(new \w+\.GameEvent\(\w+\.BalanceEvent\.ZERO_BET,--\4\)\)')
            into=r'this\._intoRespin="NORMAL"===\w+\.mode&&"'+re.escape(mode)+r'"===\w+\.nextMode'
            if re.search(into,body) and re.search(base_branch,body) and game.get('mode') in ('NORMAL',mode):return result
            if left==0:continue
            guards=(r'this\._intoRespinFS="FREESPIN"===\w+\.mode&&"'+re.escape(mode)+r'"===\w+\.nextMode',
                    r'this\._inRespinFS="'+re.escape(mode)+r'"===\w+\.mode',
                    r'if\(\(this\._inRespinFS\|\|this\._intoRespinFS\)&&"FREESPIN"!==this\._data\.nextMode\)\w+\.EventHandler\.dispatchEvent\(new \w+\.GameEvent\(\w+\.BalanceEvent\.ZERO_BET,this\._freespinsLeft\)\)')
            if all(re.search(pattern,body) for pattern in guards) and game.get('mode') in ('FREESPIN',mode):return result
    return None

