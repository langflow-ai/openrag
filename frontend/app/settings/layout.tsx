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

import { Suspense } from "react";
import { SettingsShell } from "./_components/settings-shell";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense>
      <SettingsShell>{children}</SettingsShell>
    </Suspense>
  );
}
