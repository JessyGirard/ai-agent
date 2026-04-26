# API Testing Basics

## 1. HTTP Methods

- `GET`: Retrieve data. Typical success status: `200 OK`. Usually no request body.
- `POST`: Create a resource. Typical success status: `201 Created`. Usually includes request body.
- `PUT`: Replace an entire existing resource. Typical success statuses: `200 OK` or `204 No Content`.
- `PATCH`: Update part of a resource. Typical success statuses: `200 OK` or `204 No Content`.
- `DELETE`: Remove a resource. Typical success statuses: `200 OK` or `204 No Content`.

## 2. Status Codes

- `200 OK`: Request succeeded and response body is returned.
- `201 Created`: Resource created successfully.
- `204 No Content`: Request succeeded with no response body.
- `400 Bad Request`: Invalid request format, parameters, or body.
- `401 Unauthorized`: Missing or invalid authentication credentials.
- `403 Forbidden`: Authenticated but not allowed to access this resource.
- `404 Not Found`: Endpoint or resource does not exist.
- `405 Method Not Allowed`: Method is wrong for endpoint; check `Allow` header for supported methods.
- `415 Unsupported Media Type`: Body format is not accepted (for example, wrong `Content-Type`).
- `429 Too Many Requests`: Rate limit exceeded; retry after waiting.

## 3. Headers

- `Content-Type`: Declares request body format (for example, `application/json`).
- `Authorization`: Carries credentials (for example, `Bearer <token>`).
- Practical check: invalid or missing headers should return clear errors (`400`, `401`, or `415` depending on API rules).

## 4. Testing Strategies

- **Positive testing**: Send valid request and verify expected status, headers, and key response fields.
- **Negative testing**: Send invalid inputs (missing auth, wrong method, bad body) and verify correct error codes.
- **Boundary testing**: Test limits (min/max values, empty strings, large payloads) and verify stable behavior.
- Practical rule: every endpoint should have at least one positive test and one negative test.

## 5. Customer Intake Questions

- What endpoint (URL) should be tested?
- What HTTP method should be used (`GET`, `POST`, etc.)?
- Is authentication required? If yes, what type (`API key`, `Bearer token`, etc.)?
- What is the expected success status code?
- What should a successful response contain (key fields)?
- Is there test data we should use?
- What error cases should be validated?
- Are there rate limits?
- Is this a test or production environment?
- Do you require proof or test reports?

## 6. Authentication Testing

- `401 Unauthorized` usually means credentials are missing, invalid, or expired.
- `403 Forbidden` usually means authentication is valid, but access is not allowed for this user/token.
- Common auth method: `Authorization` header with `Bearer <token>`.
- Typical mistakes:
  - missing `Authorization` header
  - malformed token
  - expired token
- Practical test cases:
  - request with no auth -> expect `401`
  - request with invalid token -> expect `401`
  - request with valid token -> expect `200` (or expected success status code)

## 7. Request Body Basics

- Request body = data sent with the request.
- Most commonly used with `POST`, `PUT`, and `PATCH`.
- `GET` usually does not need a body.
- Request body often contains JSON.
- `Content-Type` should usually match body format (for example, `application/json`).
- Practical test cases:
  - valid body -> expect success status
  - missing required field -> expect `400`
  - wrong data type -> expect `400`
  - malformed JSON -> expect `400` or `415` depending on API rules

## 8. Error Case Testing

- Purpose: verify the API fails correctly and safely.
- Common error types to test:
  - wrong HTTP method -> expect `405`
  - missing authentication -> expect `401`
  - invalid authentication -> expect `401` or `403`
  - missing required fields -> expect `400`
  - wrong data type -> expect `400`
  - malformed JSON -> expect `400` or `415`
  - unsupported `Content-Type` -> expect `415`
- Practical strategy:
  - include at least one negative test per endpoint
  - compare expected vs actual status code
  - check error response message (if available)
- Optional:
  - test rate limiting -> expect `429`

## 9. Proof and Client Reporting

- Purpose: show clear, trustworthy proof of testing results.
- What to include in a report:
  - endpoint tested (URL)
  - method used (`GET`, `POST`, etc.)
  - test case description (what was tested)
  - expected status vs actual status
  - key response fields (if relevant)
  - latency (response time)
- Optional but valuable:
  - screenshots or logs
  - JSON response excerpts
  - pass/fail summary
- Practical tips:
  - keep it simple and readable
  - highlight failures clearly
  - avoid unnecessary technical noise
  - focus on what matters to the client

## 10. Rate Limit Testing

- Purpose: prevent abuse by limiting number of requests.
- Common signal:
  - status code `429 Too Many Requests`
- Typical behavior:
  - API blocks or delays requests after a threshold
- Practical test cases:
  - send multiple rapid requests -> expect `429` after limit
  - verify retry works after waiting
- Useful checks:
  - presence of rate limit headers (if available)
  - clear error message when limit is hit

## 11. Test Case Design

- Purpose: define clear, repeatable tests for each endpoint.
- Basic structure:
  - endpoint (URL)
  - method (`GET`, `POST`, etc.)
  - input (headers, body, params)
  - expected status code
  - expected response (key fields)
- Types of test cases:
  - positive test (valid request)
  - negative test (invalid input, missing fields, wrong method)
- Practical rules:
  - at least one positive and one negative test per endpoint
  - keep tests simple and focused
  - compare expected vs actual results
- Optional:
  - include edge cases (large input, empty values, etc.)

## 12. Query Params and Path Params

- Path params:
  - part of the URL path (for example, `/users/123`)
  - used to identify a specific resource
- Query params:
  - added after `?` in URL (for example, `?limit=10&page=2`)
  - used for filtering, pagination, searching, and sorting
- Practical examples:
  - `GET /users/123` -> get one user
  - `GET /users?limit=10` -> get limited list
- Common mistakes:
  - missing required path param -> expect `404` or `400`
  - invalid query value -> expect `400`
- Testing ideas:
  - valid param -> expect success
  - invalid param -> expect error
  - missing param -> verify behavior

## 13. API Test Plan Response Style

- When asked what tests to run, do **not** dump a long category list.
- Start with one baseline test first.
- Baseline test must include:
  - method + endpoint
  - expected status
  - what to verify in the response
- Then give exactly one next test.
- Keep the answer short and execution-focused.
- Mention other possible tests only after the first test is complete, or if the user asks for more.
- Ask only necessary missing-info questions:
  - is authentication required?
  - what fields should the response contain?
  - is pagination supported?
- Practical response structure:
  - test description
  - expected result
  - next step

## 14. Pagination Testing

- Purpose: split large result sets into smaller pages.
- Common params:
  - `page`
  - `limit`
  - `offset`
  - `cursor`
- Practical test cases:
  - valid page + limit -> expect success
  - limit too high -> expect capped result or `400` depending on API
  - invalid page value -> expect `400`
  - empty page -> expect empty list with success status if supported
- Useful checks:
  - response includes expected number of items
  - pagination metadata if available
  - no duplicate/missing records between pages

## 15. Single vs Multi-Request Testing

- Single request:
  - used to test one endpoint quickly
  - good for debugging one issue
- Multi-request (test suite):
  - multiple requests grouped together
  - used to validate multiple endpoints or scenarios
  - useful for repeatable testing and proof
- JSON suite concept:
  - defines multiple test cases
  - each case includes method, URL, expected status, and checks
- Practical usage:
  - use single request for quick checks
  - use suite for full validation or client proof
- Simple workflow:
  - start with single request
  - confirm behavior
  - expand into suite for coverage
