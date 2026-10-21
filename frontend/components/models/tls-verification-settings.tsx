"use client";

import { AlertTriangle } from "lucide-react";
import { useRef } from "react";
import { LabelWrapper } from "@/components/label-wrapper";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  isDefaultTlsSetting,
  isTlsVerificationDisabled,
  parseTlsSetting,
} from "./tls-verification";

const SWITCH_DESCRIPTION =
  "Validates the cluster certificate before sending credentials or model traffic.";
const CA_PATH_LABEL = "Custom CA bundle path";

/**
 * A provider's `tls_verify` catalogue field (its `ssl_verify` credential) as a
 * switch plus an optional CA bundle path. The stored value stays a single
 * string — blank or a true-equivalent word (verify), a false-equivalent word
 * (don't), or a CA path — which is what the backend's `resolve_ssl_verify`
 * reads.
 *
 * The catalogue supplies the copy and the default: `label` names the switch,
 * `tooltip` helps with the CA path, `placeholder` is the CA path example and
 * `default_value` is what "verify" is stored as (blank when it has none).
 */
export function TlsVerificationField({
  field,
  value,
  savedValue,
  onValueChange,
  idPrefix,
}: {
  field: CatalogCredentialField;
  value?: string;
  /**
   * The saved `ssl_verify`; blank when unset, as the credential-target check
   * reads it. Turning verification back on, or clearing the CA path, restores
   * it where it verifies, so neither reads as a target change.
   */
  savedValue?: string;
  onValueChange: (value: string) => void;
  idPrefix: string;
}) {
  // Written when verification is on with no CA path and nothing to restore.
  const verifiedValue =
    typeof field.default_value === "string" ? field.default_value : "";
  const { enabled, caPath } = parseTlsSetting(value);
  const saved = savedValue?.trim();
  const restoredValue =
    saved !== undefined && !isTlsVerificationDisabled(saved)
      ? saved
      : verifiedValue;
  const clearedValue =
    saved !== undefined && isDefaultTlsSetting(saved) ? saved : verifiedValue;
  // The value verification was switched off from. It lasts only as long as
  // this mount — a collapsed accordion section unmounts it — so the saved
  // value is the fallback.
  const valueBeforeDisabling = useRef<string | null>(null);

  const switchId = `${idPrefix}-tls-verify`;
  const descriptionId = `${switchId}-description`;
  const caPathId = `${idPrefix}-tls-ca-path`;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 py-1">
        <div className="space-y-1">
          <Label htmlFor={switchId} className="text-mmd font-medium">
            {field.label}
          </Label>
          <p id={descriptionId} className="text-sm text-muted-foreground">
            {SWITCH_DESCRIPTION}
          </p>
        </div>
        <Switch
          id={switchId}
          checked={enabled}
          aria-describedby={descriptionId}
          onCheckedChange={(checked) => {
            if (checked) {
              onValueChange(valueBeforeDisabling.current ?? restoredValue);
              return;
            }
            valueBeforeDisabling.current = (value ?? "").trim();
            onValueChange("false");
          }}
        />
      </div>

      {enabled ? (
        <LabelWrapper
          id={caPathId}
          label={CA_PATH_LABEL}
          helperText={field.tooltip ?? undefined}
        >
          <Input
            id={caPathId}
            value={caPath}
            placeholder={field.placeholder ?? undefined}
            autoComplete="off"
            onChange={(event) =>
              onValueChange(event.target.value || clearedValue)
            }
          />
        </LabelWrapper>
      ) : (
        <div
          role="alert"
          className="flex gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          <AlertTriangle
            className="mt-0.5 h-4 w-4 shrink-0"
            aria-hidden="true"
          />
          <p>
            Certificate verification is disabled. Credentials and model traffic
            can be intercepted. Use this only for local development.
          </p>
        </div>
      )}
    </div>
  );
}
