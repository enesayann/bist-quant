import { useCallback, useMemo, useState, type ReactNode } from "react";
import { AnalysisContext } from "./context";
import type { AnalysisResponse } from "./types";
export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [results, setResults] = useState<Record<string, AnalysisResponse>>({});
  const save = useCallback(
    (result: AnalysisResponse) =>
      setResults((previous) => ({ ...previous, [result.ticker]: result })),
    [],
  );
  const value = useMemo(() => ({ results, save }), [results, save]);
  return (
    <AnalysisContext.Provider value={value}>
      {children}
    </AnalysisContext.Provider>
  );
}
