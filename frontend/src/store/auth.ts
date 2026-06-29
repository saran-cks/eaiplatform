import { decodeJwt } from "jose";
import { create } from "zustand";

import type { AuthSession, ScopeClaims } from "@/auth/types";

const STORAGE_KEY = "eai.auth.token";

/** Best-effort decode of scope claims from a JWT (server is the real verifier). */
export function decodeClaims(token: string): ScopeClaims | null {
  try {
    const raw = decodeJwt(token);
    if (typeof raw.tenant_id !== "string" || !raw.tenant_id) return null;
    const permissions = Array.isArray(raw.permissions)
      ? raw.permissions.map(String)
      : [];
    return {
      tenant_id: raw.tenant_id,
      permissions,
      sub: typeof raw.sub === "string" ? raw.sub : undefined,
      exp: typeof raw.exp === "number" ? raw.exp : undefined,
      iss: typeof raw.iss === "string" ? raw.iss : undefined,
      aud: typeof raw.aud === "string" ? raw.aud : undefined,
    };
  } catch {
    return null;
  }
}

function isExpired(claims: ScopeClaims | null): boolean {
  if (!claims?.exp) return false;
  return claims.exp * 1000 <= Date.now();
}

interface AuthState {
  token: string | null;
  claims: ScopeClaims | null;
  /** Persist a freshly obtained token and derive its claims. */
  setSession: (session: AuthSession) => void;
  /** Hydrate from a raw token (e.g. localStorage); rejects expired/invalid. */
  loadToken: (token: string) => boolean;
  clear: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  claims: null,

  setSession: (session) => {
    localStorage.setItem(STORAGE_KEY, session.token);
    set({ token: session.token, claims: session.claims });
  },

  loadToken: (token) => {
    const claims = decodeClaims(token);
    if (!claims || isExpired(claims)) {
      localStorage.removeItem(STORAGE_KEY);
      set({ token: null, claims: null });
      return false;
    }
    localStorage.setItem(STORAGE_KEY, token);
    set({ token, claims });
    return true;
  },

  clear: () => {
    localStorage.removeItem(STORAGE_KEY);
    set({ token: null, claims: null });
  },

  isAuthenticated: () => {
    const { token, claims } = get();
    return Boolean(token) && !isExpired(claims);
  },
}));

/** The persisted token key + a non-hook reader for restore-on-load. */
export function readStoredToken(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}
