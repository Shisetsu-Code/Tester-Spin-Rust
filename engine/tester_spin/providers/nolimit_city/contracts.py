"""One state -> action -> acknowledgment -> money contract for live and HAR.

Captured requests are observations, never authority to invent a domain. Only
server state primitives and the exact current client's bindings authorize actions.
"""
import hashlib,re
from .errors import Unlearned
from .protocol import _money

SCHEMA='nolimit-city/operation-contract/v1'


def _contract(answer,family,source,*,request=None,domain=None,client_source=None):
    phase=(answer.get('game') or {}).get('nextMode')
    evidence={'source':source}
    if client_source is not None:evidence['client_sha256']=hashlib.sha256(client_source.encode('utf-8')).hexdigest()
    return {'schema':SCHEMA,'family':family,'state':phase,'request':request,'domain':domain,
        'acknowledgment':{'phase':phase,'kind':'PHASE_ENTRY'},
        'money':{'stake':'0.00','settlement':'ROUND_LEDGER','quote_field':domain.get('price_source') if domain else None},
        'evidence':evidence}


def resolve_operation(answer,mode=None,*,raw_answer=None,client_source=None,direct_demo_transport=False):
    from .runtime import continuation,_extra_response
    from .client_actions import automatic_command
    from .choices import choice_domain,has_collect_contract
    from .operation_fields import collect_available
    mode=mode or {};raw=raw_answer if raw_answer is not None else answer
    funded=answer.get('_funded_extra_spin') or {}
    if raw_answer is not None and '_funded_extra_spin' not in raw_answer and funded:
        game=raw.get('game') or {}
        from .extra_choices import funded_followup_matches
        if funded_followup_matches(funded,raw):
            return _contract(raw,'FUNDED_EXTRA_CONTINUATION','VERIFIED_QUOTED_PRIZE_DEBIT',
                request={'type':'zeroBet','bet':'0.00'})
    try:
        request=continuation(answer,raw_answer=raw,
            declared_options=mode.get('declared_feature_options',()),declared_categories=mode.get('declared_feature_categories',()),
            declared_purchase_options=mode.get('declared_purchase_options',()),declared_catalog=mode.get('declared_feature_catalog'),
            declared_game_modes=mode.get('declared_game_modes',()))
        return _contract(raw,'AUTOMATIC_CONTINUATION','SERVER_STATE_PRIMITIVE',request=request)
    except Unlearned as blocker:
        if client_source is None:raise blocker
    action_context={'direct_demo_transport':True} if direct_demo_transport is True else {}
    automatic=automatic_command(client_source,raw,**action_context)
    if (automatic is None and answer.get('_verified_numeric_extra_context') is True
            and raw_answer is not None and '_verified_numeric_extra_context' not in raw_answer
            and ((raw.get('game') or {}).get('wasExtraSpin') is True or (raw.get('game') or {}).get('isExtraSpin') is True)
            and (raw.get('game') or {}).get('nextMode')!='EXTRA_SPIN'):
        # The extra has already been paid. Stale quote/extra flags must not hide
        # a current client-bound, argument-free follow-up animation. A fresh
        # EXTRA_SPIN decision is always excluded and needs its own quoted domain.
        funded_view={**raw,'game':{**raw['game'],'extraSpinCost':0,'wasExtraSpin':False,'isExtraSpin':False}}
        automatic=automatic_command(client_source,funded_view,**action_context)
        if automatic is not None:return _contract(raw,'AUTOMATIC_CONTINUATION','CURRENT_CLIENT_BINDING_AFTER_VERIFIED_EXTRA_DEBIT',request=automatic,client_source=client_source)
    if automatic is not None:
        contract=_contract(raw,'AUTOMATIC_CONTINUATION','CURRENT_CLIENT_BINDING',request=automatic,client_source=client_source)
        if direct_demo_transport is True:contract['evidence']['execution_context']='DIRECT_FRESH_DEMO_TRANSPORT'
        return contract
    game=raw.get('game') or {}
    if collect_available(game):
        if not has_collect_contract(client_source):raise Unlearned('Nolimit City: cobro no declarado por cliente')
        domain={'state':'GAMBLE','options':[True],'available':[True],'ack_field':'gambleCollect',
            'request_field':'gambleCollected','request_type':'gambleBet','source':'CLIENT_CONFIRMED_COLLECT','scope':'SETTLEMENT_ONLY'}
        family='COLLECT'
    elif _extra_response(game) and game.get('nextMode')=='EXTRA_SPIN':
        if not all(re.search(r'zeroBet\(\{playExtraSpin:[\"\']'+value+r'[\"\']\}\)',client_source) for value in ('yes','no')):
            raise Unlearned('Nolimit City: cliente no declara ambas decisiones del extra spin')
        price=_money(game.get('extraSpinCost'),positive=True)
        domain={'state':'EXTRA_SPIN','options':['yes','no'],'available':['yes','no'],
            'ack_field':'extra_spin_transition','request_field':'playExtraSpin','price_source':'game.extraSpinCost'}
        from tester_spin.providers.repeat_purchase import funded_domain
        domain=funded_domain(domain,price,_money(game.get('accumulatedRoundWin')),accept='yes',decline='no',funding_source='ACCUMULATED_ROUND_WIN')
        family='QUOTED_EXTRA_SPIN'
    else:
        from .extra_choices import numeric_domain
        domain=numeric_domain(client_source,game,direct_demo_transport=direct_demo_transport)
        if domain is not None:
            return _contract(raw,'QUOTED_NUMERIC_EXTRA',domain['source'],domain=domain,client_source=client_source)
        from .extra_choices import literal_domain
        domain=literal_domain(client_source,game,direct_demo_transport=direct_demo_transport)
        if domain is not None:
            return _contract(raw,'QUOTED_LITERAL_EXTRA',domain['source'],domain=domain,client_source=client_source)
        try:domain=choice_domain(client_source,raw,mode)
        except ValueError as exc:raise Unlearned(str(exc)) from exc
        family='FINITE_SELECTION'
    return _contract(raw,family,domain['source'] if 'source' in domain else 'CURRENT_CLIENT_QUOTED_EXTRA',domain=domain,client_source=client_source)


def confirm_operation(contract,answer,selected=None):
    from .choices import confirm_choice
    game=answer.get('game') or {};phase=contract['acknowledgment']['phase']
    if game.get('mode')!=phase:raise Unlearned('Nolimit City: continuación sin acuse de la fase solicitada')
    domain=contract.get('domain')
    if domain is None:return
    if contract.get('family')=='QUOTED_LITERAL_EXTRA':
        from .extra_choices import confirm_literal
        confirm_literal(domain,selected,answer);return
    if contract.get('family')=='QUOTED_NUMERIC_EXTRA':
        from .extra_choices import confirm_numeric
        confirm_numeric(domain,selected,answer);return
    field=domain.get('request_field','selectedIndex')
    if field=='gambleCollected':
        if game.get('nextMode')!='NORMAL' or game.get('gambleCollect') is not True:raise Unlearned('Nolimit City: cobro no confirmado')
    elif field=='playExtraSpin':
        if ((selected=='yes' and (game.get('nextMode')!='FREESPIN' or game.get('isExtraSpin') is not True))
                or (selected=='no' and game.get('nextMode')!='NORMAL')):raise Unlearned('Nolimit City: decisión extra spin no confirmada')
    else:confirm_choice(domain,selected,answer)


def observed_request_matches(contract,request):
    """Check an actual HAR request against authority; never learn its parameters."""
    if contract.get('request') is not None:return request==contract['request'],None
    domain=contract['domain'];field=domain.get('request_field','selectedIndex');interaction=request.get('playerInteraction')
    if (request.get('type')!=domain.get('request_type','zeroBet') or _money(request.get('bet'))!=0
            or not isinstance(interaction,dict) or set(interaction)!={field}):return False,None
    selected=next((v for v in domain['available'] if type(interaction[field]) is type(v) and interaction[field]==v
        or field=='selectedIndex' and interaction[field]==str(v)),None)
    return selected is not None,selected


def selection_adjustment(contract,request,answer,previous,accumulated):
    """A declared, acknowledged choice may lose part or all of an unsettled prize.

    This is a result delta, never a negative stake or an additional wallet charge.
    Require final settlement so the ledger can independently reconcile the wallet.
    """
    from decimal import Decimal
    from .state import settled_state
    if (not isinstance(contract,dict) or contract.get('family')!='FINITE_SELECTION'
            or not (contract.get('evidence') or {}).get('client_sha256')
            or contract.get('state')!=previous.get('nextMode')
            or not isinstance(request,dict) or request.get('type')!='zeroBet'
            or not settled_state(answer) or answer.get('balance') is None):
        raise Unlearned('Nolimit City: descuento de premio sin elección y liquidación contrastadas')
    matches,selected=observed_request_matches(contract,request)
    if not matches:raise Unlearned('Nolimit City: descuento fuera de la elección declarada')
    confirm_operation(contract,answer,selected)
    delta=Decimal(str(answer['game']['win']))
    if (not delta.is_finite() or delta>=0 or delta < -accumulated
            or delta!=delta.quantize(Decimal('.01'))
            or _money(previous.get('accumulatedRoundWin'))!=accumulated):
        raise ValueError('Nolimit City: descuento excede el premio pendiente o tiene precisión inválida')
    return delta
