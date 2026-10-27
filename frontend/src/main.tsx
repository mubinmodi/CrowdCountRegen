import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { Shell } from "./components/Shell";
import "./index.css";
import { RequireAuth } from "./lib/auth";
import { useAppConfig } from "./lib/config";
import { AnalyticsPage } from "./pages/Analytics";
import { LoginPage, SignupPage } from "./pages/Auth";
import { CameraEditPage } from "./pages/CameraEdit";
import { CamerasPage } from "./pages/Cameras";
import { IncidentsPage } from "./pages/Incidents";
import { LivePage } from "./pages/Live";
import { PublishPage } from "./pages/Publish";

/** The public demo has no accounts, so the sign-in pages just lead to the app. */
function NoAuthInDemo({ children }: { children: ReactNode }) {
  return useAppConfig().demo_mode ? <Navigate to="/" replace /> : children;
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<NoAuthInDemo><LoginPage /></NoAuthInDemo>} />
          <Route path="/signup" element={<NoAuthInDemo><SignupPage /></NoAuthInDemo>} />
          {/* Opened on phones from a camera's publish link; authorized by the token, no login. */}
          <Route path="/publish/:token" element={<PublishPage />} />
          <Route
            element={
              <RequireAuth>
                <Shell />
              </RequireAuth>
            }
          >
            <Route index element={<LivePage />} />
            <Route path="cameras" element={<CamerasPage />} />
            <Route path="cameras/new" element={<CameraEditPage />} />
            <Route path="cameras/:id" element={<CameraEditPage />} />
            <Route path="incidents" element={<IncidentsPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
