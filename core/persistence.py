import json
import os
import tempfile
from datetime import datetime, timezone

_PERSISTENCE_HEALTH_EVENTS = []


def _atomic_write_text(target_file, content):
    target_file.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_file.parent,
            delete=False,
            prefix=f".{target_file.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = temp_file.name
        os.replace(temp_path, target_file)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _append_jsonl_line(target_file, line_text):
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(target_file, "a", encoding="utf-8") as f:
        f.write(line_text + "\n")
        f.flush()
        os.fsync(f.fileno())


def _next_memory_id(existing_ids):
    max_id = 0
    for memory_id in existing_ids:
        if not isinstance(memory_id, str):
            continue
        if not memory_id.startswith("mem_"):
            continue
        suffix = memory_id[4:]
        if suffix.isdigit():
            max_id = max(max_id, int(suffix))
    return f"mem_{max_id + 1:04d}"


def _normalize_memory_items_with_unique_ids(memory_items):
    if not isinstance(memory_items, list):
        return []
    normalized = []
    seen = set()
    for item in memory_items:
        if not isinstance(item, dict):
            continue
        row = item.copy()
        memory_id = row.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id.strip() or memory_id in seen:
            memory_id = _next_memory_id(seen)
            row["memory_id"] = memory_id
        seen.add(memory_id)
        normalized.append(row)
    return normalized


def _record_health_event(event_type, detail):
    _PERSISTENCE_HEALTH_EVENTS.append({"event_type": event_type, "detail": detail})


def consume_persistence_health_events():
    events = list(_PERSISTENCE_HEALTH_EVENTS)
    _PERSISTENCE_HEALTH_EVENTS.clear()
    return events


def load_state(state_file, default_state):
    if not state_file.exists():
        return default_state.copy()

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return default_state.copy()

        merged = default_state.copy()
        merged.update(data)
        return merged

    except (json.JSONDecodeError, OSError):
        _record_health_event("state_load_fallback", str(state_file))
        return default_state.copy()


def save_state(state_file, current_state):
    try:
        content = json.dumps(current_state, indent=2, ensure_ascii=False)
        _atomic_write_text(state_file, content)
    except OSError:
        _record_health_event("state_save_failure", str(state_file))
        return


def load_project_journal(journal_file, max_entries=None):
    if not journal_file.exists():
        return []

    entries = []
    malformed_lines = 0
    try:
        with open(journal_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    malformed_lines += 1
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        _record_health_event("journal_load_fallback", str(journal_file))
        return []
    if malformed_lines:
        _record_health_event("journal_malformed_lines_skipped", str(malformed_lines))

    if max_entries is not None and max_entries > 0:
        return entries[-max_entries:]
    return entries


def write_project_journal(journal_file, entries):
    try:
        content = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries)
        _atomic_write_text(journal_file, content)
    except OSError:
        return


def archive_project_journal_entries(journal_archive_file, entries, reason):
    if not entries:
        return

    journal_archive_file.parent.mkdir(parents=True, exist_ok=True)
    first_ts = entries[0].get("timestamp", "")
    last_ts = entries[-1].get("timestamp", "")
    by_type = {}

    for entry in entries:
        etype = entry.get("entry_type", "unknown")
        by_type[etype] = by_type.get(etype, 0) + 1

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "archived_count": len(entries),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "entry_type_counts": by_type,
    }

    try:
        _append_jsonl_line(journal_archive_file, json.dumps(summary, ensure_ascii=False))
    except OSError:
        return


def append_project_journal(journal_file, entry):
    try:
        _append_jsonl_line(journal_file, json.dumps(entry, ensure_ascii=False))
    except OSError:
        return


def load_memory_payload(memory_file, default_memory_payload, dedupe_memory_items):
    if not memory_file.exists():
        return default_memory_payload()

    try:
        with open(memory_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        _record_health_event("memory_load_fallback", str(memory_file))
        return default_memory_payload()

    if not isinstance(data, dict):
        _record_health_event("memory_payload_invalid_root", str(memory_file))
        return default_memory_payload()

    if "memory_items" not in data or not isinstance(data["memory_items"], list):
        _record_health_event("memory_payload_repaired_items", str(memory_file))
        data["memory_items"] = []
    else:
        data["memory_items"] = dedupe_memory_items(data["memory_items"])

    if "meta" not in data or not isinstance(data["meta"], dict):
        _record_health_event("memory_payload_repaired_meta", str(memory_file))
        data["meta"] = default_memory_payload()["meta"]

    return data


def save_memory_payload(memory_file, payload):
    if not isinstance(payload, dict):
        _record_health_event("memory_payload_repaired_root_on_save", str(memory_file))
        payload = {}
    if "meta" not in payload or not isinstance(payload["meta"], dict):
        _record_health_event("memory_payload_repaired_meta_on_save", str(memory_file))
        payload["meta"] = {}
    memory_items = _normalize_memory_items_with_unique_ids(payload.get("memory_items", []))
    payload["memory_items"] = memory_items
    payload["meta"]["memory_count"] = len(memory_items)
    try:
        content = json.dumps(payload, indent=2, ensure_ascii=False)
        _atomic_write_text(memory_file, content)
    except OSError:
        _record_health_event("memory_save_failure", str(memory_file))
        return
