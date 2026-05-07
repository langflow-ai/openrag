"use client";

import { Check, ChevronDown, Minus } from "lucide-react";
import { Fragment, useState } from "react";

import {
  type AdminPermission,
  useGetAdminPermissionsQuery,
} from "@/app/api/queries/useGetAdminPermissionsQuery";
import {
  type AdminRole,
  useGetAdminRolesQuery,
} from "@/app/api/queries/useGetAdminRolesQuery";
import { Button } from "@/components/ui/button";
import { getRolePillClass } from "@/lib/role-styles";
import { cn } from "@/lib/utils";

/**
 * Friendly description mapping for what each permission *actually* gates
 * in the live system. Curated alongside the backend `require_permission`
 * sites and the frontend `<RequirePermission>` wrappers, so admins can
 * see at a glance which permission unlocks which UI / API surface.
 *
 * Anything not in this map falls back to the backend's free-form
 * `description` column from the permissions table — there's always a
 * description, this just adds a "where it bites" hint for the built-ins.
 */
const PERMISSION_GATES: Record<string, { ui: string; api: string }> = {
  // Config / Infra
  "config:read": {
    ui: "Settings page reads",
    api: "GET /settings",
  },
  "config:write": {
    ui: "Knowledge Ingest, Onboarding, Docling preset",
    api: "POST /settings, /onboarding, /onboarding/state, /onboarding/rollback, /settings/docling-preset",
  },
  "providers:read": {
    ui: "Model Providers section (read)",
    api: "GET /models, /providers",
  },
  "providers:write": {
    ui: "Model Providers section (edit)",
    api: "POST /settings (provider fields)",
  },
  "providers:override:self": {
    ui: "Per-user provider key override (Phase 4)",
    api: "PATCH /api/users/me/preferences",
  },
  "opensearch:admin": {
    ui: "(internal)",
    api: "OpenSearch security setup at startup",
  },

  // Users / RBAC
  "users:list": {
    ui: "Users & Roles table",
    api: "GET /api/admin/users",
  },
  "users:read": {
    ui: "User detail",
    api: "GET /api/admin/users/{id}",
  },
  "users:invite": {
    ui: "Activate / deactivate user",
    api: "PATCH /api/admin/users/{id}",
  },
  "users:delete": {
    ui: "Delete user (admin)",
    api: "DELETE /api/admin/users/{id}",
  },
  "roles:list": {
    ui: "Available Roles + this matrix",
    api: "GET /api/admin/roles, /api/admin/permissions",
  },
  "roles:assign": {
    ui: "+ Assign role / × Revoke role",
    api: "POST /api/admin/users/{id}/roles, DELETE /api/admin/users/{id}/roles/{role_id}",
  },
  "roles:create": {
    ui: "Create custom role (planned)",
    api: "POST /api/admin/roles",
  },
  "roles:edit": {
    ui: "Edit role permissions (planned)",
    api: "PATCH /api/admin/roles/{id}",
  },
  "roles:delete": {
    ui: "Delete custom role (planned)",
    api: "DELETE /api/admin/roles/{id}",
  },
  "audit:read": {
    ui: "Recent Activity table",
    api: "GET /api/admin/audit",
  },

  // Connectors
  "connectors:list:own": {
    ui: "List own connectors",
    api: "GET /connectors (filtered to user)",
  },
  "connectors:list:all": {
    ui: "List all users' connectors (admin)",
    api: "GET /connectors (no filter)",
  },
  "connectors:create": {
    ui: "Connect / Configure buttons in Settings",
    api: "POST /connectors/{type}/sync, OAuth init",
  },
  "connectors:delete:own": {
    ui: "Disconnect button on own connector",
    api: "DELETE /connectors/{type}/disconnect",
  },
  "connectors:delete:any": {
    ui: "Disconnect any user's connector (admin)",
    api: "DELETE /connectors/{type}/disconnect (any user)",
  },
  "connectors:use": {
    ui: "Sync, browse buckets, OAuth callback",
    api: "POST /connectors/{type}/sync, /connectors/sync-all",
  },

  // Knowledge
  "knowledge:upload": {
    ui: "Add Knowledge dropdown, file picker, folder ingest",
    api: "POST /upload, /upload_path, /upload_context, /upload_bucket",
  },
  "knowledge:delete:own": {
    ui: "Delete own document (row + bulk)",
    api: "POST /documents/delete-by-filename (own)",
  },
  "knowledge:delete:any": {
    ui: "Delete any document (admin)",
    api: "POST /documents/delete-by-filename (any)",
  },
  "knowledge:read:own": {
    ui: "Knowledge tab visibility, browse own docs",
    api: "GET /search, /knowledge/* (own scope)",
  },
  "knowledge:read:all": {
    ui: "Browse all users' docs (admin)",
    api: "GET /search, /knowledge/* (no scope)",
  },
  "kf:create": {
    ui: "Create Filter button",
    api: "POST /knowledge-filter",
  },
  "kf:edit:own": {
    ui: "Edit/Delete own KF (Save/Update/Delete buttons)",
    api: "PUT/DELETE /knowledge-filter/{id} (own)",
  },
  "kf:edit:any": {
    ui: "Edit/Delete any KF (admin)",
    api: "PUT/DELETE /knowledge-filter/{id} (any)",
  },
  "kf:share": {
    ui: "Share KF (planned)",
    api: "(planned)",
  },

  // Chat / search
  "chat:use": {
    ui: "Chat tab + send message + New Conversation",
    api: "POST /chat, /langflow",
  },
  "search:use": {
    ui: "Search bar",
    api: "POST /search",
  },
  "conversations:read:own": {
    ui: "Own chat history",
    api: "GET /chat/history, /langflow/history",
  },
  "conversations:read:all": {
    ui: "All users' history (admin)",
    api: "(planned)",
  },
  "conversations:delete:own": {
    ui: "Delete conversation menu item",
    api: "DELETE /sessions/{id} (own)",
  },
  "conversations:delete:any": {
    ui: "Delete any conversation (admin)",
    api: "DELETE /sessions/{id} (any)",
  },

  // Flows / agent
  "flows:read": {
    ui: "View Langflow",
    api: "GET /flows/*",
  },
  "flows:edit": {
    ui: "Edit in Langflow + Restore flow buttons",
    api: "POST /reset-flow/{type}",
  },
  "agent:prompt:override": {
    ui: "Per-user agent prompt (Phase 4)",
    api: "PATCH /api/users/me/preferences",
  },
  "agent:prompt:global": {
    ui: "Workspace agent system prompt textarea",
    api: "POST /settings (agent.system_prompt)",
  },

  // API keys
  "apikeys:create:self": {
    ui: "Create Key button",
    api: "POST /keys",
  },
  "apikeys:revoke:self": {
    ui: "Revoke own key (trash icon)",
    api: "DELETE /keys/{id}, /keys/{id}/permanent",
  },
  "apikeys:revoke:any": {
    ui: "Revoke any user's key (admin)",
    api: "(planned)",
  },
  "apikeys:list:any": {
    ui: "List all users' keys (admin)",
    api: "(planned)",
  },
};

interface MatrixRowProps {
  perm: AdminPermission;
  roles: AdminRole[];
}

function MatrixRow({ perm, roles }: MatrixRowProps) {
  const gate = PERMISSION_GATES[perm.name];
  return (
    <tr className="border-t hover:bg-muted/30">
      <td className="px-4 py-2.5 align-top">
        <div className="flex flex-col gap-0.5">
          <code className="text-xs font-mono text-foreground">{perm.name}</code>
          {perm.description && (
            <span className="text-xs text-muted-foreground">
              {perm.description}
            </span>
          )}
          {gate && (
            <div className="flex flex-col gap-0.5 mt-1">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                UI:{" "}
                <span className="normal-case text-muted-foreground/80">
                  {gate.ui}
                </span>
              </span>
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                API:{" "}
                <code className="normal-case text-muted-foreground/80 font-mono">
                  {gate.api}
                </code>
              </span>
            </div>
          )}
        </div>
      </td>
      {roles.map((r) => {
        const has = r.permissions.includes(perm.name);
        return (
          <td key={r.id} className="px-3 py-2.5 text-center align-top">
            {has ? (
              <Check
                className="h-4 w-4 mx-auto text-emerald-600 dark:text-emerald-400"
                aria-label={`${r.name} has ${perm.name}`}
              />
            ) : (
              <Minus
                className="h-4 w-4 mx-auto text-muted-foreground/30"
                aria-label={`${r.name} does not have ${perm.name}`}
              />
            )}
          </td>
        );
      })}
    </tr>
  );
}

export function RolePermissionsMatrix() {
  const [open, setOpen] = useState(false);
  const rolesQuery = useGetAdminRolesQuery();
  const permsQuery = useGetAdminPermissionsQuery({
    enabled: open, // lazy fetch — only when the matrix is expanded
  });

  const roles = rolesQuery.data ?? [];
  const perms = permsQuery.data ?? [];

  // Group permissions by resource for readable section headers.
  const groupedPerms = perms.reduce<Record<string, AdminPermission[]>>(
    (acc, p) => {
      if (!acc[p.resource]) acc[p.resource] = [];
      acc[p.resource].push(p);
      return acc;
    },
    {},
  );
  const sortedGroups = Object.entries(groupedPerms).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  return (
    <div className="border rounded-lg overflow-hidden">
      <Button
        type="button"
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        className="w-full justify-between h-auto px-4 py-3 rounded-none hover:bg-muted/30"
      >
        <span className="flex items-center gap-2 text-sm font-medium">
          Role × Permission matrix
          <span className="text-xs text-muted-foreground">
            ({perms.length || roles.length} permissions
            {roles.length > 0 ? ` × ${roles.length} roles` : ""})
          </span>
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </Button>

      {open && (
        <div className="border-t">
          {permsQuery.isLoading ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground">
              Loading…
            </div>
          ) : permsQuery.isError ? (
            <div className="px-4 py-6 text-sm text-destructive">
              Failed to load permission catalog:{" "}
              {(permsQuery.error as Error).message}
            </div>
          ) : perms.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground italic">
              No permissions returned (need <code>roles:list</code>).
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-muted/50 sticky top-0">
                  <tr>
                    <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                      Permission
                    </th>
                    {roles.map((r) => (
                      <th
                        key={r.id}
                        className="text-center text-sm font-medium px-3 py-3 min-w-[100px]"
                      >
                        <span className={getRolePillClass(r.name)}>
                          {r.name}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedGroups.map(([resource, resourcePerms]) => (
                    <Fragment key={`group-${resource}`}>
                      <tr className="bg-muted/20">
                        <td
                          colSpan={1 + roles.length}
                          className="px-4 py-1.5 text-[10px] uppercase tracking-wide text-muted-foreground font-semibold"
                        >
                          {resource}
                        </td>
                      </tr>
                      {resourcePerms
                        .sort((a, b) => a.action.localeCompare(b.action))
                        .map((p) => (
                          <MatrixRow key={p.id} perm={p} roles={roles} />
                        ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
