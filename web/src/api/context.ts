import { createContext, useContext } from "react";
import type { AnalysisResponse } from "./types";
export const AnalysisContext = createContext<{
  results: Record<string, AnalysisResponse>;
  save(result: AnalysisResponse): void;
} | null>(null);
export function useAnalysis() {
  const context = useContext(AnalysisContext);
  if (!context) throw new Error("useAnalysis requires AnalysisProvider");
  return context;
}
