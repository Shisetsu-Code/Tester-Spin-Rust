"""New paid BASIC rounds in the same live session, after all feature jobs."""
from .ledger import RoundLedger
from .runtime import terminal, minimum_round_seconds, BONUS_ID
from tester_spin.return_to_base import verify_return_to_base, save_exchange

def check_return(send,directory,*,before,stake,currency,stop_event=None,minimum_duration=0,previous_round_id=None):
    current=before
    seen={previous_round_id} if previous_round_id else set()
    def play(target):
        nonlocal current
        import time
        started=time.monotonic()
        ledger=RoundLedger(current,currency,stake,1)
        captures=[];had_feature=False
        payload={'bets':[{'betAmount':stake}],'offerId':None,'promotionId':None,'autoplay':False}
        for step in range(1,17):
            if stop_event is not None and stop_event.is_set():raise InterruptedError('Detención solicitada')
            data=send(payload)
            captures.append(save_exchange(target,payload,data,step))
            ledger.accept(data)
            if step == 1:
                if ledger.round_id in seen:raise ValueError("Hacksaw: el giro de retorno reutilizó una ronda anterior")
                seen.add(ledger.round_id)
            current=ledger.after
            rd=data['round']
            for event in rd['events']:
                content=event.get('c') or {}
                actions=content.get('actions',[]) if isinstance(content,dict) else []
                had_feature=had_feature or event.get('etn') in {'feature_enter','pick'} or any(
                    isinstance(a,dict) and a.get('at')=='bonusfeaturewon' for a in actions)
            if terminal(data):
                return {'ok':True,'known':True,'base':not had_feature,'captures':captures,'ledger':ledger.proof()}
            actions=rd['possibleActions']
            if rd['status']=='wfwpc' and actions==[]:
                remaining=max(0,minimum_round_seconds(minimum_duration)-(time.monotonic()-started))
                if stop_event is not None:
                    if stop_event.wait(remaining):raise InterruptedError('Detención solicitada')
                elif remaining:time.sleep(remaining)
                selected='win_presentation_complete'
            elif (rd['status']=='started' and 0<len(actions)<=16
                    and all(isinstance(a,str) and BONUS_ID.fullmatch(a) and a!='win_presentation_complete' for a in actions)
                    and len(set(actions))==len(actions)):
                had_feature=True
                selected='play' if 'play' in actions else next((a for a in actions if a!='gamble'),None)
                if selected is None:return {'ok':True,'known':False,'base':False,'captures':captures,'reason':'no safe return selector'}
            else:return {'ok':True,'known':False,'base':False,'captures':captures,'reason':'unknown continuation'}
            payload={'roundId':rd['roundId'],'continueInstructions':{'action':selected}}
        return {'ok':True,'known':False,'base':False,'captures':captures,'reason':'continuation limit'}
    return verify_return_to_base(directory,play,stop_event=stop_event)
