import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpDown,
  ArrowUpRight,
  CalendarDays,
  RefreshCw,
  Search,
} from "lucide-react";
import { useScanner } from "../market/useMarket";
import type { Freshness, MarketStatus, Quote } from "../market/types";
import { Badge, Button, Card, CardHeading } from "./ui";
import { PageHeader } from "./Layout";
import { money, percent, shortNumber } from "../lib/format";

export const marketTime = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat("en-GB", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Europe/Istanbul",
      }).format(new Date(value)) + " TRT"
    : "Unavailable";
export const statusLabel = (value: string) =>
  (
    ({
      open: "Open",
      closed: "Closed",
      pre_market_or_auction: "Pre-market / auction",
      holiday: "Holiday",
      unknown: "Unknown",
      fresh: "Fresh",
      delayed: "Delayed / provider",
      stale: "Stale",
      market_closed: "Market closed",
    }) as Record<string, string>
  )[value] ?? value;
export function FreshnessBadge({ status }: { status: Freshness }) {
  return (
    <Badge
      tone={
        status === "stale"
          ? "negative"
          : status === "delayed"
            ? "accent"
            : "muted"
      }
    >
      {statusLabel(status)}
    </Badge>
  );
}
export function MarketStatusBadge({ status }: { status: MarketStatus }) {
  return (
    <Badge tone={status === "open" ? "accent" : "muted"}>
      Market {statusLabel(status).toLowerCase()}
    </Badge>
  );
}
export function ApiMarketHeading() {
  const state = useScanner();
  return (
    <>
      <PageHeader
        title="Market Overview"
        description="Market monitoring & quantitative research."
      >
        <Badge tone="accent">Research / Paper Trading</Badge>
        <MarketStatusBadge
          status={
            state.error ? "unknown" : (state.data?.session.status ?? "unknown")
          }
        />
      </PageHeader>
      <div className="session-line">
        <CalendarDays size={14} />
        <span>
          Market snapshot {marketTime(state.data?.fetched_at ?? null)}
        </span>
        <span className="session-fixture">
          Provider data · No guaranteed real-time feed
        </span>
      </div>
    </>
  );
}
export function MarketError({
  message,
  retry,
  retained = false,
}: {
  message: string;
  retry(): void;
  retained?: boolean;
}) {
  return (
    <div className="market-error" role="alert">
      <div>
        <strong>Market data unavailable</strong>
        <p>{message}</p>
        {retained && (
          <p>
            Showing the last successful provider snapshot. It may be stale; no
            demo values were substituted.
          </p>
        )}
      </div>
      <Button onClick={retry}>Retry market data</Button>
    </div>
  );
}
export function RealScannerTable({
  rows,
  preview = false,
  retainedError = false,
}: {
  rows: Quote[];
  preview?: boolean;
  retainedError?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<{
    key: "ticker" | "price" | "change_pct" | "volume";
    direction: number;
  }>({ key: "ticker", direction: 1 });
  const visible = useMemo(
    () =>
      rows
        .filter(
          (row) =>
            row.ticker.toLowerCase().includes(query.toLowerCase().trim()) &&
            (filter === "all" || row.freshness_status === filter),
        )
        .sort((a, b) => {
          const left = a[sort.key],
            right = b[sort.key];
          if (left === null) return right === null ? 0 : 1;
          if (right === null) return -1;
          return (
            (typeof left === "string" && typeof right === "string"
              ? left.localeCompare(right)
              : Number(left) - Number(right)) * sort.direction
          );
        }),
    [rows, query, filter, sort],
  );
  const header = (label: string, key: typeof sort.key) => (
    <th
      aria-sort={
        sort.key === key
          ? sort.direction === 1
            ? "ascending"
            : "descending"
          : "none"
      }
    >
      <button
        className="sort-button"
        onClick={() =>
          setSort({ key, direction: sort.key === key ? -sort.direction : 1 })
        }
      >
        {label}
        <ArrowUpDown size={12} />
      </button>
    </th>
  );
  return (
    <>
      {!preview && (
        <div className="scanner-toolbar">
          <label className="search-input">
            <Search size={16} />
            <input
              aria-label="Search market ticker"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search ticker…"
            />
          </label>
          <label className="market-filter">
            Freshness
            <select
              aria-label="Filter market freshness"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">All states</option>
              {["fresh", "delayed", "stale", "market_closed", "unknown"].map(
                (value) => (
                  <option key={value} value={value}>
                    {statusLabel(value)}
                  </option>
                ),
              )}
            </select>
          </label>
        </div>
      )}
      <div className="table-scroll scanner-scroll">
        <table className="real-scanner-table">
          <thead>
            <tr>
              {header("Ticker", "ticker")}
              {header("Last price", "price")}
              {header("Daily change", "change_pct")}
              {header("Volume", "volume")}
              <th>Market status</th>
              <th>Freshness</th>
              <th>Updated</th>
              <th>Provider</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.ticker}>
                <td>
                  <Link className="ticker-cell" to={`/stocks/${row.ticker}`}>
                    <span className="ticker-symbol">
                      {row.ticker.slice(0, 2)}
                    </span>
                    <strong>{row.ticker}</strong>
                  </Link>
                </td>
                <td>
                  {row.price === null
                    ? "Unavailable"
                    : row.currency === "TRY"
                      ? money(row.price)
                      : `${row.price.toFixed(2)} ${row.currency ?? "(currency unknown)"}`}
                  {row.error && (
                    <small className="cell-subtext negative">
                      {row.error.message}
                    </small>
                  )}
                </td>
                <td
                  className={
                    row.change_pct === null
                      ? "muted"
                      : row.change_pct >= 0
                        ? "positive"
                        : "negative"
                  }
                >
                  {row.change_pct === null
                    ? "Unavailable"
                    : percent(row.change_pct, true)}
                </td>
                <td>
                  {row.volume === null
                    ? "Unavailable"
                    : shortNumber(row.volume)}
                </td>
                <td>
                  <MarketStatusBadge
                    status={retainedError ? "unknown" : row.market_status}
                  />
                </td>
                <td>
                  {row.error ? (
                    <Badge tone="negative">Provider error</Badge>
                  ) : (
                    <FreshnessBadge
                      status={retainedError ? "stale" : row.freshness_status}
                    />
                  )}
                </td>
                <td className="muted update-cell">
                  {marketTime(row.quote_time ?? row.last_bar_time)}
                  <small className="cell-subtext">
                    {row.price_basis === "last_completed_close"
                      ? "Completed bar"
                      : "Provider quote"}
                  </small>
                </td>
                <td className="muted">{row.provider}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!visible.length && (
        <div className="empty-table">
          <p>No tickers match these filters.</p>
          <Button
            onClick={() => {
              setQuery("");
              setFilter("all");
            }}
          >
            Reset filters
          </Button>
        </div>
      )}
      <div className="table-footer">
        <span>{visible.length} market-data tickers</span>
        <span>Strategy scores unavailable · Analyze individually</span>
      </div>
    </>
  );
}
export function MarketScannerPanel({ preview = false }: { preview?: boolean }) {
  const state = useScanner();
  return (
    <Card className="scanner-card">
      <CardHeading
        title={preview ? "Market scanner" : "BIST market watchlist"}
        subtitle="Fixed 10-ticker basket · Delayed / provider data"
        action={
          <div className="market-card-actions">
            {preview && (
              <Link className="text-link" to="/scanner">
                View all
                <ArrowUpRight size={14} />
              </Link>
            )}
            <Button
              variant="ghost"
              onClick={() => void state.refresh()}
              disabled={state.refreshing}
              aria-label="Refresh scanner"
              title="Refresh market snapshot"
            >
              <RefreshCw size={14} />
              {state.refreshing ? "Updating…" : "Refresh"}
            </Button>
          </div>
        }
      />
      {state.error && (
        <MarketError
          message={state.error}
          retry={() => void state.refresh()}
          retained={!!state.data}
        />
      )}
      {state.data?.partial_failure && (
        <p className="partial-market-warning" role="status">
          Partial provider failure. Failed tickers remain visible with their
          errors.
        </p>
      )}
      {state.data ? (
        <RealScannerTable
          rows={state.data.rows}
          preview={preview}
          retainedError={!!state.error}
        />
      ) : (
        !state.error && (
          <div className="market-loading" role="status">
            Loading market data…
          </div>
        )
      )}
      <div className="card-bottom-note">
        Retrieved {marketTime(state.data?.fetched_at ?? null)} · Polls every 60
        seconds while visible · Yahoo is not a guaranteed real-time feed
      </div>
    </Card>
  );
}
