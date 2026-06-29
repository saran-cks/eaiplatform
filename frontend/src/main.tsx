import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AuthProvider, useAuth } from "@/auth/AuthProvider";
import { router } from "@/router";
import { ThemeProvider } from "@/theme/ThemeProvider";

import "@/theme/themes.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000, refetchOnWindowFocus: false },
  },
});

/**
 * Hold the router until the AuthProvider has restored any persisted session.
 * This makes the route guard's auth read deterministic (no login-flash on
 * reload) — see router.tsx.
 */
function AppGate() {
  const { initializing } = useAuth();
  if (initializing) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <span className="block-caret font-body text-sm text-muted-foreground">
          loading
        </span>
      </div>
    );
  }
  return <RouterProvider router={router} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AppGate />
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
