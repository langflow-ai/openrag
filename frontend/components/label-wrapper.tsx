import { Info } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

export function LabelWrapper({
  label,
  helperText,
  id,
  required,
  children,
}: {
  label: string;
  helperText: string;
  id: string;
  required: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <Label
        htmlFor={id}
        className="text-mmd font-medium flex items-center gap-1"
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
      <div className="relative">{children}</div>
    </div>
  );
}
