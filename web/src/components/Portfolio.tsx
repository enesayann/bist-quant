import { stockPath } from "../market/mode";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  CircleDollarSign,
  Layers3,
  Shield,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import type { Position, Portfolio } from "../types";
import { money, percent, pnlPercent } from "../lib/format";
import { Card, CardHeading } from "./ui";

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  positive = false,
}: {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  positive?: boolean;
}) {
  return (
    <Card className="metric-card">
      <div className="metric-label">
        <span>{label}</span>
        <Icon size={17} strokeWidth={1.6} />
      </div>
      <strong className={positive ? "positive" : ""}>{value}</strong>
      <p>
        {positive && <ArrowUpRight size={13} />}
        {detail}
      </p>
    </Card>
  );
}
export const metricIcons = {
  value: CircleDollarSign,
  pnl: TrendingUp,
  risk: Shield,
  positions: Layers3,
};
export function OpenPositionsCard({ positions }: { positions: Position[] }) {
  return (
    <Card className="positions-card">
      <CardHeading
        title="Open positions"
        subtitle="Demo paper positions · Example values"
        action={
          <Link
            className="text-link"
            to="/positions"
            aria-label="View all positions"
          >
            <ArrowUpRight size={17} />
          </Link>
        }
      />
      <div className="table-scroll">
        <table className="positions-table">
          <thead>
            <tr>
              {["Ticker", "Entry", "Current", "P&L", "Stop", "TP1", "TP2"].map(
                (label) => (
                  <th key={label}>{label}</th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => (
              <tr key={position.ticker}>
                <td>
                  <Link className="ticker-link" to={stockPath(position.ticker)}>
                    {position.ticker}
                  </Link>
                </td>
                <td>{money(position.entry)}</td>
                <td>{money(position.current)}</td>
                <td
                  className={
                    position.current >= position.entry ? "positive" : "negative"
                  }
                >
                  {percent(pnlPercent(position.entry, position.current), true)}
                </td>
                <td>{money(position.stop)}</td>
                <td>{money(position.tp1)}</td>
                <td>{money(position.tp2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="position-note">
        <span className="status-dot" />
        {positions.length} illustrative positions
        <span>No execution connected</span>
      </div>
    </Card>
  );
}
export function PositionsLedger({ portfolio }: { portfolio: Portfolio }) {
  return (
    <Card>
      <CardHeading
        title="Paper position ledger"
        subtitle="Demo holdings · No position files are read"
      />
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {[
                "Ticker",
                "Entry",
                "Quantity",
                "Current value",
                "Unrealized P&L",
                "Stop",
                "TP1",
                "TP2",
              ].map((label) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {portfolio.positions.map((position) => {
              const pnl =
                (position.current - position.entry) * position.quantity;
              return (
                <tr key={position.ticker}>
                  <td>
                    <Link
                      className="ticker-link"
                      to={stockPath(position.ticker)}
                    >
                      {position.ticker}
                    </Link>
                  </td>
                  <td>{money(position.entry)}</td>
                  <td>{position.quantity}</td>
                  <td>{money(position.current * position.quantity)}</td>
                  <td className={pnl >= 0 ? "positive" : "negative"}>
                    {pnl >= 0 ? "+" : "−"}
                    {money(Math.abs(pnl))}
                  </td>
                  <td>{money(position.stop)}</td>
                  <td>{money(position.tp1)}</td>
                  <td>{money(position.tp2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="ledger-footer">
        <span>Available paper cash</span>
        <strong>{money(portfolio.cash)}</strong>
      </div>
    </Card>
  );
}
