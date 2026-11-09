import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface SkipUpdateConfirmDialogProps {
  open: boolean;
  isBusy: boolean;
  isDismissing: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdate: () => void;
  onDismiss: () => void;
}

export function SkipUpdateConfirmDialog({
  open,
  isBusy,
  isDismissing,
  onOpenChange,
  onUpdate,
  onDismiss,
}: SkipUpdateConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[540px]">
        <DialogHeader>
          <DialogTitle>Skip the Langflow update</DialogTitle>
          <DialogDescription className="sr-only">
            Skip the Langflow update confirmation
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2 text-sm text-muted-foreground leading-relaxed">
          <p>
            OpenRAG flows are designed to work with the latest supported version
            of Langflow.
          </p>
          <p>
            If you skip this update, some flows might become incompatible and
            stop working correctly.
          </p>
        </div>

        <DialogFooter>
          <Button onClick={onUpdate} disabled={isBusy}>
            <div>Update</div>
          </Button>
          <Button variant="outline" onClick={onDismiss} disabled={isBusy}>
            <div>{isDismissing ? "Skipping..." : "Skip update"}</div>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
