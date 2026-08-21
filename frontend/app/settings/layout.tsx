import { Suspense } from "react";
import { UnsavedChangesProvider } from "@/contexts/unsaved-changes-context";
import { SettingsShell } from "./_components/settings-shell";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense>
      <UnsavedChangesProvider>
        <SettingsShell>{children}</SettingsShell>
      </UnsavedChangesProvider>
    </Suspense>
  );
}
