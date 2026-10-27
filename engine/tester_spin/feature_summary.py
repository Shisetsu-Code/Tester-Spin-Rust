"""Display discovered features consistently across providers without playing games."""
from __future__ import annotations


def _feature_summary(result: dict, *, counts_only=False):
    modes = [m for m in result.get('discovered_modes', []) if isinstance(m, dict)]
    purchases = set()
    antebets = set()
    uncertain = set()
    domains = result.get("feature_domains") or {}
    complete = set()
    declared = {}
    for category in ("purchase", "ante"):
        domain = domains.get(category) if isinstance(domains, dict) else None
        if (isinstance(domain, dict) and domain.get("complete") is True
                and isinstance(domain.get("source"), str) and domain["source"].strip()
                and isinstance(domain.get("options"), list)
                and all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in domain["options"])):
            complete.add(category)
            declared[category] = {str(v) for v in domain["options"]}
    for mode in modes:
        mid = str(mode.get('id') or '')
        kind = str(mode.get('kind') or '').upper()
        if kind == 'SPIN' and mode.get('spin_validated') is False:
            continue
        if kind == 'UNKNOWN_FEATURE':
            # These provider declarations expose a feature whose entry contract
            # is not known yet. They cannot prove that the feature is absent.
            if mid == 'AVAILABLE_BOOSTERS':
                uncertain.add('ante')
            elif mid.startswith(('BUY_', 'PURCHASE_', 'AVAILABLE_BUY_')):
                uncertain.add('purchase')
            else:
                uncertain.update(('purchase', 'ante'))
            continue
        belatra_vip = (result.get('provider') == 'belatra'
                       and mid == 'BELATRA_START_SELECTOR_MATRIX'
                       and any(isinstance(dimension, dict)
                               and dimension.get('field') == 'vipOn'
                               and 0 in dimension.get('values', [])
                               and 1 in dimension.get('values', [])
                               for dimension in mode.get('dimensions', [])))
        # Coverage paths inside a bonus are not new entry purchases/wagers.
        if (kind in {'CHOICE_BRANCH', 'CONTINUATION', 'FEATURE'} and not belatra_vip) or mode.get('origin_mode_id'):
            continue
        if mode.get('enabled') is False:
            continue
        is_ante = belatra_vip or kind.startswith('ANTE_BET') or mid.upper().startswith('ANTE_BET')
        # BGaming transports chance wagers via purchased_feature too, but they
        # increase the chance on a regular spin rather than buy the bonus.
        if result.get('provider') == 'bgaming':
            request = mode.get('request') or {}
            feature = str(request.get('purchased_feature') or mode.get('purchase_name') or mid).upper()
            is_ante = is_ante or 'CHANCE' in feature.split('_')
        category = ('ante' if is_ante else 'purchase'
                    if kind in {'PURCHASE', 'PURCHASE_BRANCH'} or
                    (kind in {'', 'DISCOVERED_ONLY', 'UNRESOLVED'} and
                     mid.upper().startswith(('PURCHASE_', 'BUY_BONUS'))) else '')
        # Red Tiger settings expose backend buy contracts even when the
        # client offers no purchase button. Historic observed=True meant
        # server metadata, so only explicit client evidence confirms a buy.
        if (result.get('provider') == 'redtiger' and category == 'purchase'
                and mode.get('client_observed') is not True and mode.get('server_declared') is not True):
            uncertain.add('purchase')
            continue
        client_purchase = (result.get('provider') == '3oaks' and category == 'purchase'
                           and mode.get('client_observed') is True)
        if ((mode.get('observed') is False and not client_purchase) or kind == 'DISCOVERED_ONLY'
                or 'UNRESOLVED' in kind
                or (mode.get('evidence_level') == 'SERVER_ADVERTISED'
                    and mode.get('client_observed') is False)):
            if category and category not in complete:
                uncertain.add(category)
            continue
        if mode.get('discovery_state') in {'DISCOVERED_LITERAL_ONLY', 'BASE_CONTRACT_UNRESOLVED'}:
            if category:
                uncertain.add(category)
            continue
        if category == 'purchase':
            options = mode.get('required_options') if kind == 'PURCHASE_BRANCH' else None
            purchases.update((mid, str(option)) for option in options) if options else purchases.add((mid, ''))
        elif category == 'ante':
            antebets.add(mid)
    if counts_only:
        def amount(values, category):
            if category in complete and category not in uncertain:
                return len(declared[category])
            return len(values) if values else None
        return amount(purchases, 'purchase'), amount(antebets, 'ante')
    def label(values, category):
        if declared.get(category) or values:
            return 'Sí'
        return 'No' if category in complete and category not in uncertain else 'Sin datos'
    if 'purchase' in complete and 'purchase' not in uncertain:
        count = str(len(declared['purchase']))
    elif purchases:
        count = f'{len(purchases)} detectadas; total sin confirmar'
    else:
        count = 'Sin datos'
    summary = f"Compras: {label(purchases, 'purchase')} | Cantidad: {count} | Antebets: {label(antebets, 'ante')}"
    if result.get('provider') in {'hacksaw','nolimit_city'}:
        domain = domains.get('feature_spin') if isinstance(domains, dict) else None
        if isinstance(domain, dict) and domain.get('complete') is True and isinstance(domain.get('options'), list):
            label="Apuestas mejoradas" if result.get("provider")=="nolimit_city" else "FeatureSpins"
            summary += f" | {label}: {len(set(map(str, domain['options'])))}"
    return summary



def provider_summary_lines(rows: list[dict]) -> list[str]:
    lines = ['RESUMEN POR PROVEEDOR', 'Cantidad = opciones de compra detectadas por juego.']
    for provider in sorted({str(row.get('provider') or 'Sin proveedor') for row in rows}):
        lines += ['', provider]
        games = [row for row in rows if str(row.get('provider') or 'Sin proveedor') == provider]
        for row in sorted(games, key=lambda r: str(r.get('game_name') or r.get('slug') or '').casefold()):
            name = ' '.join(str(row.get('game_name') or row.get('slug') or 'Sin nombre').split())
            lines.append(f'- {name}: {feature_summary(row)}')
    return lines


def feature_summary(result: dict) -> str:
    return _feature_summary(result)


def feature_table_counts(result: dict) -> tuple[int | None, int | None]:
    """Numeric options using the same evidence as reports; None is unknown."""
    return _feature_summary(result, counts_only=True)
