"use client";

import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import { SettingsNav } from "./settings-nav";

export function SettingsShell({ children }: { children: React.ReactNode }) {
  const isCloudBrand = useIsCloudBrand();
  return (
    <div
      className={cn(
        "pb-6",
        isCloudBrand && "font-ibm-plex-sans ibm-settings-page",
      )}
    >
      <h2
        className={cn(
          "text-lg font-semibold mb-6",
          isCloudBrand && "ibm-section-title",
        )}
      >
        Settings
      </h2>
      <SettingsNav />
      {children}
    </div>
  );
}
