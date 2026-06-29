import { useAuthStore } from "@/store/auth";

/**
 * Decode the caller's permission scope for *conditional rendering only*. This is
 * UX defense-in-depth (DD-19): the server re-enforces every scope, so hiding a
 * control here is a convenience, never the security boundary.
 */
export function useScope() {
  const claims = useAuthStore((s) => s.claims);

  const permissions = claims?.permissions ?? [];
  const permissionSet = new Set(permissions);

  return {
    tenantId: claims?.tenant_id ?? null,
    subjectId: claims?.sub ?? null,
    permissions,
    has: (permission: string) => permissionSet.has(permission),
    hasAny: (...perms: string[]) => perms.some((p) => permissionSet.has(p)),
    hasAll: (...perms: string[]) => perms.every((p) => permissionSet.has(p)),
  };
}
