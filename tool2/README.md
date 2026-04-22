# Tool 2 Workspace

This folder exists so Tool 2 is visible as a first-class area in the project explorer.

Current Tool 2 runtime pieces:

- UI panel: `app/ui.py` (`Tool 2` surface)
- Operator runner: `app/system_eval_operator.py` (`run_tool2_prompt_response_eval`)
- Core lane execution: `core/system_eval.py` (`lane: "prompt_response"`)
- Sample suite: `system_tests/suites/tool2_prompt_demo/tool2_prompt_response_smoke.json`

Use this folder for upcoming Tool 2-specific assets (schemas, examples, docs, and utilities).
