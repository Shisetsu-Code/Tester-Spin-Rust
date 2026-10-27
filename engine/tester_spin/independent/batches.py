"""Provider-neutral batches; changes of network happen only after a game exits."""
import re
from contextlib import nullcontext
from tester_spin.models import GameTestResult
from tester_spin.vpn.quota import IpQuota
from .processes import UnsafeProcessTree
from tester_spin.vpn.wireguard import WireGuardTunnel,NetworkContextError

def run_batches(games,*,execute,record,profiles,games_per_ip,stop_event,tunnel_factory=None,progress=lambda _:None,block_check=None):
    games=list(games);profiles=list(profiles)
    quota=IpQuota(games_per_ip) if profiles else None
    factory=tunnel_factory or (lambda p:WireGuardTunnel(p,stop_event=stop_event))
    report={'selected':len(games),'attempted':0,'pending':len(games),'reason':'COMPLETED','statuses':{},'ip_counts':{},'results':[]}
    def preflight():
        if block_check is None:return False
        game=games[report['attempted']]
        result=block_check(game)
        if stop_event.is_set():
            report['reason']='CANCELLED';return True
        if result is None:return False
        if result.provider!=game.provider or result.slug!=game.slug:raise RuntimeError('El resultado no corresponde al juego de la cola')
        record(result)
        report['attempted']+=1;report['pending']=len(games)-report['attempted']
        report['statuses'][result.status]=report['statuses'].get(result.status,0)+1
        report['results'].append({'provider':game.provider,'slug':game.slug,'status':result.status})
        report['reason']='RATE_LIMIT'
        progress(f"{game.name}: {result.status}; {result.error}")
        stop_event.set()
        return True
    for profile in profiles or [None]:
        if report['attempted']>=len(games):break
        if stop_event.is_set():report['reason']='CANCELLED';break
        if preflight():return report
        try:
            with factory(profile) if profile is not None else nullcontext(None) as connection:
                ip=connection.ip if connection else None
                while report['attempted']<len(games) and (quota is None or quota.remaining(ip)>0):
                    if stop_event.is_set():report['reason']='CANCELLED';return report
                    if preflight():return report
                    if connection:connection.verify()
                    game=games[report['attempted']]
                    if quota:quota.consume(ip);report['ip_counts']=dict(quota.counts)
                    report['attempted']+=1;report['pending']=len(games)-report['attempted']
                    progress(f"{report['attempted']}/{len(games)}: {game.name}")
                    try:result=execute(game)
                    except UnsafeProcessTree:
                        stop_event.set();raise
                    except Exception as exc:
                        result=GameTestResult(game.provider,game.slug,game.name,game.url,1,0,1,'ERROR',symbol=game.symbol,
                            error='INDEPENDENT_WORKER_FAILURE: '+type(exc).__name__)
                    if result.provider!=game.provider or result.slug!=game.slug:raise RuntimeError('El resultado no corresponde al juego de la cola')
                    context_error=False
                    if connection:
                        try:connection.verify()
                        except NetworkContextError as exc:
                            report['network_error']=str(exc)
                            context_error=True
                            result.status='PARCIAL' if result.status=='OK' else result.status
                            result.error=(result.error+' NETWORK_CONTEXT_NOT_VERIFIED').strip()
                        result.structural_map['network_context']={'verified':not context_error,'exit_ip':ip,'games_on_ip':quota.counts[ip]}
                    record(result)
                    report['statuses'][result.status]=report['statuses'].get(result.status,0)+1
                    report['results'].append({'provider':game.provider,'slug':game.slug,'status':result.status})
                    progress(f"{game.name}: {result.status}")
                    if context_error:report['reason']='VPN_ERROR';return report
                    if 'SERVER_RETRY_AFTER' in (result.error or '') or re.search(r'\b(?:HTTP(?: Error)?\s+429|429(?:\s+Too Many Requests)?)\b',result.error or '',re.I):
                        report['reason']='RATE_LIMIT';stop_event.set();return report
                    if result.status in {'CANCELADO','CANCELLED'} or stop_event.is_set():
                        report['reason']='CANCELLED';stop_event.set();return report
        except NetworkContextError as exc:
            report['network_error']=str(exc)
            report['reason']='VPN_ERROR';return report
    if report['reason']=='COMPLETED':
        if stop_event.is_set():report['reason']='CANCELLED'
        elif report['pending']:report['reason']='IP_QUOTA_EXHAUSTED'
    return report
