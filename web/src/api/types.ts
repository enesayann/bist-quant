import type { AnalysisExplanation } from "./explanation";
export interface AnalysisResponse {
  explanation?: AnalysisExplanation | null;
  ticker: string;
  symbol: string;
  analysis_type: "daily_v1";
  mode: "research";
  as_of: string;
  source: string;
  data_freshness: {
    last_bar: string;
    market_status: "unknown";
    is_stale: boolean;
    expected_last_bar: string;
    completed_bars_only: boolean;
    session_note: string;
  };
  market: {
    price: number;
    previous_close: number;
    change: number;
    change_pct: number;
    price_basis: string;
  };
  scores: {
    overall: number;
    technical: number;
    trend: number;
    momentum: number;
    volume: number;
    volatility: number;
    fundamental: number | null;
    news: number | null;
    support_resistance_adjustment: number;
    category_maxima: Record<
      "trend" | "momentum" | "volume" | "volatility",
      number
    >;
    scope: string;
  };
  indicators: {
    rsi: number | null;
    ema20: number | null;
    ema50: number | null;
    ema200: number | null;
    atr: number | null;
    adx: number | null;
    macd: number | null;
    macd_signal: number | null;
    mfi: number | null;
    cmf: number | null;
    obv: number | null;
    vwap: number | null;
    historical_volatility_pct: number | null;
    supertrend: number | null;
  };
  strategy: {
    name: string;
    score: number;
    technical_score: number;
    state: "setup" | "no_setup";
    signal: string | null;
    classification: string | null;
    scope: string;
  };
  risk: { atr_pct: number | null; volatility_state: string | null };
  price_series: Array<{ date: string; value: number }>;
  data_quality: {
    rows_downloaded: number;
    rows_removed: number;
    usable_rows: number;
    warnings: string[];
  };
  cache: { hit: boolean; ttl_seconds: number; age_seconds: number };
  warnings: string[];
  disclaimer: string;
}
