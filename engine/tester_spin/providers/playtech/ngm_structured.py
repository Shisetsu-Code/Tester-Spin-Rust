"""Source-bound CommonBet entry used by NGM gamelet clients."""
import re
from .client_sources import _function_bodies
from .ngm_contracts import NAME, _constants, request_catalog
from .ngm_plan import _call_arguments


def _fixed_title(functions, constants, row, source=None):
    field=row.get('fields',{}).get('gameTitle')
    if not field:return None
    sites=[]
    for _,(_,body) in functions.items():
        create=re.search(r'('+NAME+r')=new '+re.escape(row['constructor'])+r'(?![\w$])',body)
        if not create:continue
        model=re.escape(create[1])
        if re.search(model+r'\[',body) or len(re.findall(model+r'\.'+re.escape(field)+r'(?![\w$])',body))!=1:return None
        writes=re.findall(re.escape(create[1])+r'\.'+re.escape(field)+r'=('+NAME+r');',body)
        if len(writes)!=1 or len(constants.get(writes[0],set()))!=1:return None
        if source is not None and len(re.findall(r'(?<![\w$.])'+re.escape(writes[0])+r'=(?!=)',source))!=1:return None
        sites.append(next(iter(constants[writes[0]])))
    return sites[0] if len(sites)==1 else None


def _lifecycle_roles(functions, constants, rows, entry, source):
    title=_fixed_title(functions,constants,entry,source)
    if title is None or not entry['name'].endswith('StartSpinRequest'):return {}
    prefix=entry['name'][:-len('StartSpinRequest')]
    roles={}
    specs={'OpenGameRequest':(-4,'lifecycle'),'DisplayJackpotRequest':(-2,'lifecycle'),
           'FinishSpinRequest':(2,'round_finish')}
    for row in rows:
        if row['unresolved_fields'] or _fixed_title(functions,constants,row,source)!=title:continue
        fields=set(row['fields'])
        for suffix,(delta,role) in specs.items():
            if (row['name']==prefix+suffix and row['message_id']==entry['message_id']+delta
                and {'gameTitle','play4fun'}<=fields and fields<={'gameTitle','gameId','play4fun','ID','umid','windowId'}):
                roles[row['name']]=role
        if (row['name']=='CommonSaveStateRequest' and row['message_id']==46120
            and {'gameTitle','savedStates'}<=fields and fields<={'gameTitle','gameId','savedStates','ver','ID','umid'}):
            roles[row['name']]='state_save'
    return roles


def structured_spin_contract(source):
    functions, constants = _function_bodies(source), _constants(source)
    rows = request_catalog(source, value_classes=('CommonBet',))
    bets = [r for r in rows if r['name']=='CommonBet' and not r['unresolved_fields']]
    if len(bets)!=1 or not {'stake','type'} <= set(bets[0]['fields']) or set(bets[0]['fields'])-{'stake','type','pick','winlines'}:
        return None
    bet = bets[0]
    candidates=[]
    for row in rows:
        if row['unresolved_fields'] or not {'bet','closeAvailable'} <= set(row['fields']):
            continue
        if set(row['fields'])-{'bet','closeAvailable','gameTitle','gameId','ID','umid','windowId'}:
            continue
        if len(re.findall(r'\bnew\s+'+re.escape(row['constructor'])+r'(?![\w$])',source))!=1:continue
        sites=[]
        for fn,(args,body) in functions.items():
            create=re.search(r'('+NAME+r')=new '+re.escape(row['constructor'])+r'(?![\w$])',body)
            if not create:continue
            field=re.escape(create[1])+r'\.'+re.escape(row['fields']['bet'])
            writes=re.findall(field+r'=('+NAME+r');',body)
            if len(writes)!=1 or writes[0] not in args or len(re.findall(field+r'(?![\w$])',body))!=1:
                continue
            formal=writes[0]
            if len(re.findall(r'(?<![\w$.])'+re.escape(formal)+r'(?![\w$])',body))!=1:
                continue
            if re.search(re.escape(create[1])+r'\[',body):continue
            sites.append((fn,args.index(formal)))
        if len(sites)!=1:continue
        sender,position=sites[0]
        if len(re.findall(r'(?<![\w$])'+re.escape(sender)+r'\(',source))!=2:continue
        calls=[]
        for caller,(_,body) in functions.items():
            for call in re.finditer(r'(?<![\w$])'+re.escape(sender)+r'\(',body):
                args=_call_arguments(body,call.end())
                if args and len(args)>position:calls.append((caller,body,args[position]))
        if len(calls)!=1:continue
        caller,body,model=calls[0]
        if not re.fullmatch(NAME,model) or not re.search(re.escape(model)+r'=new '+re.escape(bet['constructor'])+r'(?![\w$])',body):continue
        if re.search(re.escape(model)+r'\[',body):continue
        writes=re.findall(re.escape(model)+r'\.('+NAME+r')=([^;]+);',body)
        if len(writes)!=1 or writes[0][0]!=bet['fields']['type']:continue
        value=writes[0][1]
        if value not in ("'line'",'"line"'):
            if constants.get(value)!={'line'} or len(re.findall(r'(?<![\w$.])'+re.escape(value)+r'=(?!=)',source))!=1:continue
        if len(re.findall(r'(?<![\w$.])'+re.escape(model)+r'(?![\w$])',body))>5:continue
        stakes=[]
        for call in re.finditer(r'('+NAME+r')\(',body):
            args,definition=functions.get(call[1],([],''))
            if len(args)!=2 or definition!=args[0]+'.'+bet['fields']['stake']+'='+args[1]:continue
            params=_call_arguments(body,call.end())
            if not params or len(params)!=2 or params[0]!=model:continue
            scale=re.search(r'/([1-9][0-9]{0,5})\)*$',params[1])
            if scale:stakes.append((call[1],int(scale[1])))
        if len(stakes)!=1:continue
        roles=_lifecycle_roles(functions,constants,rows,row,source)
        candidates.append(dict(lifecycle_roles=roles,name=row['name'],constructor=row['constructor'],message_id=row['message_id'],
            bet_field=row['fields']['bet'],amount_field=bet['fields']['stake'],type_field=bet['fields']['type'],
            scale=stakes[0][1],sender=sender,caller=caller,amount_setter=stakes[0][0],bet_type='line',
            evidence='CommonBet.serializer+unique-source-producer+explicit-unit-division'))
    return candidates[0] if len(candidates)==1 else None


def observation_expression(contract, request):
    obj=request+'.'+contract['bet_field']
    amount=obj+'.'+contract['amount_field']
    scale=str(contract['scale'])
    # Field accesses are derived identifiers. No captured expression is evaluated.
    return ('('+request+' instanceof '+contract['constructor']+'&&'+obj+'&&'+obj+'.'+contract['type_field']+
            "==='line'&&typeof "+amount+"==='number'&&Number.isFinite("+amount+')&&'+amount+'>0&&'+
            'Math.abs('+amount+'*'+scale+'-Math.round('+amount+'*'+scale+'))<1e-7?'+
            '{bet:Math.round('+amount+'*'+scale+'),wager_format:"structured-line",bet_type:"line"}:null)')
