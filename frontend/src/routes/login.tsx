import { useNavigate, useSearch } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { useAuth } from "@/auth/AuthProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Login form. The Core API has no login route and never will — this only produces
 * a bearer the backend will *verify* (DD-19). Two paths behind one AuthProvider seam:
 * dev-mint collects tenant/subject/permissions and signs an HS256 token in-browser;
 * cognito collects username/password and runs the SRP flow directly against the user
 * pool (Option B — our own form, not the Hosted UI). Swap = VITE_AUTH_PROVIDER.
 */
export function LoginPage() {
  const { provider, signInDevMint, signInCognito } = useAuth();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { redirect?: string };

  const [tenantId, setTenantId] = useState("acme");
  const [subject, setSubject] = useState("dev-user");
  const [permissions, setPermissions] = useState("kb:read, agent:run, obs:read");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (provider === "cognito") {
        await signInCognito({
          username: username.trim(),
          password,
          newPassword: newPassword || undefined,
        });
      } else {
        await signInDevMint({
          tenantId: tenantId.trim(),
          subject: subject.trim(),
          permissions: permissions
            .split(",")
            .map((p) => p.trim())
            .filter(Boolean),
        });
      }
      await navigate({ to: search.redirect ?? "/conversation" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-background p-6">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-surface p-6"
      >
        <div>
          <h1 className="font-accent text-lg">eai//platform</h1>
          <p className="text-xs text-muted-foreground">
            {provider === "cognito"
              ? "sign in with your organization account"
              : "dev sign-in — mints a local HS256 token"}
          </p>
        </div>

        {provider === "cognito" && (
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">username</span>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">password</span>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">
                new password (only on first sign-in)
              </span>
              <Input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
            </label>
          </div>
        )}

        {provider === "dev-mint" && (
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">tenant_id</span>
              <Input
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                required
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">subject (sub)</span>
              <Input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                required
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">
                permissions (comma-separated)
              </span>
              <Input
                value={permissions}
                onChange={(e) => setPermissions(e.target.value)}
              />
            </label>
          </div>
        )}

        {error && <p className="text-xs text-destructive">{error}</p>}

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "signing in…" : "sign in"}
        </Button>
      </form>
    </div>
  );
}
