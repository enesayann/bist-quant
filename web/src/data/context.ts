import { createContext, useContext } from "react";
import type { DashboardSnapshot } from "../types";
export const DataContext = createContext<DashboardSnapshot | null>(null);
export function useDashboard() {
  const data = useContext(DataContext);
  if (!data) throw new Error("useDashboard requires DashboardDataProvider");
  return data;
}
