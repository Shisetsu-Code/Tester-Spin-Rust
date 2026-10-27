"""Local maintenance and explicit Git publication for the desktop application."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from tester_spin.run_diagnostics import sanitize

REPORT_NAMES = ('diagnostic.json', 'run-tree.json', 'path-coverage.json',
                'sample-catalog.json', 'server-observations.json')
CODE_DIRS = ('tester_spin', 'tests', 'docs', 'scripts', 'schema', '.github')
CODE_FILES = ('.gitignore', 'README.md', 'requirements.txt', 'run.py', 'run_ui_index.py',
              'launcher.py', 'Abrir-Tester-Spin.cmd', 'Abrir-Tester-Spin-UI-Index.cmd',
              'Abrir-Tester-Spin-Silencioso.vbs')


def _inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError(f'Ruta fuera del directorio permitido: {path.name}')
    return path


def _backup(root, label):
    path = root/'data'/'history-backups'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+label+'-'+uuid4().hex[:8])
    path.mkdir(parents=True)
    return path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize(data), ensure_ascii=False, indent=2), encoding='utf-8')


def export_reports(root, storage, progress):
    """Publishable snapshot: latest stored run per game, never raw HAR/session data."""
    root = Path(root).resolve()
    progress('Preparando el último resultado de cada juego...')
    rows = storage.latest_results()
    stage = root/'data'/('report-export-'+uuid4().hex)
    stage.mkdir(parents=True)
    index = []
    for number, row in enumerate(rows, 1):
        result = row
        provider, slug = result['provider'], result['slug']
        if any(not re.fullmatch(r'[\w.-]+', str(v)) or v in {'.','..'} for v in (provider, slug)):
            raise ValueError('Proveedor o identificador inválido en los resultados')
        target = _inside(stage/provider/slug, stage)
        _write(target/'result.json', result)
        run = _inside(Path(result['run_dir']), root/'data'/'providers') if result.get('run_dir') else None
        if run:
            for name in REPORT_NAMES:
                source = run/name
                if source.is_file():
                    _inside(source, root/'data'/'providers')
                    _write(target/name, json.loads(source.read_text(encoding='utf-8-sig')))
        index.append({'provider':provider, 'game':result['game_name'], 'status':(result.get('manual_validation') or {}).get('status', result['status']),
                      'report':f'{provider}/{slug}/result.json'})
        if number == 1 or number % 25 == 0 or number == len(rows):
            progress(f'Exportando informes: {number}/{len(rows)}')
    _write(stage/'index.json', index)
    (stage/'README.md').write_text('# Resultados de pruebas\n\nÚltimo resultado registrado por juego. '
        'Los JSON se filtran para ocultar claves de sesión. No incluye HAR ni capturas originales; '
        'las rutas locales que aparecen dentro de los informes son referencias de origen.\n', encoding='utf-8')
    destination = _inside(root/'test-evidence', root)
    backup = None
    if destination.exists():
        backup = _backup(root, 'previous-export')/'test-evidence'
        destination.rename(backup)
    try:
        stage.rename(destination)
    except Exception:
        if backup:
            backup.rename(destination)
        raise
    progress(f'Exportación lista: {len(rows)} juegos.')
    return destination


def clear_history(root, storage, provider, progress):
    """Archive run evidence and reset one provider, with rollback on failure."""
    if not re.fullmatch(r'[\w-]+', provider):
        raise ValueError('Proveedor inválido')
    root = Path(root).resolve()
    base = _inside(root/'data'/'providers'/provider, root/'data'/'providers')
    backup = _backup(root, provider)
    moved, edited = [], []
    progress(f'Guardando copia local del historial de {provider}...')
    with storage._lock, storage._connect() as db:
        with closing(sqlite3.connect(backup/'database.sqlite3')) as saved:
            db.backup(saved)
        candidates = []
        metadata = []
        if base.exists():
            for game in base.iterdir():
                _inside(game, base)
                if not game.is_dir() or game.name == 'bootstrap-runs':
                    continue
                for relative in ('tests', 'coverage-history.json', 'farm-contract.json', 'analysis/farm-contract-candidate.json'):
                    if (game/relative).exists():
                        candidates.append(game/relative)
                if (game/'game.json').is_file():
                    metadata.append(game/'game.json')
            if (base/'bootstrap-runs').exists():
                candidates.append(base/'bootstrap-runs')
        # Old batch reports can contain this provider together with others.
        for path in (root/'test-evidence'/provider, root/'data'/'reports'):
            if path.exists():
                candidates.append(path)
        try:
            for path in candidates:
                path = _inside(path, root)
                target = _inside(backup/path.relative_to(root), backup)
                target.parent.mkdir(parents=True, exist_ok=True)
                path.rename(target)
                moved.append((path, target))
            for path in metadata:
                path = _inside(path, base)
                original = path.read_bytes()
                value = json.loads(original)
                value.pop('last_test', None)
                for field in ('last_status','last_error','last_test_at','last_latency_ms'):
                    if field in value:
                        value[field] = 'PENDIENTE' if field == 'last_status' else None if field == 'last_latency_ms' else ''
                saved = backup/path.relative_to(root);saved.parent.mkdir(parents=True, exist_ok=True);saved.write_bytes(original)
                edited.append((path, original))
                path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            db.execute('DELETE FROM manual_validations WHERE result_id IN '
                       '(SELECT id FROM test_results WHERE provider=?)', (provider,))
            db.execute('DELETE FROM test_results WHERE provider=?', (provider,))
            db.execute("UPDATE games SET last_status='PENDIENTE', last_error='', last_test_at='', last_latency_ms=NULL WHERE provider=?", (provider,))
            db.commit()
        except Exception:
            db.rollback()
            for path, original in reversed(edited):
                path.write_bytes(original)
            for path, saved in reversed(moved):
                saved.rename(path)
            raise
    progress(f'Historial limpio. Copia local: {backup}')
    return backup


def _git(root, *args, timeout=120):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=timeout, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        detail = sanitize(result.stderr.strip() or result.stdout.strip())
        detail = re.sub(r'(https?://)[^/\s@]+@', r'\1[REDACTED]@', detail)
        raise RuntimeError(f'Git {args[0]}: {detail[:1600]}')
    return result.stdout.strip()


def repository_info(root):
    root = Path(root).resolve()
    if Path(_git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise RuntimeError('Abrí la aplicación desde la raíz del repositorio.')
    branch = _git(root, 'branch', '--show-current')
    if not branch:
        raise RuntimeError('Elegí una rama antes de publicar.')
    _git(root, 'remote', 'get-url', 'origin')
    return branch


def publish(root, kind, progress):
    root = Path(root).resolve()
    if kind not in {'program', 'reports'}:
        raise ValueError('Tipo de publicación inválido')
    branch = repository_info(root)
    if _git(root, 'diff', '--cached', '--name-only'):
        raise RuntimeError('Hay cambios preparados en Git. Confirmalos o retiralos del área de preparación antes de usar este botón.')
    if kind == 'reports':
        scopes = ['test-evidence']
    else:
        scopes = [p for p in CODE_DIRS+CODE_FILES if (root/p).exists() or _git(root, 'ls-files', '--', p)]
    if not scopes:
        raise RuntimeError('No hay archivos para publicar.')
    progress(f'Preparando {"programa" if kind == "program" else "reportes"} en la rama {branch}...')
    _git(root, 'add', '-A', '--', *scopes)
    if _git(root, 'diff', '--cached', '--name-only'):
        _git(root, 'commit', '-m', 'Actualiza programa y pruebas' if kind == 'program' else 'Actualiza reportes de pruebas')
        progress('Cambios guardados en un commit local.')
    else:
        progress('Sin cambios nuevos; comprobando el envío de commits pendientes.')
    progress('Subiendo a origin. Esto puede tardar...')
    _git(root, 'push', '-u', 'origin', branch, timeout=180)
    progress(f'Publicación completada: origin/{branch}')
    return branch
