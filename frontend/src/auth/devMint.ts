import { SignJWT } from "jose";

import { env } from "@/lib/env";
import { decodeClaims, readStoredToken } from "@/store/auth";

import type { AuthProviderAdapter, AuthSession, SignInOptions } from "./types";

/**
 * Local-dev auth: mint an HS256 JWT in the browser against the shared dev secret
 * (VITE_DEV_JWT_SECRET, which must equal the Core API's JWT_SECRET). The minted
 * claims — tenant_id, permissions[], sub, iss, aud, exp — are exactly what the
 * backend's AuthMiddleware + PermissionScope.from_claims expect.
 *
 * NEVER ship this path to prod: the secret would be exposed client-side. Prod
 * uses the Cognito OIDC adapter behind the same AuthProviderAdapter seam.
 */
export function createDevMintAdapter(): AuthProviderAdapter {
  return {
    kind: "dev-mint",

    async restore() {
      const token = readStoredToken();
      if (!token) return null;
      const claims = decodeClaims(token);
      if (!claims) return null;
      if (claims.exp && claims.exp * 1000 <= Date.now()) return null;
      return { token, claims };
    },

    async signIn(options?: SignInOptions): Promise<AuthSession | null> {
      if (!options || !("tenantId" in options)) {
        throw new Error("dev-mint signIn requires DevMintOptions");
      }
      const ttl = options.ttlSeconds ?? 3600;
      const secret = new TextEncoder().encode(env.devJwt.secret);

      const token = await new SignJWT({
        tenant_id: options.tenantId,
        permissions: options.permissions,
      })
        .setProtectedHeader({ alg: "HS256", typ: "JWT" })
        .setSubject(options.subject)
        .setIssuer(env.devJwt.issuer)
        .setAudience(env.devJwt.audience)
        .setIssuedAt()
        .setExpirationTime(`${ttl}s`)
        .sign(secret);

      const claims = decodeClaims(token);
      if (!claims) return null;
      return { token, claims };
    },

    async signOut() {
      // Stateless: clearing the store (caller) is sufficient.
    },
  };
}
