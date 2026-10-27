"""Conservative framing evidence observed in three official practice demos.

No requests, serializer, field semantics, paid inventory or settlement inferred.
"""
import hashlib


def inspect_frame(data: bytes, *, opcode: int) -> dict:
    if not isinstance(data, bytes) or opcode != 2 or not 7 <= len(data) <= 256:
        raise ValueError('UNSUPPORTED_GAMEHUB_FRAME')
    # Reuse the observed framing parser, including multibyte length prefixes.
    # Parsing an invocation does not assign semantics to its numeric payload.
    from tester_spin.providers.playngo import decode_invocation
    decoded = decode_invocation(data)
    label = decoded.get('target')
    if label not in ('ProcessPacket', 'Commands'):
        raise ValueError('UNSUPPORTED_GAMEHUB_COMMAND')
    return {'primitive': 'playngo.gamehub.observed-framing/v1',
            'command': label, 'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'action_semantics_verified': False, 'terminal': False,
            'paid_inventory_complete': False}
