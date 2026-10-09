import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useHistory, useQuote } from "../market/useMarket";
import { useAnalysis } from "../api/context";
import { analyzeStock } from "../api/analysis";
import { Badge, Button, Card, CardHeading } from "../components/ui";
import {
  FreshnessBadge,
  marketTime,
  MarketError,
  MarketStatusBadge,
} from "../components/MarketData";
import { StockPriceChart } from "../components/Charts";
import { RealAnalysis } from "../components/RealAnalysis";
import { money, percent, shortNumber } from "../lib/format";

export function MarketStockDetail({ symbol }: { symbol: string }) {
  const quote = useQuote(symbol);
  const history = useHistory(symbol);
  const { results, save } = useAnalysis();
  const result = results[symbol];
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function analyze() {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      save(await analyzeStock(symbol));
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setLoading(false);
    }
  }
  const data = quote.data;
  return (
    <>
      <Link className="back-link" to="/scanner">
        <ArrowLeft size={14} />
        Market Scanner
      </Link>
      <div className="stock-heading">
        <div className="stock-identity">
          <span className="stock-avatar">{symbol.slice(0, 2)}</span>
          <div>
            <h1>
              {symbol}
              <Badge>BIST · {symbol}.IS</Badge>
            </h1>
            <p>Market data · Quant analysis kept separately</p>
          </div>
        </div>
        <div className="stock-quote">
          <strong>
            {data?.price == null
              ? "Unavailable"
              : data.currency === "TRY"
                ? money(data.price)
                : `${data.price.toFixed(2)} ${data.currency ?? "(currency unknown)"}`}
          </strong>
          <span
            className={
              data?.change_pct == null
                ? "muted"
                : data.change_pct >= 0
                  ? "positive"
                  : "negative"
            }
          >
            {data?.change_pct == null
              ? "Change unavailable"
              : percent(data.change_pct, true)}
            <small>
              {data?.price_basis === "last_completed_close"
                ? "Last completed close"
                : "Provider quote · Delay not guaranteed"}
            </small>
          </span>
        </div>
      </div>
      <div className="analysis-provenance">
        <div>
          <Badge tone="accent">Market data</Badge>
          <MarketStatusBadge
            status={
              quote.error ? "unknown" : (data?.market_status ?? "unknown")
            }
          />
          <FreshnessBadge
            status={
              quote.error && data
                ? "stale"
                : (data?.freshness_status ?? "unknown")
            }
          />
        </div>
        <Button
          onClick={() => void quote.refresh()}
          disabled={quote.refreshing}
        >
          {quote.refreshing ? "Updating…" : "Refresh quote"}
        </Button>
        <p>
          Quote timestamp {marketTime(data?.quote_time ?? null)} · Last
          completed bar {marketTime(data?.last_bar_time ?? null)} · Retrieved{" "}
          {marketTime(data?.fetched_at ?? null)} ·{" "}
          {data?.provider ?? "Provider unavailable"}
        </p>
      </div>
      {quote.error && (
        <MarketError
          message={quote.error}
          retry={() => void quote.refresh()}
          retained={!!data}
        />
      )}
      {!data && !quote.error && (
        <p className="market-loading" role="status">
          Loading provider quote…
        </p>
      )}
      {data && (
        <Card className="market-day-card">
          <div className="performance-grid">
            {[
              ["Day open", data.day_open],
              ["Day high", data.day_high],
              ["Day low", data.day_low],
              ["Volume", data.volume],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <span>{label}</span>
                <strong>
                  {value === null
                    ? "Unavailable"
                    : label === "Volume"
                      ? shortNumber(Number(value))
                      : data.currency === "TRY"
                        ? money(Number(value))
                        : Number(value).toFixed(2)}
                </strong>
              </div>
            ))}
          </div>
        </Card>
      )}
      {history.error && (
        <MarketError
          message={history.error}
          retry={() => void history.refresh()}
          retained={!!history.data}
        />
      )}
      {history.data ? (
        <>
          <StockPriceChart
            history={history.data.points.map((point) => ({
              date: point.date,
              value: point.close,
            }))}
            ticker={symbol}
            provenance="api"
          />
          <div className="history-provenance">
            <FreshnessBadge
              status={history.error ? "stale" : history.data.freshness_status}
            />
            <span>
              History: completed daily bars only · Retrieved{" "}
              {marketTime(history.data.fetched_at)} · {history.data.provider}
            </span>
            <Button
              variant="ghost"
              onClick={() => void history.refresh()}
              disabled={history.refreshing}
            >
              Refresh history
            </Button>
          </div>
        </>
      ) : (
        !history.error && (
          <Card className="market-loading" role="status">
            Loading completed daily history…
          </Card>
        )
      )}
      <div className="section-label">
        <h2>Quant analysis</h2>
        <span>On demand · Never recalculated by quote polling</span>
      </div>
      {result ? (
        <RealAnalysis
          result={result}
          refresh={() => void analyze()}
          loading={loading}
          error={error}
          analysisOnly
        />
      ) : (
        <Card className="analysis-request-card">
          <CardHeading
            title="Daily Strategy v1"
            subtitle="Strategy scores are unavailable until analysis is requested."
            action={<Badge>On demand</Badge>}
          />
          <div>
            <Button
              variant="accent"
              onClick={() => void analyze()}
              disabled={loading}
            >
              {loading ? "Analyzing…" : "Analyze Daily v1"}
            </Button>
            {error && (
              <p className="negative" role="alert">
                {error}
              </p>
            )}
            <p>
              Market quotes do not feed back into the protected analysis engine.
              Analysis uses its own completed-candle data and timestamp.
            </p>
          </div>
        </Card>
      )}
      {data?.warnings.length || history.data?.quality.warnings.length ? (
        <Card className="methodology-card">
          <CardHeading title="Market data quality notes" />
          <ul>
            {Array.from(
              new Set([
                ...(data?.warnings ?? []),
                ...(history.data?.quality.warnings ?? []),
              ]),
            ).map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Card>
      ) : null}
    </>
  );
}
