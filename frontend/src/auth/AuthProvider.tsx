import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { env } from "@/lib/env";
import { useAuthStore } from "@/store/auth";

import { createCognitoAdapter } from "./cognito";
import { createDevMintAdapter } from "./devMint";
import type { AuthProviderAdapter, CognitoCredentials, DevMintOptions } from "./types";

interface AuthContextValue {
  provider: AuthProviderAdapter["kind"];
  /** True until the initial restore() resolves — guard routes on this. */
  initializing: boolean;
  isAuthenticated: boolean;
  signInDevMint: (options: DevMintOptions) => Promise<void>;
  signInCognito: (credentials: CognitoCredentials) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function selectAdapter(): AuthProviderAdapter {
  return env.authProvider === "cognito"
    ? createCognitoAdapter()
    : createDevMintAdapter();
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const adapter = useMemo(selectAdapter, []);
  const setSession = useAuthStore((s) => s.setSession);
  const clear = useAuthStore((s) => s.clear);
  const isAuthenticated = useAuthStore((s) => Boolean(s.token));
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void adapter.restore().then((session) => {
      if (cancelled) return;
      if (session) setSession(session);
      setInitializing(false);
    });
    return () => {
      cancelled = true;
    };
  }, [adapter, setSession]);

  const signInDevMint = useCallback(
    async (options: DevMintOptions) => {
      const session = await createDevMintAdapter().signIn(options);
      if (session) setSession(session);
    },
    [setSession],
  );

  const signInCognito = useCallback(
    async (credentials: CognitoCredentials) => {
      const session = await createCognitoAdapter().signIn(credentials);
      if (session) setSession(session);
    },
    [setSession],
  );

  const signOut = useCallback(async () => {
    await adapter.signOut();
    clear();
  }, [adapter, clear]);

  const value = useMemo<AuthContextValue>(
    () => ({
      provider: adapter.kind,
      initializing,
      isAuthenticated,
      signInDevMint,
      signInCognito,
      signOut,
    }),
    [adapter.kind, initializing, isAuthenticated, signInDevMint, signInCognito, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
