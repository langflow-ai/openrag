"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          // Mimics Carbon inline-notification (no Carbon package — project tokens only):
          //   light → tinted surface (accent-* bg) + accent-foreground left border
          //   dark  → neutral card surface + accent-foreground left border only
          success:
            "group-[.toaster]:!bg-accent-emerald dark:group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-accent-emerald dark:group-[.toaster]:!border-border [&_[data-description]]:!text-muted-foreground [border-left:3px_solid_hsl(var(--accent-emerald-foreground))]",
          warning:
            "group-[.toaster]:!bg-accent-amber dark:group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-accent-amber dark:group-[.toaster]:!border-border [&_[data-description]]:!text-muted-foreground [border-left:3px_solid_hsl(var(--accent-amber-foreground))]",
          error:
            "group-[.toaster]:!bg-accent-red dark:group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-accent-red dark:group-[.toaster]:!border-border [&_[data-description]]:!text-muted-foreground [border-left:3px_solid_hsl(var(--accent-red-foreground))]",
          description: "!text-muted-foreground",
          actionButton:
            "!bg-secondary !text-secondary-foreground hover:!bg-secondary-hover",
          cancelButton: "!bg-muted !text-muted-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
