"""Conservative reverse engineering of client-bound settlement buttons.

Bindings, literal wire ids and root-dependent visibility must all agree. No game
name, phase name, feature selector or observed click supplies a missing domain.
"""
import re
from .client_actions import _block,_exported_class,_mode_reference
from .protocol import MAX_BODY,_money
from .lifecycle import expressions,methods


def _method(body,name):
    found=methods(body,_block).get(name)
    return '{'+found[1]+'}' if found is not None else None


def _idle_classes(source,phase):
    ref='(?:'+_mode_reference(source,phase)+'|"'+re.escape(phase)+'")'
    binding=r'addGameModeFlowStatePresentationMap\('+ref+r',new Map\(\[\[\w+\.FlowState\.IDLE,(\w+)\]'
    for m in re.finditer(binding,source):
        prefix=source[max(0,m.start()-12000):m.start()]
        assigns=list(re.finditer(r'\b'+re.escape(m[1])+r'=new \w+\.(\w+)(?:\(\))?(?=[,;)])',prefix))
        if not assigns:continue
        last=assigns[-1]
        if re.search(r'\b'+re.escape(m[1])+r'\s*=',prefix[last.end():]):continue
        body=_exported_class(source,last[1])
        if body:yield body


def settlement_button_domain(source,answer,mode):
    if not isinstance(source,str) or len(source)>MAX_BODY:return None
    game=answer.get('game') or {};phase=game.get('nextMode');mode=mode or {}
    if (not isinstance(phase,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]+',phase)
            or game.get('wasFeatureBuy') is not True or mode.get('kind')!='PURCHASE'
            or not isinstance(mode.get('selector'),str) or _money(game.get('accumulatedRoundWin'))<=0):return None
    # The standard SDK must encode this method as one exact, zero-stake choice.
    wire=(r'pickAndClickBet\((\w+),(\w+)=!0\)\{const (\w+)=\{selectedIndex:\1\.toString\(\)\},'
        r'(\w+)=\{type:\w+\.APIBetType\.ZERO_BET,bet:"0\.00",playerInteraction:\3\};this\.sendRequest\(\4,!\2\)\}')
    if not re.search(wire,source):return None
    candidates=[]
    for idle in _idle_classes(source,phase):
        # Explicit live branch, separately from the replay-selected value.
        live=re.search(r'else \w+\.add\(\w+\.\w+\.(\w+)\.(\w+)\(\)\)',idle)
        if not live:continue
        owner,panel=live.groups()
        creates=list(re.finditer(r'\b\w+\.'+re.escape(owner)+r'=new \w+\.(\w+)(?=[,;(])',source))
        if len(creates)!=1:continue
        body=_exported_class(source,creates[0][1])
        if not body:continue
        method=_method(body,panel)
        if not method:continue
        header=re.match(r'\{const (\w+)=\w+\.\w+\.model\.(\w+)\?0:1;return \w+\.gsap\.timeline\(\)\.add\(\(\)=>\{',method)
        if not header:continue
        flagvar,flag=header.groups()
        callbacks=re.match(r'this\.(\w+)=0=='+re.escape(flagvar)+r'\?this\.(\w+):this\.(\w+),this\.(\w+)=this\.(\w+),',method[header.end():])
        if not callbacks:continue
        yes_cb,yes_method,warning,no_cb,no_method=callbacks.groups()
        enable=re.search(r'this\.(\w+)\.enable\(!0\),1=='+re.escape(flagvar)+r'&&this\.(\w+)\.enable\(!0\)',method)
        if not enable:continue
        yes_button,no_button=enable.groups()
        callback_body=_block(method,header.end()-1)
        parts=expressions(callback_body[1:-1]) if callback_body else []
        expected=[
            r'this\.'+re.escape(yes_cb)+r'=0=='+re.escape(flagvar)+r'\?this\.'+re.escape(yes_method)+r':this\.'+re.escape(warning),
            r'this\.'+re.escape(no_cb)+r'=this\.'+re.escape(no_method),
            r'this\.\w+\.visible=!0',r'this\.\w+\.visible=!1',
            r'this\.\w+\.state\.setAnimation\(0,"[^"\\]{1,80}",!0\)',
            r'this\.'+re.escape(yes_button)+r'\.enable\(!0\)',
            r'1=='+re.escape(flagvar)+r'&&this\.'+re.escape(no_button)+r'\.enable\(!0\)',
        ]
        if len(parts)!=len(expected) or not all(re.fullmatch(pattern,part) for pattern,part in zip(expected,parts)):continue
        parameter=re.fullmatch(r'(\w+)=!1',methods(body,_block)[panel][0])
        if not parameter:continue
        duration=re.escape(parameter[1])+r'\?0:\.2'
        fade=(r'\)\.add\(\w+\.gsap\.to\(this\.'+re.escape(yes_button)+r',\{duration:'+duration+r',alpha:1\}\)\)'
            +r'\.add\(\w+\.gsap\.to\(this\.'+re.escape(no_button)+r',\{duration:'+duration+r',alpha:'+re.escape(flagvar)+r'\}\),"<"\)\}')
        if not re.fullmatch(fade,method[header.end()-1+len(callback_body):]):continue

        if any(len(re.findall(r'this\.'+re.escape(button)+r'\.enable\(',method))!=1 for button in (yes_button,no_button)):continue
        if re.search(r'\.(?:pause|kill|stop|clear|reverse)\(',method):continue
        # Resolve the model predicate from the current client, not feature spelling.
        predicates=re.findall(r'this\.'+re.escape(flag)+r'="([A-Z][A-Z0-9_]+)"==this\.buyFeatureName&&this\.data\.wasFeatureBuy',source)
        if (not predicates or len(set(predicates))!=1
                or len(re.findall(r'this\.'+re.escape(flag)+r'=(?!=)',source))!=len(predicates)):continue
        restricted=mode['selector']==predicates[0]
        ids=[]
        for name in (no_method,yes_method):
            callback=_method(body,name)
            if not callback:break
            parts=expressions(callback[1:-1])
            if any(re.search(r'\b(return|throw|if|for|while|switch|try)\b',part) for part in parts):break
            calls=[m[1] for part in parts if (m:=re.fullmatch(r'\w+\.\w+\.apiPlugin\.betHandler\.pickAndClickBet\((\d+),!1\)',part))]
            if len(re.findall(r'pickAndClickBet\(',callback))!=len(calls):break
            if len(calls)!=1:break
            ids.append(int(calls[0]))
        if len(ids)!=2 or len(set(ids))!=2 or any(v>31 for v in ids):continue
        # The confirmation panel must reach the same accept method, and its back
        # button returns to the original panel rather than dispatching a request.
        warning_body=_method(body,warning)
        sound=r'\w+\.\w+\.soundPlayer\.playSound\(\w+\.\w+\.[A-Z][A-Z0-9_]*\)'
        warning_parts=expressions(warning_body[1:-1]) if warning_body else []
        expected_warning=[
            r'this\.'+re.escape(yes_cb)+r'=this\.'+re.escape(yes_method),
            r'this\.'+re.escape(no_cb)+r'=\(\)=>\{'+sound+r',this\.'+re.escape(panel)+r'\(!0\)\}',
            r'this\.\w+\.visible=!1',r'this\.\w+\.visible=!0',sound,
        ]
        if len(warning_parts)!=len(expected_warning) or not all(re.fullmatch(pattern,part) for pattern,part in zip(expected_warning,warning_parts)):continue
        # Callback installation is local to these actual buttons.
        constructor=_method(body,'constructor')
        if not constructor:continue
        if not all(re.search(r'this\.'+re.escape(button)+r'\.addClickCallback\(\(\)=>this\.'+re.escape(cb)+r'\(\)\)',constructor) for button,cb in ((yes_button,yes_cb),(no_button,no_cb))):continue
        options=[ids[1]] if restricted else ids
        candidates.append({'state':phase,'options':options,'available':options,
            'ack_field':'SETTLED_PHASE_AND_MONEY','source':'CLIENT_BOUND_SETTLEMENT_BUTTONS',
            'request_field':'selectedIndex','root_selector':mode['selector'],
            'visibility':'ROOT_DEPENDENT_CLIENT_PREDICATE','terminal_required':True})
    return candidates[0] if len(candidates)==1 else None
