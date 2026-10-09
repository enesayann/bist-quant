import { Link } from "react-router-dom";
import { AlertCircle, ArrowLeft, Database, ShieldCheck } from "lucide-react";
import type { AnalysisResponse } from "../api/types";
import { StockPriceChart } from "./Charts";
import { Badge, Button, Card, CardHeading, ScoreBar } from "./ui";
import { money, percent } from "../lib/format";
import { AnalysisExplanation } from "./AnalysisExplanation";

const categories = ["trend", "momentum", "volume", "volatility"] as const;
const names = {
  trend: "Trend",
  momentum: "Momentum",
  volume: "Volume",
  volatility: "Volatility",
};
const indicatorLabels: Record<keyof AnalysisResponse["indicators"], string> = {
  rsi: "RSI",
  ema20: "EMA 20",
  ema50: "EMA 50",
  ema200: "EMA 200",
  atr: "ATR",
  adx: "ADX",
  macd: "MACD",
  macd_signal: "MACD signal",
  mfi: "MFI",
  cmf: "CMF",
  obv: "OBV",
  vwap: "Daily VWAP approximation",
  historical_volatility_pct: "Historical volatility (%)",
  supertrend: "SuperTrend direction",
};
const number = (value: number | null) =>
  value === null
    ? "Unavailable"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(
        value,
      );

export function RealAnalysis({
  result,
  refresh,
  loading,
  error,
  analysisOnly = false,
}: {
  result: AnalysisResponse;
  refresh(): void;
  loading: boolean;
  error: string | null;
  analysisOnly?: boolean;
}) {
  const time = new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Istanbul",
  }).format(new Date(result.as_of));
  return (
    <>
      {!analysisOnly && (
        <>
          <Link className="back-link" to="/scanner">
            <ArrowLeft size={14} />
            Market Scanner · Demo basket
          </Link>
          <div className="stock-heading">
            <div className="stock-identity">
              <span className="stock-avatar">{result.ticker.slice(0, 2)}</span>
              <div>
                <h1>
                  {result.ticker}
                  <Badge>BIST · {result.symbol}</Badge>
                </h1>
                <p>{result.strategy.name} · Completed daily close analysis</p>
              </div>
            </div>
            <div className="stock-quote">
              <strong>{money(result.market.price)}</strong>
              <span
                className={
                  result.market.change_pct >= 0 ? "positive" : "negative"
                }
              >
                {percent(result.market.change_pct, true)}
                <small>vs previous usable close</small>
              </span>
            </div>
          </div>
        </>
      )}
      <div className="analysis-provenance">
        <div>
          <Badge tone="accent">Research / Paper Trading</Badge>
          <Badge
            tone={result.data_freshness.is_stale ? "negative" : "positive"}
          >
            {result.data_freshness.is_stale
              ? "Stale / review data"
              : "Latest expected weekday"}
          </Badge>
          <Badge>
            {result.cache.hit
              ? `API cache · ${result.cache.age_seconds.toFixed(0)}s old`
              : "API analysis"}
          </Badge>
        </div>
        <Button onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh analysis"}
        </Button>
        <p>
          Quant analysis as of {time} TRT · Analysis bar{" "}
          {result.data_freshness.last_bar} · Market status unknown
        </p>
      </div>
      {loading && (
        <p className="analysis-loading" role="status">
          Refreshing from the Analysis API. Showing the previous analysis
          snapshot until it succeeds.
        </p>
      )}
      {error && (
        <div className="analysis-error" role="alert">
          <AlertCircle size={17} />
          <div>
            <strong>Refresh failed</strong>
            <p>{error}</p>
            <p>
              The previous successful snapshot remains above; no demo values
              have been substituted.
            </p>
          </div>
        </div>
      )}
      {!analysisOnly && (
        <StockPriceChart
          history={result.price_series}
          ticker={result.ticker}
          provenance="api"
        />
      )}
      <div className="section-label">
        <h2>Technical snapshot</h2>
        <span>Existing engine category points</span>
      </div>
      <div className="analytics-grid">
        {categories.map((category) => (
          <Card className="analytics-card" key={category}>
            <div className="metric-label">
              <span>{names[category]}</span>
              <Database size={16} />
            </div>
            <div className="analytics-value">
              <strong>
                {number(result.scores[category])}
                <small>/{result.scores.category_maxima[category]}</small>
              </strong>
              <Badge>Engine score</Badge>
            </div>
            <ScoreBar
              value={
                (result.scores[category] /
                  result.scores.category_maxima[category]) *
                100
              }
              label={`${names[category]} relative to engine category maximum`}
            />
            <p>Original category scale · No reweighting</p>
          </Card>
        ))}
      </div>
      <div className="stock-bottom">
        <Card>
          <CardHeading
            title="Current strategy"
            subtitle={result.strategy.name}
            action={
              <Badge
                tone={result.strategy.state === "setup" ? "positive" : "muted"}
              >
                {result.strategy.state === "setup" ? "Setup" : "No setup"}
              </Badge>
            }
          />
          <div className="strategy-overall">
            <div>
              <span>Final score · Technical-only scope</span>
              <strong>
                {number(result.scores.overall)}
                <small>/100</small>
              </strong>
            </div>
            <div className="score-ring">
              <ShieldCheck size={22} />
              <span>
                Research only
                <br />
                No execution
              </span>
            </div>
          </div>
          <dl className="analysis-list">
            <div>
              <dt>Technical score</dt>
              <dd>{number(result.scores.technical)} / 100</dd>
            </div>
            <div>
              <dt>Support / resistance adjustment</dt>
              <dd>{number(result.scores.support_resistance_adjustment)}</dd>
            </div>
            <div>
              <dt>Engine signal type</dt>
              <dd>{result.strategy.signal ?? "None"}</dd>
            </div>
            <div>
              <dt>Engine classification</dt>
              <dd>
                {result.strategy.classification ?? "Unavailable · No setup"}
              </dd>
            </div>
            <div>
              <dt>Fundamentals / news</dt>
              <dd>Unavailable / Unavailable</dd>
            </div>
          </dl>
          <p className="card-bottom-note">
            Missing fundamentals/news contribute zero to the unchanged engine
            formula. They are not measured scores. Technical denominator remains
            80.
          </p>
        </Card>
        <div className="stock-side">
          <Card>
            <CardHeading
              title="Risk & volatility"
              subtitle="Derived from the existing engine"
            />
            <div className="performance-grid">
              <div>
                <span>ATR / close</span>
                <strong>
                  {result.risk.atr_pct === null
                    ? "Unavailable"
                    : percent(result.risk.atr_pct)}
                </strong>
              </div>
              <div>
                <span>Historical vol.</span>
                <strong>
                  {result.indicators.historical_volatility_pct === null
                    ? "Unavailable"
                    : percent(result.indicators.historical_volatility_pct)}
                </strong>
              </div>
              <div>
                <span>Volatility state</span>
                <strong className="unavailable-value">
                  {result.risk.volatility_state ?? "Unavailable"}
                </strong>
              </div>
              <div>
                <span>Previous close</span>
                <strong>{money(result.market.previous_close)}</strong>
              </div>
            </div>
          </Card>
          <Card>
            <CardHeading
              title="Data quality"
              subtitle="Existing Yahoo ingestion validation"
            />
            <dl className="analysis-list">
              <div>
                <dt>Downloaded rows</dt>
                <dd>{result.data_quality.rows_downloaded}</dd>
              </div>
              <div>
                <dt>Removed rows</dt>
                <dd>{result.data_quality.rows_removed}</dd>
              </div>
              <div>
                <dt>Usable rows</dt>
                <dd>{result.data_quality.usable_rows}</dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>
      <Card className="indicator-card">
        <CardHeading
          title="Indicator values"
          subtitle="Existing daily calculations · Unavailable values remain null"
          action={<Badge>Engine data</Badge>}
        />
        <dl className="indicator-grid">
          {(
            Object.keys(indicatorLabels) as Array<
              keyof AnalysisResponse["indicators"]
            >
          ).map((key) => (
            <div key={key}>
              <dt>{indicatorLabels[key]}</dt>
              <dd>{number(result.indicators[key])}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <AnalysisExplanation explanation={result.explanation} />
      <Card className="methodology-card">
        <CardHeading
          title="Scope & provider notes"
          subtitle="Read-only deterministic analysis"
        />
        <ul>
          {[...result.warnings, ...result.data_quality.warnings].map(
            (warning, index) => (
              <li key={index}>{warning}</li>
            ),
          )}
        </ul>
        <p className="card-bottom-note">
          {result.disclaimer} Portfolio performance, paper levels and historical
          trade statistics are not part of this real analysis.
        </p>
      </Card>
    </>
  );
}
