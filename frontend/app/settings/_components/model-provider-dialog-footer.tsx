import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type ModelProviderDialogFooterProps = {
  showRemoveConfirm: boolean;
  onCancelRemove: () => void;
  onConfirmRemove: () => void;
  isRemovePending: boolean;

  isConfigured: boolean;
  canRemove: boolean;
  removeDisabledTooltip: string;
  onRequestRemove: () => void;

  onCancel: () => void;
  isSavePending: boolean;
  isValidating: boolean;
};

const ModelProviderDialogFooter = ({
  showRemoveConfirm,
  onCancelRemove,
  onConfirmRemove,
  isRemovePending,
  isConfigured,
  canRemove,
  removeDisabledTooltip,
  onRequestRemove,
  onCancel,
  isSavePending,
  isValidating,
}: ModelProviderDialogFooterProps) => {
  if (showRemoveConfirm) {
    return (
      <DialogFooter className="mt-4 flex items-center gap-2 rounded-lg border border-red-500/10 bg-red-500/5 px-4 py-3 animate-in fade-in-0 slide-in-from-bottom-2 duration-150">
        <div className="border-l-2 border-destructive pl-3 mr-auto text-sm text-red-100">
          Remove configuration?
        </div>
        <Button variant="ghost" type="button" onClick={onCancelRemove}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="destructive"
          disabled={isRemovePending}
          onClick={onConfirmRemove}
        >
          {isRemovePending ? "Removing..." : "Remove"}
        </Button>
      </DialogFooter>
    );
  }

  return (
    <DialogFooter className="mt-4 animate-in fade-in-0 slide-in-from-bottom-2 duration-150">
      {isConfigured && (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="mr-auto">
                <Button
                  variant="ghost"
                  type="button"
                  className="text-destructive hover:text-destructive"
                  disabled={!canRemove}
                  onClick={onRequestRemove}
                >
                  Remove
                </Button>
              </span>
            </TooltipTrigger>
            {!canRemove && (
              <TooltipContent>{removeDisabledTooltip}</TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
      )}
      <Button variant="outline" type="button" onClick={onCancel}>
        Cancel
      </Button>
      <Button type="submit" disabled={isSavePending || isValidating}>
        {isSavePending ? "Saving..." : isValidating ? "Validating..." : "Save"}
      </Button>
    </DialogFooter>
  );
};

export default ModelProviderDialogFooter;
