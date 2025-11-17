import * as React from "react";
import { cn } from "@/lib/utils";

export type ScrollAreaProps = React.HTMLAttributes<HTMLDivElement>;

const ScrollArea = React.forwardRef<HTMLDivElement, ScrollAreaProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn("overflow-auto scrollbar-hide", className)}
        {...props}
      >
        {children}
      </div>
    );
  },
);

ScrollArea.displayName = "ScrollArea";

export { ScrollArea };
