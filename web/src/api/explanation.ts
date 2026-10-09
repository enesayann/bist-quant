export interface ExplanationEvidence {
  rule_id: string;
  inputs: Record<string, number>;
  observation: string;
  derived: boolean;
}
export interface ExplanationComponent {
  state: string;
  headline: string;
  points: string[];
  evidence: ExplanationEvidence[];
  missing_inputs: string[];
}
export interface AnalysisExplanation {
  rules_version: "analysis-explanation-v1";
  scope: string;
  analysis_as_of: string | null;
  analysis_last_bar: string | null;
  market_status: string;
  trend: ExplanationComponent;
  momentum: ExplanationComponent;
  volume: ExplanationComponent;
  risk: ExplanationComponent;
  summary: { headline: string; text: string };
  warnings: string[];
}
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string");
const states = [
  "bullish",
  "bearish",
  "mixed",
  "neutral",
  "unknown",
  "weak",
  "positive",
  "strong",
  "overextended",
  "negative",
  "moderate",
  "low",
  "elevated",
  "high",
];

// Explanation is optional: a legacy or malformed narrative never hides valid numbers.
export function readExplanation(
  value: unknown,
  asOf: string,
  lastBar: string,
): AnalysisExplanation | null {
  if (
    !object(value) ||
    value.rules_version !== "analysis-explanation-v1" ||
    value.analysis_as_of !== asOf ||
    value.analysis_last_bar !== lastBar ||
    typeof value.scope !== "string" ||
    typeof value.market_status !== "string" ||
    !strings(value.warnings)
  )
    return null;
  if (
    !object(value.summary) ||
    typeof value.summary.headline !== "string" ||
    typeof value.summary.text !== "string"
  )
    return null;
  for (const key of ["trend", "momentum", "volume", "risk"]) {
    const part = value[key];
    if (
      !object(part) ||
      !states.includes(String(part.state)) ||
      typeof part.headline !== "string" ||
      !strings(part.points) ||
      !strings(part.missing_inputs) ||
      !Array.isArray(part.evidence)
    )
      return null;
    for (const evidence of part.evidence) {
      if (
        !object(evidence) ||
        typeof evidence.rule_id !== "string" ||
        typeof evidence.observation !== "string" ||
        typeof evidence.derived !== "boolean" ||
        !object(evidence.inputs) ||
        !Object.values(evidence.inputs).every(
          (value) => typeof value === "number" && Number.isFinite(value),
        )
      )
        return null;
    }
  }
  return value as unknown as AnalysisExplanation;
}
