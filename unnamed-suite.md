# System Eval Report: unnamed-suite

- Target: `unspecified-target`
- Status: `FAIL`
- Executed cases: `1`
- Passed: `0`
- Failed: `1`
- Elapsed seconds: `1.409`

## Case Results

- `FAIL` `hard_pass_scenario` lane=(none) (POST https://httpbin.org/anything/issue-token)
  - step failed: {"step": "step1_issue_token"} body_json_path missing path: {"path": "json.auth.token"}
  - step failed: {"step": "step1_issue_token"} body_json_path missing path: {"path": "json.user.id"}
  ### Steps

  - step1_issue_token — FAIL — 1407 ms — https://httpbin.org/anything/issue-token
    - Reason: body_json_path missing path: {"path": "json.auth.token"} | body_json_path missing path: {"path": "json.user.id"}

