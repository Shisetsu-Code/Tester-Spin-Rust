"""Read-only ELK CAPI declaration/settlement primitives from captured XML.

This module sends no requests. Financial mode coverage is kept separate from
full paid-control inventory certification, which remains unknown without a
reviewed client binding. Producer summaries alone never establish settlement.
"""
import hashlib,json,re,shutil
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from tester_spin.models import GameTestResult,SpinAttempt
from tester_spin.paid_options import write_paid_option_inventory


def money(value):
    amount=Decimal(value)
    if not amount.is_finite() or amount<0:raise ValueError('INVALID_MONEY')
    return amount


def read_xml(path):
    body=path.read_bytes()
    if len(body)>8*1024*1024 or b'<!DOCTYPE' in body.upper():raise ValueError('XML_CONTRACT_LIMIT')
    root=ET.fromstring(body)
    for node in root.iter():
        if node.tag=='gamesession':
            identity=node.findtext('id') if list(node) else node.text
            if identity and identity.strip()!='REDACTED':raise ValueError('UNREDACTED_SESSION')
        if node.tag=='playerhash' and node.text and node.text!='REDACTED':raise ValueError('UNREDACTED_PLAYER')
        for key in ('gamesession','extsession'):
            if key in node.attrib and node.attrib[key]!='REDACTED':raise ValueError('UNREDACTED_SESSION')
    return root


def response(path,method):
    node=read_xml(path)
    if node.findtext('method')!=method or node.findtext('errorcode')!='0':raise ValueError('CAPI_RESPONSE_NOT_ACCEPTED:'+method)
    return node


def declared_modes(initial):
    levels=initial.find('betlevels')
    if levels is None:raise ValueError('BETLEVEL_DOMAIN_MISSING')
    quotes={};ids=set()
    for level in levels.findall('betlevel'):
        identity=level.attrib.get('id')
        if not identity or identity in ids:raise ValueError('BETLEVEL_IDENTITY_INVALID')
        ids.add(identity);modes=level.findall('bmodes/bmode')
        if not modes and 'amount' in level.attrib:modes=[ET.Element('bmode',{'id':'DEF','amount':level.attrib['amount']})]
        if not modes:raise ValueError('BETLEVEL_MODES_MISSING')
        seen=set()
        for mode in modes:
            code=mode.attrib.get('id');amount=money(mode.attrib.get('amount'))
            if not code or code in seen or amount<=0:raise ValueError('BMODE_DECLARATION_INVALID')
            seen.add(code);quotes.setdefault(code,{})[identity]=amount
    if 'DEF' not in quotes:raise ValueError('BASE_MODE_UNBOUND')
    return quotes


def inspect_purchase_capture(event, *, game_id, quotes, currency):
    """Validate an observed purchase against captured init quotes, never settle it.

    Returned evidence excludes session/player/round identifiers. A purchase
    response alone cannot establish complete paid controls or a checkwin ACK.
    """
    url = urlsplit(event.get('url', ''))
    if (url.scheme != 'https' or not (url.hostname or '').endswith('-stage.contentmedia.eu')
            or url.port not in (None, 443) or url.username or url.password
            or url.path != f'/capi/{game_id}/play/purchase'
            or event.get('method') != 'POST' or event.get('status') != 200
            or event.get('bodyError') or event.get('base64Encoded')):
        raise ValueError('CAPI_CAPTURE_IDENTITY_OR_TRANSPORT_INVALID')
    def xml(text):
        if not isinstance(text, str) or len(text.encode('utf-8')) > 8 * 1024 * 1024 or '<!DOCTYPE' in text.upper():
            raise ValueError('XML_CONTRACT_LIMIT')
        return ET.fromstring(text)
    request = xml(event.get('request_body_xml'))
    paid = xml(event.get('response_body_xml'))
    if request.tag != 'request' or paid.tag != 'response' or paid.findtext('method') != 'purchase' or paid.findtext('errorcode') != '0':
        raise ValueError('CAPI_RESPONSE_NOT_ACCEPTED')
    code, level = request.get('bmode'), request.get('betlevel')
    cost = money(request.get('amount'))
    quote = quotes.get(code, {}).get(level)
    if quote is None or cost <= 0 or cost != money(quote) or request.get('cur') != currency:
        raise ValueError('PURCHASE_DECLARATION_MISMATCH')
    info = paid.find('roundinfo')
    roundid = paid.findtext('roundid')
    if (info is None or not roundid or info.findtext('roundid') != roundid
            or info.findtext('bmode') != code or info.findtext('betlevel') != level
            or info.findtext('currency') != currency or paid.findtext('player/currency') != currency
            or money(info.findtext('betamount')) != cost):
        raise ValueError('ROUND_IDENTITY_OR_COST_MISMATCH')
    win = money(info.findtext('winamount'))
    debit_balance = money(paid.findtext('player/balance'))
    if money(info.findtext('balanceafterwin')) != debit_balance + win:
        raise ValueError('REPORTED_BALANCE_MISMATCH')
    public = xml(paid.findtext('game/pubdata'))
    purchases = public.findall('PURCHASE') if public.tag == 'PURCHASES' else []
    if len(purchases) != 1:
        raise ValueError('PUBLIC_PURCHASE_SCHEMA_UNBOUND')
    purchase = purchases[0]
    if (purchase.get('bmode') != code or purchase.get('betlevel') != level
            or purchase.get('currency') != currency or money(purchase.get('betamount')) != cost
            or money(purchase.get('winamount')) != win):
        raise ValueError('PUBLIC_PURCHASE_MISMATCH')
    return {'primitive': 'elk.capi.purchase-observation/v1', 'accepted': True,
            'mode': code, 'level': level, 'cost': str(cost), 'win': str(win),
            'terminal': False, 'paid_inventory_complete': False,
            'unresolved': ['CHECKWIN_AND_BALANCE_CHAIN_REQUIRED', 'CLIENT_PAID_CONTROL_INVENTORY_UNVERIFIED']}


def convert_case(game,source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination==source or destination.is_relative_to(source):raise ValueError('IMMUTABLE_SOURCE_REQUIRED')
    destination.mkdir(parents=True,exist_ok=False)
    report=json.loads((source/'result.json').read_text(encoding='utf-8'))
    result=GameTestResult(game.provider,game.slug,game.name,game.url,len(report.get('rounds',[])),0,0,'PARCIAL',symbol=game.symbol,run_dir=str(destination))
    issues=[];quotes={};balance=None;valid_ids=set();last_mode=None
    endpoint=report.get('endpoint','');parsed=urlsplit(endpoint)
    try:
        if (parsed.scheme!='https' or not (parsed.hostname or '').endswith('-stage.contentmedia.eu')
                or parsed.path!='/capi/'+game.symbol+'/play' or parsed.query or parsed.fragment
                or parsed.username or parsed.password or report.get('slug')!=game.slug):
            raise ValueError('DEMO_ENDPOINT_OR_GAME_IDENTITY_UNBOUND')
        initial=response(source/'001-init-response.redacted.xml','init')
        init_request=read_xml(source/'001-init-request.redacted.xml')
        if init_request.attrib.get('opid')!='44':raise ValueError('DEMO_OPERATOR_UNBOUND')
        currency=init_request.attrib.get('cur')
        if not currency:raise ValueError('CURRENCY_UNBOUND')
        quotes=declared_modes(initial);balance=money(initial.findtext('player/balance'))
        declared={row.get('id') for row in report.get('declaredModes',[])}
        if declared!=set(quotes):issues.append('SUMMARY_INIT_INVENTORY_MISMATCH')
        shutil.copy2(source/'001-init-response.redacted.xml',destination/'init-response.redacted.xml')
    except Exception as exc:
        issues.append(type(exc).__name__+': '+str(exc));currency=None
    for index,row in enumerate(report.get('rounds',[])):
        directory=destination/('mode-'+str(index+1));directory.mkdir()
        attempt=SpinAttempt(index+1,False,mode_id=str(row.get('id','UNKNOWN')),mode_kind='SPIN' if row.get('id')=='DEF' else 'BET_MODE',symbol=game.symbol,endpoint=endpoint+'/purchase',artifact_dir=str(directory))
        result.attempts.append(attempt);counter=2+index*2
        try:
            if balance is None or not quotes:raise ValueError('INIT_NOT_VERIFIED')
            if row.get('status')!='closed':raise ValueError('DISPATCHED_OR_UNCLOSED_OPERATION')
            files={
                'purchase_request':source/f'{counter:03d}-purchase-request.redacted.xml',
                'purchase_response':source/f'{counter:03d}-purchase-response.redacted.xml',
                'checkwin_request':source/f'{counter+1:03d}-checkwin-request.redacted.xml',
                'checkwin_response':source/f'{counter+1:03d}-checkwin-response.redacted.xml',
            }
            request=read_xml(files['purchase_request']);paid=response(files['purchase_response'],'purchase')
            check=read_xml(files['checkwin_request']);settled=response(files['checkwin_response'],'checkwin')
            code=request.attrib.get('bmode');level=request.attrib.get('betlevel');cost=money(request.attrib.get('amount'))
            if (code not in quotes or level not in quotes[code] or cost!=quotes[code][level]
                    or code!=row.get('id') or level!=str(row.get('betlevel'))
                    or cost!=money(row.get('amount')) or request.attrib.get('cur')!=currency):
                raise ValueError('PURCHASE_DECLARATION_MISMATCH')
            info=paid.find('roundinfo');roundid=paid.findtext('roundid')
            if (info is None or not roundid or info.findtext('bmode')!=code or info.findtext('betlevel')!=level
                    or money(info.findtext('betamount'))!=cost or money(row.get('balanceBefore'))!=balance):
                raise ValueError('ROUND_IDENTITY_OR_BALANCE_CHAIN_MISMATCH')
            win=money(info.findtext('winamount'));after=balance-cost+win
            if cost>balance or money(paid.findtext('player/balance'))!=balance-cost:
                raise ValueError('PURCHASE_DEBIT_NOT_RECONCILED')
            public=ET.fromstring(paid.findtext('game/pubdata'))
            if (public.tag!='PURCHASES' or not public.findall('PURCHASE')
                    or any(node.tag.upper() in {'CHOICE','SELECT','OPTIONS','PICK'} for node in public.iter())):
                raise ValueError('PUBLIC_RESULT_OR_CHOICE_CONTRACT_UNBOUND')
            if (money(info.findtext('balanceafterwin'))!=after or check.attrib.get('roundid')!=roundid
                    or settled.findtext('roundid')!=roundid or money(settled.findtext('player/balance'))!=after
                    or money(row.get('win'))!=win or money(row.get('balanceAfter'))!=after):
                raise ValueError('SETTLEMENT_OR_SUMMARY_MISMATCH')
            artifacts=[]
            for label,file in files.items():
                target=directory/(label+'.redacted.xml');shutil.copy2(file,target)
                artifacts.append({'path':target.name,'redacted_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
            (directory/'response.json').write_text(json.dumps({'schema':'elk-capi-closed-round/v1','mode':code,'level':level,'roundid':roundid,
                'cost':str(cost),'win':str(win),'balance_before':str(balance),'balance_after':str(after),
                'terminal':True,'verified_by':'purchase+checkwin+roundid+balance','redacted_xml':artifacts},indent=2),encoding='utf-8')
            attempt.ok=True;attempt.terminal=True;attempt.wire_steps=2;attempt.status_code=200
            balance=after;valid_ids.add(code);last_mode=code;result.successful_spins+=1
        except Exception as exc:
            attempt.error=type(exc).__name__+': '+str(exc);issues.append(attempt.error)
            # Subsequent rows cannot repair an unverified earlier balance chain.
            balance=None
    result.failed_spins=sum(not attempt.ok for attempt in result.attempts)
    complete=bool(quotes) and set(quotes)<=valid_ids and last_mode=='DEF' and not issues
    result.discovered_modes=[{'id':code,'kind':'SPIN' if code=='DEF' else 'BET_MODE','validated':code in valid_ids,
        'coverage_required':True,'required_options':[code],'covered_options':[code] if code in valid_ids else [],
        'quotes':{level:str(amount) for level,amount in levels.items()}} for code,levels in quotes.items()]
    result.feature_domains={'server_bmodes':{'source':'fresh CAPI init.betlevels union','complete':bool(quotes),'options':list(quotes)}}
    result.structural_map={'ui_inventory_verified':False,'return_to_base_verified':last_mode=='DEF' and balance is not None,
        'elk_capi_validation':{'primitive':'elk.capi.xml-evidence/v1','all_declared_modes_closed':complete,
                              'versions_observed_by_collector':report.get('versions',{}),'scope':'redacted captured XML; no session continuity or complete client paid-control declaration certified'}}
    write_paid_option_inventory(result,primitive={'id':'elk.client-paid-controls-unresolved','version':1},
        source='CAPI modes verified separately; full client paid-control binding unresolved',options=[],complete=False,
        evidence_files=['init-response.redacted.xml'] if (destination/'init-response.redacted.xml').exists() else [],
        unresolved=['CLIENT_PAID_CONTROL_INVENTORY_UNVERIFIED'])
    result.error='; '.join(dict.fromkeys([*issues,'Complete paid-option inventory remains unverified.']))
    (destination/'result.json').write_text(json.dumps(result.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
    return result
