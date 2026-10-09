import { stockPath } from "../market/mode";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ArrowUpRight,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import type { MarketStock, Signal, Strategy } from "../types";
import { money, percent, shortNumber } from "../lib/format";
import { Badge, Button, Card, CardHeading, ScoreBar } from "./ui";

type SortKey =
  | "ticker"
  | "price"
  | "change"
  | "trend"
  | "momentum"
  | "volume"
  | "volatility"
  | "score";
export function SignalBadge({ signal }: { signal: Signal }) {
  return (
    <Badge
      tone={
        signal === "LONG" ? "positive" : signal === "WATCH" ? "accent" : "muted"
      }
    >
      {signal === "LONG" && <span className="status-dot" />}
      {signal}
    </Badge>
  );
}
export function MarketScannerTable({
  stocks,
  preview = false,
}: {
  stocks: MarketStock[];
  preview?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [signal, setSignal] = useState<Signal | "all">("all");
  const [strategy, setStrategy] = useState<Strategy | "all">("all");
  const [sort, setSort] = useState<{ key: SortKey; direction: "asc" | "desc" }>(
    { key: "score", direction: "desc" },
  );
  const filtered = useMemo(() => {
    const result = stocks.filter(
      (stock) =>
        stock.ticker.toLowerCase().includes(query.trim().toLowerCase()) &&
        (signal === "all" || stock.signal === signal) &&
        (strategy === "all" || stock.strategy === strategy),
    );
    const getValue = (stock: MarketStock, key: SortKey): string | number =>
      key === "trend" || key === "momentum" || key === "volatility"
        ? stock.scores[key]
        : stock[key];
    return result.sort((a, b) => {
      const left = getValue(a, sort.key),
        right = getValue(b, sort.key);
      const difference =
        typeof left === "string" && typeof right === "string"
          ? left.localeCompare(right)
          : Number(left) - Number(right);
      return (
        (sort.direction === "asc" ? difference : -difference) ||
        a.ticker.localeCompare(b.ticker)
      );
    });
  }, [stocks, query, signal, strategy, sort]);
  const rows = preview ? stocks : filtered;
  function resetFilters() {
    setQuery("");
    setSignal("all");
    setStrategy("all");
  }
  function sortHeader(label: string, key: SortKey) {
    const active = sort.key === key;
    return (
      <th
        key={key}
        aria-sort={
          active
            ? sort.direction === "asc"
              ? "ascending"
              : "descending"
            : "none"
        }
      >
        <button
          className="sort-button"
          onClick={() =>
            setSort({
              key,
              direction: active && sort.direction === "desc" ? "asc" : "desc",
            })
          }
        >
          {label}
          {active ? (
            sort.direction === "desc" ? (
              <ArrowDown size={12} />
            ) : (
              <ArrowUp size={12} />
            )
          ) : (
            <ArrowUpDown size={12} />
          )}
        </button>
      </th>
    );
  }
  return (
    <Card className={`scanner-card ${preview ? "scanner-preview" : ""}`}>
      <CardHeading
        title={preview ? "Market scanner" : "BIST watchlist"}
        subtitle={
          preview
            ? "10-ticker basket · Illustrative setups"
            : "10-ticker research basket · All scores are demo examples"
        }
        action={
          preview ? (
            <Link className="text-link" to="/scanner">
              View all <ArrowUpRight size={14} />
            </Link>
          ) : (
            <Badge>
              <SlidersHorizontal size={12} />
              Daily v1 examples
            </Badge>
          )
        }
      />
      {!preview && (
        <div className="scanner-toolbar">
          <label className="search-input">
            <Search size={16} />
            <input
              aria-label="Search by ticker"
              placeholder="Search ticker…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            {query && (
              <button
                aria-label="Clear ticker search"
                onClick={() => setQuery("")}
              >
                <X size={14} />
              </button>
            )}
          </label>
          <div className="scanner-filters">
            <label>
              <span>Signal</span>
              <select
                aria-label="Filter by signal"
                value={signal}
                onChange={(event) =>
                  setSignal(event.target.value as Signal | "all")
                }
              >
                <option value="all">All signals</option>
                {["LONG", "WATCH", "NEUTRAL"].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Strategy</span>
              <select
                aria-label="Filter by strategy"
                value={strategy}
                onChange={(event) =>
                  setStrategy(event.target.value as Strategy | "all")
                }
              >
                <option value="all">All strategies</option>
                <option>Daily v1</option>
                <option>No Setup</option>
              </select>
            </label>
          </div>
        </div>
      )}
      <div className="table-scroll scanner-scroll">
        <table>
          <thead>
            <tr>
              {preview ? (
                <>
                  <th>Ticker</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>Strategy</th>
                  <th>Score</th>
                  <th>Volume</th>
                  <th>Signal</th>
                </>
              ) : (
                <>
                  {sortHeader("Ticker", "ticker")}
                  {sortHeader("Last price", "price")}
                  {sortHeader("Daily change", "change")}
                  {sortHeader("Trend", "trend")}
                  {sortHeader("Momentum", "momentum")}
                  {sortHeader("Volume", "volume")}
                  {sortHeader("Volatility", "volatility")}
                  {sortHeader("Strategy score", "score")}
                  <th>Signal</th>
                  <th>Updated</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((stock) => (
              <tr key={stock.ticker}>
                <td>
                  <Link className="ticker-cell" to={stockPath(stock.ticker)}>
                    <span
                      className={`ticker-symbol ${stock.signal === "LONG" ? "ticker-symbol-accent" : ""}`}
                    >
                      {stock.ticker.slice(0, 2)}
                    </span>
                    <span>
                      <strong>{stock.ticker}</strong>
                      {!preview && <small>{stock.name}</small>}
                    </span>
                  </Link>
                </td>
                <td>{money(stock.price)}</td>
                <td className={stock.change >= 0 ? "positive" : "negative"}>
                  {percent(stock.change, true)}
                </td>
                {preview ? (
                  <>
                    <td className="muted">{stock.strategy}</td>
                    <td>
                      <span className="table-score">{stock.score}</span>
                    </td>
                    <td className="muted">{shortNumber(stock.volume)}</td>
                  </>
                ) : (
                  <>
                    <td className="muted">{stock.scores.trend}</td>
                    <td className="muted">{stock.scores.momentum}</td>
                    <td>
                      <span>{shortNumber(stock.volume)}</span>
                      <small className="cell-subtext">
                        Score {stock.scores.volume}
                      </small>
                    </td>
                    <td className="muted">{stock.scores.volatility}</td>
                    <td>
                      <div className="table-score-bar">
                        <strong>{stock.score}</strong>
                        <ScoreBar
                          label={`${stock.ticker} demo overall score`}
                          value={stock.score}
                        />
                      </div>
                    </td>
                  </>
                )}
                <td>
                  <SignalBadge signal={stock.signal} />
                </td>
                {!preview && (
                  <td className="muted update-cell">
                    {stock.updated}
                    <small className="cell-subtext">Fixture</small>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!preview && rows.length === 0 && (
        <div className="empty-table" role="status">
          <Search size={23} />
          <h3>No matching tickers</h3>
          <p>Try a different ticker or clear the filters.</p>
          <Button onClick={resetFilters}>Reset filters</Button>
        </div>
      )}
      <div className="table-footer">
        <span>
          {preview
            ? "10 demo tickers"
            : `${filtered.length} of ${stocks.length} tickers`}
        </span>
        <span>
          {preview
            ? "Signals are UI examples"
            : "Scores: 0–100 · Illustrative, not computed"}
        </span>
      </div>
    </Card>
  );
}
