# System Eval Report: steps-demo

- Target: `operator`
- Status: `PASS`
- Run at (UTC): `2026-04-25T06:51:34.609119+00:00`
- Executed cases: `1`
- Passed: `1`
- Failed: `0`
- Elapsed seconds: `1.946`

## Case Results

- `PASS` `2-step simple test` lane=`smoke` (POST https://httpbin.org/post)
  ### Steps

  - step_1_get — PASS — 993 ms — https://httpbin.org/json
  - step_2_post — PASS — 948 ms — https://httpbin.org/post

