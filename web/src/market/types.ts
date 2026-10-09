export type Freshness =
  "fresh" | "delayed" | "stale" | "market_closed" | "unknown";
export type MarketStatus =
  "open" | "closed" | "pre_market_or_auction" | "holiday" | "unknown";
export interface Quote {
  symbol: string;
  ticker: string;
  price: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  day_open: number | null;
  day_high: number | null;
  day_low: number | null;
  volume: number | null;
  currency: string | null;
  quote_time: string | null;
  last_bar_time: string | null;
  provider: string;
  provider_delay_status: "unknown" | "delayed" | "real_time_guaranteed";
  market_status: MarketStatus;
  freshness_status: Freshness;
  price_basis: string;
  fetched_at: string;
  warnings: string[];
  error: { code: string; message: string } | null;
  cache: { hit: boolean; ttl_seconds: number; age_seconds: number };
}
export interface SessionInfo {
  status: MarketStatus;
  as_of: string;
  timezone: string;
  calendar_version: string;
  half_day: boolean;
  expected_completed_session: string | null;
  note: string;
}
export interface ScannerData {
  fetched_at: string;
  session: SessionInfo;
  provider: string;
  rows: Quote[];
  partial_failure: boolean;
  cache: Quote["cache"];
  strategy_analysis: false;
}
export interface MarketHistory {
  ticker: string;
  symbol: string;
  interval: "1d";
  range: "1mo" | "3mo" | "6mo" | "1y";
  provider: string;
  fetched_at: string;
  completed_only: true;
  last_bar_time: string | null;
  freshness_status: Freshness;
  market_status: MarketStatus;
  points: Array<{
    date: string;
    timestamp: string;
    close: number;
    volume: number | null;
  }>;
  quality: {
    downloaded_rows: number;
    removed_rows: number;
    usable_rows: number;
    incomplete_rows: number;
    future_rows: number;
    warnings: string[];
  };
  cache: Quote["cache"];
}
