"""Conservative, provider-neutral mechanics evidence; absence is never inferred."""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA = "tester-spin/mechanics/v1"

def merge_mechanics(*records):
    items = {}
    for record in records:
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            continue
        raw_items = record.get("items", [])
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            key = item.get("id")
            if not isinstance(key, str) or not key or not all(isinstance(item.get(k), str) and item[k] for k in ("label", "source", "status")) or item["status"] not in {"confirmed", "indication"}:
                continue
            if key not in items or item["status"] == "confirmed":
                items[key] = {k: item[k] for k in ("id", "label", "status", "source")}
    return {"schema": SCHEMA, "items": sorted(items.values(), key=lambda x: x["id"])}

def classify_mechanics(payload):
    if not isinstance(payload, dict):
        return merge_mechanics()
    records = [payload.get("mechanics", {})]
    def add(key, label, status, source):
        records.append({"schema": SCHEMA, "items": [{"id": key, "label": label, "status": status, "source": source}]})
    modes = payload.get("discovered_modes", [])
    for mode in modes if isinstance(modes, list) else []:
        if not isinstance(mode, dict) or mode.get("observed") is not True:
            continue
        if isinstance(mode.get("kind"), str) and mode["kind"] in {"INDEXED_CHOICE", "FSO_BRANCH"}:
            add("choices", "Elecciones", "confirmed", "discovered_modes." + mode["kind"])
        if mode.get("coverage_scope") == "available_actions_not_all_repeat_counts":
            add("decision_ladder", "Escalera de decisiones", "confirmed", "discovered_modes.coverage_scope")
    stack = [(payload, "$", 0)]
    visited = 0
    while stack and visited < 12000:
        node, path, depth = stack.pop()
        visited += 1
        if depth > 24:
            continue
        if isinstance(node, dict):
            choice = node.get("choices")
            if isinstance(choice, dict) and "selected" in choice and isinstance(choice.get("available"), list) and choice["available"] and all(isinstance(x, str) and x for x in choice["available"]):
                add("choices", "Elecciones", "confirmed", path + ".choices.available")
            picker = node.get("picker")
            if isinstance(picker, dict) and isinstance(picker.get("options"), list) and picker["options"] and isinstance(picker.get("choices"), list) and picker["choices"]:
                if all(isinstance(x, dict) and isinstance(x.get("option"), int) and not isinstance(x.get("option"), bool) and 0 <= x["option"] < len(picker["options"]) for x in picker["choices"]):
                    add("choices", "Elecciones", "confirmed", path + ".picker")
            progress = node.get("progress")
            if isinstance(progress, dict) and any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in progress.values()):
                add("progress", "Progreso", "indication", path + ".progress")
            if isinstance(node.get("lockedTiles"), list) and node["lockedTiles"]:
                add("persistent_symbols", "Símbolos persistentes", "indication", path + ".lockedTiles")
            # Ignore our own metadata and requests: only response/state structure is evidence.
            stack.extend((v, path + "." + str(k), depth + 1) for k, v in node.items() if k not in {"mechanics", "request", "request_body"} and isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend((v, path + "[]", depth + 1) for v in node[:512] if isinstance(v, (dict, list)))
    return merge_mechanics(*records)

def mechanics_badge(record):
    items = merge_mechanics(record)["items"]
    confirmed = [x["label"] for x in items if x["status"] == "confirmed"]
    indications = [x["label"] for x in items if x["status"] == "indication"]
    return ("Sí — " + " / ".join(confirmed)) if confirmed else (("Indicio — " + " / ".join(indications)) if indications else "Sin datos")

def run_mechanics(payload):
    """Bounded local artifact inspection, to be called outside Tk's thread."""
    record = classify_mechanics(payload)
    if not isinstance(payload.get("run_dir", ""), str):
        return record
    root = Path(payload.get("run_dir") or "")
    if not payload.get("run_dir") or not root.is_dir():
        return record
    count = 0
    for path in root.rglob("*.json"):
        if count >= 80:
            break
        if not any(word in path.name.lower() for word in ("response", "summary", "return-to-base", "choice")):
            continue
        count += 1
        try:
            if path.stat().st_size > 512000:
                continue
            value = json.loads(path.read_text(encoding="utf-8"))
            found = classify_mechanics(value)
            for item in found["items"]:
                item["source"] = str(path.relative_to(root)) + ":" + item["source"]
            record = merge_mechanics(record, found)
        except (OSError, ValueError, RecursionError):
            continue
    return record
