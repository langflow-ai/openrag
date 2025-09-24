"use client";

import { ReactNode, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface ConfirmationDialogProps {
  trigger: ReactNode;
  title: string;
  description: ReactNode;
  confirmText?: string;
  cancelText?: string;
  onConfirm: (closeDialog: () => void) => void;
  onCancel?: () => void;
  variant?: "default" | "destructive" | "warning";
  confirmIcon?: ReactNode | null;
}

export function ConfirmationDialog({
  trigger,
  title,
  description,
  confirmText = "Continue",
  cancelText = "Cancel",
  onConfirm,
  onCancel,
  variant = "default",
  confirmIcon = null,
}: ConfirmationDialogProps) {
  const [open, setOpen] = useState(false);

  const handleConfirm = () => {
    const closeDialog = () => setOpen(false);
    onConfirm(closeDialog);
  };

  const handleCancel = () => {
    onCancel?.();
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="mb-4">{title}</DialogTitle>
          <DialogDescription className="text-left">
            {description}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={handleCancel} size="sm">
            {cancelText}
          </Button>
          <Button variant={variant} onClick={handleConfirm} size="sm">
            {confirmText}
            {confirmIcon}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
