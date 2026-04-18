# Project story + where the full history lives

**Purpose:** New chats (especially ChatGPT) have no memory. This file is the **short narrative** of what `ai-agent` is and how it got here, plus a **map** to every place the full detail actually lives. It is **not** a duplicate of those docs — read them when you need depth.

### How to read the three anchors (roadmap vs log vs SYNC block)

| Piece | What it is | How to use it |
|--------|------------|----------------|
| **`docs/roadmaps/TEST_ENGINEERING_ROADMAP.md`** | **Plan:** mission, phases, North Star, and the agreed **near-term PR sequence** (what we intend to build over time). | Read when you want direction and boundaries. It changes when strategy changes, not after every commit. |
| **`docs/handoffs/SESSION_SYNC_LOG.md`** | **Record:** append-only diary; **newest block is at the bottom.** What actually shipped, which files, regression **X / Y**, and “what’s next” *as of that session.* | Read the **last one to three entries** to see current reality. Older entries stay for history (their “next” lines may be outdated). |
| **`[SYNC MESSAGE]` … `[END]`** (from Cursor in chat) | **Handoff stub:** same kind of info as a fresh log entry, formatted so you can **paste into ChatGPT** immediately. | It does **not** live in the repo unless that session’s work also **appended** a matching block to `SESSION_SYNC_LOG.md`. Treat chat + bottom of log as a pair after each task group. |

**Rule of thumb:** Conflicts → **bottom of `SESSION_SYNC_LOG.md`** beats an old roadmap line; **roadmap** beats a vague memory; **reliability doc + passing tests** beat all opinions.

---

## The story (readable version)

**What this repo is:** A Python **local AI assistant** centered on `playground.py`: orchestration, memory, journal, routing, prompts, optional web fetch, and a Streamlit UI (`app/ui.py`). The tagline in `README.md` is personal: building something that can grow into a capable ally.

**How we worked:** In small, safe steps. The protected gate is **`python tests/run_regression.py`** (hundreds of scenarios; count grows over time — **trust the latest run**, not a number quoted in an old note). Pytest and other scripts are supplemental. The operator preference: **no scope creep**, regression green before trusting changes.

**Major evolution (architecture):** Runtime logic was **split into services** so `playground.py` stays orchestration-focused: `core/persistence.py`, `services/memory_service.py`, `journal_service.py`, `routing_service.py`, `prompt_builder.py`. Memory behavior was hardened over time (normalization, dedupe, uncertainty handling, conflict guards, retrieval scoring). Offline memory import/extract pipelines live under `memory/`.

**Reliability layer:** Long-running stability is exercised with **`tests/run_soak.py`** (chunked runs, checkpoints, aggregates). **GitHub Actions** run regression plus soak tiers (`.github/workflows/`). **`docs/reliability/RELIABILITY_EVIDENCE.md`** records gates, artifacts, and what we claim under what conditions.

**New product direction (testing workbench):** The project is also becoming an **AI Testing Workbench**: one **shared spine** — `core/system_eval.py`, `tools/system_eval_runner.py`, JSON suites under `system_tests/suites/` — supporting **three tool profiles**: (1) API reliability, (2) prompt↔response testing, (3) regression (existing harness). Long-term **North Star** (personal assistant that grows with the operator) is in the roadmap; **first execution lane** is disciplined test-engineering capability.

**Collaboration:** Work is split between **Cursor** (implementation in-repo) and **ChatGPT** (reasoning/scope). **Jessy** carries messages between them. Day-to-day continuity is **`docs/handoffs/SESSION_SYNC_LOG.md`** (append-only). Protocol and paste text: **`docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md`**.

**Right now:** Implementation status and the exact “what we did last” live in the **bottom entries** of `docs/handoffs/SESSION_SYNC_LOG.md` — this narrative is not updated on every merge.

**Snapshot (2026-04-17):** The **FETCH (browser)** vertical shipped through **Increment 13** (Playwright path, **`diag=`** diagnostics, glossary in **`docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md`**). Hard sites may still yield **`low_content`** / **`browser_timeout`** — use **`diag=`** + that runbook. **UI + Tool 1 (API):** **`Launch-Agent-UI.cmd`**, cockpit **`app/ui.py`** (top bar **Agent / API / …**), Tool 1 **single-request** auth helpers, customer-facing summaries, **rerun last request** + copyable request/curl, and **append-only** **`logs/tool1_runs.jsonl`** via **`app/tool1_run_log.py`** — each line is full JSON **plus** a plain-text **`summary`** for stakeholders (Inc **18**); suite runs still logged from **`app/system_eval_operator.py`**. **Public demo suites** (JSONPlaceholder + httpbin, no secrets): **`system_tests/suites/tool1_public_demo/`** (Inc **19**); **`tool1_demo_public_smoke.json`** has been run live **PASS 3/3** — first **operationally proven** end-to-end Tool 1 suite on real HTTP. **Next product focus:** continue **engine / assertions** in thin slices as approved. **`core/system_eval.py`** includes minimal + JSON/header assertions, plus **`steps`** multi-request scenarios, **`step_templates`** / **`use`**, **`{{variable}}`** substitution, **`step_results`** in JSON, and **`### Steps`** in suite **`.md`** artifacts (Increments **42–46**; see log). **Regression gate:** **`297 / 297`** at last alignment — confirm **`SESSION_SYNC_LOG.md` (bottom)**. **Show state** / **Reset state** in the sidebar **Advanced** area still call **`playground`** (no change to that contract in this arc).

---

## Where the full history lives (source of truth map)

| If you need… | Read this (in repo) |
|--------------|---------------------|
| **What happened session-to-session / what Cursor did last** | `docs/handoffs/SESSION_SYNC_LOG.md` (newest at **bottom**) |
| **How to open a new ChatGPT chat + sync rules** | `docs/handoffs/CHATGPT_DAILY_BOOTSTRAP.md` |
| **Longer collaboration rules + doc order** | `docs/handoffs/CHATGPT_COLLAB_SYNC.md` |
| **Three-tool framing + alignment questions** | `docs/handoffs/THREE_TOOLS_ALIGNMENT_BRIEF.md` |
| **Detailed “what we changed” narrative (paste-sized)** | `docs/handoffs/HANDOFF_RECENT_WORK.md` |
| **Milestones by date / commit era** | `CHANGELOG.md` |
| **Every important file and what it’s for** | `docs/specs/PROJECT_SPECIFICATION.md` |
| **Gates, soak artifacts, what “pass” means** | `docs/reliability/RELIABILITY_EVIDENCE.md` |
| **Mission, phases, North Star, constraints** | `docs/roadmaps/TEST_ENGINEERING_ROADMAP.md` |
| **How to run HTTP system eval + launch Streamlit on Windows** | `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` |
| **Browser fetch manual validation + `diag=` glossary** | `docs/runbooks/FETCH_BROWSER_MANUAL_VALIDATION.md` |
| **Commands and architecture overview** | `README.md` |
| **Line-by-line history** | `git log` (not duplicated in markdown) |

---

## Is “everything” in one file?

**No — on purpose.** One file would go stale, get huge, and fight git merges. The pattern is:

- **Story + map** → this file (stable overview).
- **Truth of last session** → `SESSION_SYNC_LOG.md`.
- **Deep history** → handoff + changelog + spec + git.

If something is missing from the map above, add a row here rather than growing the sync log into a novel.

---

*Last narrative refresh: 2026-04-17 (FETCH lane through Incr. 13 + UI lane start / launcher). Update when phases or primary lane change materially.*
