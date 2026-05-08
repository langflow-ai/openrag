"use client";

import { Copy, Key, Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useCreateApiKeyMutation } from "@/app/api/mutations/useCreateApiKeyMutation";
import { useRevokeApiKeyMutation } from "@/app/api/mutations/useRevokeApiKeyMutation";
import { useGetApiKeysQuery } from "@/app/api/queries/useGetApiKeysQuery";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { LabelWrapper } from "@/components/label-wrapper";
import { RequirePermission } from "@/components/require-permission";
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
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";

function formatDate(dateString: string | null) {
  if (!dateString) return "Never";
  return new Date(dateString).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function ApiKeysSection() {
  const isCloudBrand = useIsCloudBrand();
  const { isAuthenticated, isNoAuthMode } = useAuth();

  const [createKeyDialogOpen, setCreateKeyDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<string | null>(null);
  const [showKeyDialogOpen, setShowKeyDialogOpen] = useState(false);

  const { data: apiKeysData, isLoading: apiKeysLoading } = useGetApiKeysQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const createApiKeyMutation = useCreateApiKeyMutation({
    onSuccess: (data) => {
      setNewlyCreatedKey(data.api_key);
      setCreateKeyDialogOpen(false);
      setShowKeyDialogOpen(true);
      setNewKeyName("");
      toast.success("API key created");
    },
    onError: (error) => {
      toast.error("Failed to create API key", { description: error.message });
    },
  });

  const revokeApiKeyMutation = useRevokeApiKeyMutation({
    onSuccess: () => {
      toast.success("API key revoked");
    },
    onError: (error) => {
      toast.error("Failed to revoke API key", { description: error.message });
    },
  });

  const handleCreateApiKey = () => {
    if (!newKeyName.trim()) {
      toast.error("Please enter a name for the API key");
      return;
    }
    createApiKeyMutation.mutate({ name: newKeyName.trim() });
  };

  const handleCopyApiKey = async () => {
    if (newlyCreatedKey) {
      try {
        await navigator.clipboard.writeText(newlyCreatedKey);
        toast.success("API key copied to clipboard");
      } catch {
        toast.error("Failed to copy API key to clipboard");
      }
    }
  };

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between mb-3">
            <CardTitle
              className={cn(
                "text-lg",
                isCloudBrand && "ibm-settings-section-title",
              )}
            >
              API Keys
            </CardTitle>
            <RequirePermission perm="apikeys:create:self">
              <Button onClick={() => setCreateKeyDialogOpen(true)} size="sm">
                <Plus className="h-4 w-4 mr-2" />
                Create Key
              </Button>
            </RequirePermission>
          </div>
          <CardDescription>
            API keys allow programmatic access to OpenRAG via the public API.
            Keep your keys secure and never share them publicly.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {apiKeysLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : apiKeysData?.keys && apiKeysData.keys.length > 0 ? (
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                      Name
                    </th>
                    <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                      Key
                    </th>
                    <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                      Created
                    </th>
                    <th className="text-left text-sm font-medium text-muted-foreground px-4 py-3">
                      Last Used
                    </th>
                    <th className="text-right text-sm font-medium text-muted-foreground px-4 py-3">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeysData.keys.map((key) => (
                    <tr key={key.key_id} className="border-t">
                      <td className="px-4 py-3 text-sm font-medium">
                        {key.name}
                      </td>
                      <td className="px-4 py-3">
                        <code className="text-sm bg-muted px-2 py-1 rounded">
                          {key.key_prefix}...
                        </code>
                      </td>
                      <td className="px-4 py-3 text-sm text-muted-foreground">
                        {formatDate(key.created_at)}
                      </td>
                      <td className="px-4 py-3 text-sm text-muted-foreground">
                        {formatDate(key.last_used_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <ConfirmationDialog
                          trigger={
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive hover:bg-destructive/10"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          }
                          title="Revoke API Key"
                          description={
                            <>
                              Are you sure you want to revoke the API key{" "}
                              <strong>{key.name}</strong>? This action cannot be
                              undone and any applications using this key will
                              stop working.
                            </>
                          }
                          confirmText="Revoke"
                          variant="destructive"
                          onConfirm={(closeDialog) => {
                            revokeApiKeyMutation.mutate({ key_id: key.key_id });
                            closeDialog();
                          }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8">
              <Key className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
              <p className="text-muted-foreground mb-4">
                No API keys yet. Create one to get started.
              </p>
              <RequirePermission perm="apikeys:create:self">
                <Button
                  variant="outline"
                  onClick={() => setCreateKeyDialogOpen(true)}
                  size="sm"
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Create your first API key
                </Button>
              </RequirePermission>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={createKeyDialogOpen} onOpenChange={setCreateKeyDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create API Key</DialogTitle>
            <DialogDescription>
              Give your API key a name to help you identify it later.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <LabelWrapper label="Name" id="api-key-name">
              <Input
                id="api-key-name"
                placeholder="e.g., Production App, Development"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreateApiKey();
                }}
              />
            </LabelWrapper>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => {
                setCreateKeyDialogOpen(false);
                setNewKeyName("");
              }}
              size="sm"
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreateApiKey}
              disabled={createApiKeyMutation.isPending || !newKeyName.trim()}
              size="sm"
            >
              {createApiKeyMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Creating...
                </>
              ) : (
                "Create Key"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showKeyDialogOpen}
        onOpenChange={(open) => {
          setShowKeyDialogOpen(open);
          if (!open) setNewlyCreatedKey(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API Key Created</DialogTitle>
            <DialogDescription>
              Copy your API key now. You won&apos;t be able to see it again.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <div className="bg-muted rounded-lg p-4 font-mono text-sm break-all">
              {newlyCreatedKey}
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setShowKeyDialogOpen(false)}
              size="sm"
            >
              Close
            </Button>
            <Button onClick={handleCopyApiKey} size="sm">
              <Copy className="h-4 w-4 mr-2" />
              Copy Key
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
