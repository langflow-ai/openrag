import { useEffect, useRef } from "react";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import { secretsToReenter } from "@/components/models/provider-credentials";

/**
 * The saved secrets that must be typed again before Submit, reported to the
 * parent as one readable reason (or `null` once nothing blocks it).
 *
 * A saved secret is not sent to an endpoint or TLS setting other than the one
 * it was saved for, so changing the target leaves those fields to re-enter.
 * Returns their keys so each field can say why.
 */
export function useOnboardingCompletionBlocker({
  credentials,
  savedSecrets,
  activeKeys,
  targetChanged,
  fields,
  onCompletionBlockerChange,
}: {
  credentials: Record<string, string>;
  savedSecrets: Set<string>;
  /** The keys the chosen auth method uses, or null when every field applies. */
  activeKeys: Set<string> | null;
  targetChanged: boolean;
  fields: CatalogCredentialField[];
  onCompletionBlockerChange?: (blocker: string | null) => void;
}): string[] {
  const reenterKeys = secretsToReenter(
    credentials,
    savedSecrets,
    activeKeys,
    targetChanged,
  );
  const reenterLabels = reenterKeys.map(
    (key) => fields.find((field) => field.key === key)?.label ?? key,
  );
  // A string, so the effect below re-runs only when the reason changes.
  const completionBlocker =
    reenterLabels.length > 0
      ? `Enter ${reenterLabels.join(", ")} again: the endpoint or TLS setting changed.`
      : null;
  const onCompletionBlockerChangeRef = useRef(onCompletionBlockerChange);
  onCompletionBlockerChangeRef.current = onCompletionBlockerChange;
  useEffect(() => {
    onCompletionBlockerChangeRef.current?.(completionBlocker);
  }, [completionBlocker]);
  // A tab that is switched away from must not keep blocking the next one.
  useEffect(() => () => onCompletionBlockerChangeRef.current?.(null), []);

  return reenterKeys;
}
