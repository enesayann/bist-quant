import type { DashboardDataSource } from "../types";
import { mockMarket } from "./mockMarket";
import { mockPortfolio } from "./mockPortfolio";
import { mockActivity, mockStrategies } from "./mockActivity";
export const mockDataSource: DashboardDataSource = {
  async loadDashboard() {
    return {
      fixtureDate: "09 Oct 2026",
      session: "18:10 TRT · End of session",
      marketStatus: "Market Closed",
      stocks: mockMarket,
      portfolio: mockPortfolio,
      activity: mockActivity,
      strategies: mockStrategies,
    };
  },
};
