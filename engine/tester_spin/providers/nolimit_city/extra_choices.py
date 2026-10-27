"""Client-declared literal offers funded only by the pending round prize."""
import hashlib,re
from functools import lru_cache
from decimal import Decimal
from .protocol import _money
from .errors import Unlearned
from .client_counters import counter_contract, counter_from_contract
from .operation_fields import step_win
from tester_spin.providers.repeat_purchase import funded_domain


def _selector_values(expression,depth=0):
    from .lifecycle import conditional_arms,_paren_end
    if depth>4:return None
    expression=expression.strip()
    while expression.startswith('(') and _paren_end(expression,0)==len(expression)-1:
        expression=expression[1:-1].strip()
    if re.fullmatch(r"(?:0|1|\"(?:0|1|yes|no)\"|'(?:0|1|yes|no)')",expression):return [expression]
    arms=conditional_arms(expression)
    if arms is None:return None
    left=_selector_values(arms[0],depth+1);right=_selector_values(arms[1],depth+1)
    return left+right if left is not None and right is not None else None


def numeric_domain(source,game,*,direct_demo_transport=False):
    if game.get('nextMode')!='EXTRA_SPIN':return None
    pattern=r'zeroBet\(\{playerSelectedExtraSpin:([^{}]{1,40})\}\)'
    literals=re.findall(pattern,source)
    if not literals or len(literals)!=len(re.findall(r'zeroBet\(\{playerSelectedExtraSpin:',source)):return None
    branches=[_selector_values(value) for value in literals]
    if any(value is None for value in branches):return None
    literals=[literal for values in branches for literal in values]
    if all(value in ('0','1') for value in literals) and set(literals)=={'0','1'}:options=[0,1]
    elif all(re.fullmatch(r"[\"'](?:0|1)[\"']",value) for value in literals) and {value[1:-1] for value in literals}=={'0','1'}:options=['0','1']
    elif all(re.fullmatch(r"[\"'](?:yes|no)[\"']",value) for value in literals) and {value[1:-1] for value in literals}=={'no','yes'}:options=['no','yes']
    else:return None
    price=_money(game.get('extraSpinCost'),positive=True)
    accumulated=_money(game.get('accumulatedRoundWin'))
    target=game.get('nextModeForExtraSpin')
    if target is not None and (not isinstance(target,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]+',target) or target in ('NORMAL','EXTRA_SPIN','EXTRA_SPIN_CHECK')):
        raise Unlearned('Nolimit City: destino del giro extra no declarado')
    domain={'state':'EXTRA_SPIN','options':options,'available':options,
        'request_field':'playerSelectedExtraSpin','wire_encoding':'PRESERVE_LITERAL',
        'ack_field':'numeric_extra_transition','source':'CLIENT_QUOTED_NUMERIC_EXTRA',
        'price_source':'game.extraSpinCost','quoted_price':str(price),
        'quoted_accumulated':str(accumulated),'target_phase':target}
    counter=counter_contract(source)
    if counter is not None:domain['remaining_counter_contract']=counter
    bound_returns=_bound_returns(source,direct_demo_transport)
    if bound_returns:
        domain['allowed_return_states']=[{'phase':phase,'freespins_left':left} for phase,left in bound_returns]
        domain['return_binding_sha256']=hashlib.sha256(source.encode('utf-8')).hexdigest()
    return funded_domain(domain,price,accumulated,accept=options[1],decline=options[0],funding_source='ACCUMULATED_ROUND_WIN')


def confirm_numeric(domain,selected,answer):
    game=dict(answer.get('game') or {});accept=selected==domain['options'][1]
    if domain.get('remaining_counter_contract'):
        game['freespinsLeft']=counter_from_contract(answer,domain['remaining_counter_contract'])
    price=_money(domain['quoted_price'],positive=True)
    if not any(type(selected) is type(value) and selected==value for value in domain['available']) or game.get('mode')!='EXTRA_SPIN' or _money(game.get('extraSpinCost'),positive=True)!=price:
        raise Unlearned('Nolimit City: giro extra sin precio o decisión confirmados')
    win=Decimal(str(step_win(game)))
    if accept:
        allowed=domain.get('allowed_return_states')
        if allowed:
            target_ok=({'phase':game.get('nextMode'),'freespins_left':game.get('freespinsLeft')} in allowed and bool(domain.get('return_binding_sha256')))
            accumulated_ok=_money(game.get('accumulatedRoundWin'))==_money(domain['quoted_accumulated'])-price
        else:
            target_ok=game.get('nextMode') in ('FREESPIN','SUPER_FREESPIN','FREESPIN_SUPER','FREESPIN_BETTER') and game.get('freespinsLeft')==0
            accumulated_ok=True
        if (game.get('wasExtraSpin') is not True or not target_ok or not accumulated_ok
                or domain['target_phase'] is not None and game.get('nextMode')!=domain['target_phase']
                or type(game.get('freespinsLeft')) is not int or win!=-price):
            raise Unlearned('Nolimit City: giro extra sin descuento o transición cotizados')
    elif game.get('wasExtraSpin') is not False or game.get('nextMode')!='NORMAL' or win!=0:
        raise Unlearned('Nolimit City: rechazo del giro extra sin liquidación confirmada')
    if 'isExtraSpin' in game and game['isExtraSpin'] is not accept:
        raise Unlearned('Nolimit City: indicadores de giro extra contradictorios')
    return -price if accept else Decimal(0)


@lru_cache(maxsize=8)
def _bound_returns(source,direct_demo_transport=False):
    """Probe only static client phase references; the existing action prover decides."""
    from .client_actions import automatic_command
    from .protocol import MAX_BODY
    if not isinstance(source,str) or len(source)>MAX_BODY:return ()
    phase=r'[A-Z][A-Z0-9_]+'
    reference=r'(?:[\w]+\.[\w]+\.)?(["\']?'+phase+r'["\']?)'
    candidates=set()
    for pattern in (r'addGameModeFlowStatePresentationMap\('+reference,
                    r'nextMode=={1,2}'+reference,
                    r'\b('+phase+r'):\{idle:'):
        candidates.update(value.strip('"\'') for value in re.findall(pattern,source))
    # Enum properties can carry different wire values. Include the literal value;
    # automatic_command still requires the complete exact binding and call path.
    for key,value in re.findall(r'\b\w+\.('+phase+r')="('+phase+r')"',source):
        if key in candidates:candidates.add(value)
    result=[]
    for target in sorted(candidates-{'NORMAL','EXTRA_SPIN','EXTRA_SPIN_CHECK'}):
        for left in (0,1):
            view={'game':{'mode':'EXTRA_SPIN','nextMode':target,'freespinsLeft':left}}
            if automatic_command(source,view,**({'direct_demo_transport':True} if direct_demo_transport is True else {}))=={'type':'zeroBet','bet':'0.00'}:
                result.append((target,left))
    return tuple(result)


def literal_domain(source,game,*,direct_demo_transport=False):
    """The yes/no dialect resumes the phase that advertised one extra spin."""
    if game.get('nextMode')!='EXTRA_SPIN':return None
    # These are two wire field dialects, not game-specific aliases. Preserve
    # the one declared by all call sites; never translate the outgoing key.
    fields=[]
    for field in ('playExtraSpin','extraSpin'):
        values=re.findall(r'zeroBet\(\{'+field+r':([^{}]{1,40})\}\)',source)
        if not values:continue
        if len(values)!=len(re.findall(r'zeroBet\(\{'+field+r':',source)):return None
        branches=[_selector_values(value) for value in values]
        if any(value is None for value in branches):return None
        literals=[literal for branch in branches for literal in branch]
        if not all(re.fullmatch(r"[\"'](?:yes|no)[\"']",value) for value in literals):return None
        if {value[1:-1] for value in literals}!={'yes','no'}:return None
        fields.append(field)
    if len(fields)!=1:return None
    request_field=fields[0]
    price=_money(game.get('extraSpinCost'),positive=True);accumulated=_money(game.get('accumulatedRoundWin'))
    target=game.get('nextModeForExtraSpin',game.get('mode'))
    bound_returns=_bound_returns(source,direct_demo_transport)
    valid_target=isinstance(target,str) and re.fullmatch(r'[A-Z][A-Z0-9_]+',target) and target not in ('NORMAL','EXTRA_SPIN','EXTRA_SPIN_CHECK')
    if not valid_target and ('nextModeForExtraSpin' in game or not bound_returns):
        raise Unlearned('Nolimit City: fase de retorno del giro extra no demostrada')
    flagless=('isExtraSpin' not in game and not re.search(r'\b(?:isExtraSpin|wasExtraSpin)\b',source) and bool(bound_returns))
    if type(game.get('isExtraSpin')) is not bool and not flagless:raise Unlearned('Nolimit City: indicador de giro extra no demostrado')
    domain={'state':'EXTRA_SPIN','options':['no','yes'],'available':['no','yes'],
        'request_field':request_field,'wire_encoding':'PRESERVE_LITERAL',
        'ack_field':'quoted_literal_transition','source':'CLIENT_QUOTED_LITERAL_EXTRA',
        'price_source':'game.extraSpinCost','quoted_price':str(price),'quoted_accumulated':str(accumulated),
        'target_phase':target,'history_extra':game.get('isExtraSpin'),'flag_contract':'NONE' if flagless else 'BOOLEAN',
        'quoted_target_phase':game.get('nextModeForExtraSpin'),
        'native_return_contract':'nolimit-city/single-extra-freespin/v1'}
    counter=counter_contract(source)
    if counter is not None:domain['remaining_counter_contract']=counter
    if bound_returns:
        domain['allowed_return_states']=[{'phase':phase,'freespins_left':left} for phase,left in bound_returns]
        domain['return_binding_sha256']=hashlib.sha256(source.encode('utf-8')).hexdigest()
    return funded_domain(domain,price,accumulated,accept='yes',decline='no',funding_source='ACCUMULATED_ROUND_WIN')


def confirm_literal(domain,selected,answer):
    from .operation_fields import remaining_alias
    game=dict(answer.get('game') or {})
    if domain.get('remaining_counter_contract'):
        game['freespinsLeft']=counter_from_contract(answer,domain['remaining_counter_contract'])
    elif 'freespinsLeft' not in game and 'freespinsRemaining' in game:game['freespinsLeft']=remaining_alias(answer)
    price=_money(domain['quoted_price'],positive=True)
    if selected not in domain['available'] or game.get('mode')!='EXTRA_SPIN' or _money(game.get('extraSpinCost'),positive=True)!=price:
        raise Unlearned('Nolimit City: giro extra sin precio o decisión confirmados')
    win=Decimal(str(step_win(game)))
    if domain.get('flag_contract')=='NONE' and 'wasExtraSpin' in game and game['wasExtraSpin'] is not (selected=='yes'):
        raise Unlearned('Nolimit City: indicador secundario de giro extra contradictorio')
    if selected=='yes':
        quoted_target=domain.get('quoted_target_phase')
        if quoted_target is not None and game.get('nextMode')!=quoted_target:
            raise Unlearned('Nolimit City: retorno distinto del destino cotizado')
        allowed=domain.get('allowed_return_states')
        native=(domain.get('native_return_contract')=='nolimit-city/single-extra-freespin/v1'
            and game.get('nextMode')=='FREESPIN' and type(game.get('freespinsLeft')) is int
            and game['freespinsLeft']==1 and type(answer.get('remainingFreeSpins')) is int
            and answer['remainingFreeSpins']==1
            and isinstance(answer.get('features',{}),dict)
            and answer.get('features',{}).get('available') in (None,[])
            and answer.get('features',{}).get('active') in (None,'','FREESPIN')
            and not any(container.get(field) not in (None,False,[],{})
                for container in (answer,game) for field in ('screens','pickAndClick','gambleOptions')))
        if allowed or native:
            target_ok=(native or ({'phase':game.get('nextMode'),'freespins_left':game.get('freespinsLeft')} in allowed
                and bool(domain.get('return_binding_sha256'))))
            try:accumulated_ok=_money(game.get('accumulatedRoundWin'))==_money(domain['quoted_accumulated'])-price
            except ValueError:accumulated_ok=False
        else:
            target_ok=game.get('nextMode')==domain['target_phase'] and game.get('freespinsLeft')==1
            accumulated_ok=True
        flag_ok=(game.get('isExtraSpin') is True or domain.get('flag_contract')=='NONE' and 'isExtraSpin' not in game and bool(allowed))
        if (not flag_ok or not target_ok or not accumulated_ok
                or type(game.get('freespinsLeft')) is not int or win!=-price):
            raise Unlearned('Nolimit City: giro extra sin descuento o retorno a la fase que lo ofreció')
        return -price
    flag_ok=(type(game.get('isExtraSpin')) is bool or domain.get('flag_contract')=='NONE' and 'isExtraSpin' not in game)
    if (game.get('nextMode')!='NORMAL' or win!=0 or not flag_ok
            or game.get('isExtraSpin') is True and domain['history_extra'] is not True):
        raise Unlearned('Nolimit City: rechazo del giro extra sin liquidación o con historia incoherente')
    return Decimal(0)


def funded_followup_matches(receipt,answer):
    """A ledger-produced receipt binds one paid continuation to its exact ACK."""
    from .client_counters import counter_from_contract
    from .operation_fields import remaining_alias
    game=answer.get('game') or {}
    try:
        proof=receipt.get('remaining_counter_contract')
        left=counter_from_contract(answer,proof) if proof else remaining_alias(answer)
        price=_money(receipt.get('price'),positive=True)
        flags=[game[k] for k in ('wasExtraSpin','isExtraSpin') if k in game]
        flags_ok=(all(v is True for v in flags) and (bool(flags) or receipt.get('flag_contract')=='NONE'))
        return (game.get('mode')=='EXTRA_SPIN' and game.get('nextMode')==receipt.get('target_phase')
            and type(left) is int and left==receipt.get('regular_left',0) and flags_ok
            and _money(game.get('extraSpinCost'),positive=True)==price
            and Decimal(str(step_win(game)))==-price)
    except (ValueError,ArithmeticError):return False
