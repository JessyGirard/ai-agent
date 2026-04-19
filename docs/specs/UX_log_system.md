# UX log — operator / Agent surface increments

**Purpose:** Short record of **UX-focused increments** on this repo (launcher + Streamlit Agent experience + related **`app/ui.py`** moves). Primary table = **UI-01 … UI-09** (shipped) + **UI-10** (next). **Companion sections below** list cockpit-era HANDOFF increments, named wiring slices, Tool 1 panel work, and experiments so nothing material is “missing from the log.” For execution philosophy (U1–U6 / M1–M5), see `docs/specs/UX_system.md`.

**Numbering (this file):** **UI-01 … UI-09** = nine shipped items in the **operator / Agent-input / launch** track (table below). **UI-10** = next increment. Session notes once called the launcher slice **“UI-09A”** — that is the **same delivery** as **UI-08** in this table (renamed so the count stays **1…8 shipped**, then **9** next).

**If ChatGPT only sees UI-07 then “UI-09A”:** that is an **outdated paste**. On disk, **UI-08** is the launcher row; re-open or re-copy **`docs/specs/UX_log_system.md`** from the repo.

**If ChatGPT still assumes “mic reverted / expander-only Agent speech”:** that was true **only until** **`SESSION_SYNC_LOG.md`** block **`### 2026-04-19` — UI-09** — **UI-09** shipped the **voice-draft composer + mic beside input** path; read the log bottom + this table’s **UI-09** row.

**Log updated:** **2026-04-18** — **LATENCY-21** (`playground.py`): **`fetched_stripped_word_count`** from **`len(fetched_stripped.split())`** only when **`fetched_stripped_len <= _LATENCY10_TRIVIAL_MAX_CHARS`**; passed into **`_latency10`** (no **`.split()`** in helper). **LATENCY-20** (**`fetched_stripped_len`**). **LATENCY-19**–**LATENCY-12**, **LATENCY-11**, **LATENCY-07 … LATENCY-10**. **`SESSION_SYNC_LOG.md` (`### 2026-04-19`)** — **LATENCY-06** (`app/ui.py`). **Same file / same date line** — **UI-09**; **UI-X1** / **UI-X2**; companion register; **LAUNCH-08** + **CLI-01/02** — see **`SESSION_SYNC_LOG.md`** (bottom entries).

---

## Crosswalk — do not confuse with cockpit “UI Increment 8”

`docs/handoffs/HANDOFF_RECENT_WORK.md` uses a **separate** lane: **UI Increments 1–8 (cockpit era, ~2026-04-17)** — scaffolding, sidebar, tabs→radio, popover, and **Increment 8 = top surface bar** (Agent / API / …) in **`app/ui.py`**.

| Track | What “8” means |
|--------|----------------|
| **This file (UX_log)** | **UI-08** = **Windows demo launcher** theme (`pythonw` / Silent.ps1; **LAUNCH-08** = **`.lnk` → Chrome `--app` only**, server = **`Start-Agent-Server.cmd`** separately; UI-09A→renamed). |
| **HANDOFF cockpit** | **UI Increment 8** = **top surface bar** + backup nav wording — **not** logged as its own row here; it overlaps the **UI-06 / UI-07** era layout work in practice. |

So: **cockpit Inc 8 was never a separate “UI-08” row in this log** on purpose — this log’s **UI-08** slot was reserved for the **later launcher increment** and then filled when we formalized **UI-09A → UI-08**. If you need one timeline that merges both naming schemes, use this table + HANDOFF bullets together, plus **Companion register → HANDOFF “UI Increment” cockpit** below (Inc **1–8** one-line each).

---

## Increments (summary)

| ID | Summary | Main touchpoints |
|----|---------|------------------|
| **UI-01** | Windows launch without a stuck black console for shortcuts; visible console still available via `.cmd`. | `Launch-Agent-UI-Silent.ps1` (CreateNoWindow), `Create-Agent-UI-Shortcut.ps1`, `Launch-Agent-UI.cmd` (REM / when to use which), runbook / README pointers |
| **UI-02** | **Audit only:** traced `st.chat_input` → `run_query` → `playground` → rerun; risks for paste/commands/outcomes; recommended dual input path for UI-03. | No code change (narrative audit in session) |
| **UI-03** | Long-form paste: expander + text area + explicit send into the same pipeline as chat, before `st.chat_input`. | `app/ui.py` |
| **UI-04** | Pasted-text safety: caps and shape checks so multiline logs / fat lines do not hijack state commands or outcome heuristics. | `playground.py`, `tests/run_regression.py` (and baseline count in docs) |
| **UI-05** | Optional microphone speech-to-text → editable transcript → explicit send (same pipeline as chat/paste). Includes **UI-05A** safe draft clear (see companion register). | `app/ui.py`, `requirements.txt` (`streamlit-mic-recorder`), README / spec notes |
| **UI-06** | Agent-first layout: conversation leads; surface switch compact on Agent; sidebar **Tools · navigation · state** expander bundles backup nav + state; menu/shortcuts tucked in expander. Sub-slice **UI-06B**: on **Agent**, top five-button surface bar is suppressed (calmer landing); switching via sidebar backup. | `app/ui.py` |
| **UI-07** | Open-and-go: empty-Agent **Ready** banner, sidebar **collapsed** on first paint, optional **`?ui_surface=…`** once then stripped, clearer “ready to chat” copy in menu; launcher/README notes on bookmarking. | `app/ui.py`, launch scripts (comments), `README.md` |
| **UI-08** | Demo launch chain: **`pythonw`** + silent script for optional no-console paths; docs + **re-pin** guidance. *(Previously called UI-09A in session notes.)* **LAUNCH-08:** **`.lnk`** = Chrome **`--app`** only; server manual via **`Start-Agent-Server.cmd`**. Debug path unchanged: **`Launch-Agent-UI.cmd`**. | `Create-Agent-UI-Shortcut.ps1`, `Start-Agent-Server.cmd`, `Launch-Agent-UI-Silent.ps1`, `Launch-Agent-UI.cmd` (REM), `SYSTEM_EVAL_RUNBOOK.md`, `README.md` |
| **UI-09** | Agent input polish: **`Message Joshua…`** chat placeholder; **🎤** toggle beside send row; **voice-draft composer** when open (large transcript, **append** per speech segment, **Send draft** → same **`run_query`** pipeline + **`voice_draft_clear_pending`** clear). **Same delivery as Cursor label UI-06D.** | `app/ui.py` |

### Experiments (layout — may keep, tune, or revert after manual test)

| ID | Summary | Main touchpoints |
|----|---------|------------------|
| **UI-X1** | Messages only inside **`chat_container = st.container()`** (persistent slot test; input unchanged). | `app/ui.py` → `render_agent_center_minimal` |
| **UI-X2** | Fixed viewport test: **`.chat-wrapper`** CSS `70vh` + `overflow-y: auto`; markdown open/close div around messages + voice composer; input **outside**. Caveat: Streamlit DOM may not nest blocks inside the div. | `app/ui.py` → `_inject_ui_x2_chat_viewport_css`, `render_agent_center_minimal` |

---

## Companion register — increments & moves not given their own UI-0x row

Use this with **`docs/handoffs/SESSION_SYNC_LOG.md`** (search **“UI Increment”** / **Tool 1**) for full prose.

### HANDOFF “UI Increment” cockpit & navigation (2026-04-17)

Same **`app/ui.py`** evolution; **`HANDOFF_RECENT_WORK.md`** numbers these **1–8** separately from **UI-01…** above.

| HANDOFF Inc | Summary | Primary touchpoints |
|-------------|---------|---------------------|
| **1** | Windows one-click Streamlit launch (`Launch-Agent-UI.cmd`, dev shell, runbook). Overlaps **UI-01** theme (launch ergonomics). | Root scripts, `docs/runbooks/SYSTEM_EVAL_RUNBOOK.md` |
| **2** | Operator cockpit scaffolding: tabs (Assistant first, Tool 1, placeholders, Terminal); Assistant split shortcuts vs Agent chat. | `app/ui.py` |
| **3** | Sidebar + main **Focus · Stage · Fetch** status strip; env mirror for fetch mode. | `app/ui.py` |
| **4** | Tab/panel copy: Shortcuts vs Conversation, Tool 1 “when to use”, placeholder roadmap blurbs, Terminal wording. | `app/ui.py` |
| **5** | **Agent-first:** remove main tabs; **`st.sidebar` radio** surfaces; **`render_main_surface()`**; minimal Agent center + expanders for tools. | `app/ui.py` |
| **6** | **Minimal sidebar rail:** radio only, one-line status, **Advanced** expander (focus/stage, fetch mirror, memory). | `app/ui.py` |
| **7** | Agent center: status / New chat / shortcuts into **`st.popover("⋯")`** (expander fallback); thread + **`st.chat_input`** dominate. | `app/ui.py` |
| **8** | **Top surface bar:** Agent · API · Prompt · Regression · Terminal; **`_SURFACE_NAV`** / **`render_top_surface_bar()`**; sidebar **Surface · backup** buttons. | `app/ui.py`, docs (API wording) |

### Named slices (session / code labels)

| Label | What shipped | Where |
|-------|----------------|--------|
| **UI-05A** | Voice draft **`voice_draft_clear_pending`**: clear **`voice_draft_text` on the next rerun** before widgets re-bind, avoiding duplicate / stale transcript submit after **Send draft**. | `app/ui.py` → `_render_agent_speech_to_text_inner` |
| **UI-06B** | On **`ui_surface == "Agent"`**, **`render_top_surface_bar()`** returns immediately — **no top five-button strip** on Agent; calmer landing; surface change via sidebar **Tools · navigation · state** backup nav. | `app/ui.py` → `render_top_surface_bar` |
| **UI-06D** | **Alias for UX table row UI-09** (voice-draft composer + mic column + Joshua placeholder). | `app/ui.py` → `render_agent_center_minimal` |

### Windows launch — fixed port & Chrome shortcut (LAUNCH-08)

| Label | What shipped | Where |
|-------|----------------|--------|
| **LAUNCH-08** | **`Start-Agent-Server.cmd`** runs Streamlit on **`--server.port 8501`** (manual). **`Create-Agent-UI-Shortcut.ps1`** writes **`.lnk`** with **Target** = **`chrome.exe`** and **Arguments** **`--app=http://localhost:8501`** only — no `.cmd` from the shortcut (no black box). Stable **`http://localhost:8501`** for bookmarks/mic when the server is up. | `Start-Agent-Server.cmd`, `Create-Agent-UI-Shortcut.ps1`, `README.md`, `SYSTEM_EVAL_RUNBOOK.md` |

### Operator CLI — terminal `joshua` (CLI-01 / CLI-02)

| Label | What shipped | Where |
|-------|----------------|--------|
| **CLI-01** | Repo root **`joshua.ps1`**: runs **`streamlit run app\ui.py`** on **8501** via **`.venv-win\Scripts\python.exe`**. | `joshua.ps1` (repo root) |
| **CLI-02** | Optional **Windows PowerShell** profile: **`function joshua { & "<fixed-path-to-repo>\joshua.ps1" }`** so **`joshua`** works from any cwd (path is machine-specific). | User **`$PROFILE`** — not in git |

### Perceived latency (LATENCY-01 — LATENCY-21, cross-cutting)

| Label | What shipped | Where |
|-------|----------------|--------|
| **LATENCY-01** | Chat UX: defer assistant “Thinking…” work so the **user line paints on the prior run** (queue drain at top of chat). | `app/ui.py` |
| **LATENCY-02** | Cap oversized **`content`** / post-fetch body before model calls (`_latency_truncate_text` / caps). | `playground.py` |
| **LATENCY-03** | Prompt path: cache invariant system text; cap oversized append-only context blocks. | `services/prompt_builder.py` |
| **LATENCY-04** | Fetch branch: **`fetch_page`** in **`ThreadPoolExecutor(max_workers=1)`** with independent prep before **`future.result()`** — same outputs. | `playground.py` |
| **LATENCY-05** | Stronger **default brevity** in system / open / strict / post-fetch prompt copy. | `services/prompt_builder.py` |
| **LATENCY-06** | Streamlit: drop redundant **`st.rerun()`** where one **`main()`** pass already refreshes main; success path does **not** format the assistant reply twice before rerun. | `app/ui.py` |
| **LATENCY-07** | **`TOOL:fetch`** must be a **single-line** full-string tool line (no trailing prose) before running fetch. | `playground.py` |
| **LATENCY-08** | Skip second **`ask_ai`** when fetch body is **unusable** (failure tag, empty, whitespace-only, no alphanumerics after norm). | `playground.py` |
| **LATENCY-09** | Reuse one **strip/truncate** result for skip-vs-second-pass branching (no duplicate normalization work). | `playground.py` |
| **LATENCY-10** | Skip second **`ask_ai`** when fetch is **valid** but **trivially small** (deterministic char + word caps). | `playground.py` |
| **LATENCY-11** | Deterministic fetch short-circuit reply: module-level cap + empty-answer constants, **`_latency07_structured_fetch_reply_tail`**, one **`len(body)`** / branch for ellipsis — **same rendered output** as before. | `playground.py` |
| **LATENCY-12** | Fetch branch: compute **`fetch_failure_tag`** once for normalized raw and once for stripped truncated body; pass into skip / trivial-size helpers — **no behavior change**. | `playground.py` |
| **LATENCY-13** | **`_latency10_is_trivially_small`**: char length + word count supplied from fetch branch when under cap (**LATENCY-20** / **LATENCY-21**). Same thresholds and short-circuit order. | `playground.py` |
| **LATENCY-14** | Fetch branch: one **`any(...isalnum...)`** scan on **`fetch_raw_norm`** for skip logic (see **LATENCY-17** for negated flag passed into **`_latency08`**). | `playground.py` |
| **LATENCY-15** | Fetch branch: **`fetched_stripped_is_empty`** once, passed into **`_latency08`** / **`_latency10`** — same emptiness semantics, no extra string truthiness in helpers. | `playground.py` |
| **LATENCY-16** | Fetch branch: **`fetch_raw_is_empty`** once, passed into **`_latency08`** — same first-condition skip as **`not fetch_raw_norm`**. | `playground.py` |
| **LATENCY-17** | Fetch branch: **`fetch_raw_no_alnum = not fetch_raw_has_alnum`** once; **`_latency08`** fifth check is **`if fetch_raw_no_alnum`** (was **`not fetch_raw_has_alnum`**). | `playground.py` |
| **LATENCY-18** | Fetch branch: **`fetch_raw_has_failure_tag`** once; **`_latency08`** / **`_latency10`** use it for raw-tag presence. | `playground.py` |
| **LATENCY-19** | Fetch branch: **`fetch_stripped_has_failure_tag`** once; **`_latency08`** / **`_latency10`** use it for stripped-tag presence (no **`failure_tag_stripped is not None`** in helpers). | `playground.py` |
| **LATENCY-20** | Fetch branch: **`fetched_stripped_len`** once; **`_latency10`** compares to **`_LATENCY10_TRIVIAL_MAX_CHARS`** without calling **`len(fetched_stripped)`** again. | `playground.py` |
| **LATENCY-21** | Fetch branch: **`fetched_stripped_word_count`** only if **`len <= _LATENCY10_TRIVIAL_MAX_CHARS`**; **`_latency10`** uses it (no **`.split()`** in helper; placeholder when over char cap). | `playground.py` |

### API — Tool 1 operator panel in `app/ui.py` (engine Inc 10 in `core/`)

Operator HTTP tab (**internal surface `Tool 1`**, label **API**). Harness work lives in **`core/system_eval.py`** / **`tests/run_regression.py`**; UI slices below are **`app/ui.py`** / **`app/system_eval_operator.py`** / **`app/tool1_run_log.py`**.

| HANDOFF / log Inc | Summary | Primary touchpoints |
|-------------------|---------|---------------------|
| **(wiring)** | First **Tool 1** tab + **`run_tool1_system_eval_http`** (suite path, Run, PASS/FAIL + artifact previews). Session log: search **“System eval (HTTP)”**. | `app/ui.py`, `app/system_eval_operator.py`, `app/__init__.py` |
| **10** | Engine: **`expected_status`**, **`body_contains`**, **`header_contains`** (+ suite validation, regression). | `core/system_eval.py`, `tests/run_regression.py` |
| **11** | Single-request auth merge: None / Bearer / Basic (+ header merge rules). | `app/ui.py` |
| **12** | Per-case PASS/FAIL clarity, run summary, failure surfacing patterns. | `app/ui.py` |
| **13** | **API key** header mode on top of Inc 11. | `app/ui.py` |
| **14** | Customer-readable run summary + per-case glance lines. | `app/ui.py` |
| **15** | **Rerun last request**, copyable plain summary + approximate **curl** (`shlex`). | `app/ui.py` |
| **17** | Append-only **`logs/tool1_runs.jsonl`** wiring from operator paths; UI warns on **`run_log_error`**. | `app/tool1_run_log.py`, `app/system_eval_operator.py`, `app/ui.py` |
| **18** | Human-readable **`summary`** field on each JSONL record (`compose_tool1_run_human_summary`). | `app/tool1_run_log.py` |
| **19** | Public demo suite pack (fixtures + folder README only). | `system_tests/suites/tool1_public_demo/` |

*(Inc **16** not used as a separate public row in HANDOFF bullets; if we discover a mapped slice, append here.)*

---

## Keeping this log in sync

- **Manual:** After shipping UX or latency behavior in **`app/ui.py`** or **`playground.py`**, add or extend a row in the tables above and bump **Log updated** (top). Narrative session history stays in **`docs/handoffs/SESSION_SYNC_LOG.md`**.
- **Semi-automatic (IDE):** The repo ships **`.cursor/hooks.json`** with an **`afterFileEdit`** hook that runs **`python scripts/ux_log_drift_check.py --cursor-hook-stdin`**. When the agent saves **`app/ui.py`** or **`playground.py`**, it compares **comment tags** (`UI-…`, `LATENCY-…`, `LAUNCH-…`) to this file and prints a **warning to the Hooks output** if a tag is missing here. It does **not** rewrite Markdown (that would need a deliberate edit or a doc-gen tool).
- **CI / pre-push (optional):** `python scripts/ux_log_drift_check.py` exits **1** if any tag from those two files is absent from this log — use before commit when you touched UI or fetch orchestration.

The **running Streamlit UI** cannot safely update this file by itself without new server-side code and a chosen sync policy; treat the IDE hook + manual edits as the supported workflow.

## Scope note

- This log is **increment tracking**, not a full product spec. See `docs/specs/PROJECT_SPECIFICATION.md` for inventory and `docs/specs/UX_system.md` for the broader two-lane plan.
- Older handoff text (`docs/handoffs/HANDOFF_RECENT_WORK.md`) may use **different UI numbering** (e.g. cockpit Increments 1–8 from 2026-04-17). **UI-01…UI-09** here is the **operator Agent / input / launch** sequence in the table; **UI-10** is next.

---

*End of log — nine shipped (UI-01 … UI-09); UI-X1/UI-X2 experiments; companion register for cockpit Inc 1–8, UI-05A/06B/06D, Tool 1 UI 11–15+17–19, LAUNCH-08, CLI-01/02, LATENCY-01–21; UI-10 next.*
