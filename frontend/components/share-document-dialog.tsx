"use client";

import { Users, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useShareDocumentMutation } from "@/app/api/mutations/useShareDocumentMutation";
import { useUnshareDocumentMutation } from "@/app/api/mutations/useUnshareDocumentMutation";
import { useGetDocumentAclQuery } from "@/app/api/queries/useGetDocumentAclQuery";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

interface ShareDocumentDialogProps {
  filename: string;
  currentUserId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}

export const ShareDocumentDialog = ({
  filename,
  currentUserId,
  open,
  onOpenChange,
}: ShareDocumentDialogProps) => {
  const [newUserId, setNewUserId] = useState("");
  const [pendingAdd, setPendingAdd] = useState<string[]>([]);
  const [pendingRemove, setPendingRemove] = useState<string[]>([]);

  const { data: acl, isLoading } = useGetDocumentAclQuery(
    open ? filename : null,
  );
  const shareMutation = useShareDocumentMutation();
  const unshareMutation = useUnshareDocumentMutation();

  const existingUsers = acl?.allowed_users ?? [];

  // Effective list: existing + pending adds - pending removes
  const displayUsers = [
    ...existingUsers.filter((u) => !pendingRemove.includes(u)),
    ...pendingAdd,
  ];

  const handleAdd = () => {
    const trimmed = newUserId.trim();
    if (!trimmed) return;
    if (displayUsers.includes(trimmed)) {
      toast.info("User already has access");
      return;
    }
    setPendingAdd((prev) => [...prev, trimmed]);
    setNewUserId("");
  };

  const handleRemove = (userId: string) => {
    if (pendingAdd.includes(userId)) {
      setPendingAdd((prev) => prev.filter((u) => u !== userId));
    } else {
      setPendingRemove((prev) => [...prev, userId]);
    }
  };

  const handleSave = async () => {
    try {
      if (pendingAdd.length > 0) {
        await shareMutation.mutateAsync({ filename, user_ids: pendingAdd });
      }
      if (pendingRemove.length > 0) {
        await unshareMutation.mutateAsync({
          filename,
          user_ids: pendingRemove,
        });
      }
      toast.success("Sharing updated");
      setPendingAdd([]);
      setPendingRemove([]);
      onOpenChange(false);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to update sharing",
      );
    }
  };

  const isSaving = shareMutation.isPending || unshareMutation.isPending;
  const hasChanges = pendingAdd.length > 0 || pendingRemove.length > 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) {
          setPendingAdd([]);
          setPendingRemove([]);
          setNewUserId("");
        }
        onOpenChange(v);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="h-4 w-4" /> Share document
          </DialogTitle>
          <DialogDescription className="truncate text-xs text-muted-foreground">
            {filename}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="flex gap-2">
            <Input
              placeholder="Enter user ID"
              value={newUserId}
              onChange={(e) => setNewUserId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAdd();
                }
              }}
              disabled={isSaving}
            />
            <Button
              variant="secondary"
              onClick={handleAdd}
              disabled={!newUserId.trim() || isSaving}
            >
              Add
            </Button>
          </div>

          <div className="space-y-1">
            {isLoading && (
              <p className="text-sm text-muted-foreground">Loading…</p>
            )}
            {!isLoading && displayUsers.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No users have access yet.
              </p>
            )}
            {displayUsers.map((userId) => (
              <div
                key={userId}
                className="flex items-center justify-between rounded-md border px-3 py-1.5 text-sm"
              >
                <span className="truncate">
                  {userId}
                  {userId === currentUserId && (
                    <span className="ml-1 text-xs text-muted-foreground">
                      (you)
                    </span>
                  )}
                </span>
                <button
                  className="ml-2 text-muted-foreground hover:text-destructive"
                  onClick={() => handleRemove(userId)}
                  disabled={isSaving}
                  aria-label={`Remove ${userId}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isSaving}
          >
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!hasChanges || isSaving}>
            {isSaving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
