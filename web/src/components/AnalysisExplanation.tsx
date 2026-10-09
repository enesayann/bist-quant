import { AlertCircle, FileText } from "lucide-react";
import type { AnalysisExplanation as Explanation } from "../api/explanation";
import { Badge, Card, CardHeading } from "./ui";

const labels: Record<string, string> = {
  analysis_close: "Analysis close",
  ema20: "EMA20",
  ema50: "EMA50",
  adx: "ADX",
  supertrend: "SuperTrend direction",
  rsi: "RSI",
  macd: "MACD",
  macd_signal: "MACD signal",
  mfi: "MFI",
  cmf: "CMF",
  obv: "OBV",
  vwap: "Daily VWAP approximation",
  atr: "ATR",
  atr_pct: "ATR %",
  "derived.atr_pct": "Derived ATR %",
  historical_volatility_pct: "Historical volatility %",
  analysis_volume: "Analysis-bar volume",
  relative_volume: "Relative volume",
};
const label = (key: string) => labels[key] ?? key.replaceAll("_", " ");
const number = (value: number) =>
  new Intl.NumberFormat("en-US", { maximumSignificantDigits: 8 }).format(value);

export function AnalysisExplanation({
  explanation,
}: {
  explanation: Explanation | null | undefined;
}) {
  if (!explanation)
    return (
      <Card className="explanation-unavailable">
        <CardHeading
          title="Analysis Explanation"
          subtitle="Numeric analysis remains available"
          action={<FileText size={17} />}
        />
        <p>
          Explanation is unavailable for this response. The numeric indicators
          and existing engine state are shown above.
        </p>
      </Card>
    );
  return (
    <section
      className="explanation-section"
      aria-labelledby="explanation-title"
    >
      <div className="section-label">
        <h2 id="explanation-title">Analysis Explanation</h2>
        <Badge tone="accent">Deterministic · Research / Paper Trading</Badge>
      </div>
      <p className="explanation-scope">
        Observations use the completed analysis candle (
        {explanation.analysis_last_bar ?? "date unavailable"}), not the provider
        quote. Labels describe indicator regions and do not recalculate strategy
        points.
      </p>
      <div className="explanation-grid">
        {(["trend", "momentum", "volume", "risk"] as const).map((key) => {
          const part = explanation[key];
          return (
            <Card className="explanation-card" key={key}>
              <CardHeading
                title={
                  key === "risk"
                    ? "Volatility / Risk"
                    : key[0].toUpperCase() + key.slice(1)
                }
                action={
                  <Badge tone={part.state === "unknown" ? "muted" : "accent"}>
                    {part.state.replaceAll("_", " ")}
                  </Badge>
                }
              />
              <h3>{part.headline}</h3>
              {part.points.length ? (
                <ul>
                  {part.points.map((point, index) => (
                    <li key={index}>{point}</li>
                  ))}
                </ul>
              ) : (
                <p className="explanation-empty">
                  No supported indicator observations are available for this
                  component.
                </p>
              )}
              {part.missing_inputs.length > 0 && (
                <p className="explanation-missing">
                  Unavailable: {part.missing_inputs.map(label).join(", ")}.
                </p>
              )}
              {part.evidence.length > 0 && (
                <details className="explanation-evidence">
                  <summary>Metrics behind these observations</summary>
                  <div>
                    {part.evidence.map((item, index) => (
                      <div key={item.rule_id + index}>
                        <strong>
                          {item.rule_id}
                          {item.derived && <Badge>Derived</Badge>}
                        </strong>
                        <dl>
                          {Object.entries(item.inputs).map(
                            ([metric, value]) => (
                              <div key={metric}>
                                <dt>{label(metric)}</dt>
                                <dd title={String(value)}>{number(value)}</dd>
                              </div>
                            ),
                          )}
                        </dl>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </Card>
          );
        })}
      </div>
      <Card className="explanation-summary">
        <CardHeading
          title="Quant Summary"
          subtitle={explanation.summary.headline}
        />
        <p>{explanation.summary.text}</p>
        <div className="explanation-warnings">
          {explanation.warnings.map((warning, index) => (
            <div
              key={index}
              role={
                warning.includes("may not represent the current session")
                  ? "status"
                  : undefined
              }
            >
              <AlertCircle size={14} />
              <p>{warning}</p>
            </div>
          ))}
        </div>
        <div className="card-bottom-note">
          {explanation.rules_version} · Observations, not price targets,
          forecasts or personalized risk assessment.
        </div>
      </Card>
    </section>
  );
}
