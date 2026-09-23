"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

// Toast icons matching Carbon's inline-notification icon style.
// Paths derived from Carbon's filled icon set (MIT licence), scaled to 16×16 viewBox.
// Exported for unit testing only.

// checkmark--filled: green circle + white checkmark
export const SuccessIcon = () => (
  <svg viewBox="0 0 16 16" className="size-5 shrink-0" aria-hidden>
    <path
      fill="#24a148"
      d="M8 1C4.1 1 1 4.1 1 8s3.1 7 7 7 7-3.1 7-7-3.1-7-7-7z"
    />
    <path fill="white" d="M7 11 3.5 7.5l1-1L7 9l5.5-5.5 1 1z" />
  </svg>
);

// warning--alt--filled: amber circle + white exclamation
export const WarningIcon = () => (
  <svg viewBox="0 0 16 16" className="size-5 shrink-0" aria-hidden>
    <path
      fill="#f1c21b"
      d="M8 1C4.1 1 1 4.1 1 8s3.1 7 7 7 7-3.1 7-7-3.1-7-7-7z"
    />
    <path fill="#161616" d="M7.25 4.75h1.5v5h-1.5zM7.25 11.25h1.5v1.5h-1.5z" />
  </svg>
);

// error--filled: red circle + white backslash
export const ErrorIcon = () => (
  <svg viewBox="0 0 16 16" className="size-5 shrink-0" aria-hidden>
    <path
      fill="#da1e28"
      d="M8 1C4.1 1 1 4.1 1 8s3.1 7 7 7 7-3.1 7-7-3.1-7-7-7z"
    />
    <path fill="white" d="m10.7 11.5-6.2-6.2.8-.8 6.2 6.2z" />
  </svg>
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
