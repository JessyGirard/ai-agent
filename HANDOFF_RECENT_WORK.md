# Handoff: recent memory & reliability work (for ChatGPT or other assistants)

**Purpose:** Paste this whole file into another chat so the other model knows **where the project is** after the last several increments, without needing full conversation logs.

**Project:** `ai-agent` (Python). Core loop: `playground.py`. Protected baseline tests: `python tests/run_regression.py` (documented in `README.md` as the release gate; pytest is supplemental).

**User preferences we followed:** small increments, low risk, no scope creep, regression must stay green before trusting changes.

---

## What was done (rough chronological / thematic)

### Normalization & dedupe (earlier in thread)
- Stronger **canonical memory keys** (`canonicalize_memory_key_value`) so variants like hyphen vs space / punctuation don’t create duplicate memories.
- **Transient identity** filtering expanded (mood/state/temporal phrasing) so short-lived “I am …” lines don’t become durable identity memory.
- **Uncertainty phrases** initially blocked all runtime memory; then refined to **category-specific** behavior:
  - **preference / goal / identity:** uncertain phrasing still **skipped**
  - **project:** uncertain phrasing **allowed** (work-in-progress is often tentative)
- **Legacy duplicate merge** on memory load (`dedupe_memory_items`) so old JSON doesn’t keep near-duplicate rows forever.
- Explicit naming: **`normalize_memory_display_value`** vs **`canonicalize_memory_key_value`** (display vs dedupe).

### Display normalization tweak
- `normalize_memory_display_value`: normalize `-` / `_` to spaces **before** collapsing whitespace (avoids double spaces).

### Regression tests (harness)
- Most new behavior is locked in **`tests/run_regression.py`** (not only pytest).
- Examples of covered areas: memory key equivalence, transient / uncertain / question skips, display normalization, uncertain project allowed, uncertain goal skipped, retrieval ranking, conflicts, journal, tool fetch mocks, missing LLM key handling.

### Retrieval “smarts” (score-only, no schema migration)
- **Recency bonus** in `score_memory_item`: slight boost for `last_seen == "runtime"` and `trend == "reinforced"`.
- **Staleness penalty** (retrieval only): downrank imported / tentative / weak-evidence items so prompts don’t over-prefer stale rows. **Does not rewrite** stored `confidence` in JSON.

### Write-path conflict guard (identity / goal)
- Before writing runtime memory, if **same category** is `identity` or `goal`, detect **negation cue mismatch** vs an existing item with enough **token overlap** (Jaccard ≥ 0.35) → **skip write** (`write_runtime_memory` returns `None`). Avoids contradictory goals/identities piling up.

### Repo hygiene
- **`requirements.txt`:** added `requests`, `openai` (used by `tools/fetch_page.py` and `memory/extractors/run_extractor.py`).
- **`test_openai.py` / `test_claude.py`:** refactored so API calls run only under `main()`; if `RUN_LIVE_API_TESTS` is not `1`, scripts **exit without network** (safer for accidental `pytest` / imports).
- **`README.md`:** notes live API scripts + env gate.

### Documentation
- **`PROJECT_SPECIFICATION.md`** exists as a repo inventory/spec (separate from this handoff).

---

## Important clarifications (common confusion)

- **Cursor IDE chat** does **not** auto-feed into `memory/extracted_memory.json`. Runtime memory updates happen when **`playground.py` / Streamlit UI** runs and processes user lines, or via import/extractor pipelines.
- **Git** is visible to the IDE assistant when helping code; the **agent app** does not automatically read git state unless you add that later.

---

## How to verify current health

From repo root:

```bash
python tests/run_regression.py
```

At last full run in this work session, this passed **35 / 35** tests. Re-run after any local edits.

---

## Files most touched in this phase

- `playground.py` — memory extract/write, scoring, retrieval, guards
- `tests/run_regression.py` — regression coverage
- `requirements.txt`
- `test_openai.py`, `test_claude.py`
- `README.md`

---

## Suggested “next moves” (not implemented here; optional)

- Tune negation / overlap thresholds if real usage shows false positives/negatives.
- Optional: score-only “time decay” if you add real timestamps later (still avoid silent JSON mutation unless intended).
- Optional: align `PROJECT_SPECIFICATION.md` with any new files if the tree grows.

---

*End of handoff. Copy from the title through here into ChatGPT as needed.*
