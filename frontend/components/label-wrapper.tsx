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
  start,
  children,
  disabled,
}: {
  label: string;
  description?: string;
  helperText?: string | React.ReactNode;
  id: string;
  required?: boolean;
  flex?: boolean;
  start?: boolean;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex w-full items-center",
        start ? "justify-start flex-row-reverse gap-3" : "justify-between",
        disabled && "pointer-events-none",
      )}
    >
      <div
        className={cn(
          "flex flex-1 flex-col items-start",
          flex ? "gap-3" : "gap-2",
        )}
        data-disabled={disabled}
      >
        <Label
          htmlFor={id}
          className={cn(
            "font-medium flex items-center gap-1.5",
            description ? "!text-sm" : "!text-mmd",
          )}
          data-disabled={disabled}
        >
          {label}
          {required && <span className="text-red-500">*</span>}
          {helperText && (
            <Tooltip>
              <TooltipTrigger>
                <Info className="w-3.5 h-3.5 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent side="right">{helperText}</TooltipContent>
            </Tooltip>
          )}
        </Label>
        {!flex && <div className="relative w-full">{children}</div>}
        {description && (
          <p className="text-mmd text-muted-foreground">{description}</p>
        )}
      </div>
      {flex && <div className="relative items-center flex">{children}</div>}
    </div>
  );
}
