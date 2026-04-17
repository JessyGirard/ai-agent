import json
from datetime import datetime, timezone


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
        return default_state.copy()


def save_state(state_file, current_state):
    state_file.parent.mkdir(parents=True, exist_ok=True)

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(current_state, f, indent=2, ensure_ascii=False)


def load_project_journal(journal_file, max_entries=None):
    if not journal_file.exists():
        return []

    entries = []
    try:
        with open(journal_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        return []

    if max_entries is not None and max_entries > 0:
        return entries[-max_entries:]
    return entries


def write_project_journal(journal_file, entries):
    journal_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(journal_file, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
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
        with open(journal_archive_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except OSError:
        return


def append_project_journal(journal_file, entry):
    journal_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return


def load_memory_payload(memory_file, default_memory_payload, dedupe_memory_items):
    if not memory_file.exists():
        return default_memory_payload()

    try:
        with open(memory_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return default_memory_payload()

    if not isinstance(data, dict):
        return default_memory_payload()

    if "memory_items" not in data or not isinstance(data["memory_items"], list):
        data["memory_items"] = []
    else:
        data["memory_items"] = dedupe_memory_items(data["memory_items"])

    if "meta" not in data or not isinstance(data["meta"], dict):
        data["meta"] = default_memory_payload()["meta"]

    return data


def save_memory_payload(memory_file, payload):
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    payload["meta"]["memory_count"] = len(payload.get("memory_items", []))

    with open(memory_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
