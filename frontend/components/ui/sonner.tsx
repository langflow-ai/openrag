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
          success:
            "group-[.toaster]:!bg-green-600 group-[.toaster]:!text-white group-[.toaster]:!border-green-600 [&_[data-description]]:!text-white",
          warning:
            "group-[.toaster]:!bg-amber-600 group-[.toaster]:!text-white group-[.toaster]:!border-amber-600 [&_[data-description]]:!text-white",
          error:
            "group-[.toaster]:!bg-red-600 group-[.toaster]:!text-white group-[.toaster]:!border-red-600 [&_[data-description]]:!text-white",
          description: "!text-muted-foreground",
          actionButton:
            "group-data-[type=success]:!bg-white/20 group-data-[type=success]:!text-white group-data-[type=warning]:!bg-white/20 group-data-[type=warning]:!text-white group-data-[type=error]:!bg-white/20 group-data-[type=error]:!text-white !bg-primary !text-primary-foreground",
          cancelButton: "!bg-muted !text-muted-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
