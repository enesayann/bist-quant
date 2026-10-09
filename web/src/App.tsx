import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Compass } from "lucide-react";
import { DashboardDataProvider } from "./data/DashboardDataProvider";
import { AnalysisProvider } from "./api/AnalysisProvider";
import { AppLayout } from "./components/Layout";
import { Overview } from "./pages/Overview";
import { Scanner } from "./pages/Scanner";
import { StockDetail } from "./pages/AnalysisStockDetail";
import {
  BacktestsPage,
  DailyPage,
  EmptyPage,
  IntradayPage,
  PositionsPage,
  SettingsPage,
  SignalsPage,
  TelegramPage,
} from "./pages/WorkspacePages";
export default function App() {
  return (
    <DashboardDataProvider>
      <AnalysisProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Overview />} />
              <Route path="scanner" element={<Scanner />} />
              <Route path="stocks/:ticker" element={<StockDetail />} />
              <Route path="positions" element={<PositionsPage />} />
              <Route path="signals" element={<SignalsPage />} />
              <Route path="backtests" element={<BacktestsPage />} />
              <Route path="research/daily" element={<DailyPage />} />
              <Route path="research/intraday" element={<IntradayPage />} />
              <Route path="telegram" element={<TelegramPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route
                path="*"
                element={
                  <EmptyPage
                    title="Page not found"
                    description="This page is not part of the research workspace."
                    icon={Compass}
                    link="/"
                    linkLabel="Back to overview"
                  />
                }
              />
            </Route>
          </Routes>
        </BrowserRouter>
      </AnalysisProvider>
    </DashboardDataProvider>
  );
}
