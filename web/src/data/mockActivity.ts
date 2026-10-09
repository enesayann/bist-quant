import type { Activity, StrategyState } from "../types";
export const mockActivity: Activity[] = [
  {
    ticker: "ASELS",
    text: "Daily setup strengthened",
    time: "17:48",
    kind: "setup",
  },
  {
    ticker: "GARAN",
    text: "Momentum score increased",
    time: "17:32",
    kind: "momentum",
  },
  {
    ticker: "THYAO",
    text: "Setup invalidated",
    time: "16:55",
    kind: "invalidated",
  },
  {
    ticker: "SISE",
    text: "Position stop updated",
    time: "16:41",
    kind: "position",
  },
];
export const mockStrategies: StrategyState[] = [
  { name: "Daily Strategy v1", status: "Available", tone: "positive" },
  { name: "Intraday Strategy v2", status: "Not implemented", tone: "muted" },
  { name: "Intraday Data Contract", status: "Ready", tone: "accent" },
];
