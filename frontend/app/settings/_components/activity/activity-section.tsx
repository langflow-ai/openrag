"use client";

import { useAuth } from "@/contexts/auth-context";
import { FeedbackPanel } from "./feedback-panel";

export function ActivitySection() {
  const { activityAccess, permissionsResolved } = useAuth();

  if (!permissionsResolved) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  // The server is the real gate; this only avoids rendering a dead UI.
  if (!activityAccess) {
    return (
      <p role="alert" className="text-sm text-muted-foreground">
        Activity is unavailable. It requires RBAC enforcement and the audit:read
        permission.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <FeedbackPanel />
    </div>
  );
}
