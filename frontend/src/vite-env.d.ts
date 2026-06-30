/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_DEV_API_PROXY_TARGET: string;
  readonly VITE_AUTH_PROVIDER: "dev-mint" | "cognito";
  readonly VITE_DEV_JWT_SECRET: string;
  readonly VITE_DEV_JWT_ISSUER: string;
  readonly VITE_DEV_JWT_AUDIENCE: string;
  readonly VITE_COGNITO_AUTHORITY: string;
  readonly VITE_COGNITO_CLIENT_ID: string;
  readonly VITE_COGNITO_REDIRECT_URI: string;
  readonly VITE_COGNITO_SCOPE: string;
  readonly VITE_PHOENIX_URL: string;
  readonly VITE_MOCK_AGENT: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
