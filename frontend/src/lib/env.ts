/** Typed, centralized access to Vite env. Nothing else reads import.meta.env. */

export type AuthProviderKind = "dev-mint" | "cognito";

export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  authProvider: (import.meta.env.VITE_AUTH_PROVIDER ?? "dev-mint") as AuthProviderKind,
  devJwt: {
    secret: import.meta.env.VITE_DEV_JWT_SECRET ?? "change-me-dev-only",
    issuer: import.meta.env.VITE_DEV_JWT_ISSUER ?? "core-api",
    audience: import.meta.env.VITE_DEV_JWT_AUDIENCE ?? "core-api-clients",
  },
  cognito: {
    authority: import.meta.env.VITE_COGNITO_AUTHORITY ?? "",
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID ?? "",
    redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI ?? "",
    scope: import.meta.env.VITE_COGNITO_SCOPE ?? "openid profile email",
  },
  /** Phoenix UI origin the observability tab links out to (obs:admin only). */
  phoenixUrl: import.meta.env.VITE_PHOENIX_URL ?? "http://localhost:6006",
  /**
   * Use the in-browser mock agent stream + mock artifacts instead of the live
   * LangGraph backend (default on — the agent runtime isn't runnable locally).
   * Set VITE_MOCK_AGENT=0 to hit the real `/agent` endpoints.
   */
  mockAgent: (import.meta.env.VITE_MOCK_AGENT ?? "1") !== "0",
} as const;
