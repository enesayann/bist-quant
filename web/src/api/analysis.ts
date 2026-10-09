import { apiRequest, ApiError } from "./client";
import type { AnalysisResponse } from "./types";
import { readExplanation } from "./explanation";

export function normalizeTicker(value: string): string {
  const ticker = value.trim().toUpperCase().replace(/\.IS$/, "");
  if (!/^[A-Z][A-Z0-9]{0,11}$/.test(ticker))
    throw new ApiError(
      "invalid_ticker",
      "Enter a BIST ticker such as ASELS or ASELS.IS.",
    );
  return ticker;
}
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const nullableNumber = (value: unknown) => value === null || finite(value);
const stringArray = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

export function validateAnalysis(
  value: unknown,
  ticker: string,
): AnalysisResponse {
  const bad = () => {
    throw new ApiError(
      "invalid_response",
      "The API returned incomplete or invalid analysis data.",
    );
  };
  if (!object(value)) return bad();
  if (
    value.ticker !== ticker ||
    value.symbol !== `${ticker}.IS` ||
    value.mode !== "research" ||
    value.analysis_type !== "daily_v1"
  )
    return bad();
  for (const key of ["as_of", "source", "disclaimer"])
    if (typeof value[key] !== "string") return bad();
  if (!Number.isFinite(Date.parse(String(value.as_of))))
    throw new ApiError(
      "invalid_response",
      "The API returned an invalid analysis timestamp.",
    );
  for (const key of [
    "market",
    "scores",
    "indicators",
    "strategy",
    "risk",
    "data_freshness",
    "data_quality",
    "cache",
  ])
    if (!object(value[key])) return bad();
  const market = value.market as Record<string, unknown>;
  for (const key of ["price", "previous_close", "change", "change_pct"])
    if (!finite(market[key])) return bad();
  if (
    Number(market.price) <= 0 ||
    Number(market.previous_close) <= 0 ||
    typeof market.price_basis !== "string"
  )
    return bad();
  const scores = value.scores as Record<string, unknown>;
  for (const key of [
    "overall",
    "technical",
    "trend",
    "momentum",
    "volume",
    "volatility",
    "support_resistance_adjustment",
  ])
    if (!finite(scores[key])) return bad();
  if (
    !nullableNumber(scores.fundamental) ||
    !nullableNumber(scores.news) ||
    !object(scores.category_maxima) ||
    typeof scores.scope !== "string"
  )
    return bad();
  for (const key of ["trend", "momentum", "volume", "volatility"])
    if (
      !finite(scores.category_maxima[key]) ||
      Number(scores.category_maxima[key]) <= 0
    )
      return bad();
  const indicators = value.indicators as Record<string, unknown>;
  for (const key of [
    "rsi",
    "ema20",
    "ema50",
    "ema200",
    "atr",
    "adx",
    "macd",
    "macd_signal",
    "mfi",
    "cmf",
    "obv",
    "vwap",
    "historical_volatility_pct",
    "supertrend",
  ])
    if (!nullableNumber(indicators[key])) return bad();
  const freshness = value.data_freshness as Record<string, unknown>;
  for (const key of [
    "last_bar",
    "expected_last_bar",
    "market_status",
    "session_note",
  ])
    if (typeof freshness[key] !== "string") return bad();
  if (
    typeof freshness.is_stale !== "boolean" ||
    freshness.completed_bars_only !== true
  )
    return bad();
  for (const key of ["last_bar", "expected_last_bar"])
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(String(freshness[key])) ||
      !Number.isFinite(Date.parse(`${String(freshness[key])}T12:00:00Z`))
    )
      return bad();
  const strategy = value.strategy as Record<string, unknown>;
  if (
    !["setup", "no_setup"].includes(String(strategy.state)) ||
    !finite(strategy.score) ||
    !finite(strategy.technical_score)
  )
    return bad();
  for (const key of ["name", "scope"])
    if (typeof strategy[key] !== "string") return bad();
  for (const key of ["signal", "classification"])
    if (strategy[key] !== null && typeof strategy[key] !== "string")
      return bad();
  const risk = value.risk as Record<string, unknown>;
  if (
    !nullableNumber(risk.atr_pct) ||
    (risk.volatility_state !== null &&
      typeof risk.volatility_state !== "string")
  )
    return bad();
  const quality = value.data_quality as Record<string, unknown>;
  for (const key of ["rows_downloaded", "rows_removed", "usable_rows"])
    if (
      !finite(quality[key]) ||
      !Number.isInteger(quality[key]) ||
      Number(quality[key]) < 0
    )
      return bad();
  if (!stringArray(quality.warnings) || !stringArray(value.warnings))
    return bad();
  const cache = value.cache as Record<string, unknown>;
  if (
    typeof cache.hit !== "boolean" ||
    !finite(cache.ttl_seconds) ||
    !finite(cache.age_seconds)
  )
    return bad();
  if (
    !Array.isArray(value.price_series) ||
    value.price_series.length < 2 ||
    !value.price_series.every(
      (point) =>
        object(point) &&
        typeof point.date === "string" &&
        /^\d{4}-\d{2}-\d{2}$/.test(point.date) &&
        finite(point.value) &&
        point.value > 0,
    )
  )
    return bad();
  return {
    ...value,
    explanation: readExplanation(
      value.explanation,
      String(value.as_of),
      String(freshness.last_bar),
    ),
  } as unknown as AnalysisResponse;
}
export async function analyzeStock(
  value: string,
  signal?: AbortSignal,
): Promise<AnalysisResponse> {
  const ticker = normalizeTicker(value);
  return validateAnalysis(
    await apiRequest("/api/v1/analyze", { ticker }, signal),
    ticker,
  );
}
