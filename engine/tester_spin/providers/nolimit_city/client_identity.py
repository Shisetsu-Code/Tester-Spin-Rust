"""Validate public CDN identities without changing the published version."""
from __future__ import annotations

import re

from .errors import Unlearned


# The CDN publishes both release versions and labelled builds, using either
# a hyphen or a dot before the label. Keep every component path-safe.
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)*)?")
_SYMBOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def validate_client_info(info: object, requested_symbol: str) -> dict:
    """Return validated metadata; aliases and unobserved structures stay unknown."""
    if not isinstance(info, dict) or not isinstance(requested_symbol, str):
        raise Unlearned('Nolimit City: identidad o versión de cliente desconocida')
    version = info.get('version')
    if (
        not _SYMBOL.fullmatch(requested_symbol)
        or len(requested_symbol) > 128
        or info.get('name') != requested_symbol
        or not isinstance(version, str)
        or len(version) > 128
        or not _VERSION.fullmatch(version)
    ):
        raise Unlearned('Nolimit City: identidad o versión de cliente desconocida')
    return info
