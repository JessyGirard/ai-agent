# Browser fetch manual validation (FETCH Increment 4)

**Purpose:** Check whether `FETCH_MODE=browser` (Playwright) improves real-world extraction vs HTTP on a tiny, repeatable URL set.

## Prerequisites

From repo root, once per machine (use the **same** Python that runs `playground`, e.g. `.venv-win`):

```bash
pip install playwright
playwright install chromium
```

**Important:** Use **`.\.venv-win\Scripts\python.exe`** if your global `python` does not have Playwright installed.

Then run smoke with browser mode:

**PowerShell**

```powershell
$env:FETCH_MODE = "browser"
.\.venv-win\Scripts\python.exe -c "from tools.fetch_page import fetch_page, fetch_failure_tag; u='https://example.com'; o=fetch_page(u); print(fetch_failure_tag(o)); print(o[:800])"
```

**Before running regression:** unset browser mode so HTTP-mocked tests apply:

```powershell
Remove-Item Env:FETCH_MODE -ErrorAction SilentlyContinue
python tests/run_regression.py
```

## Operator reference: `diag=` suffix (browser fetch)

When **`FETCH_MODE=browser`**, some **`[fetch:browser_timeout]`**, **`[fetch:browser_error]`**, and **`[fetch:low_content]`** lines append a bounded **` diag=`** block: semicolon-separated **`key=value`** pairs. **Successful** fetches have **no** `diag=`. Token meanings:

| Key / token | Meaning |
|-------------|---------|
| **mrg** | Length of merged fetch text (page title + chosen body slice) when **`low_content`** is emitted — matches the “(N characters)” count in the human-readable line. |
| **b** | **`document.body`** present at probe time: **`1`** / **`0`**. |
| **m** | **`main`** element present: **`1`** / **`0`**. |
| **r** | **`[role="main"]`** present: **`1`** / **`0`**. |
| **a** | **`article`** element present: **`1`** / **`0`**. |
| **h1**, **h2** | Counts of **`h1`** / **`h2`** at probe time (capped in code). **`0`** means none detected *or* the count was not available on that probe tier. |
| **bit** | Character length of **`document.body.innerText`** at probe time (capped). |
| **bct** | Character length of **`document.body.textContent`** at probe time (capped). If **`bct` ≫ `bit`** while **`mrg`** is tiny, the DOM often still holds text that did not flow into the merged extract (hydration, visibility, or extraction-path limits). |
| **fb** | Which **fallback tier** produced the snapshot: **`1`** = pipe-delimited compact probe; **`2`** = micro probe (two small evaluates: **innerText** length + **textContent** length only; **`m`/`r`/`a`/`h1`/`h2`** may be **`0`** on that tier even when the page has landmarks). |
| **js** | **`1`** = primary JSON probe used its inner catch-all inside the page (diagnostic only). |
| **st** | **`1`** = *synthetic* — after navigation, **every** bounded **`page.evaluate`** probe tier failed to yield a usable parsed snapshot in Python. **Not** the same as “no DOM”: Playwright **`inner_text`** extraction may still have run. |
| **probe=none** | **`probe_attempted`** is **false**: navigation did not reach the post-goto DOM probe (typical with **`goto`** timeouts — read together with **`exc=goto_timeout`**). No **`b`/`m`/…`** keys from the probe accompany **`probe=none`**. |
| **probe=failed** | Rare: probe was marked attempted but no probe dict was attached (unexpected error). |
| **exc** | Coarse exception bucket (not a fetch tag): **`goto_timeout`**, **`blocked_transport`** (e.g. `net::ERR_…`), **`extract_timeout`**, **`extract_failed`**, **`timeout`**, **`error`**. |

**Quick patterns**

- **`browser_timeout` … `diag=exc=goto_timeout;probe=none`** — still failing during **navigation**; do not infer landmark absence from missing **`m`/`h1`**.  
- **`low_content` … includes `fb=1` or `fb=2`** — navigation completed; numeric keys come from that fallback tier.  
- **`low_content` … `diag=mrg=…;st=1`** — navigation completed; all **evaluate**-based probe tiers were unusable here; merged text remains thin.

## Manual test set (representative)

| # | Class | URL | Intent |
|---|--------|-----|--------|
| A | Simple static | `https://example.com` | Minimal HTML; readable boilerplate. |
| B | JS-heavy / news front | `https://www.reuters.com` | Heavy front page; partial text / nav / hydration. |
| C | Difficult / protected | `https://www.washingtonpost.com` | Slow, WAF, or transport quirks. |

---

## Recorded run — venv + Playwright/Chromium (this machine, 2026-04-17)

**Interpreter:** `.\.venv-win\Scripts\python.exe`  
**Env:** `FETCH_MODE=browser`  
**Playwright:** installed; Chromium installed.

| Case | URL | Outcome | `fetch_failure_tag` | Text quality |
|------|-----|---------|---------------------|----------------|
| A | https://example.com | **Success** | *(none)* | **Useful** — standard Example Domain paragraph (~142 chars). |
| B | https://www.reuters.com | **Failure (thin)** | `low_content` | **Junk / partial** — only ~11 chars visible (`reuters.com`-style snippet); front page did not yield meaningful article body in time. |
| C | https://www.washingtonpost.com | **Failure** | `browser_error` | N/A — `Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR` during navigation (`domcontentloaded`). |

**Sample exact strings**

- **A (success):** plain text starting with `Example Domain` … (no `[fetch:` prefix).  
- **B:** `[fetch:low_content] Browser extracted very little text (11 characters). Snippet: reuters.com`  
- **C:** `[fetch:browser_error] Browser fetch failed. Detail: Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.washingtonpost.com/` …

---

## Re-run after FETCH Increment 5 (navigation / wait stabilization, same venv)

**Changes in code:** `domcontentloaded` then one **`load`** retry on navigation failure; bounded **`load`** + **`networkidle`** waits after success; Chromium launch args **`--disable-http2`** and **`--disable-quic`**; same title + `body` extraction as before.

| Case | URL | Outcome | `fetch_failure_tag` | Notes |
|------|-----|---------|---------------------|--------|
| A | https://example.com | **Success** | *(none)* | Same useful Example Domain text (~142 chars). |
| B | https://www.reuters.com | **Failure (thin)** | `low_content` | Unchanged: ~11 visible chars (`reuters.com` snippet). |
| C | https://www.washingtonpost.com | **Failure** | `browser_timeout` | **Moved off** prior `browser_error` / `ERR_HTTP2_PROTOCOL_ERROR`: second attempt used `wait_until=load` and hit **20s navigation timeout** — clearer operator signal than HTTP/2 stack noise. |

**Washington Post vs Increment 4:** `browser_error` (HTTP/2) → **`browser_timeout`** (explicit timeout on `load` path).

---

## Earlier placeholder run (Cursor default `python`, no Playwright)

If system Python lacks `playwright`, all three URLs return **`[fetch:browser_unavailable]`** — that is expected and does **not** reflect site behavior.

---

## What worked

- **example.com** in browser mode: full static text extracted; confirms Playwright path end-to-end.
- **Regression:** confirm with latest gate (e.g. **297 / 297** when **`FETCH_MODE` is not set to `browser`** during `python tests/run_regression.py` — HTTP mocks).

## What failed (real browser this run)

- **Reuters:** `low_content` — SPA/news shell; current wait strategy (`domcontentloaded` + short body scrape) is not enough for headline density.
- **Washington Post (Increment 4):** `browser_error` — HTTP/2 transport error at navigation. **Increment 5:** see re-run table (`browser_timeout`).

## Recommended next improvement (based on these runs)

1. **Reuters / SPA fronts:** still **`low_content`** after bounded `networkidle` — next increment may allow **extraction-only** tweaks (e.g. `main` landmark or short scroll) *only if* approved; not done in Increment 5.  
2. **Washington Post timeouts:** **`FETCH_BROWSER_TIMEOUT_SECONDS`** (Increment 6) plus bounded **commit → domcontentloaded → load** goto ladder (Increment 7) — tag can remain **`browser_timeout`**; ladder improves early-exit cases and per-step diagnostics.  
3. **Operators:** always use venv Python for browser smoke; clear **`FETCH_MODE`** before regression.

---

## FETCH Increment 13 — operator-facing diagnostics polish (docs only)

**What changed:** This runbook only — added **Operator reference: `diag=` suffix** above (token glossary + quick patterns). No code, probe tiers, **`playground.py`**, Tool 1, or system_eval changes.

---

## Re-run after FETCH Increment 6 (env-driven browser navigation timeout only)

**Changes in code:** **`FETCH_BROWSER_TIMEOUT_SECONDS`** (integer, clamped **5–120**, default **20**) read in **`tools/fetch_page.py`** and passed into **`fetch_via_browser(..., timeout_seconds=...)`** for navigation bounds only. No extraction logic, routing, or playground changes.

| Case | URL | Env timeout | Outcome | `fetch_failure_tag` | Notes |
|------|-----|-------------|---------|---------------------|--------|
| A | https://example.com | default (20) | **Success** | *(none)* | Same as Increment 5. |
| B | https://www.reuters.com | default (20) | **Failure (thin)** | `low_content` | Unchanged. |
| C | https://www.washingtonpost.com | default (20) | **Failure** | `browser_timeout` | Still timeout on `load`; detail shows **20000ms**. |
| C′ | https://www.washingtonpost.com | **90** | **Failure** | `browser_timeout` | **Tag unchanged** vs default; detail shows **90000ms** — page did not reach `load` within budget on this host. |

**Washington Post vs Increment 5:** still **`browser_timeout`**; env only scales the timeout message / budget, not outcome class on this run.

---

## Re-run after FETCH Increment 7 (bounded wait-strategy tuning only)

**Changes in code:** **`tools/fetch_browser.py`** only — goto ladder **`commit` → `domcontentloaded` → `load`** with **per-attempt** timeout = `max(1000, timeout_ms // 3)`; post-goto **`domcontentloaded` → `networkidle` → `load`**. No extraction, facade, or playground edits.

| Case | URL | Outcome | `fetch_failure_tag` | Notes |
|------|-----|---------|---------------------|--------|
| A | https://example.com | **Success** | *(none)* | Unchanged. |
| B | https://www.reuters.com | **Failure (thin)** | `low_content` | Unchanged. |
| C | https://www.washingtonpost.com | **Failure** | `browser_timeout` | **Tag unchanged** vs Increment 6; error path is **third** `goto` step (`wait_until=load`) with **~6666ms** timeout slice in detail — clearer ladder signal, not a new success class on this host. |

---

## Re-run after FETCH Increment 8 (landmark extraction + optional scroll only)

**Changes in code:** **`tools/fetch_browser.py`** — prefer **`main` / `[role="main"]` / `article`** when they beat **`body`** on visible text length; if still thin, one bounded **`scrollBy`** + short settle + second extract pass.

| Case | URL | Outcome | `fetch_failure_tag` | Notes |
|------|-----|---------|---------------------|--------|
| A | https://example.com | **Success** | *(none)* | Unchanged. |
| B | https://www.reuters.com | **Failure (thin)** | `low_content` | **Did not improve** vs Increment 7 on this host — merged visible text still **11** chars (`reuters.com` snippet). |
| C | https://www.washingtonpost.com | **Failure** | `browser_timeout` | Unchanged. |

---

## Re-run after FETCH Increment 9 (structured headline extraction only)

**Changes in code:** **`tools/fetch_browser.py`** — bounded **`h1` / `h2` / role=heading / `header h*` / `article h*`** headline collection (de-dupe, **` | `** join, cap); prefer over thin generic visible text when rules fire; headline sample before visible path and longer of two headline passes after scroll when visible was thin.

| Site | URL | Outcome | `fetch_failure_tag` | Notes |
|------|-----|---------|---------------------|--------|
| BBC News | https://www.bbc.com/news | **Success** | *(none)* | Large extract; **4000** char cap truncates — still “works”. |
| Reuters | https://www.reuters.com | **Failure (thin)** | `low_content` | **No improvement** vs Increment 8 on this host — merged text still **11** chars; headline **`inner_text`** did not surface a qualifying bundle. |
| WaPo | https://www.washingtonpost.com | **Failure** | `browser_timeout` | Unchanged (navigation). |

---

## Re-run after FETCH Increment 10 (bounded text-node `evaluate` read only)

**Changes in code:** **`tools/fetch_browser.py`** — one **`page.evaluate`** text-node aggregation under **`main` / `[role="main"]` / `body`**, applied after headline preference when it wins the same thin/long preference rule as headlines.

| Site | URL | Outcome | `fetch_failure_tag` | Notes |
|------|-----|---------|---------------------|--------|
| BBC News | https://www.bbc.com/news | **Success** | *(none)* | Still large text (**4000** cap). |
| Reuters | https://www.reuters.com | **Failure (thin)** | `low_content` | **No gain** vs Increment 9 on this host (merged **11** chars). |
| WaPo | https://www.washingtonpost.com | **Failure** | `browser_timeout` | **Unchanged** failure mode. |

---

## Re-run after FETCH Increment 11 (hard-target `diag=` classification)

**Changes in code:** **`tools/fetch_browser.py`** — post-nav DOM probe + **`exc=`** coarse classes; **`diag=`** suffix on **`low_content`**, **`browser_timeout`**, **`browser_error`** (same **`[fetch:tag]`** names).

| Site | URL | Outcome | Notes on `diag=` |
|------|-----|---------|------------------|
| BBC News | https://www.bbc.com/news | **Success** | No `diag=` (non-failure path). |
| Reuters | https://www.reuters.com | **`low_content`** | After Increment 12 example: **`diag=mrg=11;st=1`** — merged text tiny; all bounded probe **`evaluate`** tiers unusable (**`st=1`**) vs earlier **`probe=failed`** string. |
| WaPo | https://www.washingtonpost.com | **`browser_timeout`** | Example: **`diag=exc=goto_timeout;probe=none`** — timeout on **`goto`** / **`load`** step, not a post-nav thin-DOM classification. |

---

## Re-run after FETCH Increment 12 (probe resilience)

**Changes in code:** **`tools/fetch_browser.py`** — probe only: JSON primary + retries, pipe fallback (**`fb=1`**), micro lengths (**`fb=2`**), synthetic **`st=1`** when all **`evaluate`** tiers fail after navigation.

| Site | URL | Note |
|------|-----|------|
| Reuters | https://www.reuters.com | **`low_content`** with **`diag=mrg=11;st=1`** on one venv run (no longer **`probe=failed`** in that slot). |

---

## FETCH Increment 13 — operator glossary (cross-reference)

See **Operator reference: `diag=` suffix** at the top of this file for full definitions of **`probe=none`**, **`st=1`**, **`fb=1` / `fb=2`**, **`exc=`**, **`mrg`**, **`bit` / `bct`**, **`h1` / `h2`**, **`m` / `r` / `a`**.

---

*Append new dated sections below when re-running smoke after changes.*
