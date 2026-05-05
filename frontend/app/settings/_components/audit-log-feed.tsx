"use client";

import { Activity, Loader2, RefreshCw } from "lucide-react";
import { useMemo } from "react";

import { useGetAdminUsersQuery } from "@/app/api/queries/useGetAdminUsersQuery";
import {
  type AuditEvent,
  useGetAuditEventsQuery,
} from "@/app/api/queries/useGetAuditEventsQuery";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";

/** Colored dot + label for an event. No pill chrome — pills are reserved for roles. */
const EVENT_PRESENTATION: Record<string, { label: string; dot: string }> = {
  // Greens — additive, healthy
  "user.bootstrap_admin": {
    label: "Bootstrap admin",
    dot: "bg-emerald-500",
  },
  "user.created": { label: "User created", dot: "bg-emerald-500" },
  "user.role.assigned": { label: "Role assigned", dot: "bg-emerald-500" },
  "role.created": { label: "Role created", dot: "bg-emerald-500" },

  // Blues — informational, neutral mutations
  "user.updated": { label: "User updated", dot: "bg-blue-500" },
  "role.updated": { label: "Role updated", dot: "bg-blue-500" },
  "user.merged_legacy": { label: "Merged legacy", dot: "bg-blue-500" },

  // Reds — destructive
  "user.deleted": { label: "User deleted", dot: "bg-red-500" },
  "user.role.revoked": { label: "Role revoked", dot: "bg-red-500" },
  "role.deleted": { label: "Role deleted", dot: "bg-red-500" },

  // Amber — warnings / denials
  "permission.denied": { label: "Permission denied", dot: "bg-amber-500" },
};

function formatHumanRelative(iso: string): string {
  const ts = new Date(iso).getTime();
  const diffMs = Date.now() - ts;
  const sec = Math.round(diffMs / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec} seconds ago`;
  const min = Math.round(sec / 60);
  if (min === 1) return "a minute ago";
  if (min < 60) return `${min} minutes ago`;
  const hr = Math.round(min / 60);
  if (hr === 1) return "an hour ago";
  if (hr < 24) return `${hr} hours ago`;
  const day = Math.round(hr / 24);
  if (day === 1) return "yesterday";
  if (day < 7) return `${day} days ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function summarizeMetadata(e: AuditEvent): string | null {
  const m = e.audit_metadata;
  if (!m) return null;
  if (typeof m.role_name === "string") return m.role_name;
  if (typeof m.role === "string") return m.role;
  if (typeof m.required === "string") return m.required;
  if (typeof m.name === "string") return m.name;
  return null;
}

export function AuditLogFeed() {
  const isCloudBrand = useIsCloudBrand();
  const auditQuery = useGetAuditEventsQuery({ limit: 20 });
  const usersQuery = useGetAdminUsersQuery();

  const events = auditQuery.data ?? [];
  const users = usersQuery.data ?? [];

  // Build a map: db_user_id -> display label (name or email).
  const userLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const u of users) {
      const label = u.display_name || u.email || u.oauth_subject;
      map.set(u.id, label);
      // Also key by oauth_subject so legacy events whose actor_user_id is
      // the OAuth sub still resolve.
      if (u.oauth_subject) map.set(u.oauth_subject, label);
    }
    return map;
  }, [users]);

  const labelFor = (id: string | null): string => {
    if (!id) return "—";
    return userLabel.get(id) ?? `${id.slice(0, 8)}…`;
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between mb-3">
          <CardTitle
            className={cn(
              "text-lg flex items-center gap-2",
              isCloudBrand && "ibm-settings-section-title",
            )}
          >
            <Activity className="h-5 w-5" /> Recent Activity
          </CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => auditQuery.refetch()}
            disabled={auditQuery.isFetching}
          >
            <RefreshCw
              className={cn(
                "h-4 w-4 mr-2",
                auditQuery.isFetching && "animate-spin",
              )}
            />
            Refresh
          </Button>
        </div>
        <CardDescription>
          Last 20 RBAC events. Backend writes one row per role assignment,
          revocation, or permission denial.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {auditQuery.isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : auditQuery.isError ? (
          <div className="text-sm text-destructive py-4">
            Failed to load audit log: {(auditQuery.error as Error).message}
          </div>
        ) : events.length === 0 ? (
          <div className="text-center py-8">
            <Activity className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
            <p className="text-muted-foreground text-sm">
              No events yet, or you do not have{" "}
              <code className="text-xs bg-muted px-1 py-0.5 rounded">
                audit:read
              </code>
              .
            </p>
          </div>
        ) : (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-muted/50">
                <tr>
                  <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3 w-[200px]">
                    Event
                  </th>
                  <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                    Actor
                  </th>
                  <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                    Target
                  </th>
                  <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                    Detail
                  </th>
                  <th className="text-right text-sm font-medium text-muted-foreground px-4 py-3 w-[140px]">
                    When
                  </th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => {
                  const meta = EVENT_PRESENTATION[e.event] ?? {
                    label: e.event,
                    dot: "bg-muted-foreground",
                  };
                  const summary = summarizeMetadata(e);
                  return (
                    <tr key={e.id} className="border-t">
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-2 text-sm">
                          <span
                            className={cn(
                              "h-1.5 w-1.5 rounded-full shrink-0",
                              meta.dot,
                            )}
                            aria-hidden
                          />
                          <span>{meta.label}</span>
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {labelFor(e.actor_user_id)}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {labelFor(e.target_id)}
                      </td>
                      <td className="px-4 py-3 text-sm text-muted-foreground capitalize">
                        {summary ?? "—"}
                      </td>
                      <td
                        className="px-4 py-3 text-sm text-muted-foreground text-right whitespace-nowrap"
                        title={new Date(e.ts).toLocaleString()}
                      >
                        {formatHumanRelative(e.ts)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
