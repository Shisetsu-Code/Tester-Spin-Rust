"""Plain-language review list from saved results; no gameplay requests."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from tester_spin.feature_summary import provider_summary_lines


def _read(root, name):
    try:
        value = json.loads((root / name).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _advertised_only(mode):
    return (mode.get('evidence_level') == 'SERVER_ADVERTISED'
            and mode.get('client_observed') is False
            and mode.get('executable') is False
            and mode.get('coverage_required') is False)


def _coverage_missing(mode):
    if mode.get('coverage_required') is not True:
        return False
    required = set(map(str, mode.get('required_options', [])))
    if required - set(map(str, mode.get('covered_options', []))):
        return True
    counts = mode.get('sample_counts')
    target = max(1, int(mode.get('required_samples') or 1))
    return isinstance(counts, dict) and any(int(counts.get(x, 0)) < target for x in required)


def _completed_attempts(attempts, trajectories):
    if not attempts or len(attempts) != len(trajectories):
        return False
    by_number = {(p.get('attempt'), (p.get('origin') or {}).get('mode_id', '')): p for p in trajectories}
    if len(by_number) != len(trajectories):
        return False
    for attempt in attempts:
        path = by_number.get((attempt.get('number'), attempt.get('mode_id', '')), {})
        proof = path.get('return_to_base') or {}
        if (not attempt.get('ok') or not attempt.get('terminal') or attempt.get('error') or attempt.get('warning')
                or not path.get('reported_ok') or not path.get('reported_terminal') or path.get('gaps')
                or proof.get('status') != 'CONFIRMED' or proof.get('consecutive_base', 0) < 2
                or proof.get('connection_reused') is not True):
            return False
    return True


def review_item(result):
    if (result.get('manual_validation') or {}).get('status') == 'OK MANUAL':
        return None
    root = Path(result['run_dir']) if result.get('run_dir') else None
    observations = _read(root, 'server-observations.json') if root else {}
    tree = _read(root, 'run-tree.json') if root else {}
    attempts = result.get('attempts', [])
    modes = result.get('discovered_modes', [])
    details = ' '.join([str(result.get('error', ''))] + [str(a.get(k, '')) for a in attempts for k in ('error', 'warning')]).lower()
    reasons = []
    def add(reason, action):
        if (reason, action) not in reasons:
            reasons.append((reason, action))
    if not observations or not tree:
        add('Faltan registros para revisar esta prueba.', 'Repetir la prueba para completar el diagnóstico antes de preparar un HAR.')
    failed_modes = {str(a.get('mode_id', '')) for a in attempts if not a.get('ok') or not a.get('terminal') or a.get('error') or a.get('warning')}
    advertised = [m for m in modes if _advertised_only(m) and m.get('id') not in failed_modes]
    pending = [m for m in modes if m not in advertised and (m.get('executable') is False or m.get('observed') is False or 'UNRESOLVED' in str(m.get('kind', '')) or m.get('id') in failed_modes or _coverage_missing(m))]
    availability_reason = ('El servidor menciona funciones cuya disponibilidad en el juego no está confirmada.',
                           'Comprobar si aparecen en el menú. Si no aparecen, indicar que no están disponibles; no hace falta buscar otra compra dentro del bonus.')
    if advertised:
        add(*availability_reason)
    if any('PURCHASE' in str(m.get('id', '')) or 'BUY' in str(m.get('id', '')) for m in pending) or ('compras anunciadas' in details and not advertised) or ('cobertura' in details and 'purchase_' in details and not advertised):
        add('Hay compras o apuestas especiales pendientes.', 'Capturar cada compra y opción de apuesta especial disponible, incluida su finalización.')
    if 'contract_unresolved' in details or 'wire-shape de play' in details:
        add('Falta registrar cómo se hace la tirada normal.', 'Capturar la apertura del juego y dos tiradas normales.')
    if any(word in details for word in ('play_bonus', 'buy_extra_bonus', 'select_bonus', 'gamble', 'elecciones de flujo', 'todoubledialog')):
        add('Quedaron elecciones dentro del bonus sin completar.', 'Capturar el bonus y las opciones que ofrece; indicar cuál elegiste.')
    if 'bet devuelta' in details or 'balance inconsistente' in details or 'débito' in details:
        add('La apuesta o el saldo no coincide con lo esperado.', 'Capturar una tirada normal e indicar la apuesta mostrada y el saldo antes y después.')
    if any(word in details for word in ('httperror', 'http 4', 'http 5', 'rpc error', 'rpcerror')):
        add('El servidor rechazó una solicitud.', 'Repetir en el navegador la acción que falló y capturar su respuesta.')
    trajectories = tree.get('trajectories', [])
    if any(p.get('return_to_base') and p['return_to_base'].get('status') != 'CONFIRMED' for p in trajectories) or 'regreso al juego base pendiente' in details:
        add('No se confirmó el regreso al juego normal.', 'Completar el evento y continuar hasta lograr dos tiradas normales seguidas en la misma sesión.')
    completed = _completed_attempts(attempts, trajectories)
    # Novelty remains in technical evidence; completing its trajectory with two
    # normal rounds means it is not, by itself, an unfinished player action.
    if observations.get('unparsed') or (not completed and any(o.get('review_required') for o in observations.get('observations', []))):
        add('Hay una respuesta distinta que debemos revisar.', 'Indicar qué apareció en pantalla y capturar cómo continuó el juego.')
    if result.get('status') == 'CANCELADO':
        add('La prueba se interrumpió.', 'Repetir la prueba antes de preparar un HAR.')
    if not reasons and (result.get('status') != 'OK' or pending or any(p.get('gaps') for p in trajectories)):
        add('La prueba quedó incompleta.', 'Capturar la acción pendiente y cómo se completa en el navegador.')
    if not reasons:
        return None
    only_availability = (reasons == [availability_reason] and completed and not pending and not failed_modes
        and result.get('status') not in {'ERROR', 'CANCELADO'}
        and not re.sub(r'BGaming compras anunciadas sin wire cliente demostrado: [^.]*\.', '', str(result.get('error') or '')).strip())
    if reasons == [availability_reason] and not only_availability:
        add('La prueba tiene otra condición pendiente.', 'Revisar su diagnóstico antes de darla por completada.')
    labels = {'SPIN': 'tirada normal', 'PURCHASE_FREESPIN_BUY': 'compra de tiradas gratis',
              'PURCHASE_BONUS_BUY': 'compra de bonus', 'PURCHASE_BUY_BONUS': 'compra de bonus',
              'PURCHASE_FREESPIN_CHANCE': 'apuesta con mayor probabilidad de tiradas gratis',
              'PURCHASE_BONUS_CHANCE': 'apuesta con mayor probabilidad de bonus',
              'PURCHASE_FREESPIN_AND_BONUS_CHANCE': 'apuesta con mayor probabilidad de bonus y tiradas gratis'}
    actions = []
    for mid in sorted(failed_modes | {str(m.get('id', '')) for m in pending}):
        origin, _, selector = mid.partition('_MODE_')
        base, _, level = origin.partition('_LEVEL_')
        label = labels.get(base)
        if label:
            if level:
                label += f' (variante {level})'
            if selector:
                label += f' (modo {selector})'
            if label not in actions:
                actions.append(label)
    return {'name': ' '.join(result.get('game_name', result.get('slug', '')).split()),
            'provider': result.get('provider', ''), 'reasons': reasons, 'actions': actions,
            'category': 'availability' if only_availability else 'manual'}


def render_review(results, *, expected_count=None):
    rows = [r.to_dict() if hasattr(r, 'to_dict') else r for r in results]
    items = [item for row in rows if (item := review_item(row))]
    availability = [item for item in items if item['category'] == 'availability']
    items = [item for item in items if item['category'] != 'availability']
    items.sort(key=lambda item: (item['provider'], item['name'].casefold()))
    lines = provider_summary_lines(rows) + ['', 'JUEGOS PARA REVISAR MANUALMENTE', '', f'{len(items)} juegos para revisar de {len(rows)} con resultado.']
    approved = [r for r in rows if (r.get('manual_validation') or {}).get('status') == 'OK MANUAL']
    if approved:
        lines += ['', 'OK MANUAL']
        for row in approved:
            mark = row['manual_validation']
            lines.append(f"- {row.get('game_name', row.get('slug', ''))} ({row.get('provider', '')}) — {mark.get('approved_at', '')}: {mark.get('note') or 'Revisado manualmente'}")
        lines.append('')
    missing = max(0, (expected_count if expected_count is not None else len(rows)) - len(rows))
    if missing:
        lines.append(f'{missing} juegos sin resultado; falta ejecutarlos.')
    if not items:
        lines.append('No hay acciones fallidas o incompletas que requieran revisión en este listado.')
    else:
        lines += ['', 'Para el HAR: iniciar la captura antes de abrir el juego. Completar el evento y hacer dos tiradas normales seguidas sin cerrar la sesión.']
    for index, item in enumerate(items, 1):
        lines += ['', f"{index}. {item['name']} ({item['provider']})"]
        if item['actions']:
            lines.append('   Revisar: ' + '; '.join(item['actions']) + '.')
        for reason, action in item['reasons']:
            lines.append(f'   {reason} {action}')
    if availability:
        lines += ['', 'DISPONIBILIDAD SIN CONFIRMAR', '',
                  f'{len(availability)} juegos con funciones mencionadas por el servidor, sin confirmar que estén disponibles en su menú.',
                  'No significa que queden compras dentro de una tirada. Si ya verificaste que no aparecen, no hace falta repetir las tiradas.']
        for item in sorted(availability, key=lambda item: (item['provider'], item['name'].casefold())):
            lines.append(f"- {item['name']} ({item['provider']})")
    lines += ['', 'Las respuestas distintas de recorridos completados permanecen en el diagnóstico técnico; por sí solas no se presentan como acciones pendientes.']
    return '\n'.join(lines) + '\n'


def write_review(results, directory, *, expected_count=None, baseline=None):
    results = list(results)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '-' + uuid4().hex[:8] + '-revision-manual.txt')
    from tester_spin.failure_groups import write_report
    grouped = write_report(results, path, baseline=baseline, expected_count=expected_count)
    path.write_text(render_review(results, expected_count=expected_count) + '\nGrupos y prioridades: ' + str(grouped['markdown']) + '\nSelección para reintento: ' + str(grouped['json']) + '\n', encoding='utf-8')
    return path
