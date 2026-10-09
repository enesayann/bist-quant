import { useId, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Portfolio, PricePoint } from "../types";
import { dateLabel, money, percent, signedMoney } from "../lib/format";
import { Badge, Card, CardHeading } from "./ui";

function RangeSelector({
  value,
  onChange,
}: {
  value: string;
  onChange(value: string): void;
}) {
  return (
    <div className="segmented" role="group" aria-label="Chart date range">
      {["1M", "3M", "1Y"].map((range) => (
        <button
          key={range}
          aria-pressed={value === range}
          onClick={() => onChange(range)}
        >
          {range}
        </button>
      ))}
    </div>
  );
}
function Chart({
  data,
  label,
  price = false,
  demo = true,
}: {
  data: PricePoint[];
  label: string;
  price?: boolean;
  demo?: boolean;
}) {
  const fillId = useId().replaceAll(":", "");
  return (
    <div
      className={`chart-frame ${price ? "price-chart-frame" : ""}`}
      role="img"
      aria-label={label}
    >
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <AreaChart
          data={data}
          margin={{ top: 12, right: 8, bottom: 0, left: 0 }}
        >
          <defs>
            <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.16} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            stroke="var(--border)"
            vertical={false}
            strokeDasharray="3 5"
          />
          <XAxis
            dataKey="date"
            tickFormatter={dateLabel}
            minTickGap={40}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            dy={8}
          />
          <YAxis
            domain={["dataMin - 150", "dataMax + 150"]}
            hide={!price}
            width={65}
            tickFormatter={(value) => `₺${Number(value).toFixed(0)}`}
            tick={{ fill: "var(--muted)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            {...(price ? { domain: ["dataMin * 0.98", "dataMax * 1.02"] } : {})}
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface-raised)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--text)",
            }}
            labelFormatter={(value) => dateLabel(String(value))}
            formatter={(value) => [
              money(Number(value)),
              price
                ? demo
                  ? "Example close"
                  : "Completed daily close"
                : "Example equity",
            ]}
            cursor={{ stroke: "var(--muted)", strokeDasharray: "3 4" }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke="var(--accent)"
            strokeWidth={2}
            fill={`url(#${fillId})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
export function PortfolioChart({ portfolio }: { portfolio: Portfolio }) {
  const [range, setRange] = useState("3M");
  const data = portfolio.equity.slice(
    -({ "1M": 30, "3M": 90, "1Y": 365 }[range] ?? 90),
  );
  const change = portfolio.value - data[0].value;
  return (
    <Card className="portfolio-card">
      <CardHeading
        title="Portfolio performance"
        subtitle="Illustrative equity · TRY"
        action={<RangeSelector value={range} onChange={setRange} />}
      />
      <div className="chart-summary">
        <strong>{money(portfolio.value)}</strong>
        <span className={change >= 0 ? "positive" : "negative"}>
          {signedMoney(change)}{" "}
          <span>({percent((change / data[0].value) * 100, true)})</span>
        </span>
        <small>over selected period</small>
      </div>
      <Chart
        data={data}
        label={`${range} illustrative portfolio equity, ${money(data[0].value)} to ${money(portfolio.value)}`}
      />
      <div className="chart-footnote">
        <span>
          <i className="legend-line" />
          Paper portfolio
        </span>
        <span>Demo history · No backtest results</span>
      </div>
    </Card>
  );
}
export function StockPriceChart({
  history,
  ticker,
  provenance = "demo",
}: {
  history: PricePoint[];
  ticker: string;
  provenance?: "demo" | "api";
}) {
  const [range, setRange] = useState("3M");
  const cutoff = new Date(`${history.at(-1)!.date}T12:00:00Z`);
  if (range === "1Y") cutoff.setUTCFullYear(cutoff.getUTCFullYear() - 1);
  else cutoff.setUTCMonth(cutoff.getUTCMonth() - (range === "1M" ? 1 : 3));
  const data =
    provenance === "api"
      ? history.filter(
          (point) => point.date >= cutoff.toISOString().slice(0, 10),
        )
      : history.slice(-({ "1M": 30, "3M": 90, "1Y": 365 }[range] ?? 90));
  return (
    <Card>
      <CardHeading
        title="Price history"
        subtitle={
          provenance === "api"
            ? "Yahoo completed daily close · TRY"
            : "Illustrative daily close · TRY"
        }
        action={
          <div className="chart-controls">
            <Badge>{provenance === "api" ? "Provider data" : "Demo"}</Badge>
            <RangeSelector value={range} onChange={setRange} />
          </div>
        }
      />
      <Chart
        data={data}
        label={`${ticker} ${provenance === "api" ? "completed daily" : "illustrative"} price history, ${data.length} points`}
        price
        demo={provenance !== "api"}
      />
      <div className="chart-footnote">
        <span>
          <i className="legend-line" />
          {ticker} {provenance === "api" ? "daily close" : "example close"}
        </span>
        <span>
          {data.length}{" "}
          {provenance === "api"
            ? "completed bars · No streaming"
            : "fixture points · No market feed"}
        </span>
      </div>
    </Card>
  );
}
