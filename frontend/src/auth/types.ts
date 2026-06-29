/** Auth domain types shared by the dev-mint and Cognito adapters. */

/** The permission-scope claims the Core API's AuthMiddleware reads from the JWT. */
export interface ScopeClaims {
  tenant_id: string;
  permissions: string[];
  sub?: string;
  exp?: number;
  iss?: string;
  aud?: string;
}

/** An authenticated session held in the store. */
export interface AuthSession {
  token: string;
  claims: ScopeClaims;
}

/** Inputs for minting a local dev token. */
export interface DevMintOptions {
  tenantId: string;
  subject: string;
  permissions: string[];
  /** Token lifetime in seconds (default 3600, mirrors JWT_ACCESS_TTL_SECONDS). */
  ttlSeconds?: number;
}

/**
 * One seam, two implementations (DD-19). The dev-mint adapter signs an HS256
 * token in-browser against the shared dev secret; the Cognito adapter performs
 * an OIDC PKCE redirect. Swap = config (VITE_AUTH_PROVIDER), no surface change.
 */
export interface AuthProviderAdapter {
  readonly kind: "dev-mint" | "cognito";
  /** Restore a session on app load (e.g. from localStorage or an OIDC callback). */
  restore(): Promise<AuthSession | null>;
  /** Begin/complete sign-in. dev-mint needs options; cognito ignores them (redirects). */
  signIn(options?: DevMintOptions): Promise<AuthSession | null>;
  /** Tear down local session state (and, for OIDC, optionally the IdP session). */
  signOut(): Promise<void>;
}
