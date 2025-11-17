import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "primary-input placeholder:text-placeholder-foreground min-h-fit",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
