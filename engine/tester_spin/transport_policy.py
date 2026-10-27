"""Universal execution policy; contracts remain owned by each provider.

Profiles describe implemented routes, never proof that a game or round is OK.
Unknown/new providers have no assumed executable protocol.
"""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class TransportPolicy:
    prefer_direct: bool = True
    retry_dispatched_wagers: bool = False
    reuse_har_credentials: bool = False
    browser_fallback_requires_contract: bool = True
    def may_fallback(self, *, dispatched: bool, bootstrap_only: bool, contract_supported: bool):
        return not dispatched and bootstrap_only and contract_supported

POLICY=TransportPolicy()
# Provider identifiers, never game names or purchase selectors.
_ROUTES={
 'pragmatic':('http','http','bootstrap-fallback'),
 '1spin4win':('http','websocket','bootstrap-fallback'),
 'belatra':('http','http','bootstrap-fallback'),
 'bgaming':('http','http','capture-only'),
 'ka_gaming':('http+websocket','websocket+http','none'),
 'rubyplay':('http','http','bootstrap-fallback'),
 'redtiger':('browser','http','bootstrap-required'),
 '3oaks':('http','http','challenged-login-fetch'),
 'yggdrasil':('http','http','none'),
 'hacksaw':('http','http','none'),
 'nolimit_city':('http','websocket','none'),
 'playtech':('http','websocket','none'),
 'pushgaming':('http','http','none'),
 'relax':('http','http','none'),
 'elk':('http','http','none'),
 'playson':('http','http','none'),
 'games_global':('http','http','none'),
 'playngo':('http','websocket','none'),
 'amusnet':('http','websocket','none'),
}

def execution_profile(provider, *, variant=None):
    route=_ROUTES.get(provider)
    if provider=='playtech' and variant=='ngm-offline':
        route=('browser','local-client-engine','local-engine-required')
    return {'schema':'tester-spin/transport-policy/v1', 'policy':asdict(POLICY),
        'contract_registered':route is not None,
        'bootstrap':route[0] if route else 'unimplemented',
        'gameplay':route[1] if route else 'unimplemented',
        'browser_requirement':route[2] if route else 'unknown',
        'scope':'provider-contract; actual fallback is recorded by the runtime'}
