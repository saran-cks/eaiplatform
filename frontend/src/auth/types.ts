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
 * Credentials for the Cognito SRP sign-in (DD-19, Option B): our own login form
 * authenticates the browser directly against Cognito — no Hosted UI redirect.
 * `newPassword` completes a NEW_PASSWORD_REQUIRED challenge (admin-created users
 * on first login).
 */
export interface CognitoCredentials {
  username: string;
  password: string;
  newPassword?: string;
}

/** The options either adapter's `signIn` may receive; each narrows to its own. */
export type SignInOptions = DevMintOptions | CognitoCredentials;

/**
 * One seam, two implementations (DD-19). The dev-mint adapter signs an HS256
 * token in-browser against the shared dev secret; the Cognito adapter runs the
 * SRP flow (`amazon-cognito-identity-js`) directly against the user pool from our
 * own login form and keeps the verified JWT. Swap = config (VITE_AUTH_PROVIDER),
 * no surface change — the backend only ever *verifies* the bearer.
 */
export interface AuthProviderAdapter {
  readonly kind: "dev-mint" | "cognito";
  /** Restore a session on app load (localStorage for dev-mint, cached SRP session for Cognito). */
  restore(): Promise<AuthSession | null>;
  /** Begin/complete sign-in. dev-mint takes DevMintOptions; cognito takes CognitoCredentials. */
  signIn(options?: SignInOptions): Promise<AuthSession | null>;
  /** Tear down local session state (and, for Cognito, the cached SRP tokens). */
  signOut(): Promise<void>;
}
