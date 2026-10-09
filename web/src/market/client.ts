import { apiGet, ApiError } from "../api/client";
import type { MarketHistory, Quote, ScannerData } from "./types";

const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const finite = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value);
const validTime = (value: unknown) =>
  typeof value === "string" && Number.isFinite(Date.parse(value));
const freshness = ["fresh", "delayed", "stale", "market_closed", "unknown"];
const statuses = [
  "open",
  "closed",
  "pre_market_or_auction",
  "holiday",
  "unknown",
];
const fail = (): never => {
  throw new ApiError(
    "invalid_market_response",
    "The API returned invalid market data. No demo values were substituted.",
  );
};

function quote(value: unknown): Quote {
  if (!object(value)) return fail();
  for (const key of ["symbol", "ticker", "provider", "price_basis"])
    if (typeof value[key] !== "string") return fail();
  for (const key of [
    "price",
    "previous_close",
    "change",
    "change_pct",
    "day_open",
    "day_high",
    "day_low",
    "volume",
  ])
    if (value[key] !== null && !finite(value[key])) return fail();
  for (const key of ["quote_time", "last_bar_time"])
    if (value[key] !== null && !validTime(value[key])) return fail();
  if (
    !validTime(value.fetched_at) ||
    !freshness.includes(String(value.freshness_status)) ||
    !statuses.includes(String(value.market_status))
  )
    return fail();
  if (
    !Array.isArray(value.warnings) ||
    !value.warnings.every((item) => typeof item === "string")
  )
    return fail();
  if (
    value.error !== null &&
    (!object(value.error) || typeof value.error.message !== "string")
  )
    return fail();
  if (
    (value.price !== null && Number(value.price) <= 0) ||
    (value.volume !== null && Number(value.volume) < 0)
  )
    return fail();
  return value as unknown as Quote;
}
export async function getQuote(
  ticker: string,
  signal: AbortSignal,
): Promise<Quote> {
  const result = quote(
    await apiGet(`/api/v1/market/quote/${encodeURIComponent(ticker)}`, signal),
  );
  if (result.ticker !== ticker) return fail();
  return result;
}
export async function getScanner(signal: AbortSignal): Promise<ScannerData> {
  const value = await apiGet("/api/v1/market/scanner", signal);
  if (
    !object(value) ||
    !Array.isArray(value.rows) ||
    !object(value.session) ||
    !statuses.includes(String(value.session.status)) ||
    !validTime(value.fetched_at) ||
    typeof value.partial_failure !== "boolean" ||
    value.strategy_analysis !== false
  )
    return fail();
  const rows = value.rows.map(quote);
  const symbols = [
    "ASELS",
    "THYAO",
    "TUPRS",
    "BIMAS",
    "EREGL",
    "KCHOL",
    "GARAN",
    "SISE",
    "FROTO",
    "TCELL",
  ];
  if (
    rows.length !== 10 ||
    new Set(rows.map((row) => row.ticker)).size !== 10 ||
    symbols.some((symbol) => !rows.some((row) => row.ticker === symbol))
  )
    return fail();
  return { ...value, rows } as unknown as ScannerData;
}
export async function getHistory(
  ticker: string,
  signal: AbortSignal,
): Promise<MarketHistory> {
  const value = await apiGet(
    `/api/v1/market/history/${encodeURIComponent(ticker)}?interval=1d&range=1y`,
    signal,
  );
  if (
    !object(value) ||
    value.ticker !== ticker ||
    value.interval !== "1d" ||
    value.completed_only !== true ||
    !validTime(value.fetched_at) ||
    !Array.isArray(value.points) ||
    value.points.length === 0 ||
    !object(value.quality)
  )
    return fail();
  if (!freshness.includes(String(value.freshness_status))) return fail();
  let previous = "";
  for (const point of value.points) {
    if (
      !object(point) ||
      !validTime(point.timestamp) ||
      typeof point.date !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(point.date) ||
      point.date <= previous ||
      !finite(point.close) ||
      Number(point.close) <= 0
    )
      return fail();
    previous = point.date;
  }
  if (!Array.isArray(value.quality.warnings)) return fail();
  return value as unknown as MarketHistory;
}
