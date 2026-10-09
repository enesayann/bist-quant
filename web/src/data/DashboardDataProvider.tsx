import { useEffect, useState, type ReactNode } from "react";
import type { DashboardDataSource, DashboardSnapshot } from "../types";
import { DataContext } from "./context";
import { mockDataSource } from "./source";
export function DashboardDataProvider({
  children,
  source = mockDataSource,
}: {
  children: ReactNode;
  source?: DashboardDataSource;
}) {
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    source
      .loadDashboard()
      .then((result) => {
        if (active) setData(result);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [source]);
  if (error)
    return (
      <main className="boot-state" role="alert">
        <h1>Dashboard data unavailable</h1>
        <p>Reload the page to retry loading the offline fixtures.</p>
      </main>
    );
  if (!data)
    return (
      <main className="boot-state" role="status">
        Loading dashboard…
      </main>
    );
  return <DataContext.Provider value={data}>{children}</DataContext.Provider>;
}
