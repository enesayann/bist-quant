import { Link, useParams, useSearchParams } from "react-router-dom";
import { normalizeTicker } from "../api/analysis";
import { Badge, Card } from "../components/ui";
import { DemoStockDetail } from "./StockDetail";
import { DEMO_MODE } from "../market/mode";
import { MarketStockDetail } from "./MarketStockDetail";
export function StockDetail() {
  const { ticker = "" } = useParams();
  const [params] = useSearchParams();
  if (params.get("demo") === "1" || DEMO_MODE)
    return (
      <>
        <div className="demo-analysis-switch">
          <Badge>Explicit demo view</Badge>
          {!DEMO_MODE && (
            <Link
              className="text-link"
              to={`/stocks/${encodeURIComponent(ticker)}`}
            >
              Analyze real daily data
            </Link>
          )}
          {DEMO_MODE && (
            <span className="muted">
              Set VITE_DATA_MODE=api for real market data
            </span>
          )}
        </div>
        <DemoStockDetail />
      </>
    );
  let symbol: string;
  try {
    symbol = normalizeTicker(ticker);
  } catch {
    return (
      <Card className="workspace-empty">
        <h1>Invalid ticker</h1>
        <p>Use a BIST ticker such as ASELS.</p>
        <Link className="text-link" to="/">
          Back to Overview
        </Link>
      </Card>
    );
  }
  return <MarketStockDetail key={symbol} symbol={symbol} />;
}
