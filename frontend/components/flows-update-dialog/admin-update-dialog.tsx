import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface AdminUpdateDialogProps {
  open: boolean;
  errorMessage: string | null;
  backupCustom: boolean;
  isOnboarding: boolean;
  isUpdating: boolean;
  isBusy: boolean;
  onClose: () => void;
  onBackupCustomChange: (checked: boolean) => void;
  onSkip: () => void;
  onUpdate: () => void;
}

export function AdminUpdateDialog({
  open,
  errorMessage,
  backupCustom,
  isOnboarding,
  isUpdating,
  isBusy,
  onClose,
  onBackupCustomChange,
  onSkip,
  onUpdate,
}: AdminUpdateDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <DialogContent className="sm:max-w-[540px]">
        <DialogHeader>
          <DialogTitle>Update Langflow flows</DialogTitle>
          <DialogDescription>
            New versions of one or more Langflow flows are available.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {errorMessage && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Update Failed</AlertTitle>
              <AlertDescription>{errorMessage}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-3 text-sm text-muted-foreground leading-relaxed">
            <p>
              If you have customized any flows, those customizations will be
              removed during the update.
            </p>
            <p>
              By default, OpenRAG backs up customized flows and stores the
              backups in its embedded Langflow instance. After the update, you
              can use the backups to manually reapply your customizations.
            </p>
            <p>
              If you don&apos;t have customized flows, a backup isn&apos;t
              required.
            </p>
          </div>

          <div className="flex items-center space-x-2 pt-2">
            <Checkbox
              id="backup-custom"
              checked={backupCustom}
              onCheckedChange={(checked) => onBackupCustomChange(!!checked)}
            />
            <label
              htmlFor="backup-custom"
              className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
            >
              Back up my flows before updating
            </label>
          </div>
        </div>

        <DialogFooter>
          {!isOnboarding && (
            <Button variant="outline" onClick={onSkip} disabled={isBusy}>
              <div>Skip update</div>
            </Button>
          )}
          <Button onClick={onUpdate} disabled={isBusy}>
            <div>{isUpdating ? "Updating..." : "Update"}</div>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
