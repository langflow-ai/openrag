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
