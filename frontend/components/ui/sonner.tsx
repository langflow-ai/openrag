"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

// Filled circle icons matching Carbon's inline-notification icon style.
// Each is a solid colored circle with a symbol inside.
// Exported for unit testing only.
export const SuccessIcon = () => (
  // green-500 in light, emerald-400 in dark — matches Carbon success icon brightness
  <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-green-500 dark:bg-[hsl(var(--accent-emerald-foreground))]">
    <svg viewBox="0 0 12 12" fill="none" className="size-3" aria-hidden>
      <path
        d="M2 6l3 3 5-5"
        stroke="white"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  </span>
);

export const WarningIcon = () => (
  // Bright yellow circle with dark exclamation — matches Carbon warning icon
  <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-amber-400 dark:bg-amber-300">
    <svg viewBox="0 0 12 12" fill="none" className="size-3" aria-hidden>
      <path
        d="M6 3.5v3M6 8.5v.5"
        stroke="black"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  </span>
);

export const ErrorIcon = () => (
  <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--accent-red-foreground))]">
    <svg viewBox="0 0 12 12" fill="none" className="size-3" aria-hidden>
      <path
        d="M2.5 2.5l7 7"
        stroke="white"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  </span>
);

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      icons={{
        success: <SuccessIcon />,
        warning: <WarningIcon />,
        error: <ErrorIcon />,
      }}
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
          // Override sonner's fixed 16×16 icon slot so the 20×20 circle renders fully,
          // and align it to the top of the content block (next to the title).
          icon: "!size-5 !h-auto self-start mt-0.5",
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
