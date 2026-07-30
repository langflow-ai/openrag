"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";
import { identify, initAnalytics, page } from "@/lib/analytics";

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
  const { user, isAuthenticated } = useAuth();

  useEffect(() => {
    if (settings?.segment_write_key) {
      initAnalytics(settings.segment_write_key, settings.environment ?? "");
    }
  }, [settings?.segment_write_key, settings?.environment]);

  useEffect(() => {
    if (!isAuthenticated || !user || !settings?.segment_write_key) return;
    identify(user.user_id, {
      email: user.email,
      name: user.name,
      provider: user.provider,
      roles: user.roles,
    });
  }, [isAuthenticated, user, settings?.segment_write_key]);

  useEffect(() => {
    if (pathname === "/") return;
    page(toPageName(pathname));
  }, [pathname]);

  return null;
}
