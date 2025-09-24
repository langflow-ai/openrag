import { CheckIcon, ChevronsUpDownIcon } from "lucide-react";
import { useEffect, useState } from "react";
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
  placeholder = "Select model...",
  searchPlaceholder = "Search model...",
  noOptionsPlaceholder = "No models available",
}: {
  options: {
    value: string;
    label: string;
    default?: boolean;
  }[];
  value: string;
  icon?: React.ReactNode;
  placeholder?: string;
  searchPlaceholder?: string;
  noOptionsPlaceholder?: string;
  onValueChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (value && !options.find((option) => option.value === value)) {
      onValueChange("");
    }
  }, [options, value, onValueChange]);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {/** biome-ignore lint/a11y/useSemanticElements: has to be a Button */}
        <Button
          variant="outline"
          role="combobox"
          disabled={options.length === 0}
          aria-expanded={open}
          className="w-full gap-2 justify-between font-normal text-sm"
        >
          {value ? (
            <div className="flex items-center gap-2">
              {icon && <div className="w-4 h-4">{icon}</div>}
              {options.find((framework) => framework.value === value)?.label}
              {options.find((framework) => framework.value === value)
                ?.default && (
                <span className="text-xs text-foreground p-1 rounded-md bg-muted">
                  Default
                </span>
              )}
            </div>
          ) : options.length === 0 ? (
            noOptionsPlaceholder
          ) : (
            placeholder
          )}
          <ChevronsUpDownIcon className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[400px] p-0">
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>{noOptionsPlaceholder}</CommandEmpty>
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
