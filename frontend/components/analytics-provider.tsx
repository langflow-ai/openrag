"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { initAnalytics, page } from "@/lib/analytics";

function toPageName(pathname: string): string {
  const label = pathname
    .replace(/^\//, "")
    .replace(/\//g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
  return `OpenRAG - ${label} Page Viewed`;
}

export function Analytics() {
  const pathname = usePathname();
  const { data: settings } = useGetSettingsQuery();

  useEffect(() => {
    if (settings?.segment_write_key) {
      initAnalytics(settings.segment_write_key, settings.environment ?? "");
    }
  }, [settings?.segment_write_key, settings?.environment]);

  useEffect(() => {
    if (pathname === "/") return;
    page(toPageName(pathname));
  }, [pathname]);

  return null;
}
