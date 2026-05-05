"use client";

import { ReactNode } from "react";

import { usePermissions } from "@/hooks/use-permissions";

interface RequirePermissionProps {
  /** Single permission to require. */
  perm?: string;
  /** Multiple permissions: user must have any one of these. */
  anyOf?: string[];
  /** Multiple permissions: user must have all of these. */
  allOf?: string[];
  /** Rendered when the user has the permission(s). */
  children: ReactNode;
  /** Rendered when the user does not. Defaults to null (hidden). */
  fallback?: ReactNode;
}

/**
 * Conditionally render children based on the current user's permissions.
 *
 * Backend remains the source of truth — this is a pure UX wrapper that
 * hides affordances the backend would 403 on anyway.
 *
 * Usage:
 *   <RequirePermission perm="users:list">
 *     <UsersAndRolesTab />
 *   </RequirePermission>
 *
 *   <RequirePermission anyOf={["kf:edit:own", "kf:edit:any"]}>
 *     <EditButton />
 *   </RequirePermission>
 */
export function RequirePermission({
  perm,
  anyOf,
  allOf,
  children,
  fallback = null,
}: RequirePermissionProps) {
  const { can, canAny, canAll, isLoading } = usePermissions();

  if (isLoading) return null;

  let allowed = true;
  if (perm) allowed = allowed && can(perm);
  if (anyOf && anyOf.length > 0) allowed = allowed && canAny(anyOf);
  if (allOf && allOf.length > 0) allowed = allowed && canAll(allOf);

  return <>{allowed ? children : fallback}</>;
}
