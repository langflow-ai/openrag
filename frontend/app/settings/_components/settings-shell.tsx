/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

"use client";

import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import { SettingsNav } from "./settings-nav";

export function SettingsShell({ children }: { children: React.ReactNode }) {
  const isCloudBrand = useIsCloudBrand();
  return (
    <div
      className={cn(
        "pb-6 w-full",
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
