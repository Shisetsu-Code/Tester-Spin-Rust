"""Offline, paired API-v2 capture evidence; never a title-specific protocol rule."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from tester_spin.providers.bgaming.runtime import balance_total, infer_observed_debit


def load_api_capture(path: Path | None, identifier: str) -> dict[str, Any]:
    result: dict[str, Any] = {"mode_multipliers": {}, "purchase_costs": {}, "command_options": {}, "source": str(path or "")}
    if path is None:
        return result
    try:
        entries = json.loads(path.read_text(encoding="utf-8-sig"))["log"]["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        return result
    previous: dict[str, float | None] = {}
    for entry in entries:
        url = ""
        try:
            request, response = entry["request"], entry["response"]
            url = request["url"]
            parts = urlparse(url).path.strip("/").split("/")
            if request.get("method") != "POST" or not 200 <= int(response["status"]) < 300:
                previous.pop(url, None)
                continue
            if len(parts) < 2 or parts[0] != "api" or parts[1].casefold() != identifier.casefold():
                continue
            sent = json.loads(request["postData"]["text"])
            content = response["content"]
            text = content["text"]
            if content.get("encoding") == "base64":
                text = base64.b64decode(text).decode("utf-8")
            received = json.loads(text)
            command = sent.get("command")
            flow = received.get("flow", {})
            if received.get("errors") or received.get("error") or flow.get("command") != command:
                previous.pop(url, None)
                continue
            options = sent.get("options", {})
            outcome = received.get("outcome") or {}
            base_bet = options.get("bet")
            if command == "spin" and isinstance(base_bet, (int, float)) and base_bet > 0:
                mode = options.get("mode")
                effective_bet = outcome.get("bet")
                if isinstance(mode, (str, int)) and isinstance(effective_bet, (int, float)) and effective_bet > 0:
                    key = str(mode)
                    ratio = float(effective_bet) / base_bet
                    result["mode_multipliers"][key] = ratio
                    feature = options.get("purchased_feature")
                    debit = infer_observed_debit(received, previous.get(url))
                    if isinstance(feature, str) and debit is not None and debit > 0:
                        result["purchase_costs"].setdefault(feature, {})[key] = debit / base_bet
            elif command == "respin" and set(options) == {"bet"} and isinstance(base_bet, (int, float)) and base_bet > 0:
                result["command_options"][command] = {"bet": "$base_bet"}
            previous[url] = balance_total(received)
        except (ValueError, TypeError, KeyError, AttributeError):
            previous.pop(url, None)
            continue
    return result


def expand_api_modes(specs: list[dict[str, Any]], capture: dict[str, Any]) -> list[dict[str, Any]]:
    modes = capture.get("mode_multipliers", {})
    if not modes:
        return specs
    expanded = []
    for spec in specs:
        for mode in sorted(modes, key=lambda value: (len(value), value)):
            item = dict(spec)
            purchase = spec.get("purchase")
            item["purchase"] = dict(purchase) if isinstance(purchase, dict) else None
            cost = capture.get("purchase_costs", {}).get((purchase or {}).get("name"), {}).get(mode)
            item.update(id=f"{spec['id']}_MODE_{mode}", options={"mode": mode}, origin_mode_id=spec["id"], captured_cost_per_base_bet=cost, source=capture.get("source"), discovery_state="CAPTURE_OBSERVED" if not purchase or cost is not None else "CAPTURE_SERIALIZER_CANDIDATE")
            if purchase and cost is None:
                item["purchase"]["cost_multiplier"] = None
            expanded.append(item)
    return expanded
