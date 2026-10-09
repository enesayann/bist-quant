import type { MarketStock, PricePoint, Scores, Signal } from "../types";

// Deterministic fixtures, never downloaded prices or computed strategy outputs.
export function exampleHistory(
  endValue: number,
  length: number,
  startDate: string,
  drift = 0.12,
): PricePoint[] {
  // Fixed seed gives irregular example history without runtime randomness.
  let seed = 1701;
  let walk = 0;
  const values = Array.from({ length }, (_, i) => {
    seed = (seed * 16807) % 2147483647;
    walk += (seed / 2147483647 - 0.5) * 0.004;
    return (
      1 - drift + (drift * i) / (length - 1) + walk + Math.sin(i * 0.11) * 0.004
    );
  });
  const anchor = values.at(-1)!;
  return values.map((value, i) => {
    const date = new Date(`${startDate}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + i);
    return {
      date: date.toISOString().slice(0, 10),
      value: Number(((value / anchor) * endValue).toFixed(2)),
    };
  });
}
const fixtures: Array<
  [string, string, string, number, number, Scores, Signal, number]
> = [
  [
    "ASELS",
    "Aselsan",
    "Defense & technology",
    214.3,
    2.4,
    { trend: 88, momentum: 82, volume: 76, volatility: 64 },
    "LONG",
    28400000,
  ],
  [
    "THYAO",
    "Turkish Airlines",
    "Air transportation",
    312.5,
    -1.18,
    { trend: 61, momentum: 48, volume: 67, volatility: 43 },
    "NEUTRAL",
    19200000,
  ],
  [
    "TUPRS",
    "Tüpraş",
    "Energy & refining",
    168.8,
    0.72,
    { trend: 74, momentum: 69, volume: 62, volatility: 71 },
    "WATCH",
    14600000,
  ],
  [
    "BIMAS",
    "BİM",
    "Consumer retail",
    524.0,
    0.38,
    { trend: 70, momentum: 65, volume: 58, volatility: 78 },
    "WATCH",
    3100000,
  ],
  [
    "EREGL",
    "Ereğli Demir Çelik",
    "Steel & materials",
    27.84,
    -0.64,
    { trend: 45, momentum: 42, volume: 54, volatility: 69 },
    "NEUTRAL",
    51200000,
  ],
  [
    "KCHOL",
    "Koç Holding",
    "Diversified holding",
    192.6,
    1.05,
    { trend: 77, momentum: 73, volume: 66, volatility: 72 },
    "WATCH",
    8700000,
  ],
  [
    "GARAN",
    "Garanti BBVA",
    "Banking",
    132.4,
    1.62,
    { trend: 83, momentum: 81, volume: 79, volatility: 68 },
    "LONG",
    32100000,
  ],
  [
    "SISE",
    "Şişecam",
    "Glass & materials",
    41.65,
    -0.31,
    { trend: 63, momentum: 57, volume: 61, volatility: 74 },
    "WATCH",
    24800000,
  ],
  [
    "FROTO",
    "Ford Otosan",
    "Automotive",
    108.2,
    -0.92,
    { trend: 52, momentum: 44, volume: 59, volatility: 61 },
    "NEUTRAL",
    6200000,
  ],
  [
    "TCELL",
    "Turkcell",
    "Telecommunications",
    103.7,
    0.88,
    { trend: 76, momentum: 71, volume: 68, volatility: 79 },
    "WATCH",
    12800000,
  ],
];
export const mockMarket: MarketStock[] = fixtures.map(
  ([ticker, name, sector, price, change, scores, signal, volume], index) => ({
    ticker,
    name,
    sector,
    price,
    change,
    scores,
    signal,
    volume,
    strategy: signal === "NEUTRAL" ? "No Setup" : "Daily v1",
    score: Math.round(
      Object.values(scores).reduce((sum, value) => sum + value, 0) / 4,
    ),
    updated: "18:10 TRT",
    history: exampleHistory(price, 365, "2025-10-10", 0.09 + index * 0.008),
    exampleLevels: {
      entry: Number((price * 0.985).toFixed(2)),
      stop: Number((price * 0.935).toFixed(2)),
      tp1: Number((price * 1.04).toFixed(2)),
      tp2: Number((price * 1.08).toFixed(2)),
    },
    demoPerformance: {
      trades: 12 + index,
      winRate: 50 + (index % 4) * 4.2,
      profitFactor: 1.12 + (index % 3) * 0.16,
      drawdown: 6.4 + index * 0.3,
    },
  }),
);
