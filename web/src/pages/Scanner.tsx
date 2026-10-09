import { useDashboard } from "../data/context";
import { PageHeader } from "../components/Layout";
import { Badge } from "../components/ui";
import { DemoNotice } from "../components/Research";
import { MarketScannerTable } from "../components/MarketScannerTable";
import { DEMO_MODE } from "../market/mode";
import { MarketScannerPanel } from "../components/MarketData";
export function Scanner() {
  const { stocks } = useDashboard();
  return (
    <>
      <PageHeader
        title="Market Scanner"
        description="Explore the fixed BIST research basket."
      >
        <Badge tone="accent">Paper Trading</Badge>
        <Badge>10 tickers</Badge>
      </PageHeader>
      {DEMO_MODE ? (
        <>
          <DemoNotice />
          <MarketScannerTable stocks={stocks} />
        </>
      ) : (
        <MarketScannerPanel />
      )}
      <p className="page-footnote">
        {DEMO_MODE
          ? "LONG, WATCH and NEUTRAL are explicit demo labels, not live trade recommendations."
          : "Market data only. Daily Strategy v1 scores are not fetched automatically. Open a ticker to request analysis."}
      </p>
    </>
  );
}
