"""Client-certified manual reel selections; never infer a choice from rs=mc alone."""
from __future__ import annotations

import hashlib
import html
import re
from typing import Any
from urllib.parse import urljoin, urlparse

_SCHEMA = 'pragmatic/manual-reel-selection/v1'
_MAX_SOURCE_BYTES = 12 * 1024 * 1024
_MAX_REELS = 12  # Bound materialized coverage domains; larger clients need review.


def _method(source: str, owner: str, name: str) -> str | None:
    match = re.search(re.escape(owner) + r'\.prototype\.' + re.escape(name)
                      + r'=function\([^)]*\)\{(.{0,12000}?)\};', source, re.S)
    return match.group(1) if match else None


def certify_reel_contract(js_text: str, source_url: str = '') -> dict[str, Any] | None:
    """Certify the observed parse -> independent bit toggle -> request mapping.

    Matching a game name or merely finding an ``ind`` literal is insufficient.
    Unrecognized/minifier-changed code returns None, requiring another contract.
    """
    compact = re.sub(r'\s+', '', js_text)
    # Start only at identifier boundaries. Retrying at every character of a
    # long minified token caused quadratic scans while holding Python's GIL.
    for owner in re.findall(r'(?<![\w$])([A-Za-z_$][\w$]*)\.prototype\.UpdateSpinRequest=function', compact):
        send = _method(compact, owner, 'UpdateSpinRequest')
        parse = _method(compact, owner, 'HandleResponse')
        toggle = _method(compact, owner, 'ChangeReelStatus')
        locked = _method(compact, owner, 'UpdateLockedReelsStatus')
        constructor = re.search(r'function' + re.escape(owner) + r'\(\)\{([^{}]{0,5000})\}', compact)
        if not all((send, parse, toggle, locked, constructor)):
            continue
        wire = re.search(r'([\w$]+)\.dict\[["\']([\w$]+)["\']\]=this\.([\w$]+)\.toString\(\)', send)
        trail = re.search(r'data\[this\.([\w$]+)\]\.split\(["\'];["\']\)', parse)
        status = re.search(r'([\w$]+)\[0\]==this\.([\w$]+)\)this\.([\w$]+)=_number\.otoi\(\1\[1\]\)', parse)
        bit = re.search(r'var([\w$]+)=1<<this\.rm\.reels\.length-\(([\w$]+)\+1\)', toggle)
        if not all((wire, trail, status, bit)):
            continue
        extra, wire_field, state_property = wire.groups()
        if status.group(3) != state_property:
            continue
        if f'this.{state_property}^={bit.group(1)}' not in toggle:
            continue
        if f'XT.SetObject(Vars.ToServer_RequestExtraParams,{extra})' not in send:
            continue
        if 'if(this.isRespin)' not in send or '!this.respinData.IsDone' not in parse:
            continue
        if '.split("~")' not in parse and ".split('~')" not in parse:
            continue
        if f'&this.{state_property})!=0' not in locked:
            continue
        ctor = constructor.group(1)
        trail_value = re.search(r'this\.' + re.escape(trail.group(1)) + r'=["\']([^"\']+)["\']', ctor)
        status_value = re.search(r'this\.' + re.escape(status.group(2)) + r'=["\']([^"\']+)["\']', ctor)
        if not trail_value or not status_value:
            continue
        return {
            'schema': _SCHEMA,
            'client_class': owner,
            'trail_key': trail_value.group(1),
            'status_key': status_value.group(1),
            'wire_field': wire_field,
            'source_url': source_url,
            'source_sha256': hashlib.sha256(js_text.encode('utf-8')).hexdigest(),
            'bit_order': 'leftmost reel is highest bit; 1=spin, 0=hold',
            'domain_basis': 'each reel is independently toggled with XOR; all width-bit masks are client-reachable',
            'evidence': {'constructor': ctor, 'parse': parse, 'toggle': toggle, 'send': send, 'locked': locked},
        }
    return None


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)):
        raise ValueError(f'Invalid manual reel {field}: expected a nonnegative integer')
    return int(value)


def reel_selection(response: dict[str, Any], contract: dict[str, Any] | None,
                   override: int | str | None = None) -> dict[str, Any] | None:
    """Return request fields and coverage metadata for an active certified choice.

    Domain describes client-reachable selections, not server-verified coverage.
    Missing/invalid sr on an applicable response fails closed instead of sending
    a malformed continuation. rs_t denotes a completed respin, including zero.
    """
    if str(response.get('rs', '')) != 'mc' or 'rs_t' in response:
        return None
    if contract is None:
        return None
    if contract.get('schema') != _SCHEMA:
        raise ValueError('Uncertified manual reel contract')
    width = _integer(response.get('sw'), 'width')
    if not 1 <= width <= _MAX_REELS:
        raise ValueError(f'Manual reel width outside supported coverage bound 1..{_MAX_REELS}')
    parts = str(response.get(contract['trail_key'], '')).split(';')
    matches = [part.split('~', 1)[1] for part in parts
               if '~' in part and part.split('~', 1)[0] == contract['status_key']]
    if len(matches) != 1:
        raise ValueError('Active manual reel response has missing or ambiguous default mask')
    default = _integer(matches[0], 'default mask')
    selected = default if override is None else _integer(override, 'override mask')
    limit = 1 << width
    if default >= limit or selected >= limit:
        raise ValueError('Manual reel mask exceeds server reel width')
    return {
        'fields': {contract['wire_field']: str(selected)},
        'default': str(default),
        'selected': str(selected),
        'domain': [str(value) for value in range(limit)],
        'width': width,
        'branch_signature': f"PRAGMATIC:manual-reels:{contract['trail_key']}:{contract['status_key']}:{contract['wire_field']}:width={width}",
        'domain_basis': contract['domain_basis'],
        'contract_source': contract['source_url'],
        'contract_sha256': contract['source_sha256'],
    }


def discover_client_source(session: Any, launch_html: str, launch_url: str,
                           timeout_s: float = 20.0):
    """Follow the observed desktop loader and its revision-pinned build reference.

    Makes at most two reads. No fallback routes or guessed game identifiers.
    The caller may cache the result by launch datapath/build revision.
    """
    page = html.unescape(launch_html).replace('\\/', '/')
    datapath = re.search(r'["\']datapath["\']\s*:\s*["\']([^"\']+)["\']', page)
    loader = re.search(r'UHT_CONFIG\.GAME_URL\s*\+\s*["\'](bootstrap\.js)["\']\s*\+\s*["\']\?key=["\']\s*\+\s*["\']([^"\']+)["\']', page)
    if not datapath or not loader:
        return None
    base = urljoin(launch_url, datapath.group(1))
    flags = re.findall(r'UHT_ALL\s*=\s*(true|false)', page)
    if flags and flags[-1] == 'true':
        compact = re.sub(r'\s+', '', page)
        if 'UHT_CONFIG.GAME_URL+=(UHT_CONFIG.MINI_MODE?"mini":UHT_DEVICE_TYPE.MOBILE?"mobile":"desktop")+"/"' not in compact:
            return None
        base = urljoin(base.rstrip('/') + '/', 'desktop/')
    if urlparse(base).scheme not in {'https', 'http'}:
        return None
    def read(url: str) -> tuple[str, str]:
        response = session.get(url, timeout=timeout_s)
        response.raise_for_status()
        if len(response.content) > _MAX_SOURCE_BYTES:
            raise ValueError('Official reel contract source exceeds size bound')
        return response.text, str(response.url)
    bootstrap_url = urljoin(base, loader.group(1)) + '?key=' + loader.group(2)
    bootstrap, _ = read(bootstrap_url)
    scripts = re.search(r'UHT_SCRIPTS_SIZE\s*=\s*["\']([^"\']+)["\']', bootstrap)
    if not scripts:
        return None
    refs = [entry.rsplit(':', 1)[0] for entry in scripts.group(1).split(',') if entry]
    builds = [ref for ref in refs if urlparse(ref).path == 'build.js']
    if len(builds) != 1:
        return None
    source, source_url = read(urljoin(base, builds[0]))
    return source, source_url, {'datapath':datapath.group(1),'bootstrap_url':bootstrap_url}


def discover_reel_contract(session: Any, launch_html: str, launch_url: str,
                           timeout_s: float = 20.0) -> dict[str, Any] | None:
    observed=discover_client_source(session,launch_html,launch_url,timeout_s)
    if observed is None:return None
    source,source_url,metadata=observed
    contract = certify_reel_contract(source, source_url)
    if contract is not None:
        contract.update(metadata)
    return contract

