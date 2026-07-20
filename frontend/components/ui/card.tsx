import * as React from "react";
import { cn } from "@/lib/utils";

function Card({ className, ref, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      ref={ref}
      className={cn(
        "rounded-xl border border-border bg-card text-card-foreground shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

function CardHeader({ className, ref, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      ref={ref}
      className={cn("flex flex-col space-y-1.5 p-5", className)}
      {...props}
    />
  );
}

function CardTitle({ className, ref, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      ref={ref}
      className={cn(
        "text-base font-semibold leading-tight tracking-tight text-[14px]",
        className,
      )}
      {...props}
    />
  );
}

function CardDescription({
  className,
  ref,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      ref={ref}
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

function CardContent({
  className,
  ref,
  ...props
}: React.ComponentProps<"div">) {
  return <div ref={ref} className={cn("p-5 pt-0", className)} {...props} />;
}

function CardFooter({ className, ref, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      ref={ref}
      className={cn("flex items-center p-5 pt-0", className)}
      {...props}
    />
  );
}

export {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
};
