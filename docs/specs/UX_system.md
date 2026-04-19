Yes — that needs to be part of the build plan now.

What you just added is not separate from memory. It is part of the same mission: **the agent has to be usable enough for real continuity**. If the input box breaks on pasted text, and you cannot speak to it, then even a good memory system is crippled. So from now on, I would treat this as a **two-lane execution plan**:

* **Lane 1:** durable memory
* **Lane 2:** operator input UX (large paste + microphone)

That fits the repo you showed me, because the UI already lives in `app/ui.py`, while memory behavior lives mainly in `services/memory_service.py` and `services/prompt_builder.py`. So we can keep the work cleanly separated instead of jamming everything into `playground.py`.

# Revised execution plan

## Mission

Build an agent that can:

1. remember who you are and what the project is across sessions
2. accept real pasted material without going berserk
3. accept microphone input for speech-to-text
4. stay efficient and regression-protected

---

## Where shipped work is logged (vs this plan doc)

This file is the **verbatim two-lane execution plan** (Lane 1 **M1–M5**, Lane 2 **U1–U6**, batches A–D). It does **not** try to list every merged **`app/ui.py`** slice.

**Canonical increment register:** **`docs/specs/UX_log_system.md`** — **UI-01 … UI-09** (shipped), **UI-X1 / UI-X2** (layout experiments), **companion tables** for HANDOFF **cockpit UI Increment 1–8**, named slices (**UI-05A**, **UI-06B**, **UI-06D**), **Tool 1** operator rows **(wiring)** + **10–15, 17–19**, plus **cross-cutting latency** (**LATENCY-01 … LATENCY-21**) with **`app/ui.py`** vs **`playground.py`** / **`prompt_builder.py`** touchpoints. **Semi-automatic drift nudge:** Cursor **`afterFileEdit`** hook → **`scripts/ux_log_drift_check.py`** (see UX log “Keeping this log in sync”). Session narrative + dates: **`docs/handoffs/SESSION_SYNC_LOG.md`** (bottom entries).

---

# Lane 1 — Memory

This stays exactly as the core plan:

### Increment M1 — Memory audit and backup

* inspect `memory/extracted_memory.json`
* inspect `memory/current_state.json`
* back up both
* identify canonical identity/project/preference/goal rows
* run regression

### Increment M2 — Canonical memory pack hardening

* strengthen only the 4 core rows
* make them retrieval-eligible
* keep IDs unique
* regression again

### Increment M3 — Cold-start validation

Test fresh session prompts:

* `What do you know about me?`
* `What project is this?`
* `What are we doing?`
* `hi`

### Increment M4 — Bootstrap memory path

If cold start is still weak:

* implement pinned canonical memory IDs
* keep this narrow and controlled

### Increment M5 — Regression coverage

Protect memory continuity with regression scenarios for cold-start prompts

That part stands. 

---

# Lane 2 — Input UX

This is the new required lane.

## Objective

Make the UI practical for real operator use:

* large multi-line paste must work
* document-style text dump must work
* microphone input must work
* none of this should destabilize the assistant loop

---

## Increment U1 — Input box audit

### Goal

Find out why pasted multi-line text is failing or becoming unstable.

### Focus file

* `app/ui.py`

### Tasks

* inspect current input widget choice
* inspect how pasted text is handed to `playground.handle_user_input`
* inspect whether the UI assumes short single-message chat input
* inspect any trimming / line-splitting / rerun behavior that may break large pasted text
* inspect whether Enter vs Shift+Enter behavior is part of the issue

### Exit criteria

We know exactly why:

* long paste breaks
* multi-line input behaves badly
* the UI "goes berserk"

This is diagnosis only, plus regression check if anything minor changes.

---

## Increment U2 — Large paste input mode

### Goal

Support reliable multi-line paste, including "dump a bunch of text" workflows.

### Recommended design

Add a **dedicated long-input mode** in `app/ui.py`, instead of forcing everything through a tiny chat box.

### Best first version

Two input paths:

* **Quick chat input** for short normal questions
* **Paste / long-form input box** for large blocks of text

### Expected behavior

The paste box should:

* support many lines
* preserve text cleanly
* not auto-fragment the input
* not submit unexpectedly
* send the full block as one message when the user clicks a button like:

  * `Send pasted text`
  * or `Submit long input`

### Why this is better

Trying to make one tiny chat box do everything is usually what causes chaos. A separate long-form input path is cleaner, safer, and easier to test.

### Exit criteria

You can paste a large block of text into the UI and submit it as one clean message.

---

## Increment U3 — Long-input handling guardrails

### Goal

Make sure large pasted text does not break downstream behavior.

### Tasks

* ensure `playground.handle_user_input` receives the full text as intended
* ensure the UI does not duplicate submission on rerender
* ensure long text does not accidentally trigger command parsing incorrectly
* ensure quoted text and literal control phrases do not get misread as commands
* ensure state reset / rerun behavior is stable after long submission

### Why this matters

Your handoff already mentions routing hardening and command interpretation guards. Large pasted text increases the chance of false command detection, so this needs protection. 

### Exit criteria

Large pasted text behaves like content, not like accidental UI/control noise.

---

## Increment U4 — Voice input design pass

### Goal

Add microphone input for speech-to-text.

### Requirement

You do **not** need voice output right now.
You do need:

* press mic
* talk
* convert speech to text
* send text into the same assistant flow

### Recommended first implementation

Use microphone input only as **text entry**, not a full duplex voice assistant.

### Flow

1. Click mic
2. Speak
3. Speech is transcribed to text
4. Transcript appears in the input area
5. You review if needed
6. Submit

### Why this is the right first version

It is simpler, safer, and avoids turning the UI into a full voice-agent system too early.

### Exit criteria

You can speak into the app and get usable text into the conversation flow.

---

## Increment U5 — Voice integration implementation

### Goal

Actually wire speech-to-text into the Streamlit UI.

### Surface

* `app/ui.py`

### Important design rule

Mic input should feed the **same message pipeline** as typed input.

That means:

* same handler
* same memory behavior
* same journaling
* same routing

Do not create a second assistant logic path just for voice.

### Exit criteria

Typed and spoken input both become normal user messages.

---

## Increment U6 — Input UX regression / manual checklist

### Goal

Protect the UI from becoming fragile again.

### Manual acceptance checklist

* short typed input works
* multi-line paste works
* very large pasted note works
* no accidental double-submit
* no accidental command execution from quoted text
* microphone transcript works
* transcript submits like normal text
* conversation remains stable after rerenders

### Optional automated coverage

If practical, add narrow tests around any input-normalization helpers you create.
But because UI behavior can be harder to fully regression-test, keep a manual operator checklist too.

---

# Recommended order now

Do **not** do memory and voice at the same exact time.

Here is the order I recommend:

## Batch A — Input usability first

1. **U1 — Input box audit**
2. **U2 — Large paste input mode**
3. **U3 — Long-input handling guardrails**

Reason: if you cannot paste properly, you are handicapped while trying to build/test memory.

## Batch B — Memory spine

4. **M1 — Memory audit and backup**
5. **M2 — Canonical memory pack hardening**
6. **M3 — Cold-start validation**

Reason: once input is usable, memory work becomes much easier to test.

## Batch C — Reliability upgrades

7. **M4 — Bootstrap memory path**
8. **M5 — Memory regression coverage**

## Batch D — Voice

9. **U4 — Voice input design pass**
10. **U5 — Voice integration**
11. **U6 — Manual acceptance checklist**

Reason: voice is absolutely important, but paste stability is the more immediate operator bottleneck.

---

# What to send Cursor

You can paste this:

```md
We are now working on two coordinated lanes for ai-agent:

Lane 1: durable memory
Lane 2: operator input UX

Non-negotiable UX requirements:
1. The UI must support large multi-line paste without breaking.
2. I must be able to dump large text blocks/doc-style text into the app as one submission.
3. I must be able to speak into the app with my microphone and have speech converted to text.
4. Voice output is not required right now.
5. Keep the app efficient and stable.

Implementation constraints:
- full-file replacements only
- one increment at a time
- keep playground.py as orchestration if possible
- prefer UI work in app/ui.py
- prefer memory work in services/memory_service.py and services/prompt_builder.py
- regression must stay green after each code increment

Execution order:
A. Input usability first
- U1: audit current input behavior in app/ui.py and identify why large paste/multiline input becomes unstable
- U2: implement a dedicated long-form paste input mode separate from quick chat input
- U3: add guardrails so large pasted text is handled as content, not accidental control commands

B. Memory next
- M1: audit and back up memory files
- M2: strengthen a tiny canonical memory pack (identity, project, preference, goal)
- M3: validate cold-start memory behavior

C. If needed
- M4: implement narrow bootstrap memory using pinned canonical memory IDs
- M5: add regression coverage for cold-start continuity

D. Voice after paste stability
- U4: design simple speech-to-text input flow
- U5: wire microphone transcription into the same normal message pipeline
- U6: run a manual acceptance checklist for typed, pasted, and voice input
```

---

# My recommendation for the very next increment

Start with:

**U1 — Input box audit**

That is the right next move, because before we do anything else, we need to understand why the current UI cannot handle large pasted text properly. After that, Cursor should implement **U2 — dedicated long-form paste mode**.

That gives you immediate relief and makes the rest of the project easier.
