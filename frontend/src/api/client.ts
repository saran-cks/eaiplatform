import { env } from "@/lib/env";
import { useAuthStore } from "@/store/auth";

/** Thrown for any non-2xx response; carries the status + parsed detail. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

/** Raised on 401 so the router/guard can bounce to /login. */
export class UnauthorizedError extends ApiError {
  constructor(detail: string) {
    super(401, detail);
    this.name = "UnauthorizedError";
  }
}

/** Raised on 403 so the UI can surface "you lack permission X". */
export class ForbiddenError extends ApiError {
  constructor(detail: string) {
    super(403, detail);
    this.name = "ForbiddenError";
  }
}

export function apiUrl(path: string): string {
  const base = env.apiBaseUrl.replace(/\/$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

/** Authorization header for the current session, if any. Shared with sse.ts. */
export function authHeader(): Record<string, string> {
  const token = useAuthStore.getState().token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseDetail(res: Response): Promise<string> {
  try {
    const body = (await res.clone().json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail ?? body);
  } catch {
    return res.statusText || "Request failed";
  }
}

function raiseForStatus(res: Response, detail: string): never {
  if (res.status === 401) {
    // The token is invalid/expired — drop it so the guard redirects to login.
    useAuthStore.getState().clear();
    throw new UnauthorizedError(detail);
  }
  if (res.status === 403) throw new ForbiddenError(detail);
  throw new ApiError(res.status, detail);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = apiUrl(path);
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined) params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

/**
 * The single JSON fetch wrapper: injects the Bearer token, maps 401→login and
 * 403→surface, and returns parsed JSON. SSE endpoints do NOT use this — see
 * api/sse.ts (they need POST streaming via fetch-event-source).
 */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;
  const headers: Record<string, string> = { ...authHeader() };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(buildUrl(path, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!res.ok) raiseForStatus(res, await parseDetail(res));

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}
