export type Signal = "LONG" | "WATCH" | "NEUTRAL";
export type Strategy = "Daily v1" | "No Setup";
export type Category = "trend" | "momentum" | "volume" | "volatility";
export type Scores = Record<Category, number>;
export interface PricePoint {
  date: string;
  value: number;
}
export interface MarketStock {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  change: number;
  strategy: Strategy;
  score: number;
  scores: Scores;
  signal: Signal;
  volume: number;
  updated: string;
  history: PricePoint[];
  exampleLevels: { entry: number; stop: number; tp1: number; tp2: number };
  demoPerformance: {
    trades: number;
    winRate: number;
    profitFactor: number;
    drawdown: number;
  };
}
export interface Position {
  ticker: string;
  entry: number;
  current: number;
  quantity: number;
  stop: number;
  tp1: number;
  tp2: number;
}
export interface Portfolio {
  value: number;
  dailyPnl: number;
  dailyChange: number;
  openRisk: number;
  maxPositions: number;
  cash: number;
  startingCapital: number;
  equity: PricePoint[];
  positions: Position[];
}
export interface Activity {
  ticker: string;
  text: string;
  time: string;
  kind: "setup" | "momentum" | "invalidated" | "position";
}
export interface StrategyState {
  name: string;
  status: string;
  tone: "positive" | "muted" | "accent";
}
export interface DashboardSnapshot {
  fixtureDate: string;
  session: string;
  marketStatus: string;
  stocks: MarketStock[];
  portfolio: Portfolio;
  activity: Activity[];
  strategies: StrategyState[];
}
export interface DashboardDataSource {
  loadDashboard(): Promise<DashboardSnapshot>;
}
