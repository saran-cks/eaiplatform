import { Link, Outlet, useRouter } from "@tanstack/react-router";

import { useAuth } from "@/auth/AuthProvider";
import { useScope } from "@/auth/useScope";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/theme/ThemeProvider";

const NAV = [
  { to: "/conversation", label: "conversation" },
  { to: "/search", label: "search" },
  { to: "/observability", label: "observability" },
  { to: "/dashboard", label: "dashboard" },
] as const;

/**
 * The authenticated app shell: top nav, theme toggle, tenant/scope badge, sign
 * out. Rendered by the auth-guarded layout route (see router.tsx); the /login
 * route renders outside it.
 */
export function RootShell() {
  const { theme, toggleTheme } = useTheme();
  const { signOut } = useAuth();
  const { tenantId } = useScope();
  const router = useRouter();

  const handleSignOut = async () => {
    await signOut();
    await router.navigate({ to: "/login" });
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-6 border-b border-border bg-surface px-4 py-2">
        <span className="font-accent text-sm tracking-tight">eai//platform</span>
        <nav className="flex items-center gap-1">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:text-foreground [&.active]:text-foreground [&.active]:underline [&.active]:underline-offset-4"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {tenantId && (
            <span className="text-xs text-muted-foreground">
              tenant:{tenantId}
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={toggleTheme}>
            {theme === "dark" ? "☾ dark" : "✎ typer"}
          </Button>
          <Button variant="outline" size="sm" onClick={handleSignOut}>
            sign out
          </Button>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
