"""Import paired browser evidence without replaying requests or credentials."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from tester_spin.run_diagnostics import sanitize


def _identity(url):
    parts=urlsplit(url)
    host=(parts.hostname or '').lower()
    if not host.endswith('.bgaming-network.com'):
        return ''
    path=parts.path.split('/')
    if len(path)>2 and path[1]=='api':
        return path[2]
    if parts.path.rstrip('/')=='/api':
        return host.split('.')[0]
    return ''


def _key(value):
    return re.sub('[^a-z0-9]', '', value.casefold())


def _safe_url(url):
    parts=urlsplit(url)
    path=parts.path.split('/')
    if len(path)>4 and path[1]=='api':
        # Preserve the same-session grouping without persisting reusable IDs.
        path[4:] = ['capture-' + hashlib.sha256('/'.join(path[4:]).encode()).hexdigest()[:16]]
    authority=parts.hostname or ''
    if parts.port is not None:
        authority+=f':{parts.port}'
    return urlunsplit((parts.scheme,authority,'/'.join(path),'',''))


def _safe_body(value):
    value=sanitize(value)
    if isinstance(value,dict):
        return {k: '[REDACTED]' if k in {'state_lock'} else _safe_body(v) for k,v in value.items()}
    if isinstance(value,list):
        return [_safe_body(v) for v in value]
    if isinstance(value,str) and value.startswith(('http://','https://')):
        # Returned history/launch URLs can contain credentials in their path.
        return '[URL OMITTED]'
    return value


def _normalize(entry, expected_game):
    request=entry.get('request') or {}
    if request.get('method')!='POST':
        return None
    try:
        payload=json.loads((request.get('postData') or {}).get('text') or '')
    except (TypeError,ValueError):
        return None
    if not isinstance(payload,dict) or not (payload.get('command') or payload.get('method')):
        return None
    identity=_identity(request.get('url',''))
    if not identity:
        return None
    if _key(identity)!=_key(expected_game):
        raise ValueError(f'La captura corresponde a {identity}, no a {expected_game}')
    response=entry.get('response') or {}
    status=response.get('status',0)
    if not isinstance(status,int) or not 200<=status<300:
        return None
    content=response.get('content') or {}
    try:
        text=content.get('text') or ''
        if content.get('encoding')=='base64':
            text=base64.b64decode(text).decode('utf-8')
        data=json.loads(text)
    except (TypeError,ValueError,UnicodeError):
        return None
    if not isinstance(data,dict) or data.get('error') or data.get('errors'):
        return None
    return {'startedDateTime':entry.get('startedDateTime',''),
            'request':{'method':'POST','url':_safe_url(request['url']),
                       'postData':{'mimeType':'application/json','text':json.dumps(_safe_body(payload),ensure_ascii=False)}},
            'response':{'status':status,'content':{'mimeType':'application/json','text':json.dumps(_safe_body(data),ensure_ascii=False)}}}


def load_capture_entries(path, *, expected_game):
    """Use only successful, complete pairs; reject gameplay for another game."""
    path=Path(path)
    if path.suffix.casefold()=='.zip' or path.is_dir():
        if path.is_dir():
            raw=(path/'network.jsonl').read_text(encoding='utf-8-sig')
        else:
            with zipfile.ZipFile(path) as archive:
                files=[n for n in archive.namelist() if n.endswith('/network.jsonl') or n=='network.jsonl']
                if len(files)!=1:
                    raise ValueError('Se esperaba un único network.jsonl')
                raw=archive.read(files[0]).decode('utf-8-sig')
        records=[json.loads(line) for line in raw.splitlines() if line.strip()]
        requests={r['event_id']:r for r in records if r.get('kind')=='request' and r.get('event_id')}
        entries=[]
        for response in records:
            if response.get('kind')!='response':
                continue
            request=requests.get(response.get('request_event_id'))
            if not request or request.get('post_data_truncated') or response.get('body_truncated') or response.get('body_skipped_large'):
                continue
            entries.append({'startedDateTime':datetime.fromtimestamp(request['timestamp'],timezone.utc).isoformat(),
                'request':{'method':request.get('method'),'url':request.get('url'),'postData':{'text':request.get('post_data')}},
                'response':{'status':response.get('status'),'content':{'text':response.get('body')}}})
    else:
        entries=json.loads(path.read_text(encoding='utf-8-sig')).get('log',{}).get('entries',[])
    return [normalized for entry in entries if (normalized:=_normalize(entry,expected_game))]


def write_capture_har(sources, target, *, expected_game):
    entries=[]
    provenance=[]
    for source in sources:
        path=Path(source)
        imported=load_capture_entries(path,expected_game=expected_game)
        entries.extend(imported)
        hashed_file=path/'network.jsonl' if path.is_dir() else path
        provenance.append({'file':path.name,'sha256':hashlib.sha256(hashed_file.read_bytes()).hexdigest(),'hash_file':hashed_file.name,'accepted_pairs':len(imported)})
    if not entries:
        raise ValueError('La captura no contiene solicitudes y respuestas exitosas del juego')
    target=Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'log':{'version':'1.2','creator':{'name':'Tester-Spin capture importer','version':'1'},'entries':entries},'_sources':provenance},ensure_ascii=False,indent=2),encoding='utf-8')
    return target
