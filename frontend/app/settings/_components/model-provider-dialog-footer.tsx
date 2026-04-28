import type { AffectedEmbeddingModel } from "@/app/api/mutations/useUpdateSettingsMutation";
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

  // When the backend returned a 409 because the provider's embedding models
  // are still referenced by indexed documents, pass the list here to render
  // a force-confirmation state.
  affectedModels?: AffectedEmbeddingModel[];
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
  affectedModels,
}: ModelProviderDialogFooterProps) => {
  if (showRemoveConfirm) {
    const hasAffected = !!affectedModels && affectedModels.length > 0;
    return (
      <DialogFooter className="mt-4 flex flex-col gap-3 rounded-lg border border-red-500/10 bg-red-500/5 px-4 py-3 animate-in fade-in-0 slide-in-from-bottom-2 duration-150 sm:flex-row sm:items-start">
        <div className="border-l-2 border-destructive pl-3 mr-auto text-sm text-red-100">
          {hasAffected ? (
            <div className="flex flex-col gap-1">
              <span>
                Semantic search will break for documents embedded with:
              </span>
              <ul className="list-disc pl-5 text-xs text-red-200/80">
                {affectedModels!.map((m) => (
                  <li key={m.model}>
                    <span className="font-mono">{m.model}</span>{" "}
                    <span className="opacity-70">
                      ({m.doc_count.toLocaleString()} chunks)
                    </span>
                  </li>
                ))}
              </ul>
              <span className="text-xs opacity-80">
                Re-ingest these with another embedding model, or remove anyway
                to keep keyword search only.
              </span>
            </div>
          ) : (
            "Remove configuration?"
          )}
        </div>
        <div className="flex items-center gap-2 sm:self-center">
          <Button variant="ghost" type="button" onClick={onCancelRemove}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={isRemovePending}
            onClick={onConfirmRemove}
          >
            {isRemovePending
              ? "Removing..."
              : hasAffected
                ? "Remove anyway"
                : "Remove"}
          </Button>
        </div>
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
