# Tool 3 (Regression Operator)

Tool 3 is the dedicated regression operator surface.

## Ownership

- `tool3_*` modules own Tool 3 orchestration and logging.
- Tool 3 must not reuse Tool 1 or Tool 2 operator internals.
- Shared logic belongs in neutral/shared modules only.

## Lane boundary

- Tool 3 will use its own explicit lane.
- Tool 3 cases and operator flows must stay lane-scoped and reject non-Tool-3 lanes.

## Status

- Transitioned from Tool 2 completion into Tool 3 kickoff.
- Initial implementation begins in the next increment.
