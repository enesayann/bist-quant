import { Link } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Database,
  FlaskConical,
  LockKeyhole,
  Send,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import { useDashboard } from "../data/context";
import { PageHeader } from "../components/Layout";
import { Badge, Card, CardHeading } from "../components/ui";
import {
  DemoNotice,
  RecentActivity,
  StrategyStatus,
} from "../components/Research";
import { PositionsLedger } from "../components/Portfolio";

export function PositionsPage() {
  const { portfolio } = useDashboard();
  return (
    <>
      <PageHeader
        title="Positions"
        description="A prepared view for your paper portfolio."
      >
        <Badge tone="accent">Paper Trading</Badge>
      </PageHeader>
      <DemoNotice>
        Offline example holdings. This page does not read actual position files
        or place orders.
      </DemoNotice>
      <PositionsLedger portfolio={portfolio} />
      <div className="integration-note">
        <LockKeyhole size={17} />
        <div>
          <strong>Paper ledger scaffold</strong>
          <p>
            Quantities, prices, stops and targets are fixtures. A future
            portfolio adapter can provide the same typed view.
          </p>
        </div>
      </div>
    </>
  );
}
export function BacktestsPage() {
  return (
    <>
      <PageHeader
        title="Backtests"
        description="A workspace for historical validation results."
      >
        <Badge>Awaiting data integration</Badge>
      </PageHeader>
      <DemoNotice>
        No backtest files are loaded. The sections below are prepared for future
        validated results.
      </DemoNotice>
      <div className="metrics-grid">
        {["Net return", "Max drawdown", "Profit factor", "Trades"].map(
          (label) => (
            <Card className="metric-card placeholder-metric" key={label}>
              <div className="metric-label">
                <span>{label}</span>
                <BarChart3 size={16} />
              </div>
              <strong>—</strong>
              <p>No result connected</p>
            </Card>
          ),
        )}
      </div>
      <Card>
        <CardHeading
          title="Equity curve"
          subtitle="Historical portfolio equity"
          action={<Badge>Not connected</Badge>}
        />
        <div className="chart-placeholder">
          <BarChart3 size={30} strokeWidth={1.3} />
          <h3>Results will appear here</h3>
          <p>Connect a validated result source to view equity and drawdown.</p>
          <span className="placeholder-axis" />
        </div>
      </Card>
      <div className="placeholder-grid">
        <Card>
          <CardHeading
            title="Trade log"
            subtitle="Entry, exit, holding period and net P&L"
          />
          <div className="prepared-table">
            <div>
              Ticker<span>Entry</span>
              <span>Exit</span>
              <span>Net P&L</span>
            </div>
            <p>No trade records connected.</p>
          </div>
        </Card>
        <Card>
          <CardHeading
            title="Per-ticker results"
            subtitle="Contribution, trade count and performance"
          />
          <div className="prepared-table">
            <div>
              Ticker<span>Trades</span>
              <span>Return</span>
              <span>Contribution</span>
            </div>
            <p>No ticker results connected.</p>
          </div>
        </Card>
      </div>
    </>
  );
}
export function EmptyPage({
  title,
  description,
  icon: Icon,
  link,
  linkLabel,
}: {
  title: string;
  description: string;
  icon: LucideIcon;
  link?: string;
  linkLabel?: string;
}) {
  return (
    <>
      <PageHeader title={title} description="Quant Research & Paper Trading" />
      <Card className="workspace-empty">
        <span className="empty-icon">
          <Icon size={28} strokeWidth={1.5} />
        </span>
        <Badge>Workspace preview</Badge>
        <h2>{title}</h2>
        <p>{description}</p>
        {link && (
          <Link className="button button-secondary" to={link}>
            {linkLabel}
            <ArrowUpRight size={15} />
          </Link>
        )}
      </Card>
    </>
  );
}
export function SignalsPage() {
  const { activity } = useDashboard();
  return (
    <>
      <PageHeader
        title="Signals"
        description="A prepared timeline for paper research activity."
      >
        <Badge>Demo events</Badge>
      </PageHeader>
      <DemoNotice />
      <div className="narrow-content">
        <RecentActivity activity={activity} />
        <div className="integration-note">
          <Activity size={18} />
          <div>
            <strong>Signal history is not connected</strong>
            <p>
              These four events are interface examples. No strategy runs or live
              signals are triggered.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
export function DailyPage() {
  const { strategies } = useDashboard();
  return (
    <>
      <PageHeader
        title="Daily Strategy"
        description="A prepared research view for the existing daily strategy."
      >
        <Badge tone="positive">Daily v1 · Available</Badge>
      </PageHeader>
      <div className="placeholder-grid">
        <StrategyStatus strategies={strategies} />
        <Card className="research-placeholder">
          <FlaskConical size={25} />
          <h2>Research details coming later</h2>
          <p>
            Strategy definitions and validation results can be presented here
            after data integration. This dashboard does not calculate scores.
          </p>
          <Link className="text-link" to="/scanner">
            Explore demo scanner
            <ArrowUpRight size={14} />
          </Link>
        </Card>
      </div>
    </>
  );
}
export function IntradayPage() {
  return (
    <EmptyPage
      title="Intraday Strategy"
      description="Strategy v2 is not implemented. The intraday data contract is ready; replay and strategy results are not connected to this dashboard."
      icon={Database}
      link="/research/daily"
      linkLabel="View daily research"
    />
  );
}
export function TelegramPage() {
  return (
    <EmptyPage
      title="Telegram"
      description="Notification settings will appear here after integration. Telegram is not connected, and this dashboard sends no messages."
      icon={Send}
    />
  );
}
export function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Local dashboard environment." />
      <div className="narrow-content">
        <Card>
          <CardHeading
            title="Workspace configuration"
            action={<Settings2 size={18} />}
          />
          <dl className="settings-list">
            <div>
              <dt>Workspace</dt>
              <dd>Paper Trading</dd>
            </div>
            <div>
              <dt>Data source</dt>
              <dd>
                <Badge tone="accent">Demo dashboard / API analysis</Badge>
              </dd>
            </div>
            <div>
              <dt>Display currency</dt>
              <dd>TRY · Turkish lira</dd>
            </div>
            <div>
              <dt>Theme</dt>
              <dd>Graphite dark</dd>
            </div>
            <div>
              <dt>Market / backend connection</dt>
              <dd>On-demand API · No streaming</dd>
            </div>
          </dl>
          <p className="card-bottom-note">
            Read-only environment information. No bot configuration is read or
            modified.
          </p>
        </Card>
      </div>
    </>
  );
}
