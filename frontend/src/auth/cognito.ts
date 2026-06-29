import { env } from "@/lib/env";

import type { AuthProviderAdapter, AuthSession } from "./types";

/**
 * Prod auth path: Cognito OIDC Authorization Code + PKCE (DD-19). DESIGNED, NOT
 * WIRED — the flow shape is laid out so flipping VITE_AUTH_PROVIDER=cognito is
 * the only change needed once the user pool exists and the backend swaps its
 * HS256 verifier for RS256/JWKS. Until then signIn() throws a clear error.
 *
 * FUTURE EXTENSION: implement PKCE (generate verifier/challenge → redirect to
 * the authorize endpoint → handle the /login?code= callback → exchange the code
 * at the token endpoint → store the id/access token). The IdP must map profile/
 * group attributes onto `tenant_id` + `permissions[]` claims so the backend's
 * PermissionScope.from_claims keeps working unchanged.
 */
export function createCognitoAdapter(): AuthProviderAdapter {
  const configured = Boolean(env.cognito.authority && env.cognito.clientId);

  return {
    kind: "cognito",

    async restore(): Promise<AuthSession | null> {
      // FUTURE: detect ?code=&state= callback and complete the token exchange.
      return null;
    },

    async signIn(): Promise<AuthSession | null> {
      if (!configured) {
        throw new Error(
          "Cognito is not configured. Set VITE_COGNITO_AUTHORITY and " +
            "VITE_COGNITO_CLIENT_ID, or use VITE_AUTH_PROVIDER=dev-mint for local dev.",
        );
      }
      throw new Error(
        "Cognito OIDC PKCE flow is designed but not yet wired (DD-19). " +
          "Use the dev-mint provider until the user pool + RS256/JWKS swap land.",
      );
    },

    async signOut() {
      // FUTURE: redirect to the Cognito logout endpoint to end the IdP session.
    },
  };
}
