"""Bounded client-declared choice domains; no JavaScript execution or guesses."""
import re
from .protocol import MAX_BODY

def _modes(text):
    return set(re.findall(r'\.([A-Z][A-Z0-9_]+)\b|"([A-Z][A-Z0-9_]+)"',text))

def _contains_mode(text,mode):
    return any(mode in pair for pair in _modes(text))

def choice_domain(source,answer,root_mode=None):
    if not isinstance(source,str) or len(source)>MAX_BODY:raise ValueError('Nolimit City: cliente de elecciones inválido')
    game=answer.get('game') or {};mode=game.get('nextMode');candidates=[]
    static=r'options:(?:\(\)=>)?\[(.{0,2000}?)\],type:\w+\.ASBonusPickOptions\.PICK_MODE,pickNeededForModes:\[([^\]]+)\]'
    for match in re.finditer(static,source):
        if not _contains_mode(match[2],mode):continue
        ids=[int(value) for value in re.findall(r'\bid:(\d+)\b',match[1])]
        if not ids or len(ids)>32 or len(ids)!=len(set(ids)):continue
        if not any(type(game.get(field)) is int for field in ('playerSelect','playerSelection','playerFSSelection')):
            from .finite_choices import nested_boolean_domain
            nested=nested_boolean_domain(source,answer,ids)
            if nested is not None:candidates.append(nested)
            else:
                from .literal_button_choices import literal_button_domain
                literal=literal_button_domain(source,answer,ids)
                if literal is not None:candidates.append(literal)
            continue
        candidates.append({'state':mode,'options':ids,'available':ids,'ack_field':next(field for field in ('playerSelect','playerSelection','playerFSSelection') if type(game.get(field)) is int),'source':'CLIENT_STATIC_IDS'})
    automatic=r'automaticPickGame:\{[^{}]{0,1000}?optionSelection:(\w+)=>this\.(\w+)\(\1\)[^{}]{0,1000}?pickNeededForModes:\[([^\]]+)\]'
    for match in re.finditer(automatic,source):
        if not _contains_mode(match[3],mode):continue
        function=re.search(r'\b'+re.escape(match[2])+r'\((\w+)\)\{(.{0,1200}?)return \w+\}',source)
        if not function:continue
        field=re.search(r'-1=='+re.escape(function[1])+r'\.(\w+)\[(\w+)\]&&\(\w+=\2\)',function[2])
        if not field:continue
        bounds=re.search(r'(?:let|const|var)\s+(\w+)=[\w$.]+\.randomIntInRange\(0,(\d+)\)',function[2])
        if not bounds or bounds[1]!=field[2] or int(bounds[2])>=32:continue
        values=game.get(field[1]);available=[]
        if not isinstance(values,list) or not values or len(values)!=int(bounds[2])+1 or any(type(value) is not int or value<-1 for value in values):continue
        available=[i for i,value in enumerate(values) if value==-1]
        if available:candidates.append({'state':mode,'options':list(range(len(values))),'available':available,'ack_field':field[1],'before':list(values),'source':'SERVER_UNPICKED_ARRAY'})
    from .finite_choices import boolean_array_domains
    candidates.extend(boolean_array_domains(source,answer))
    from .bound_choices import settlement_button_domain
    bound=settlement_button_domain(source,answer,root_mode)
    if bound is not None:candidates.append(bound)
    if len(candidates)!=1:raise ValueError('Nolimit City: elección sin dominio único declarado por cliente y servidor: '+str(mode))
    return candidates[0]

def confirm_choice(domain,selected,answer):
    game=answer.get('game') or {};field=domain['ack_field'];value=game.get(field)
    if selected not in domain['available']:raise ValueError('Nolimit City: elección fuera de su dominio')
    if domain['source']=='CLIENT_BOUND_SETTLEMENT_BUTTONS':
        from .state import settled_state
        if (game.get('mode')!=domain['state'] or game.get('nextMode')!='NORMAL'
                or answer.get('balance') is None or not settled_state(answer)):
            raise ValueError('Nolimit City: boton sin liquidacion y acuse de fase contrastados')
    elif domain['source']=='CLIENT_BOUND_LITERAL_BUTTONS':
        from .protocol import _money
        node=game
        for key in domain['result_path']:
            node=node.get(key) if isinstance(node,dict) else None
        if (type(selected) is not int or game.get('mode')!=domain['state']
                or game.get('nextMode')!=domain['target_phase']):
            raise ValueError('Nolimit City: elección sin resultado de fase confirmado')
        _money(node)
    elif domain['source']=='CLIENT_BOUND_NESTED_BOOLEAN':
        nested=game.get(domain['ack_path'][0])
        if (type(selected) is not int or game.get('nextMode')!=domain['target_phase'] or not isinstance(nested,dict)
                or type(nested.get(domain['ack_path'][1])) is not bool
                or nested[domain['ack_path'][1]] is not domain['ack_values'][str(selected)]):
            raise ValueError('Nolimit City: elección sin acuse booleano anidado confirmado')
    elif domain['source']=='CLIENT_UNPICKED_BOOLEAN_ARRAY':
        if (type(selected) is not int or not isinstance(value,list) or len(value)!=len(domain['before'])
                or any(type(item) is not bool for item in value)
                or value[selected] is not True
                or any(value[index] is not old for index,old in enumerate(domain['before']) if index!=selected)):
            raise ValueError('Nolimit City: elección booleana no aplicada o cambió otra casilla')
    elif domain['source']=='CLIENT_STATIC_IDS':
        if type(value) is not int or value!=selected:raise ValueError('Nolimit City: elección no confirmada por servidor')
    else:
        if (not isinstance(value,list) or len(value)!=len(domain['options'])
                or any(type(item) is not int or item<-1 for item in value) or value[selected]<0
                or any(old>=0 and value[index]!=old for index,old in enumerate(domain['before']))):
            raise ValueError('Nolimit City: elección no aplicada o dominio del servidor modificado')


def has_collect_contract(source):
    """Bind the collect call to its actual zero-stake request construction."""
    if not isinstance(source,str) or len(source)>MAX_BODY:return False
    call=r'collectWin\(\)\{return"GAMBLE"!==this\._nextMode\?Promise\.resolve\(!1\):\(this\.gambleBet\(!0\),'
    method=(r'gambleBet\((\w+),[^)]{0,80}\)\{const (\w+)=\{\};[^{}]{0,250}?'
        r'\2\.gambleCollected=\1;const (\w+)=\{type:\w+\.APIBetType\.GAMBLE_BET,'
        r'bet:"0\.00",playerInteraction:\2\};[^{}]{0,160}?this\.sendRequest\(\3\)')
    return bool(re.search(call,source) and re.search(method,source))
