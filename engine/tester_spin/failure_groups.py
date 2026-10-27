"""Read-only prioritization of batch failures, independent of provider execution."""
from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from .run_diagnostics import sanitize

SCHEMA='tester-spin/failure-groups/v1'
LABELS={'INITIALIZATION':'Inicialización o cliente incompleto','CONNECTION':'Conexión o timeout',
        'RATE_LIMIT':'Límite de solicitudes','MODALITY':'Modalidad sin reconocer','CONTINUATION':'Continuación desconocida',
        'CHOICES':'Elecciones pendientes','SETTLEMENT':'Saldo o cierre inconsistentes','SERVER':'Rechazo del servidor',
        'AVAILABILITY':'Demo o motor no disponible','UNKNOWN':'Causa sin clasificar'}
RULES=[('CANCELLED',r'DETENIDO|CANCELADO|CANCELLED'),('RATE_LIMIT',r'\b429\b|RATE_LIMIT|TOO MANY REQUESTS'),
 ('SETTLEMENT',r'BALANCE_NOT_RECONCILED|BALANCE.*MISMATCH|UNEXPECTED_CHARGE|WIN_MISMATCH|ROUND_STEP_LIMIT|BET_COST_MISMATCH|STAKE_UUID_MISMATCH|SETTLEMENT'),
 ('CHOICES',r'CHOICE_BRANCHES_PENDING|PICK_DOMAIN|PICK_COMMAND|NO_UNCONSUMED_PICK|Cobertura de ramificaciones pendiente|UN[C]?OVERED.*(?:BRANCH|CHOICE)'),
 ('MODALITY',r'UNBOUND_STAKE|BASE_MODE_UNBOUND|ACTIVE_OPTION_UNBOUND|STAKE_DECLARATION|UNKNOWN_FEATURE|CLIENT_COMMAND_BINDING|CLIENT_BET_API'),
 ('INITIALIZATION',r'BOOTSTRAP|CLIENT_ASSETS|GLU_NOT_READY|DEMO_MODE_NOT_CONFIRMED|until.*(?:boot|asset)|INICIALIZ'),
 ('CONTINUATION',r'CONTINUATION_STATE|INVALID_PACKED|PACKED_LIMIT|UNRECOGNIZED_CONTINUATION|CONTINUACI'),
 ('CONNECTION',r'TIMEOUT|TIMED OUT|CONNECTION|ERR_NETWORK|ERR_NAME|ERR_CONNECTION|SOCKET_CLOSED'),
 ('SERVER',r'EngineError|SERVER_ERROR|CLIENT_API_REJECTED|HTTP[ :]+[45][0-9]{2}'),
 ('AVAILABILITY',r'no GPAS|Ejecutor pendiente|falta aprender|SIN_DEMO|demo.*(?:unavailable|no disponible)')]


def _row(value):
    return value.to_dict() if hasattr(value,'to_dict') else value


def _latest(values):
    rows={}
    for value in values:
        row=_row(value)
        if not isinstance(row,dict) or not row.get('provider') or not row.get('slug'):continue
        key=(str(row['provider']),str(row['slug']))
        prior=rows.get(key)
        if prior is None or str(row.get('finished_at',''))>=str(prior.get('finished_at','')):rows[key]=row
    return rows


def _issue(text):
    text=str(sanitize(str(text)))
    for cause,pattern in RULES:
        if re.search(pattern,text,re.I):
            code=re.search(r'\b[A-Z][A-Z_]{4,}\b',text)
            return cause, code.group() if code and code.group() not in {'ERROR','PARCIAL'} else cause
    return 'UNKNOWN','UNCLASSIFIED'


def _contract(row):
    structural=row.get('structural_map') or {}
    binding=(structural.get('playtech_protocol') or {}).get('contract') or {}
    # Never fingerprint monetary values, title IDs, session IDs or source hashes.
    return {k:binding[k] for k in ('dialect','class','entry_id','continuation_id','pick_bound') if k in binding}


def _artifacts(run_dir):
    if not run_dir:return {}
    items={}
    for label,name in (('result','result.json'),('diagnostic','diagnostic.json'),('har','session.har'),('coverage','path-coverage.json')):
        try:
            path=Path(run_dir)/name
            if path.is_file():items[label]=str(path)
        except (OSError,ValueError):continue
    try:
        if Path(run_dir).is_dir():items['folder']=run_dir
    except (OSError,ValueError):pass
    return items


def build_report(results,*,baseline=None,expected_count=None):
    rows=_latest(results);previous=_latest(baseline or []);groups={};cancelled=0
    for key,row in sorted(rows.items()):
        status=str(row.get('status','UNKNOWN')).upper()
        if status in {'OK','OK_MANUAL','OK MANUAL'}:continue
        raw=(row.get('structural_map') or {}).get('execution_issues') or [row.get('error') or status]
        if not isinstance(raw,list):raw=[str(raw)]
        issues={_issue(t) for t in raw}
        if any(c=='CANCELLED' for c,_ in issues) or status in {'CANCELADO','CANCELLED'}:cancelled+=1;continue
        contract=_contract(row)
        pending=(row.get('structural_map') or {}).get('pending_choice_branches') or {}
        phases=sorted({phase for item in pending.values() if isinstance(item,dict) for phase in item}) if isinstance(pending,dict) else []
        for cause,code in sorted(issues):
            signature={'provider':key[0],'cause':cause,'code':code,'contract':contract,'phases':phases if cause=='CHOICES' else []}
            digest=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:20]
            group=groups.setdefault(digest,{'id':digest,**signature,'label':LABELS.get(cause,cause),'games':[]})
            run_dir=str(row.get('run_dir') or '')
            group['games'].append({'provider':key[0],'slug':key[1],'name':row.get('game_name',key[1]),'status':status,
                                   'error':sanitize(str(row.get('error',''))),'run_dir':run_dir,
                                   'artifacts':_artifacts(run_dir)})
    ordered=sorted(groups.values(),key=lambda g:(-len(g['games']),g['provider'],g['cause'],g['id']))
    for g in ordered:g.update(affected=len(g['games']),representatives=g['games'][:2])
    comparison={'fixed':[],'regressions':[],'still_pending':[],'unchanged_ok':[],'new':[]}
    for key,row in sorted(rows.items()):
        if key not in previous:category='new'
        else:
            before=previous[key].get('status')=='OK';after=row.get('status')=='OK'
            category='fixed' if after and not before else 'regressions' if before and not after else 'unchanged_ok' if after else 'still_pending'
        comparison[category].append(list(key))
    return sanitize({'schema':SCHEMA,'attempted':len(rows),'expected':expected_count if expected_count is not None else len(rows),
                     'pending':max(0,(expected_count or len(rows))-len(rows)),'cancelled':cancelled,
                     'statuses':dict(Counter(str(r.get('status','UNKNOWN')) for r in rows.values())),
                     'groups':ordered,'problem_games':len({(g['provider'],m['slug']) for g in ordered for m in g['games']}),'comparison':comparison,'baseline_available':baseline is not None,
                     'results':[{'provider':k[0],'slug':k[1],'status':r.get('status','UNKNOWN')} for k,r in sorted(rows.items())],
                     'interpretation':'Firmas candidatas para priorizar; un grupo no demuestra causalidad ni autoriza cambios de estado.'})


def select_group(report,group_id,provider):
    if not isinstance(report,dict) or report.get('schema')!=SCHEMA:raise ValueError('Informe de grupos incompatible')
    matches=[g for g in report.get('groups',[]) if isinstance(g,dict) and g.get('id')==group_id]
    if len(matches)!=1 or matches[0].get('provider')!=provider:raise ValueError('Grupo ausente o de otro proveedor')
    games=matches[0].get('games')
    if not isinstance(games,list) or any(not isinstance(g,dict) or g.get('provider')!=provider or not isinstance(g.get('slug'),str) or not g['slug'] for g in games):raise ValueError('Selección de grupo inválida')
    return {g['slug'] for g in games}


def render(report):
    lines=['# Grupos de resultados','',f"Resultados: {report['attempted']}; pendientes sin resultado: {report['pending']}; cancelados: {report['cancelled']}.",'']
    lines += ['Los grupos pueden compartir afectados si un juego presenta más de una causa.','']
    if report['baseline_available']:
        c=report['comparison'];lines += [f"Comparación: {len(c['fixed'])} corregidos; {len(c['regressions'])} regresiones; {len(c['still_pending'])} siguen pendientes.",'']
    for group in report['groups']:
        lines += [f"## {group['affected']} juegos — {group['provider']} — {group['label']}",'',f"Grupo: `{group['id']}` · código: `{group['code']}`",'','Representantes:']
        for item in group['representatives']:
            lines.append(f"- {item['name']} ({item['slug']}): {item['error']}")
            for label,path in item['artifacts'].items():lines.append(f"  - [{label}](<{Path(path).resolve().as_posix()}>)")
        lines += ['','Afectados: '+', '.join(g['slug'] for g in group['games']), '']
    if not report['groups']:lines += ['No hay grupos de fallos en estos resultados.','']
    lines += [report['interpretation'],'']
    return '\n'.join(lines)


def _atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.groups-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(text)
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)


def write_report(results,stem,*,baseline=None,expected_count=None):
    report=build_report(results,baseline=baseline,expected_count=expected_count);stem=Path(stem)
    paths={'json':stem.with_suffix('.groups.json'),'markdown':stem.with_suffix('.groups.md')}
    _atomic(paths['json'],json.dumps(report,ensure_ascii=False,indent=2));_atomic(paths['markdown'],render(report))
    return paths
