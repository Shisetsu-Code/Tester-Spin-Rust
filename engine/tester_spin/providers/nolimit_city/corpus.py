"""Offline corpus audit with the same declarations, planner and ledger as live.

This checks every recorded step, not only the first unsupported action. It never
replays a captured session or writes execution OK into the application's data.
"""
import argparse,collections,hashlib,json
from pathlib import Path
from .declarations import declared_options
from .runtime import RoundLedger
from .contracts import resolve_operation,confirm_operation,observed_request_matches


def audit_exchanges(exchanges,*,client_source=None,direct_demo_transport=False):
    report={'schema':'nolimit-city/corpus-audit/v1','ok_certified':False,'steps_checked':0,
        'money_accepted_steps':0,'closed_rounds':0,'contract_actions':0,'unresolved_actions':[],
        'money_failures':[],'families':{}}
    if not exchanges or exchanges[0]['request'].get('type')!='init':
        report['initialization_error']='MISSING_INIT';return report
    init=exchanges[0]['response']
    try:modes,_=declared_options(init)
    except ValueError as exc:report['initialization_error']=str(exc);return report
    before=init.get('balance');ledger=None;previous=None;mode=None;round_failed=False;families=collections.Counter()
    for step,pair in enumerate(exchanges[1:],1):
        request=pair['request'];answer=pair['response'];report['steps_checked']+=1;operation=None
        if request.get('type') in ('normalBet','featureBet'):
            mode=next((m for m in modes if m['kind']=='SPIN' and request['type']=='normalBet'
                or request['type']=='featureBet' and m.get('selector')==request.get('featureName')),None)
            if ledger is not None and not ledger.closed and not round_failed:
                report['money_failures'].append({'step':step,'reason':'NEW_ROOT_WITH_PENDING_ROUND'})
            ledger=None;round_failed=False
            # After a failed round only an explicit, recorded normal settlement
            # can anchor the next local round. No whole-capture success is claimed.
            if mode is None:round_failed=True;report['money_failures'].append({'step':step,'reason':'UNDECLARED_ROOT'})
            else:
                try:ledger=RoundLedger(before,{**mode,'stake':request.get('bet')})
                except ValueError as exc:round_failed=True;report['money_failures'].append({'step':step,'reason':str(exc)})
        elif previous is not None:
            phase=(previous.get('game') or {}).get('nextMode')
            try:
                contract=resolve_operation(ledger.last_answer if ledger is not None and not round_failed and hasattr(ledger,'last_answer') else previous,mode,raw_answer=previous,client_source=client_source,direct_demo_transport=direct_demo_transport)
                matches,selected=observed_request_matches(contract,request)
                if not matches:raise ValueError('OBSERVED_REQUEST_OUTSIDE_CONTRACT')
                confirm_operation(contract,answer,selected)
                operation=contract;report['contract_actions']+=1;families[contract['family']]+=1
            except ValueError as exc:
                report['unresolved_actions'].append({'step':step,'phase':phase,
                    'request_type':request.get('type'),'interaction_fields':sorted((request.get('playerInteraction') or {}).keys()),'reason':str(exc)})
        if ledger is not None and not round_failed:
            try:
                done=ledger.accept(answer,request=request,operation=operation,client_source=client_source);report['money_accepted_steps']+=1
                if done:report['closed_rounds']+=1;before=ledger.after
            except ValueError as exc:round_failed=True;report['money_failures'].append({'step':step,'reason':str(exc)})
        previous=answer
        if round_failed and answer.get('balance') is not None and (answer.get('game') or {}).get('nextMode')=='NORMAL':before=answer['balance']
    report['families']=dict(families)
    report['pending_round']=ledger is not None and not ledger.closed
    return report


def matched_sessions(rows):
    pending={};sessions={};issues=[]
    for row in rows:
        message=row['message'];connection=row.get('connection',0);key=(connection,message.get('id'))
        if not isinstance(key[1],str) or not key[1]:issues.append({'reason':'MISSING_REQUEST_ID'});continue
        if row['direction']=='sent':
            if key in pending:issues.append({'reason':'DUPLICATE_REQUEST_ID'});continue
            pending[key]=message
        elif row['direction']=='received':
            request=pending.pop(key,None)
            if request is None:issues.append({'reason':'UNMATCHED_RESPONSE'});continue
            sessions.setdefault(connection,[]).append({'request':request.get('content') or {'type':request.get('type')},'response':message})
    if pending:issues.append({'reason':'PENDING_REQUESTS','count':len(pending)})
    return list(sessions.values()),issues


def capture_rows(target,extra_roots=()):
    from .protocol import decode_capture
    if target.is_file() and target.suffix=='.ndjson':
        with target.open(encoding='utf-8') as stream:
            for line in stream:yield json.loads(line)
        return
    paths=[];seen=set()
    for root in (target,*extra_roots):
        paths.extend(sorted(root.rglob('*.har')) if root.is_dir() else [root])
    for path in paths:
        try:
            if path.stat().st_size>128_000_000:raise ValueError('CAPTURE_SIZE_LIMIT')
            data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
            if digest in seen:continue
            seen.add(digest)
            sessions,issues=matched_sessions(decode_capture(json.loads(data.decode('utf-8-sig'))))
            if not sessions:yield {'sha256':digest,'path':str(path),'exchanges':[],'import_issues':[{'reason':'NO_MATCHED_EXCHANGES'}]}
            for session in sessions:yield {'sha256':digest,'path':str(path),'exchanges':session,'import_issues':issues}
        except (ValueError,OSError) as exc:
            yield {'sha256':hashlib.sha256(str(path).encode()).hexdigest(),'path':str(path),'exchanges':[],'import_issues':[{'reason':type(exc).__name__}]}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Audit decoded Nolimit HAR corpora without replay or OK certification')
    parser.add_argument('decoded',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--client-dir',type=Path)
    parser.add_argument('--har-root',type=Path,action='append',default=[])
    args=parser.parse_args(argv);reports=[];totals=collections.Counter();blockers=collections.Counter();clients={}
    for row in capture_rows(args.decoded,args.har_root):
        source=None
        info_path=Path(row.get('path','')).parent/'bootstrap/client-info.json'
        if args.client_dir is not None and info_path.is_file():
            info=json.loads(info_path.read_text(encoding='utf-8-sig'))
            name=info.get('name','') if isinstance(info,dict) else None
            version=info.get('version','') if isinstance(info,dict) else None
            from .client_identity import validate_client_info
            from .errors import Unlearned
            try:validate_client_info(info,name)
            except Unlearned:valid=False
            else:valid=True
            if valid:
                candidates=[args.client_dir/name/(version+'.js'),args.client_dir/(name+'-'+version+'.js')]
                candidate=next((path for path in candidates if path.is_file()),None)
                if candidate is not None:
                    if candidate not in clients:clients[candidate]=candidate.read_text(encoding='utf-8')
                    source=clients[candidate]
        report=audit_exchanges(row['exchanges'],client_source=source);report['capture_sha256']=row['sha256'];report['import_issues']=row.get('import_issues',[]);reports.append(report)
        if len(reports)%200==0:print('Audited',len(reports),'captures',flush=True)
        totals.update({k:report[k] for k in ('steps_checked','money_accepted_steps','closed_rounds','contract_actions')})
        for item in report['unresolved_actions']:blockers[item['phase']]+=1
    output={'schema':'nolimit-city/corpus-summary/v1','ok_certified':False,'captures':len(reports),
        'totals':dict(totals),'unresolved_phase_steps':dict(blockers.most_common()),'reports':reports}
    args.output.write_text(json.dumps(output,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k!='reports'}))

if __name__=='__main__':main()
