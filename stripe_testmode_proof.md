# System Eval Report: stripe_testmode_proof

- Target: `operator`
- Status: `FAIL`
- Executed cases: `2`
- Passed: `1`
- Failed: `1`
- Elapsed seconds: `1.886`

## Case Results

- `FAIL` `account_info_smoke` lane=(none) (GET https://api.stripe.com/v1/account)
  - expected_status mismatch: expected 200, got 401
  - expected_json_exists missing path: {"path": "id"}
  - expected_json_exists missing path: {"path": "object"}
- `PASS` `balance_smoke` lane=(none) (GET https://api.stripe.com/v1/balance)
