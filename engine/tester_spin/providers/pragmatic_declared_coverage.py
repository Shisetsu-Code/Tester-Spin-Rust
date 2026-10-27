"""Current-session mode evidence for Pragmatic initialization domains."""
import json
import math
from pathlib import Path
from urllib.parse import parse_qs


def verified_mode_ids(result):
    from .pragmatic_protocol import server_error
    if not result.run_dir or not result.symbol:
        return set()
    root=Path(result.run_dir).resolve()
    def read(path):
        try:
            value=json.loads(path.read_text(encoding='utf8'))
            return value if isinstance(value,dict) else {}
        except (OSError,ValueError):return {}
    try:target=max(1,int(result.samples_per_path))
    except (TypeError,ValueError):return set()
    verified=set()
    for mode in result.discovered_modes:
        if mode.get('kind') not in {'PURCHASE','ANTE_BET'} or mode.get('enabled') is not True or mode.get('price_known') is not True:
            continue
        cost=mode.get('paid_cost')
        if not isinstance(cost,(int,float)) or isinstance(cost,bool) or not math.isfinite(cost) or cost<=0:
            continue
        bl,pur=mode.get('provider_bl'),mode.get('provider_pur')
        if type(bl) is not int or bl<0 or mode['kind']=='PURCHASE' and (type(pur) is not int or pur<0):continue
        paths=set()
        for attempt in result.attempts:
            if (attempt.mode_id!=mode.get('id') or attempt.mode_kind!=mode['kind']
                    or not attempt.ok or not attempt.terminal or attempt.warning or attempt.error or not attempt.artifact_dir):continue
            directory=Path(attempt.artifact_dir).resolve()
            if not directory.is_relative_to(root) or directory in paths:continue
            requests=list(directory.glob('step-000-*.request.txt'))
            if len(requests)!=1:continue
            request_path=requests[0]
            try:request=parse_qs(request_path.read_text(encoding='utf8'))
            except (OSError,ValueError):continue
            if request.get('action')!=['doSpin'] or request.get('bl')!=[str(bl)]:continue
            if result.symbol and request.get('symbol')!=[result.symbol]:continue
            if mode['kind']=='PURCHASE' and request.get('pur')!=[str(pur)]:continue
            if mode['kind']=='ANTE_BET' and 'pur' in request:continue
            prefix=request_path.name.removesuffix('.request.txt')
            response=read(directory/(prefix+'.response.json'))
            http=read(directory/(prefix+'.http.json'))
            proof=read(directory/'return-to-base.json')
            if (not response or server_error(response) or type(http.get('status')) is not int
                    or not 200<=http['status']<400 or proof.get('status')!='CONFIRMED'
                    or type(proof.get('consecutive_base')) is not int or proof['consecutive_base']<2):continue
            if response.get('bl') != str(bl):continue
            if mode['kind']=='PURCHASE' and (response.get('purtr')!='1' or response.get('puri')!=str(pur)):
                continue
            paths.add(directory)
        if len(paths)>=target:verified.add(str(mode['id']))
    return verified
