"""Persist progress before gameplay starts, including failures before a result exists."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tester_spin.models import Game
from tester_spin.run_diagnostics import sanitize


class RunJournal:
    def __init__(self, game_root: Path | None, game: Game) -> None:
        self.started = time.monotonic()
        self.path: Path | None = None
        self.lock = threading.Lock()
        if game_root is not None:
            folder = Path(game_root)/'diagnostics'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid4().hex[:12])
            folder.mkdir(parents=True, exist_ok=True)
            self.path = folder/'events.jsonl'
            self.note('START', {'provider': game.provider, 'slug': game.slug, 'name': game.name})

    def note(self, stage: str, detail) -> None:
        if self.path is None:
            return
        record = sanitize({'timestamp': datetime.now(timezone.utc).isoformat(),
                           'elapsed_ms': round((time.monotonic()-self.started)*1000, 3),
                           'stage': stage, 'detail': detail})
        with self.lock, self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False)+'\n')
