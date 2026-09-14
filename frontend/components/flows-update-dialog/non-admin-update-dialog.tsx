import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface NonAdminUpdateDialogProps {
  open: boolean;
  onClose: () => void;
  onDismiss: () => void;
}

export function NonAdminUpdateDialog({
  open,
  onClose,
  onDismiss,
}: NonAdminUpdateDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
      <DialogContent className="sm:max-w-[540px]">
        <DialogHeader>
          <DialogTitle>Langflow flow updates available</DialogTitle>
          <DialogDescription>
            Action required by an administrator
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Updates Available</AlertTitle>
            <AlertDescription className="text-muted-foreground leading-relaxed">
              New versions of one or more Langflow flows are available. An
              administrator must review and apply the updates. Until then, some
              flows might not work as expected.
            </AlertDescription>
          </Alert>
        </div>

        <DialogFooter>
          <Button onClick={onDismiss}>
            <div>Understood</div>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
