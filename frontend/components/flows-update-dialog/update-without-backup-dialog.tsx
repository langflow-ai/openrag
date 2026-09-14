import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface UpdateWithoutBackupDialogProps {
  open: boolean;
  isUpdating: boolean;
  isUpdatingWithBackup: boolean | null;
  onOpenChange: (open: boolean) => void;
  onBackupAndUpdate: () => void;
  onContinueWithoutBackup: () => void;
}

export function UpdateWithoutBackupDialog({
  open,
  isUpdating,
  isUpdatingWithBackup,
  onOpenChange,
  onBackupAndUpdate,
  onContinueWithoutBackup,
}: UpdateWithoutBackupDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[540px]">
        <DialogHeader>
          <DialogTitle>Update without a backup</DialogTitle>
          <DialogDescription className="sr-only">
            Update without a backup confirmation
          </DialogDescription>
        </DialogHeader>

        <div className="py-2 text-sm text-muted-foreground leading-relaxed">
          <p>
            If you&apos;ve customized any OpenRAG flows, updating without a
            backup permanently removes those customizations. You won&apos;t be
            able to restore them after the update.
          </p>
        </div>

        <DialogFooter>
          <Button onClick={onBackupAndUpdate} disabled={isUpdating}>
            <div>
              {isUpdating && isUpdatingWithBackup
                ? "Updating..."
                : "Back up my flows"}
            </div>
          </Button>
          <Button
            variant="outline"
            onClick={onContinueWithoutBackup}
            disabled={isUpdating}
          >
            <div>
              {isUpdating && isUpdatingWithBackup === false
                ? "Updating..."
                : "Continue without backup"}
            </div>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
