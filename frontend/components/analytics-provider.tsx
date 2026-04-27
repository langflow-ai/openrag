"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { page } from "@/lib/analytics";

function toPageName(pathname: string): string {
  const label = pathname
    .replace(/^\//, "")
    .replace(/\//g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
  return `OpenRAG - ${label} Page Viewed`;
}

export function Analytics() {
  const pathname = usePathname();

  useEffect(() => {
    if (pathname === "/") return;
    page(toPageName(pathname));
  }, [pathname]);

  return null;
}
