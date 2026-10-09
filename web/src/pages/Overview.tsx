import { CalendarDays, Circle } from "lucide-react";
import { useDashboard } from "../data/context";
import { PageHeader } from "../components/Layout";
import { Badge } from "../components/ui";
import { AnalyzeStock } from "../components/AnalyzeStock";
import {
  MetricCard,
  metricIcons,
  OpenPositionsCard,
} from "../components/Portfolio";
import { PortfolioChart } from "../components/Charts";
import { MarketScannerTable } from "../components/MarketScannerTable";
import {
  DemoNotice,
  RecentActivity,
  StrategyStatus,
} from "../components/Research";
import { money, percent, signedMoney } from "../lib/format";
import { DEMO_MODE } from "../market/mode";
import { ApiMarketHeading, MarketScannerPanel } from "../components/MarketData";

export function Overview() {
  const {
    portfolio,
    stocks,
    activity,
    strategies,
    fixtureDate,
    marketStatus,
    session,
  } = useDashboard();
  return (
    <>
      {DEMO_MODE ? (
        <>
          <PageHeader
            title="Market Overview"
            description="Your research workspace, at a glance."
          >
            <Badge tone="accent">Paper Trading</Badge>
            <Badge>
              <Circle size={8} fill="currentColor" />
              {marketStatus}
            </Badge>
          </PageHeader>
          <div className="session-line">
            <CalendarDays size={14} />
            <span>{fixtureDate}</span>
            <span className="separator">/</span>
            <span>{session}</span>
            <span className="session-fixture">Mock session</span>
          </div>
          <div className="demo-notice">
            <Badge>Demo mode</Badge>
            <p>
              Set VITE_DATA_MODE=api for provider data and on-demand analysis.
            </p>
          </div>
        </>
      ) : (
        <>
          <ApiMarketHeading />
          <AnalyzeStock />
        </>
      )}
      <DemoNotice>
        Portfolio, equity, paper positions and activity remain Demo. Market
        tables use provider data in API mode; strategy analysis is on demand.
      </DemoNotice>
      <div className="metrics-grid">
        <MetricCard
          label="Portfolio Value"
          value={money(portfolio.value)}
          detail="Demo paper portfolio · TRY"
          icon={metricIcons.value}
        />
        <MetricCard
          label="Daily P&L"
          value={signedMoney(portfolio.dailyPnl)}
          detail={`${percent(portfolio.dailyChange, true)} today · Demo`}
          icon={metricIcons.pnl}
          positive
        />
        <MetricCard
          label="Open Risk"
          value={percent(portfolio.openRisk, false, 1)}
          detail="Demo exposure at stops"
          icon={metricIcons.risk}
        />
        <MetricCard
          label="Open Positions"
          value={`${portfolio.positions.length} / ${portfolio.maxPositions}`}
          detail={`Demo · ${portfolio.maxPositions - portfolio.positions.length} available paper slots`}
          icon={metricIcons.positions}
        />
      </div>
      <div className="overview-top">
        <PortfolioChart portfolio={portfolio} />
        <OpenPositionsCard positions={portfolio.positions} />
      </div>
      <div className="overview-bottom">
        {DEMO_MODE ? (
          <MarketScannerTable stocks={stocks} preview />
        ) : (
          <MarketScannerPanel preview />
        )}
        <div className="overview-side">
          <RecentActivity activity={activity} />
          <StrategyStatus strategies={strategies} />
        </div>
      </div>
    </>
  );
}
