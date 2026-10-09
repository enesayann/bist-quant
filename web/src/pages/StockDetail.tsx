import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { useDashboard } from "../data/context";
import { StockPriceChart } from "../components/Charts";
import {
  AnalyticsBento,
  DemoNotice,
  StrategyBreakdown,
} from "../components/Research";
import { Badge, Card, CardHeading } from "../components/ui";
import { money, percent } from "../lib/format";
import { EmptyPage } from "./WorkspacePages";

export function DemoStockDetail() {
  const { ticker } = useParams();
  const { stocks } = useDashboard();
  const symbol = ticker?.toUpperCase().replace(/\.IS$/, "");
  const stock = stocks.find((item) => item.ticker === symbol);
  if (!stock)
    return (
      <EmptyPage
        title="Ticker unavailable"
        description="This ticker is not part of the 10-symbol demo basket."
        icon={ArrowUpRight}
        link="/scanner"
        linkLabel="Back to scanner"
      />
    );
  return (
    <>
      <Link className="back-link" to="/scanner">
        <ArrowLeft size={14} />
        Market Scanner
      </Link>
      <div className="stock-heading">
        <div className="stock-identity">
          <span className="stock-avatar">{stock.ticker.slice(0, 2)}</span>
          <div>
            <h1>
              {stock.ticker}
              <Badge>BIST · {stock.ticker}.IS</Badge>
            </h1>
            <p>
              {stock.name} <span>·</span> {stock.sector}
            </p>
          </div>
        </div>
        <div className="stock-quote">
          <strong>{money(stock.price)}</strong>
          <span className={stock.change >= 0 ? "positive" : "negative"}>
            {percent(stock.change, true)}
            <small>Demo daily change</small>
          </span>
        </div>
      </div>
      <DemoNotice />
      <StockPriceChart history={stock.history} ticker={stock.ticker} />
      <div className="section-label">
        <h2>Technical snapshot</h2>
        <span>Illustrative category scores · 0–100</span>
      </div>
      <AnalyticsBento stock={stock} />
      <div className="stock-bottom">
        <StrategyBreakdown stock={stock} />
        <div className="stock-side">
          <Card>
            <CardHeading
              title="Paper / example values"
              subtitle="Illustrative levels · No order placement"
              action={<Badge tone="accent">Example</Badge>}
            />
            <div className="levels-grid">
              {Object.entries(stock.exampleLevels).map(([key, value]) => (
                <div key={key}>
                  <span>
                    {
                      (
                        {
                          entry: "Entry",
                          stop: "Stop",
                          tp1: "TP1",
                          tp2: "TP2",
                        } as Record<string, string>
                      )[key]
                    }
                  </span>
                  <strong>{money(value)}</strong>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeading
              title="Historical performance"
              subtitle="Demo values · Not a backtest result"
              action={<Badge>Demo</Badge>}
            />
            <div className="performance-grid">
              <div>
                <span>Trades</span>
                <strong>{stock.demoPerformance.trades}</strong>
              </div>
              <div>
                <span>Win rate</span>
                <strong>
                  {percent(stock.demoPerformance.winRate, false, 1)}
                </strong>
              </div>
              <div>
                <span>Profit factor</span>
                <strong>{stock.demoPerformance.profitFactor.toFixed(2)}</strong>
              </div>
              <div>
                <span>Max drawdown</span>
                <strong>
                  {percent(stock.demoPerformance.drawdown, false, 1)}
                </strong>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
