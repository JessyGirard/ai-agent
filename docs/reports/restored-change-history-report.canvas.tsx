import {
  Callout,
  Divider,
  Grid,
  H1,
  H2,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
} from "cursor/canvas";

export default function RestoredChangeHistoryReport() {
  return (
    <Stack gap={20}>
      <H1>AI-Agent Chronological Change Report</H1>
      <Text tone="secondary">
        Evidence: git history, changelog, session sync log, handoff docs, and
        recent system-eval artifacts.
      </Text>

      <Grid columns={4} gap={12}>
        <Stat label="Current Gate Anchor" value="499 / 499 (doc)" tone="info" />
        <Stat label="Latest Commit Window" value="Apr 25, 2026" tone="success" />
        <Stat label="Architecture Risk" value="Moderate, controlled" tone="warning" />
        <Stat label="Breakage Danger" value="Not imminent" tone="success" />
      </Grid>

      <Callout tone="success" title="Health verdict">
        Structure is stable. The strongest risk is policy complexity drift, not
        architectural collapse.
      </Callout>

      <Divider />

      <H2>System Architecture Map</H2>
      <Table
        headers={["Layer", "Primary Components", "Role"]}
        rows={[
          ["Operator Surface", "app/ui.py", "Collect input, show outputs, run tools"],
          ["Runtime Orchestrator", "playground.py", "Route requests and coordinate services"],
          ["Prompt + Routing", "services/prompt_builder.py, services/routing_service.py", "Build system prompts and choose response mode"],
          ["Memory + Journal", "services/memory_service.py, services/journal_service.py", "Retrieve/store context and history"],
          ["LLM Adapter", "core/llm.py", "Execute model calls via OpenAI path"],
          ["API Testing Engine", "core/system_eval.py", "Run single/suite HTTP evals and return results"],
          ["Artifacts + Logs", "logs/system_eval/*, app/tool1_run_log.py", "Persist run evidence and summaries"],
          ["Regression Gate", "tests/run_regression.py", "Protect behavior during incremental change"],
        ]}
      />

      <Divider />

      <H2>Chronological What Changed and Why</H2>
      <Table
        headers={["Window", "What Changed", "Why", "Outcome"]}
        rows={[
          ["Apr 15-16", "Foundation + memory/reliability hardening", "Stabilize core before scaling", "Safer baseline behavior"],
          ["Apr 17 (early)", "Service extraction from playground", "Reduce monolith risk", "Lower blast radius per change"],
          ["Apr 17 (mid)", "Tool 1/system-eval expansions", "Make API testing operator-usable", "Usable workflow with artifacts"],
          ["Apr 17 (late)", "FETCH browser increments + diagnostics", "Handle harder sites with observability", "Better failure classification"],
          ["Apr 18", "Multi-step scenario engine", "Support realistic API sequences", "Templates/steps/variables shipped"],
          ["Apr 19", "Retrieval/packaging/runtime quality series", "Improve grounding and anti-speculation", "Stronger prompt behavior control"],
          ["Apr 22-25", "API runner awareness and response hardening", "Reduce generic replies, improve diagnosis", "Sharper next-test guidance"],
        ]}
      />

      <Divider />

      <H2>Current Stability Assessment</H2>
      <Table
        headers={["Area", "Status", "Interpretation"]}
        rowTone={["success", "success", "warning", "warning", "info"]}
        rows={[
          ["Architecture modularity", "Good", "Service boundaries support targeted safe edits"],
          ["Regression discipline", "Strong", "Incremental changes are usually test-gated"],
          ["Prompt/routing complexity", "Growing risk", "Layered instructions can collide"],
          ["Doc/runtime alignment", "Moderate risk", "Multiple anchors can drift without refresh"],
          ["Operator usability", "Improving", "API runner flow is more context-aware now"],
        ]}
      />

      <H2>Recommended Next 3 Actions</H2>
      <Table
        headers={["Priority", "Action", "Expected Outcome"]}
        rows={[
          ["1", "Run full regression gate and refresh one canonical baseline", "Single source of truth"],
          ["2", "Consolidate overlapping prompt/routing policies", "Lower behavior collisions"],
          ["3", "Maintain end-to-end API-runner smoke checks", "Protect workflow continuity"],
        ]}
      />

      <Row gap={8}>
        <Pill tone="success">Structure stable</Pill>
        <Pill tone="warning">Complexity needs pruning</Pill>
        <Pill tone="info">Focus on consolidation</Pill>
      </Row>
    </Stack>
  );
}
