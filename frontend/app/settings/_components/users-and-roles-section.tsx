"use client";

import { Loader2, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useAssignRoleMutation } from "@/app/api/mutations/useAssignRoleMutation";
import { useRevokeRoleMutation } from "@/app/api/mutations/useRevokeRoleMutation";
import {
  type AdminRole,
  useGetAdminRolesQuery,
} from "@/app/api/queries/useGetAdminRolesQuery";
import {
  type AdminUser,
  useGetAdminUsersQuery,
} from "@/app/api/queries/useGetAdminUsersQuery";
import { RolePermissionsPreview } from "@/components/role-permissions-preview";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { getRolePillClass } from "@/lib/role-styles";
import { cn } from "@/lib/utils";

import { AuditLogFeed } from "./audit-log-feed";
import { RolePermissionsMatrix } from "./role-permissions-matrix";

interface UserRowProps {
  u: AdminUser;
  roles: AdminRole[];
  onAssign: (userId: string, roleId: string) => void;
  onRevoke: (userId: string, roleId: string, roleName: string) => void;
  pending: boolean;
  selfDbId?: string;
}

function UserRow({
  u,
  roles,
  onAssign,
  onRevoke,
  pending,
  selfDbId,
}: UserRowProps) {
  const [selectedRole, setSelectedRole] = useState<string>("");
  const isSelf = selfDbId && selfDbId === u.id;
  const availableRoles = roles.filter((r) => !u.roles.includes(r.name));

  return (
    <tr className="border-t">
      <td className="px-4 py-3">
        <div className="flex items-center gap-3 min-w-0">
          <Avatar className="rounded-md w-8 h-8 shrink-0">
            {u.picture_url && (
              <AvatarImage src={u.picture_url} alt={u.display_name ?? ""} />
            )}
            <AvatarFallback className="text-xs rounded-md">
              {(u.display_name ?? u.email ?? "?").charAt(0).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium truncate">
                {u.display_name ?? "(unnamed)"}
              </p>
              {isSelf && (
                <Badge variant="outline" className="text-[10px] py-0 px-1.5">
                  you
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground truncate">
              {u.email ?? u.oauth_subject}
            </p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {u.roles.length === 0 ? (
            <span className="text-xs text-muted-foreground italic">
              no roles
            </span>
          ) : (
            u.roles.map((r) => {
              const role = roles.find((rr) => rr.name === r);
              return (
                <span key={r} className={getRolePillClass(r)}>
                  {r}
                  {role && (
                    <RolePermissionsPreview
                      name={role.name}
                      description={role.description}
                      permissions={role.permissions}
                    />
                  )}
                  {role && (
                    <button
                      type="button"
                      aria-label={`Remove ${r}`}
                      disabled={pending}
                      onClick={() => onRevoke(u.id, role.id, role.name)}
                      className="inline-flex h-5 w-5 items-center justify-center rounded-full hover:bg-foreground/10 transition-colors -mr-1 disabled:opacity-50"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </span>
              );
            })
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <Select
          value={selectedRole}
          onValueChange={(v) => {
            setSelectedRole("");
            const role = roles.find((rr) => rr.id === v);
            if (role) onAssign(u.id, role.id);
          }}
          disabled={pending || availableRoles.length === 0}
        >
          <SelectTrigger className="h-9 w-[160px] text-sm ml-auto">
            <SelectValue placeholder="+ Assign role" />
          </SelectTrigger>
          <SelectContent>
            {availableRoles.map((r) => (
              <SelectItem key={r.id} value={r.id} className="text-sm py-2">
                <span className="capitalize font-medium">{r.name}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </td>
    </tr>
  );
}

export function UsersAndRolesSection() {
  const isCloudBrand = useIsCloudBrand();
  const { user: currentUser } = useAuth();
  const usersQuery = useGetAdminUsersQuery();
  const rolesQuery = useGetAdminRolesQuery();
  const assignMutation = useAssignRoleMutation();
  const revokeMutation = useRevokeRoleMutation();

  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<string>("__all");

  const [pendingRevoke, setPendingRevoke] = useState<{
    user_id: string;
    role_id: string;
    role_name: string;
  } | null>(null);

  const onAssign = (user_id: string, role_id: string) => {
    assignMutation.mutate(
      { user_id, role_id },
      {
        onSuccess: () => toast.success("Role assigned"),
        onError: (err: Error) => toast.error(err.message),
      },
    );
  };

  const performRevoke = (user_id: string, role_id: string) => {
    revokeMutation.mutate(
      { user_id, role_id },
      {
        onSuccess: () => toast.success("Role revoked"),
        onError: (err: Error) => toast.error(err.message),
      },
    );
  };

  const onRevoke = (user_id: string, role_id: string, role_name: string) => {
    if (role_name === "admin") {
      setPendingRevoke({ user_id, role_id, role_name });
      return;
    }
    performRevoke(user_id, role_id);
  };

  const isLoading = usersQuery.isLoading || rolesQuery.isLoading;
  const isMutating = assignMutation.isPending || revokeMutation.isPending;
  const users = usersQuery.data ?? [];
  const roles = rolesQuery.data ?? [];

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter((u) => {
      if (filterRole !== "__all" && !u.roles.includes(filterRole)) return false;
      if (!q) return true;
      const hay =
        `${u.email ?? ""} ${u.display_name ?? ""} ${u.oauth_subject}`.toLowerCase();
      return hay.includes(q);
    });
  }, [users, search, filterRole]);

  const selfDbId = useMemo(() => {
    if (!currentUser) return undefined;
    const match = users.find(
      (u) =>
        u.oauth_subject === currentUser.user_id || u.id === currentUser.user_id,
    );
    return match?.id;
  }, [users, currentUser]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between mb-3">
            <CardTitle
              className={cn(
                "text-lg flex items-center gap-2",
                isCloudBrand && "ibm-settings-section-title",
              )}
            >
              <ShieldCheck className="h-5 w-5" /> Users & Roles
            </CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                usersQuery.refetch();
                rolesQuery.refetch();
              }}
              disabled={usersQuery.isFetching || rolesQuery.isFetching}
            >
              <RefreshCw
                className={cn(
                  "h-4 w-4 mr-2",
                  (usersQuery.isFetching || rolesQuery.isFetching) &&
                    "animate-spin",
                )}
              />
              Refresh
            </Button>
          </div>
          <CardDescription>
            Assign or revoke roles for users in your workspace. Backend enforces
            all permission checks; this UI mirrors the live state.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Search + filter row — heights match Settings primitives (h-9) */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search by name, email, or ID"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select value={filterRole} onValueChange={setFilterRole}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="All roles" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all">All roles</SelectItem>
                {roles.map((r) => (
                  <SelectItem key={r.id} value={r.name}>
                    <span className="capitalize">{r.name}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* User table — matches API Keys table styling */}
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : usersQuery.isError ? (
            <div className="text-sm text-destructive py-4">
              Failed to load users: {(usersQuery.error as Error).message}
            </div>
          ) : filteredUsers.length === 0 ? (
            <div className="text-sm text-muted-foreground italic py-8 text-center">
              {users.length === 0
                ? "No users found, or you do not have permission to list users."
                : "No users match your search."}
            </div>
          ) : (
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                      User
                    </th>
                    <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                      Roles
                    </th>
                    <th className="text-right text-sm font-medium text-muted-foreground px-4 py-3 w-[180px]">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.map((u) => (
                    <UserRow
                      key={u.id}
                      u={u}
                      roles={roles}
                      onAssign={onAssign}
                      onRevoke={onRevoke}
                      pending={isMutating}
                      selfDbId={selfDbId}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Available Roles strip + collapsible matrix */}
          {roles.length > 0 && (
            <div className="pt-2 space-y-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
                  Available Roles
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {roles.map((r) => (
                    <span key={r.id} className={getRolePillClass(r.name)}>
                      {r.name}
                      <RolePermissionsPreview
                        name={r.name}
                        description={r.description}
                        permissions={r.permissions}
                      />
                    </span>
                  ))}
                </div>
              </div>
              <RolePermissionsMatrix />
            </div>
          )}
        </CardContent>
      </Card>

      <AuditLogFeed />

      <Dialog
        open={pendingRevoke !== null}
        onOpenChange={(open) => !open && setPendingRevoke(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="mb-4">Revoke admin role?</DialogTitle>
            <DialogDescription className="text-left">
              <span className="block mb-2">
                You are about to remove the <strong>admin</strong> role from
                this user. They will lose all admin permissions immediately.
              </span>
              <span className="block text-xs text-muted-foreground">
                The backend prevents removing the last admin in the workspace.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setPendingRevoke(null)}
              size="sm"
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (pendingRevoke) {
                  performRevoke(pendingRevoke.user_id, pendingRevoke.role_id);
                  setPendingRevoke(null);
                }
              }}
              size="sm"
            >
              Revoke admin
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
