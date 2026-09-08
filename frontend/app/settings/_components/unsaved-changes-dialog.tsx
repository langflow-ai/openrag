"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useUnsavedChangesGuard } from "@/contexts/unsaved-changes-context";

export function UnsavedChangesDialog() {
  const { showDialog, confirmLeave, cancelLeave } = useUnsavedChangesGuard();

  return (
    <Dialog open={showDialog} onOpenChange={(open) => !open && cancelLeave()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="mb-4">Unsaved changes</DialogTitle>
          <DialogDescription className="text-left">
            You have unsaved changes that will be lost if you leave this page.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={cancelLeave} size="sm">
            Stay
          </Button>
          <Button variant="destructive" onClick={confirmLeave} size="sm">
            Leave
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
