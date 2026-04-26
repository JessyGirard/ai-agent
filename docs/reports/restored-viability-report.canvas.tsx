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

export default function RestoredViabilityReport() {
  return (
    <Stack gap={20}>
      <H1>AI Agent Project Viability Diagnostic</H1>
      <Text tone="secondary" size="small">
        Final restored canvas version (click Open from canvas card).
      </Text>
      <Text tone="secondary">
        Snapshot basis: repository structure, reliability evidence, regression
        harness health, architecture decomposition, and current operational risks.
      </Text>

      <Grid columns={3} gap={16}>
        <Stat label="Success Probability" value="72%" tone="success" />
        <Stat label="Failure Probability" value="28%" tone="warning" />
        <Stat label="Forecast Confidence" value="61%" tone="info" />
      </Grid>

      <Callout tone="info" title="Bottom line">
        The project has stronger-than-average odds because it has real
        architecture separation and test-gated increments. Main downside risk is
        behavior-format drift and product-fit uncertainty, not structural collapse.
      </Callout>

      <Divider />

      <H2>Weighted Score Inputs</H2>
      <Table
        headers={["Factor", "Weight", "Score", "Contribution", "Evidence"]}
        rows={[
          ["Architecture and modularity", "20%", "78", "15.6", "Core/services/ui split with playground as orchestrator"],
          ["Testing and reliability discipline", "25%", "82", "20.5", "Regression harness + soak + CI/nightly gates"],
          ["Operational maintainability", "15%", "67", "10.1", "Growing prompt policy complexity and doc drift risk"],
          ["Product behavior consistency", "20%", "58", "11.6", "Occasional format/routing misfit on conversational prompts"],
          ["Execution momentum and delivery readiness", "20%", "71", "14.2", "Strong handoffs, runbooks, and operating rhythm"],
        ]}
      />
      <Text tone="secondary" size="small">
        Aggregate weighted score: 72.0 / 100 (interpreted as 72% success probability).
      </Text>

      <Divider />

      <H2>Strengths</H2>
      <Table
        headers={["Strength", "Impact"]}
        rows={[
          ["Service-oriented architecture", "Safer targeted fixes without full rewrites"],
          ["Regression-first quality gate", "Lower silent breakage risk during iteration"],
          ["Clear orchestration path", "Faster runtime tracing and debugging"],
          ["Operational documentation", "Repeatable workflow instead of ad-hoc execution"],
        ]}
      />

      <H2>Primary Risks</H2>
      <Table
        headers={["Risk Driver", "Impact if Unchecked"]}
        rowTone={["warning", "warning", "warning", "warning"]}
        rows={[
          ["Prompt enforcement collisions", "Assistant can sound rigid or over-templated"],
          ["Routing edge-case misses", "Normal prompts can enter wrong response mode"],
          ["Doc-to-runtime drift", "Trust drops when recorded status lags real state"],
          ["Product-fit uncertainty", "Engineering strength may not equal daily workflow fit"],
        ]}
      />

      <H2>Failure Scenario Split (28%)</H2>
      <Table
        headers={["Scenario", "Share", "Notes"]}
        rows={[
          ["Behavior quality drift persists", "10%", "Template-heavy responses reduce usability"],
          ["Operational complexity slows iteration", "7%", "More rules can increase diagnosis time"],
          ["Delivery consistency drops", "6%", "Workflow mismatches delay safe change"],
          ["External/market mismatch", "5%", "Technical success does not guarantee adoption"],
        ]}
      />

      <Row gap={10}>
        <Pill tone="success">Strong engineering base</Pill>
        <Pill tone="warning">Behavior consistency risk</Pill>
        <Pill tone="info">Moderate forecast confidence</Pill>
      </Row>
    </Stack>
  );
}
