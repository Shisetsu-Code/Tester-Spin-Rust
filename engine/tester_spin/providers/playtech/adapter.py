"""Executable GPAS adapter sharing the existing Playtech catalog."""
import json
import re
import time
import uuid
from pathlib import Path
from tester_spin.models import GameTestResult, SpinAttempt, utc_now_iso
from tester_spin.providers.catalogs.adapter import CatalogProvider
from tester_spin.providers.catalogs.sources import SOURCES
from .protocol import resolve_configuration
from .primitives import COMMAND, client_contract, discover_modes, entry_command, PickState, RoundLedger, paid_option_declaration
from tester_spin.paid_options import write_paid_option_inventory
from .direct_runtime import DemoSession
from .ngm_runtime import NGMDemoSession


class PlaytechProvider(CatalogProvider):
    key='playtech'
    display_name='Playtech'
    catalog_url=SOURCES['playtech']['url']
    execution_supported=True
    max_test_concurrency=2
    session_factory=DemoSession
    ngm_session_factory=NGMDemoSession

    def test_game(self,game,*,spins,timeout_s,stop_event,progress):
        if not re.fullmatch(r'gpas_[A-Za-z0-9_]+',game.symbol or ''):
            from .ngm_execution import test_ngm_game
            return test_ngm_game(self,game,spins=spins,timeout_s=timeout_s,stop_event=stop_event,progress=progress)
        start=time.monotonic();run=self.har_artifact_dir(game)/'runs'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
        result=GameTestResult(self.key,game.slug,game.name,game.url,spins,0,0,'PARCIAL',symbol=game.symbol,run_dir=str(run))
        issues=[];pending={};offered={};covered={};replays={};targets_seen=set()
        try:
            if stop_event.is_set():raise InterruptedError('DETENIDO')
            with self.session_factory(game.symbol,run,timeout_s,stop_event) as session:
                (run/'bootstrap.json').write_text(json.dumps({'manifest':session.manifest,'source_sha256':session.source_hashes,'contract':None,'configuration_status':'captured_in_session_har'},indent=2),encoding='utf-8')
                contract=client_contract(session.manifest,session.sources,adapter_config=getattr(session,"adapter_config",None))
                resolved=resolve_configuration(session.config,{'betType':'default'})
                plan=discover_modes(resolved,contract,session.sources)
                result.discovered_modes=plan['modes'];result.feature_domains=plan['domains'];issues.extend(plan['unresolved'])
                result.structural_map['playtech_protocol']={'contract':contract,'source_sha256':session.source_hashes,'configuration':resolved,'fresh_demo':True,'transport':getattr(session,'transport_kind','unspecified')}
                (run/'bootstrap.json').write_text(json.dumps({'manifest':session.manifest,'configuration':resolved,'contract':contract,'source_sha256':session.source_hashes},indent=2),encoding='utf-8')
                write_paid_option_inventory(result, **paid_option_declaration(plan), evidence_files=['bootstrap.json'])
                base=next((m for m in plan['modes'] if m['kind']=='SPIN'),None)
                if base is None:raise ValueError('BASE_MODE_UNBOUND')
                sequence=[m for m in plan['modes'] if m['kind']!='UNKNOWN_FEATURE' for _ in range(max(1,int(spins)))]
                result.requested_spins=len(sequence)+1
                sequence.append(dict(base,id=base['id'],return_to_base=True))
                for index,mode in enumerate(sequence,1):
                    if stop_event.is_set():raise InterruptedError('DETENIDO')
                    directory=run/('mode-'+str(index));directory.mkdir()
                    attempt=SpinAttempt(index,False,mode_id=mode['id'],mode_kind=mode['kind'],symbol=game.symbol,artifact_dir=str(directory))
                    result.attempts.append(attempt);clock=time.monotonic()
                    ledger=RoundLedger(session.balance,mode['id'],mode['cost']*mode['multiplier']);picks=PickState(mode.get('choice_target'))
                    request=entry_command(mode,contract)
                    (directory/'request.json').write_text(json.dumps(request,indent=2),encoding='utf-8')
                    try:
                        for step in range(200):
                            response=session.exchange(request,contract)
                            (directory/('response.json' if step==0 else f'response-{step}.json')).write_text(json.dumps(response,indent=2),encoding='utf-8')
                            data=ledger.accept(response);attempt.wire_steps+=1
                            if ledger.closed:break
                            parameters=picks.parameters(data,contract['pick_bound'])
                            if not data.get('nextRound'):raise ValueError('CONTINUATION_STATE_UNKNOWN')
                            request={'_type':COMMAND,'gameData':{'_type':contract['class'],'ID':contract['continuation_id'],'parameters':parameters}}
                            if contract['dialect']=='modern':request['autoplay']=False
                            (directory/f'request-{step+1}.json').write_text(json.dumps(request,indent=2),encoding='utf-8')
                        if not ledger.closed:raise ValueError('ROUND_STEP_LIMIT')
                        session.wait(lambda:ledger.verify(session.balance),'BALANCE_NOT_RECONCILED')
                        attempt.ok=True;attempt.terminal=True;result.successful_spins+=1
                        mode['validated']=True
                        mode_offered=offered.setdefault(mode['id'],{})
                        mode_covered=covered.setdefault(mode['id'],{})
                        for phase,options in picks.offered.items():
                            mode_offered.setdefault(phase,set()).update(options)
                            mode_covered.setdefault(phase,set()).update(picks.selected.get(phase,set()))
                        declared=next(m for m in plan['modes'] if m['id']==mode['id'])
                        declared['validated']=True
                        declared['choice_domains']=[{'id':phase,'options':sorted(options),'covered':sorted(mode_covered.get(phase,set())),
                            'source':'fresh_response.listPickPlayerPickOptions'} for phase,options in mode_offered.items()]
                        missing={phase:sorted(options-mode_covered.get(phase,set())) for phase,options in mode_offered.items() if options-mode_covered.get(phase,set())}
                        if missing:pending[mode['id']]=missing
                        else:pending.pop(mode['id'],None)
                        if missing and not mode.get('return_to_base'):
                            phase=next(iter(missing));option=missing[phase][0];target=(mode['id'],phase,option)
                            # Re-enter via a new closed round; never choose exclusive alternatives in-place.
                            if target not in targets_seen and replays.get(mode['id'],0)<32:
                                targets_seen.add(target);replays[mode['id']]=replays.get(mode['id'],0)+1
                                sequence.insert(index,dict(declared,choice_target={phase:option}))
                                result.requested_spins+=1
                        if mode.get('return_to_base'):result.structural_map['return_to_base_verified']=True
                        (directory/'summary.json').write_text(json.dumps({'closed':True,'stake':ledger.cost,'win':ledger.wins,'balance_before':ledger.before,'balance_after':session.balance,'pending_choice_branches':missing},indent=2),encoding='utf-8')
                        progress(f"[{game.name}] {mode['name']}: ronda cerrada, coste {ledger.cost}, premio {ledger.wins}.")
                    except Exception as exc:
                        attempt.error=str(exc);issues.append(str(exc));raise
                    finally:attempt.elapsed_ms=(time.monotonic()-clock)*1000
                if session.errors:issues.extend(session.errors)
        except Exception as exc:
            reason=type(exc).__name__+': '+str(exc)
            if reason not in issues:issues.append(reason)
        if pending:issues.extend('CHOICE_BRANCHES_PENDING:'+identity for identity in pending)
        result.failed_spins=sum(not a.ok for a in result.attempts)
        result.structural_map['pending_choice_branches']=pending
        result.structural_map['execution_issues']=list(dict.fromkeys(issues))
        result.status='OK' if not issues and result.attempts and all(a.ok for a in result.attempts) and result.structural_map.get('return_to_base_verified') else 'PARCIAL'
        result.error='; '.join(dict.fromkeys(issues))
        result.finished_at=utc_now_iso();result.elapsed_ms=(time.monotonic()-start)*1000
        (run/'result.json').write_text(json.dumps(result.to_dict(),indent=2),encoding='utf-8')
        progress(f'[{game.name}] {result.status}: {result.successful_spins} rondas completas. '+result.error)
        return result
