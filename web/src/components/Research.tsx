import { stockPath } from "../market/mode";
import {
  ArrowUpRight,
  CircleCheck,
  CircleMinus,
  Clock3,
  ShieldCheck,
  TrendingUp,
  Waves,
  Zap,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { Activity, MarketStock, StrategyState } from "../types";
import { Badge, Card, CardHeading, ScoreBar } from "./ui";

export function RecentActivity({ activity }: { activity: Activity[] }) {
  return (
    <Card>
      <CardHeading
        title="Recent activity"
        action={<Badge>Demo events</Badge>}
      />
      <div className="activity-list">
        {activity.map((item) => (
          <div className="activity-item" key={`${item.ticker}-${item.time}`}>
            <span
              className={`activity-icon ${item.kind === "invalidated" ? "negative" : item.kind === "position" ? "accent" : "positive"}`}
            >
              {item.kind === "invalidated" ? (
                <CircleMinus size={15} />
              ) : item.kind === "position" ? (
                <ShieldCheck size={15} />
              ) : (
                <TrendingUp size={15} />
              )}
            </span>
            <div>
              <Link to={stockPath(item.ticker)}>{item.ticker}</Link>
              <p>{item.text}</p>
            </div>
            <time>{item.time}</time>
          </div>
        ))}
      </div>
      <div className="card-bottom-note">
        Illustrative events · No live signals
      </div>
    </Card>
  );
}
export function StrategyStatus({
  strategies,
}: {
  strategies: StrategyState[];
}) {
  return (
    <Card>
      <CardHeading title="Strategy status" />
      <div className="strategy-states">
        {strategies.map((state) => (
          <div key={state.name}>
            <span>{state.name}</span>
            <Badge tone={state.tone}>{state.status}</Badge>
          </div>
        ))}
      </div>
    </Card>
  );
}
const categories = [
  {
    key: "trend",
    label: "Trend",
    icon: TrendingUp,
    low: "Mixed structure",
    high: "Upward structure",
    description: "Direction & price structure",
  },
  {
    key: "momentum",
    label: "Momentum",
    icon: Zap,
    low: "Moderate momentum",
    high: "Strengthening",
    description: "Relative price momentum",
  },
  {
    key: "volume",
    label: "Volume",
    icon: Waves,
    low: "Typical participation",
    high: "Elevated participation",
    description: "Example participation score",
  },
  {
    key: "volatility",
    label: "Volatility",
    icon: ShieldCheck,
    low: "Elevated variability",
    high: "Contained variability",
    description: "Example stability score",
  },
] as const;
export function AnalyticsBento({ stock }: { stock: MarketStock }) {
  return (
    <div className="analytics-grid">
      {categories.map((category) => {
        const value = stock.scores[category.key];
        const Icon = category.icon;
        return (
          <Card className="analytics-card" key={category.key}>
            <div className="metric-label">
              <span>{category.label}</span>
              <Icon size={17} />
            </div>
            <div className="analytics-value">
              <strong>
                {value}
                <small>/100</small>
              </strong>
              <Badge tone={value >= 70 ? "accent" : "muted"}>
                {value >= 70 ? category.high : category.low}
              </Badge>
            </div>
            <ScoreBar value={value} label={`${category.label} demo score`} />
            <p>{category.description} · Demo</p>
          </Card>
        );
      })}
    </div>
  );
}
export function StrategyBreakdown({ stock }: { stock: MarketStock }) {
  return (
    <Card>
      <CardHeading
        title="Current strategy"
        subtitle="Daily Strategy v1"
        action={<Badge>UI example</Badge>}
      />
      <div className="strategy-overall">
        <div>
          <span>Overall score</span>
          <strong>
            {stock.score}
            <small>/100</small>
          </strong>
        </div>
        <div className="score-ring">
          <CircleCheck size={22} />
          <span>
            Illustrative
            <br />
            score only
          </span>
        </div>
      </div>
      <div className="breakdown-list">
        {categories.map((category) => (
          <div key={category.key}>
            <span>{category.label}</span>
            <ScoreBar
              value={stock.scores[category.key]}
              label={`${category.label} illustrative strategy score`}
            />
            <strong>{stock.scores[category.key]}</strong>
          </div>
        ))}
      </div>
      <p className="card-bottom-note">
        Fixture scores are not calculated strategy outputs or trade
        recommendations.
      </p>
    </Card>
  );
}
export function DemoNotice({ children }: { children?: React.ReactNode }) {
  return (
    <div className="demo-notice">
      <Clock3 size={15} />
      <p>
        {children ??
          "Offline demo. Prices, scores, signals and performance are illustrative UI data."}
      </p>
      <span>FIXTURE DATA</span>
    </div>
  );
}
export function ResearchLink() {
  return (
    <Link className="text-link" to="/research/daily">
      Research workspace
      <ArrowUpRight size={14} />
    </Link>
  );
}
