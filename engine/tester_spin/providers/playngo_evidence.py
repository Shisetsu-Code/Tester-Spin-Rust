"""Conservative framing evidence observed in three official practice demos.

No requests, serializer, field semantics, paid inventory or settlement inferred.
"""
import hashlib


def inspect_frame(data: bytes, *, opcode: int) -> dict:
    if not isinstance(data, bytes) or opcode != 2 or not 7 <= len(data) <= 256:
        raise ValueError('UNSUPPORTED_GAMEHUB_FRAME')
    if data[0] != len(data) - 1:
        raise ValueError('UNSUPPORTED_GAMEHUB_LENGTH')
    label = next((name for name in (b'ProcessPacket', b'Commands') if data[6:].startswith(name)), None)
    if label is None:
        raise ValueError('UNSUPPORTED_GAMEHUB_COMMAND')
    return {'primitive': 'playngo.gamehub.observed-framing/v1',
            'command': label.decode('ascii'), 'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'action_semantics_verified': False, 'terminal': False,
            'paid_inventory_complete': False}
