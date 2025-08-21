"use client"

import * as React from "react"
import { X, ChevronDown, Check } from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { ScrollArea } from "@/components/ui/scroll-area"

interface Option {
  value: string
  label: string
  count?: number
}

interface MultiSelectProps {
  options: Option[]
  value: string[]
  onValueChange: (value: string[]) => void
  placeholder?: string
  className?: string
  maxSelection?: number
  searchPlaceholder?: string
  showAllOption?: boolean
  allOptionLabel?: string
}

export function MultiSelect({
  options,
  value,
  onValueChange,
  placeholder = "Select items...",
  className,
  maxSelection,
  searchPlaceholder = "Search...",
  showAllOption = true,
  allOptionLabel = "All"
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false)
  const [searchValue, setSearchValue] = React.useState("")

  const isAllSelected = value.includes("*")
  
  const filteredOptions = options.filter(option =>
    option.label.toLowerCase().includes(searchValue.toLowerCase())
  )

  const handleSelect = (optionValue: string) => {
    if (optionValue === "*") {
      // Toggle "All" selection
      if (isAllSelected) {
        onValueChange([])
      } else {
        onValueChange(["*"])
      }
    } else {
      let newValue: string[]
      if (value.includes(optionValue)) {
        // Remove the item
        newValue = value.filter(v => v !== optionValue && v !== "*")
      } else {
        // Add the item and remove "All" if present
        newValue = [...value.filter(v => v !== "*"), optionValue]
        
        // Check max selection limit
        if (maxSelection && newValue.length > maxSelection) {
          return
        }
      }
      onValueChange(newValue)
    }
  }

  const handleRemove = (optionValue: string) => {
    if (optionValue === "*") {
      onValueChange([])
    } else {
      onValueChange(value.filter(v => v !== optionValue))
    }
  }

  const getDisplayText = () => {
    if (isAllSelected) {
      return allOptionLabel
    }
    
    if (value.length === 0) {
      return placeholder
    }
    
    // Extract the noun from placeholder (e.g., "Select data sources..." -> "data sources")
    const noun = placeholder.toLowerCase().replace('select ', '').replace('...', '')
    return `${value.length} ${noun}`
  }

  const getSelectedBadges = () => {
    if (isAllSelected) {
      return [
        <Badge 
          key="all" 
          variant="secondary" 
          className="mr-1 mb-1"
        >
          {allOptionLabel}
          <Button
            variant="ghost"
            size="sm"
            className="ml-1 h-auto p-0 text-muted-foreground hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation()
              handleRemove("*")
            }}
          >
            <X className="h-3 w-3" />
          </Button>
        </Badge>
      ]
    }

    return value.map(val => {
      const option = options.find(opt => opt.value === val)
      return (
        <Badge 
          key={val} 
          variant="secondary" 
          className="mr-1 mb-1"
        >
          {option?.label || val}
          <Button
            variant="ghost"
            size="sm"
            className="ml-1 h-auto p-0 text-muted-foreground hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation()
              handleRemove(val)
            }}
          >
            <X className="h-3 w-3" />
          </Button>
        </Badge>
      )
    })
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "w-full justify-between min-h-[40px] h-auto text-left",
            className
          )}
        >
          <span className="text-foreground text-sm">
            {getDisplayText()}
          </span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-full p-0" align="start">
        <Command>
          <CommandInput
            placeholder={searchPlaceholder}
            value={searchValue}
            onValueChange={setSearchValue}
          />
          <CommandEmpty>No items found.</CommandEmpty>
          <CommandGroup>
            <ScrollArea className="max-h-64">
              {showAllOption && (
                <CommandItem
                  key="all"
                  onSelect={() => handleSelect("*")}
                  className="cursor-pointer"
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      isAllSelected ? "opacity-100" : "opacity-0"
                    )}
                  />
                  <span className="flex-1">{allOptionLabel}</span>
                  <span className="text-xs text-blue-500 bg-blue-500/10 px-1.5 py-0.5 rounded ml-2">
                    *
                  </span>
                </CommandItem>
              )}
              {filteredOptions.map((option) => (
                <CommandItem
                  key={option.value}
                  onSelect={() => handleSelect(option.value)}
                  className="cursor-pointer"
                  disabled={isAllSelected}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value.includes(option.value) ? "opacity-100" : "opacity-0"
                    )}
                  />
                  <span className="flex-1">{option.label}</span>
                  {option.count !== undefined && (
                    <span className="text-xs text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded ml-2">
                      {option.count}
                    </span>
                  )}
                </CommandItem>
              ))}
            </ScrollArea>
          </CommandGroup>
        </Command>
      </PopoverContent>
    </Popover>
  )
}