import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { DashboardPage } from "@/routes/dashboard/index";
import { LoginPage } from "@/routes/login";
import { ObservabilityPage } from "@/routes/observability/index";
import { RootShell } from "@/routes/__root";
import { ConversationPage } from "@/routes/conversation/index";
import { SearchPage } from "@/routes/search/index";
import { useAuthStore } from "@/store/auth";

/**
 * Code-based route tree (not the file-based codegen plugin) — same type-safety,
 * no generated routeTree step. The auth guard lives on a pathless layout route
 * (`authLayout`): every child redirects to /login when there's no valid token.
 * The store is restored before the router renders (see AppGate in main.tsx), so
 * the guard reads a settled auth state with no redirect flash.
 */

const rootRoute = createRootRoute({ component: () => <Outlet /> });

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
  }),
  component: LoginPage,
});

const authLayout = createRoute({
  getParentRoute: () => rootRoute,
  id: "authed",
  beforeLoad: ({ location }) => {
    if (!useAuthStore.getState().isAuthenticated()) {
      throw redirect({ to: "/login", search: { redirect: location.href } });
    }
  },
  component: RootShell,
});

const indexRoute = createRoute({
  getParentRoute: () => authLayout,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/conversation" });
  },
});

const conversationRoute = createRoute({
  getParentRoute: () => authLayout,
  path: "/conversation",
  component: ConversationPage,
});

const searchRoute = createRoute({
  getParentRoute: () => authLayout,
  path: "/search",
  component: SearchPage,
});

const observabilityRoute = createRoute({
  getParentRoute: () => authLayout,
  path: "/observability",
  component: ObservabilityPage,
});

const dashboardRoute = createRoute({
  getParentRoute: () => authLayout,
  path: "/dashboard",
  component: DashboardPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authLayout.addChildren([
    indexRoute,
    conversationRoute,
    searchRoute,
    observabilityRoute,
    dashboardRoute,
  ]),
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
