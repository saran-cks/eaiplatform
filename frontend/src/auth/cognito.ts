import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
  type CognitoUserSession,
} from "amazon-cognito-identity-js";

import { env } from "@/lib/env";
import { decodeClaims } from "@/store/auth";

import type { AuthProviderAdapter, AuthSession, SignInOptions } from "./types";

/**
 * Prod auth path (DD-19, Option B): AWS Cognito via the **SRP** flow, run directly
 * against the user pool from our *own* login form — no Hosted UI redirect. The
 * password never reaches the Core API; the browser gets id/access/refresh tokens
 * from Cognito and sends the chosen one as `Authorization: Bearer`, which the
 * backend only *verifies* (RS256/JWKS). Flipping VITE_AUTH_PROVIDER=cognito +
 * setting the pool/client ids is the only change needed once the pool exists.
 *
 * The bearer is `VITE_COGNITO_TOKEN_USE` (default "access", matching the Core
 * API's COGNITO_TOKEN_USE). `amazon-cognito-identity-js` persists + refreshes the
 * SRP session in localStorage, so `restore()` rehydrates across reloads.
 */

function selectToken(session: CognitoUserSession): string {
  return env.cognito.tokenUse === "id"
    ? session.getIdToken().getJwtToken()
    : session.getAccessToken().getJwtToken();
}

/** Map a verified Cognito session to our AuthSession, or throw if claims are unusable. */
function sessionToAuth(session: CognitoUserSession): AuthSession {
  const token = selectToken(session);
  const claims = decodeClaims(token);
  if (!claims) {
    throw new Error(
      `Cognito ${env.cognito.tokenUse} token carries no tenant_id/permissions. Map ` +
        "cognito:groups -> permissions and a tenant attribute -> tenant_id (the id " +
        "token carries custom:tenant_id; the access token needs a pre-token Lambda). See DD-19.",
    );
  }
  return { token, claims };
}

export function createCognitoAdapter(): AuthProviderAdapter {
  const configured = Boolean(env.cognito.userPoolId && env.cognito.clientId);
  const pool = configured
    ? new CognitoUserPool({
        UserPoolId: env.cognito.userPoolId,
        ClientId: env.cognito.clientId,
      })
    : null;

  function requirePool(): CognitoUserPool {
    if (!pool) {
      throw new Error(
        "Cognito is not configured. Set VITE_COGNITO_USER_POOL_ID and " +
          "VITE_COGNITO_CLIENT_ID, or use VITE_AUTH_PROVIDER=dev-mint for local dev.",
      );
    }
    return pool;
  }

  return {
    kind: "cognito",

    async restore(): Promise<AuthSession | null> {
      const user = pool?.getCurrentUser();
      if (!user) return null;
      return new Promise((resolve) => {
        user.getSession((err: Error | null, session: CognitoUserSession | null) => {
          if (err || !session?.isValid()) {
            resolve(null);
            return;
          }
          try {
            resolve(sessionToAuth(session));
          } catch {
            resolve(null); // valid signature but unusable claims — treat as signed-out
          }
        });
      });
    },

    async signIn(options?: SignInOptions): Promise<AuthSession | null> {
      if (!options || !("username" in options)) {
        throw new Error("cognito signIn requires { username, password }");
      }
      const userPool = requirePool();
      const { username, password, newPassword } = options;
      const user = new CognitoUser({ Username: username, Pool: userPool });
      const details = new AuthenticationDetails({ Username: username, Password: password });

      return new Promise<AuthSession | null>((resolve, reject) => {
        const done = (session: CognitoUserSession) => {
          try {
            resolve(sessionToAuth(session));
          } catch (e) {
            reject(e instanceof Error ? e : new Error(String(e)));
          }
        };
        const fail = (err: unknown) =>
          reject(err instanceof Error ? err : new Error(String(err)));

        user.authenticateUser(details, {
          onSuccess: done,
          onFailure: fail,
          newPasswordRequired: () => {
            if (!newPassword) {
              reject(
                new Error(
                  "This account must set a new password on first sign-in — " +
                    "re-submit with a new password.",
                ),
              );
              return;
            }
            // Pass no attribute updates: pools that *require* new attributes on the
            // challenge are a FUTURE EXTENSION (would need extra form fields).
            user.completeNewPasswordChallenge(
              newPassword,
              {},
              { onSuccess: done, onFailure: fail },
            );
          },
        });
      });
    },

    async signOut() {
      pool?.getCurrentUser()?.signOut();
    },
  };
}
