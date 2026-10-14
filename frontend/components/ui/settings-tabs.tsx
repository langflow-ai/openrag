"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      orientation={orientation}
      className={cn(
        "group/tabs flex gap-2 data-[orientation=horizontal]:flex-col",
        className,
      )}
      {...props}
    />
  );
}

const tabsListVariants = cva(
  "group/tabs-list inline-flex w-fit items-center justify-center rounded-lg p-[3px] text-muted-foreground group-data-[orientation=horizontal]/tabs:h-8 group-data-[orientation=vertical]/tabs:h-fit group-data-[orientation=vertical]/tabs:flex-col data-[variant=line]:rounded-none",
  {
    variants: {
      variant: {
        default: "bg-muted",
        line: "mb-6 h-auto gap-0 rounded-none bg-transparent p-0 group-data-[orientation=horizontal]/tabs:h-auto",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function TabsList({
  className,
  variant = "default",
  ...props
}: ComponentProps<typeof TabsPrimitive.List> &
  VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  );
}

function TabsTrigger({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-1.5 py-0.5 text-sm font-medium whitespace-nowrap text-foreground/60 transition-all group-data-[orientation=vertical]/tabs:w-full group-data-[orientation=vertical]/tabs:justify-start hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 dark:text-muted-foreground dark:hover:text-foreground data-[state=active]:group-data-[variant=default]/tabs-list:shadow-xs data-[state=active]:group-data-[variant=line]/tabs-list:shadow-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        "hover:group-data-[variant=default]/tabs-list:bg-accent hover:group-data-[variant=default]/tabs-list:text-accent-foreground data-[state=active]:group-data-[variant=default]/tabs-list:bg-background data-[state=active]:group-data-[variant=default]/tabs-list:text-foreground data-[state=active]:group-data-[variant=default]/tabs-list:shadow-xs dark:hover:group-data-[variant=default]/tabs-list:bg-neutral-900 dark:hover:group-data-[variant=default]/tabs-list:text-white dark:focus-visible:group-data-[variant=default]/tabs-list:bg-neutral-900 dark:focus-visible:group-data-[variant=default]/tabs-list:text-white dark:focus-visible:group-data-[variant=default]/tabs-list:ring-0 dark:focus-visible:group-data-[variant=default]/tabs-list:ring-offset-0 dark:data-[state=active]:group-data-[variant=default]/tabs-list:bg-neutral-900 dark:data-[state=active]:group-data-[variant=default]/tabs-list:text-white",
        "group-data-[variant=line]/tabs-list:box-border group-data-[variant=line]/tabs-list:flex-none group-data-[variant=line]/tabs-list:h-auto group-data-[variant=line]/tabs-list:shrink-0 group-data-[variant=line]/tabs-list:rounded-none group-data-[variant=line]/tabs-list:border-0 group-data-[variant=line]/tabs-list:border-b-2 group-data-[variant=line]/tabs-list:border-b-transparent group-data-[variant=line]/tabs-list:px-4 group-data-[variant=line]/tabs-list:py-[11px] group-data-[variant=line]/tabs-list:font-normal group-data-[variant=line]/tabs-list:shadow-none group-data-[variant=line]/tabs-list:transition-none hover:group-data-[variant=line]/tabs-list:bg-transparent data-[state=active]:group-data-[variant=line]/tabs-list:font-semibold hover:data-[state=active]:group-data-[variant=line]/tabs-list:bg-transparent group-data-[variant=line]/tabs-list:after:hidden",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({
  className,
  ...props
}: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("flex-1 text-sm outline-hidden", className)}
      {...props}
    />
  );
}

export { Tabs, TabsContent, TabsList, TabsTrigger };
