export const DEMO_MODE = import.meta.env.VITE_DATA_MODE === "demo";
export const stockPath = (ticker: string) =>
  `/stocks/${ticker}${DEMO_MODE ? "?demo=1" : ""}`;
