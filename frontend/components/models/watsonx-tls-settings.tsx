"use client";

import { AlertTriangle } from "lucide-react";
import { useRef } from "react";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

export const WATSONX_TLS_DISABLED_VALUES: Record<string, true> = {
  false: true,
  "0": true,
  no: true,
  off: true,
};
const TRUE_VALUES: Record<string, true> = {
  true: true,
  "1": true,
  yes: true,
  on: true,
};

export function WatsonxTlsSettings({
  value,
  onValueChange,
  idPrefix,
}: {
  value?: string;
  onValueChange: (value: string) => void;
  idPrefix: string;
}) {
  const normalized = (value ?? "").trim().toLowerCase();
  const enabled = WATSONX_TLS_DISABLED_VALUES[normalized] !== true;
  const caPath =
    !normalized ||
    TRUE_VALUES[normalized] === true ||
    WATSONX_TLS_DISABLED_VALUES[normalized] === true
      ? ""
      : (value ?? "");
  const lastCaPath = useRef(caPath);
  if (caPath) lastCaPath.current = caPath;

  const switchId = `${idPrefix}-tls-verify`;
  const descriptionId = `${switchId}-description`;
  const caPathId = `${idPrefix}-tls-ca-path`;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 py-1">
        <div className="space-y-1">
          <Label htmlFor={switchId} className="text-mmd font-medium">
            Verify TLS certificates
          </Label>
          <p id={descriptionId} className="text-sm text-muted-foreground">
            Recommended. Validates the cluster certificate before sending
            credentials or model traffic.
          </p>
        </div>
        <Switch
          id={switchId}
          checked={enabled}
          aria-describedby={descriptionId}
          onCheckedChange={(checked) =>
            onValueChange(
              checked ? lastCaPath.current.trim() || "true" : "false",
            )
          }
        />
      </div>

      {enabled ? (
        <LabelWrapper
          id={caPathId}
          label="Custom CA bundle path"
          helperText="Optional backend filesystem path to a mounted CA bundle. Include public roots too if this OpenRAG deployment also calls public providers."
        >
          <Input
            id={caPathId}
            value={caPath}
            placeholder="/etc/ssl/certs/openrag-ca.pem"
            autoComplete="off"
            onChange={(event) => {
              const next = event.target.value;
              if (next) lastCaPath.current = next;
              onValueChange(next || "true");
            }}
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
