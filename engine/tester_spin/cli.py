"""Run one provider on a PC or a CI runner without importing the desktop GUI."""
from __future__ import annotations
import argparse,json,multiprocessing as mp,os,signal,sys,uuid,tempfile
from contextlib import nullcontext
from pathlib import Path
from tester_spin.providers.registry import PROVIDERS,create_provider

def positive(value):
    try:n=int(value)
    except ValueError:raise argparse.ArgumentTypeError('Se requiere un entero positivo')
    if n<=0:raise argparse.ArgumentTypeError('Se requiere un entero positivo')
    return n

def nonnegative(value):
    try:n=int(value)
    except ValueError:raise argparse.ArgumentTypeError('Se requiere un entero no negativo')
    if n<0:raise argparse.ArgumentTypeError('Se requiere un entero no negativo')
    return n

def parser():
    root=argparse.ArgumentParser(prog='tester-spin')
    sub=root.add_subparsers(dest='command',required=True)
    sub.add_parser('providers',help='listar los proveedores independientes')
    for name in ('catalog','run'):
        p=sub.add_parser(name);p.add_argument('provider',choices=PROVIDERS)
        p.add_argument('--data-root',type=Path,default=Path(os.environ.get('TESTER_SPIN_DATA_ROOT','data')))
        p.add_argument('--wg-config',type=Path,action='append',default=[])
        p.add_argument('--wg-dir',type=Path)
        if name=='run':
            p.add_argument('--games-per-ip',type=positive)
            p.add_argument('--limit',type=nonnegative,default=0);p.add_argument('--offset',type=nonnegative,default=0)
            p.add_argument('--spins',type=positive,default=1);p.add_argument('--timeout',type=positive,default=20)
            p.add_argument('--wall-timeout',type=positive,default=180)
            p.add_argument('--statuses',nargs='+',default=['PENDIENTE','PARCIAL','ERROR','SIN_DEMO'])
            p.add_argument('--game');p.add_argument('--refresh-catalog',action='store_true')
            p.add_argument('--group-report',type=Path,help='informe .groups.json de una corrida anterior')
            p.add_argument('--group-id',help='identificador del grupo a repetir')
            p.add_argument('--dry-run',action='store_true');p.add_argument('--public-summary',type=Path)
    return root

def profiles_for(args):
    from tester_spin.vpn.wireguard import validate_config
    profiles=list(args.wg_config)
    if args.wg_dir:
        if not args.wg_dir.is_dir():raise ValueError('No existe la carpeta de configuraciones WireGuard')
        profiles+=sorted(args.wg_dir.glob('*.conf'))
    if (args.wg_dir or args.wg_config) and not profiles:raise ValueError('No hay perfiles .conf exportados en esa carpeta')
    profiles=list(dict.fromkeys(p.resolve() for p in profiles))
    for p in profiles:validate_config(p)
    if args.command=='run':
        if profiles and args.games_per_ip is None:raise ValueError('WireGuard requiere --games-per-ip')
        if not profiles and args.games_per_ip is not None:raise ValueError('--games-per-ip requiere perfiles WireGuard')
    return profiles

def public_report(report):
    allowed={'provider','run_id','games_per_ip','selected','attempted','pending','reason','statuses','results','network_error'}
    return {k:v for k,v in report.items() if k in allowed}

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.tester-report-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as target:json.dump(value,target,ensure_ascii=False,indent=2)
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def main(argv=None):
    os.environ.setdefault('PYTHONUTF8','1');os.environ.setdefault('PYTHONIOENCODING','utf-8')
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    args=parser().parse_args(argv)
    if args.command=='run' and bool(args.group_report)!=bool(args.group_id):
        parser().error('--group-report y --group-id se requieren juntos')
    if args.command=='providers':
        print(json.dumps({k:v[2] for k,v in PROVIDERS.items()},ensure_ascii=False,indent=2));return 0
    try:profiles=profiles_for(args)
    except (ValueError,RuntimeError) as exc:print(str(exc),file=sys.stderr);return 2
    from tester_spin.storage import Storage
    from tester_spin.vpn.wireguard import WireGuardTunnel
    data_root=args.data_root.resolve();storage=Storage(data_root/'tester-spin.sqlite3')
    provider=create_provider(args.provider,data_root)
    if args.command=='run' and not args.dry_run and not getattr(provider,'execution_supported',True):
        print('Ejecutor pendiente: usa catalog para cargar este proveedor, sin iniciar pruebas ni cambiar la red.',file=sys.stderr);return 2
    stop=mp.get_context('spawn').Event()
    old_signal={}
    for sig in (signal.SIGINT,signal.SIGTERM):
        old_signal[sig]=signal.signal(sig,lambda *_:stop.set())
    try:
        games=storage.list_games(args.provider)
        needs_catalog=args.command=='catalog' or (args.command=='run' and not args.dry_run and (not games or args.refresh_catalog))
        if needs_catalog:
            check=getattr(provider,'test_start_block_reason',None)
            reason=check(timeout_s=getattr(args,'timeout',30)) if check is not None else ''
            if reason:
                if args.command=='run' and games:
                    needs_catalog=False
                else:
                    print(json.dumps({'provider':args.provider,'reason':'RATE_LIMIT','attempted':0,'error':reason},ensure_ascii=False))
                    return 3
        if needs_catalog:
            connection=WireGuardTunnel(profiles[0],stop_event=stop) if profiles else nullcontext()
            with connection:
                found=provider.crawl_catalog(stop_event=stop,progress=lambda _:None,max_pages=100)
                storage.upsert_games(found)
            games=storage.list_games(args.provider)
        if not games and not (args.command=='run' and args.dry_run):raise RuntimeError('No hay catálogo verificable; no se inicia una corrida vacía')
        if args.command=='catalog':
            print(json.dumps({'provider':args.provider,'catalog_games':len(games)}));return 0
        allowed={v.upper() for v in args.statuses}
        if args.group_report:
            from tester_spin.failure_groups import select_group
            if args.group_report.stat().st_size>8*1024*1024:raise ValueError('Informe de grupos demasiado grande')
            group_data=json.loads(args.group_report.read_text(encoding='utf-8'))
            slugs=select_group(group_data,args.group_id,args.provider)
            games=[g for g in games if g.slug in slugs]
        elif 'ALL' not in allowed:games=[g for g in games if g.last_status.upper() in allowed]
        if args.game:games=[g for g in games if g.slug==args.game or g.symbol==args.game]
        games=games[args.offset:]
        if args.limit:games=games[:args.limit]
        if args.dry_run:
            print(json.dumps({'provider':args.provider,'selected_games':[g.slug for g in games],'wireguard_profiles':len(profiles),
                'games_per_ip':args.games_per_ip,'network_changed':False}));return 0
        from tester_spin.independent.batches import run_batches
        from tester_spin.independent.worker import execute_game
        run_id=uuid.uuid4().hex;directory=data_root/'independent'/'runs'/run_id;directory.mkdir(parents=True)
        target=args.public_summary or directory/'summary.json';target.parent.mkdir(parents=True,exist_ok=True)
        batch_results=[];baseline=storage.latest_results(args.provider)
        checkpoint={'provider':args.provider,'run_id':run_id,'games_per_ip':args.games_per_ip,'selected':len(games),
            'attempted':0,'pending':len(games),'reason':'RUNNING','statuses':{},'results':[]}
        write_json(target,checkpoint)
        def execute(game):return execute_game(game,data_root=data_root,run_root=directory,spins=args.spins,timeout=args.timeout,
            wall_timeout=args.wall_timeout,stop_event=stop,vpn=bool(profiles))
        def record(result):
            proof=result.structural_map.get('network_context')
            if proof and proof.get('verified') is False or result.structural_map.get('execution_abort',{}).get('forced') is True:
                farm_root=provider.farm_contract_dir(next(g for g in games if g.slug==result.slug))
                for p in ([farm_root/'farm-contract.json'] if farm_root else []):
                    if p.is_file():
                        contract=json.loads(p.read_text(encoding='utf-8'));contract['ready']=False
                        contract.setdefault('unresolved',[]).append('CURRENT_EXECUTION_CONTEXT_NOT_VERIFIED')
                        p.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
            storage.record_result(result)
            batch_results.append(result)
            checkpoint['attempted']+=1;checkpoint['pending']-=1
            checkpoint['statuses'][result.status]=checkpoint['statuses'].get(result.status,0)+1
            checkpoint['results'].append({'provider':result.provider,'slug':result.slug,'status':result.status})
            write_json(target,public_report(checkpoint))
        def block_check(game):
            check=getattr(provider,'test_start_block_reason',None)
            reason=check(timeout_s=args.timeout) if check is not None else ''
            if not reason:return None
            from tester_spin.models import GameTestResult
            result=GameTestResult(game.provider,game.slug,game.name,game.url,args.spins,0,args.spins,'ERROR',symbol=game.symbol,error=reason)
            metadata_check=getattr(provider,'test_start_block_metadata',None)
            metadata=metadata_check() if metadata_check is not None else {}
            if isinstance(metadata,dict):result.structural_map.update(metadata)
            result.structural_map['execution_block']={'source':'provider.test_start_block_reason','reason':reason}
            return result
        report=run_batches(games,execute=execute,record=record,profiles=profiles,games_per_ip=args.games_per_ip,stop_event=stop,progress=print,block_check=block_check)
        report.update(provider=args.provider,run_id=run_id,games_per_ip=args.games_per_ip)
        (directory/'summary.private.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        from tester_spin.failure_groups import write_report
        write_report(batch_results,directory/'summary',baseline=baseline,expected_count=len(games))
        groups_written=True
        safe=public_report(report)
        target=args.public_summary or directory/'summary.json';target.parent.mkdir(parents=True,exist_ok=True)
        write_json(target,safe)
        print(json.dumps(safe,ensure_ascii=False))
        return 0 if report['reason']=='COMPLETED' else 3
    except Exception as exc:
        if getattr(exc,'preserve_network',False):
            if 'checkpoint' in locals():
                checkpoint['reason']='PROCESS_TREE_NOT_CLOSED'
                write_json(target,public_report(checkpoint))
            print('No se comprobó el cierre de todos los procesos. La VPN se conserva activa; no se inicia otro lote.',file=sys.stderr)
            return 4
        print('Ejecución detenida: '+type(exc).__name__+'. Revisá la configuración y los registros locales.',file=sys.stderr);return 2
    finally:
        if 'batch_results' in locals() and not locals().get('groups_written',False):
            try:
                from tester_spin.failure_groups import write_report
                write_report(batch_results,directory/'summary',baseline=baseline,expected_count=len(games))
            except Exception:
                print('No se pudo guardar el informe de grupos de la corrida interrumpida.',file=sys.stderr)
        for sig,handler in old_signal.items():signal.signal(sig,handler)

if __name__=='__main__':
    os.environ.setdefault('PYTHONUTF8','1');os.environ.setdefault('PYTHONIOENCODING','utf-8')
    mp.freeze_support();raise SystemExit(main())
