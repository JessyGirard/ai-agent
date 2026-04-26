# System Eval Report: httpbin_jsonplaceholder_full

- Target: `unspecified-target`
- Status: `FAIL`
- Run at (UTC): `2026-04-25T23:47:36.270470+00:00`
- Executed cases: `8`
- Passed: `7`
- Failed: `1`
- Elapsed seconds: `7.837`

## Case Results

- `PASS` `GET httpbin basic` lane=`smoke` (GET https://httpbin.org/get)
- `FAIL` `GET with query params` lane=`smoke` (GET https://httpbin.org/get)
  - expected_json missing path: {"path": "args.name"}
  - expected_json missing path: {"path": "args.role"}
- `PASS` `POST json body` lane=`smoke` (POST https://httpbin.org/anything)
- `PASS` `PUT update` lane=`smoke` (PUT https://httpbin.org/put)
- `PASS` `PATCH partial update` lane=`smoke` (PATCH https://httpbin.org/patch)
- `PASS` `DELETE request` lane=`smoke` (DELETE https://httpbin.org/delete)
- `PASS` `GET real post` lane=`smoke` (GET https://jsonplaceholder.typicode.com/posts/1)
- `PASS` `GET all posts (latency check)` lane=`smoke` (GET https://jsonplaceholder.typicode.com/posts)
