import { Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Label } from "./ui/label";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

export function LabelWrapper({
  label,
  description,
  helperText,
  id,
  required,
  flex,
  children,
}: {
  label: string;
  description?: string;
  helperText?: string;
  id: string;
  required?: boolean;
  flex?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex w-full items-center justify-between">
      <div
        className={cn(
          "flex flex-1 flex-col items-start",
          flex ? "gap-3" : "gap-2",
        )}
      >
        <Label
          htmlFor={id}
          className="!text-mmd font-medium flex items-center gap-1"
        >
          {label}
          {required && <span className="text-red-500">*</span>}
          {helperText && (
            <Tooltip>
              <TooltipTrigger>
                <Info className="w-3.5 h-3.5 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent>{helperText}</TooltipContent>
            </Tooltip>
          )}
        </Label>
        {!flex && <div className="relative w-full">{children}</div>}
        {description && (
          <p className="text-mmd text-muted-foreground">{description}</p>
        )}
      </div>
      {flex && <div className="relative">{children}</div>}
    </div>
  );
}
