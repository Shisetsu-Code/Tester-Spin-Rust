"""Passive Yggdrasil wire discovery; historical purchases never imply a spin."""
import re
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit

SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
COMMAND = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
PURCHASE = re.compile(r"(?:BB(?:_[A-Za-z0-9_-]+|[0-9]+)?|BUY(?:_[A-Za-z0-9_-]+|(?:MAX)?BONUS|[RS]FS)?|BONUSBUY[0-9]*|(?:MAX|SUPER)_BUY_(?:A_)?BONUS)\Z", re.I)
ANTE = re.compile(r"(?:GOLDENBET|GOLDEN_BET(?:_WILD)?)\Z", re.I)

def command_values(value):
    if value in (None,"",[],{}):return []
    if isinstance(value,str):return value.split(",")
    return value if isinstance(value,list) else [value]


def mode_kind(name):
    return "SPIN" if name=="BASIC" else "PURCHASE" if PURCHASE.fullmatch(name) else "ANTE_BET" if ANTE.fullmatch(name) else "UNKNOWN_FEATURE"

ENDPOINT = "https://demo.yggdrasilgaming.com/game.web/service?fn=play"


def play_records(har: dict) -> list[dict]:
    records = []
    for entry in har.get("log", {}).get("entries", []):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request", {})
        parsed = urlsplit(request.get("url", ""))
        host = (parsed.hostname or "").lower()
        if (request.get("method") != "POST" or parsed.scheme != "https"
                or host != "demo.yggdrasilgaming.com"
                or parsed.path.rstrip("/") != "/game.web/service"
                or parse_qs(parsed.query).get("fn") != ["play"]):
            continue
        post = request.get("postData", {})
        if not str(post.get("mimeType", "")).startswith("application/x-www-form-urlencoded"):
            continue
        values = parse_qs(str(post.get("text", "")), keep_blank_values=True)
        if not values and isinstance(post.get("params"), list):
            for item in post["params"]:
                values.setdefault(str(item.get("name", "")), []).append(str(item.get("value", "")))
        if any(len(value) != 1 for value in values.values()):
            continue
        body = {key: value[0] for key, value in values.items()}
        cmd, gameid = body.get("cmd", ""), body.get("gameid", "")
        if (cmd and not COMMAND.fullmatch(cmd)) or not gameid.isdecimal() or "amount" not in body:
            continue
        collect = (cmd == "C" and body["amount"] == "0"
                   and body.get("step", "").isdecimal() and body.get("betid", "").isdecimal())
        if not collect and "coin" not in body:
            continue
        if not cmd:
            try:
                amount = Decimal(body["amount"])
                coin = Decimal(body["coin"])
            except (InvalidOperation, KeyError):
                continue
            if (not amount.is_finite() or not coin.is_finite() or amount <= 0 or coin <= 0
                    or "step" in body or "wagerid" in body):
                continue
        response = entry.get("response", {})
        next_commands, terminal, pending_commands = [], False, False
        try:
            value = json.loads(response.get("content", {}).get("text", ""))
            data = value.get("data") if isinstance(value, dict) else None
            wager = data.get("wager") if isinstance(data, dict) else None
            if isinstance(wager, dict) and value.get("code") == 0 and response.get("status") == 200:
                bets = wager.get("bets")
                if isinstance(bets, list):
                    for bet in bets:
                        if not isinstance(bet, dict):
                            continue
                        betdata, event = bet.get("betdata"), bet.get("eventdata")
                        candidates = (betdata.get("cmds", []) if isinstance(betdata, dict) else [])
                        candidates = list(candidates) if isinstance(candidates, list) else []
                        if isinstance(event, dict):
                            nxt = event.get("nextCmds")
                            candidates.extend(command_values(nxt))
                        pending_commands = pending_commands or any(candidate not in (None, "", [], {}) for candidate in candidates)
                        for candidate in candidates:
                            if isinstance(candidate, str) and COMMAND.fullmatch(candidate) and candidate not in next_commands:
                                next_commands.append(candidate)
                    terminal = (wager.get("status") == "Finished" and bool(bets)
                                and all(isinstance(bet, dict) and bet.get("status") == "RESULTED" for bet in bets)
                                and not pending_commands)
        except (ValueError, TypeError, AttributeError):
            pass
        # Allowlist only: no session identifiers, clientinfo, balances or raw responses.
        records.append({"gameid": gameid, "cmd": cmd, "amount": body["amount"],
                        "coin": body.get("coin", ""), "http_status": response.get("status"),
                        "endpoint": ENDPOINT, "next_commands": next_commands,
                        "terminal_captured": terminal, "collect": collect})

    return records


def discovered_modes(records: list[dict], gameid: str) -> list[dict]:
    modes = [{"id": "SPIN", "kind": "SPIN", "validated": False, "executable": False,
              "coverage_required": True, "required_options": ["DOMAIN_UNRESOLVED"],
              "covered_options": [], "reason": "BASE_COMMAND_AND_TERMINAL_CAPTURE_REQUIRED"}]
    seen = set()
    for record in records:
        if not gameid or record["gameid"] != gameid or record["cmd"] in seen or not record["cmd"]:
            continue
        cmd = record["cmd"]
        seen.add(cmd)
        purchase = bool(PURCHASE.fullmatch(cmd))
        modes.append({"id": cmd, "kind": "PURCHASE" if purchase else "CONTINUATION" if record.get("collect") else "UNKNOWN_FEATURE",
            "wire_command": cmd, "observed": True, "validated": False, "executable": False,
            "evidence_level": "WIRE_CAPTURE", "coverage_required": not record.get("collect", False),
            "required_options": [cmd], "covered_options": [],
            "request_shape": {"cmd": cmd, "gameid": "<dynamic:gameid>",
                              "amount": "<dynamic:amount>", "coin": "<dynamic:coin>"},
            "observed_amount": record["amount"], "observed_coin": record["coin"],
            "terminal_captured": any(r.get("terminal_captured") for r in records if r.get("gameid") == gameid and r.get("cmd") == cmd),
            "reason": "LIVE_EXECUTOR_REQUIRED" if record.get("collect") else "BOOTSTRAP_AND_TERMINAL_CAPTURE_REQUIRED"})
    base = [r for r in records if r.get("gameid") == gameid and r.get("cmd") == ""]
    if base:
        modes[0].update(observed=True, evidence_level="WIRE_CAPTURE",
                        base_command_omitted=True,
                        terminal_captured=any(r.get("terminal_captured") for r in base),
                        reason="LIVE_BASE_EXECUTOR_REQUIRED")
    return modes


def declared_modes(available: dict, records: list[dict], gameid: str) -> list[dict]:
    """The server domain sets expected options; captures supply wire evidence only."""
    observed = {m['id']: m for m in discovered_modes(records, gameid)}
    modes = [observed['SPIN']]
    modes[0].update(source='server.game.cfg.Modes', observed='BASIC' in available)
    for command in available:
        if command == 'BASIC':
            continue
        if not isinstance(command, str) or not COMMAND.fullmatch(command):
            command = 'UNSUPPORTED_MODE'
        purchase = bool(PURCHASE.fullmatch(command))
        mode = dict(observed.get(command) or {})
        mode.update(id=command, kind='PURCHASE' if purchase else 'UNKNOWN_FEATURE',
                    source='server.game.cfg.Modes', evidence_level='SERVER_ADVERTISED',
                    declared=True, executable=False, validated=False, coverage_required=True,
                    required_options=[command], covered_options=[], reason='LIVE_EXECUTOR_REQUIRED')
        modes.append(mode)
    return modes


def game_declarations(har: dict) -> list[dict]:
    declarations = []
    for entry in har.get('log', {}).get('entries', []):
        request, response = entry.get('request', {}), entry.get('response', {})
        parsed = urlsplit(request.get('url', ''))
        if (parsed.scheme != 'https' or parsed.hostname != 'demo.yggdrasilgaming.com'
                or parsed.path != '/game.web/service' or parse_qs(parsed.query).get('fn') != ['game']
                or response.get('status') != 200):
            continue
        try:
            payload = json.loads(response.get('content', {}).get('text', ''))
            data = payload.get('data')
            if payload.get('code') != 0 or not isinstance(data, dict):
                continue
            gameid = str(data.get('gameid') or data.get('gameId') or '')
            cfg = data.get('cfg') or {}
            props = cfg.get('props', [])
            values = [prop.get('value') for prop in props if isinstance(prop, dict) and prop.get('prop') == 'Modes']
            if len(values) != 1 or not gameid.isdecimal():
                continue
            value = json.loads(values[0]) if isinstance(values[0], str) else values[0]
            if (not isinstance(value, dict) or 'BASIC' not in value
                    or not all(isinstance(k, str) and COMMAND.fullmatch(k) and isinstance(v, dict) for k, v in value.items())):
                continue
            declarations.append({'gameid': gameid, 'modes': value})
        except (ValueError, TypeError, AttributeError):
            continue
    return declarations
