import * as React from "react";
import { cn } from "@/lib/utils";

export type ScrollAreaProps = React.ComponentProps<"div">;

function ScrollArea({ className, children, ref, ...props }: ScrollAreaProps) {
  return (
    <div
      ref={ref}
      className={cn("overflow-auto scrollbar-hide", className)}
      {...props}
    >
      {children}
    </div>
  );
}

export { ScrollArea };
