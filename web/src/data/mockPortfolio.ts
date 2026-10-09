import type { Portfolio } from "../types";
import { exampleHistory } from "./mockMarket";
export const mockPortfolio: Portfolio = {
  value: 102478.3,
  dailyPnl: 1230.4,
  dailyChange: 1.22,
  openRisk: 1.8,
  maxPositions: 5,
  cash: 35316.3,
  startingCapital: 100000,
  equity: exampleHistory(102478.3, 365, "2025-10-10", 0.025),
  positions: [
    {
      ticker: "ASELS",
      entry: 202.2,
      current: 214.3,
      quantity: 140,
      stop: 200.2,
      tp1: 218.4,
      tp2: 225.6,
    },
    {
      ticker: "GARAN",
      entry: 128.6,
      current: 132.4,
      quantity: 180,
      stop: 124.4,
      tp1: 137.0,
      tp2: 141.8,
    },
    {
      ticker: "SISE",
      entry: 42.1,
      current: 41.65,
      quantity: 320,
      stop: 39.55,
      tp1: 44.8,
      tp2: 47.1,
    },
  ],
};
