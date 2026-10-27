"""Session purchase domains from explicit server and client declarations.

A missing ante API has no absence semantics until its active client binding is
proved. A buy-feature flag plus a uniquely resolved client type describes the
single buy_feature API already used by this adapter, not unobserved controls.
"""
import math
import re


def initialization_domains(data, modes, profile):
    source = 'init.buy_feature_configs+client.getBuyFeatureType'
    domains = {category: {'complete': False, 'source': source, 'options': [],
                         'reason': category.upper() + '_CLIENT_CONTRACT_UNRESOLVED'}
               for category in ('purchase', 'ante')}
    if not isinstance(profile, dict):
        profile = {}
    body = data.get('data')
    if data.get('status') != 'ok' or data.get('topic') != 'gameserver/init' or not isinstance(body, dict):
        return domains
    flag = body.get('buy_feature_available')
    if flag is False:
        if body.get('buy_feature_available_server') is True and not (
                profile.get('buy_feature_client_supported') is False
                and 'client.buy-feature.contract=absent' in profile.get('evidence', [])):
            return domains
        domains['purchase'] = {'complete': True, 'source': 'init.buy_feature_available/effective-client', 'options': []}
        return domains
    if flag is not True or profile.get('buy_feature_client_supported') is not True:
        return domains
    feature = profile.get('buy_feature_type')
    digest = profile.get('bundle_sha256')
    if (not isinstance(feature, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', feature)
            or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
            or not any(str(value).startswith('client.getBuyFeatureType->Action wrapper')
                       for value in profile.get('evidence', []))):
        return domains
    for key in ('wager', 'buy_feature_multiplier'):
        value = profile.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            return domains
    menu = body.get('buy_feature_configs')
    if not isinstance(menu, list) or len(menu) != 1 or not isinstance(menu[0], dict):
        return domains
    quote = menu[0].get('priceMultiplier')
    if (menu[0].get('buyFeatureType') != feature or not isinstance(quote, (int, float))
            or isinstance(quote, bool) or not math.isfinite(quote) or quote <= 0
            or quote != profile['buy_feature_multiplier']):
        return domains
    purchases = [mode for mode in modes if mode.get('kind') == 'PURCHASE']
    if len(purchases) != 1:
        return domains
    mode = purchases[0]
    if (not mode.get('id') or mode.get('executable') is not True
            or mode.get('wire_command') != 'buy_feature' or mode.get('buy_feature_type') != feature
            or mode.get('feature_multiplier') != profile['buy_feature_multiplier']):
        return domains
    domains['purchase'] = {'complete': True, 'source': source, 'options': [mode['id']],
                           'client_source_sha256': digest,
                           'evidence_files': ['bootstrap/paid-client-profile.json', 'bootstrap/init-response.json']}
    return domains
