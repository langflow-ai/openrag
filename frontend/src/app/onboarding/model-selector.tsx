import { CheckIcon, ChevronsUpDownIcon } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function ModelSelector({
  options,
  value,
  onValueChange,
  icon,
}: {
  options: {
    value: string;
    label: string;
    default?: boolean;
  }[];
  value: string;
  icon?: React.ReactNode;
  onValueChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {/** biome-ignore lint/a11y/useSemanticElements: has to be a Button */}
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full gap-2 justify-between font-normal text-sm"
        >
          {value ? (
            <div className="flex items-center gap-2">
              <div className="w-4 h-4">{icon}</div>
              {options.find((framework) => framework.value === value)?.label}
              {options.find((framework) => framework.value === value)
                ?.default && (
                <span className="text-xs text-foreground p-1 rounded-md bg-muted">
                  Default
                </span>
              )}
            </div>
          ) : (
            "Select model..."
          )}
          <ChevronsUpDownIcon className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[400px] p-0">
        <Command>
          <CommandInput placeholder="Search model..." />
          <CommandList>
            <CommandEmpty>No model found.</CommandEmpty>
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.value}
                  value={option.value}
                  onSelect={(currentValue) => {
                    if (currentValue !== value) {
                      onValueChange(currentValue);
                    }
                    setOpen(false);
                  }}
                >
                  <CheckIcon
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === option.value ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <div className="flex items-center gap-2">
                    {option.label}
                    {option.default && (
                      <span className="text-xs text-foreground p-1 rounded-md bg-muted">
                        Default
                      </span>
                    )}
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
