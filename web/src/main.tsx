import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ThemeProvider } from "./lib/theme";
import { BacktestPage } from "./pages/Backtest";
import { BacktestsPage } from "./pages/Backtests";
import { ComparePage } from "./pages/Compare";
import { DocPage, FilePage } from "./pages/Doc";
import { JournalPage } from "./pages/Journal";
import { LivePage } from "./pages/Live";
import { NotFound } from "./pages/NotFound";
import { OrbPage } from "./pages/Orb";
import { OverviewPage } from "./pages/Overview";
import { ResearchPage } from "./pages/Research";
import { StudyPage } from "./pages/Study";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, refetchOnWindowFocus: false, retry: 1 } },
});

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <OverviewPage /> },
      { path: "/research", element: <ResearchPage /> },
      { path: "/research/*", element: <StudyPage /> },
      { path: "/doc", element: <DocPage /> },
      { path: "/file", element: <FilePage /> },
      { path: "/backtests", element: <BacktestsPage /> },
      { path: "/backtests/compare", element: <ComparePage /> },
      { path: "/backtests/:runId", element: <BacktestPage /> },
      { path: "/live", element: <LivePage /> },
      { path: "/journal", element: <JournalPage /> },
      { path: "/orb", element: <OrbPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
