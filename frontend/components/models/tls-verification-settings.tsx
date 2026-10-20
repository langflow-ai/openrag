"use client";

import { AlertTriangle } from "lucide-react";
import { useRef } from "react";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { isDefaultTlsSetting, parseTlsSetting } from "./tls-verification";

const SWITCH_LABEL = "Verify TLS certificates";
const CA_PATH_LABEL = "Custom CA bundle path";

/**
 * A provider's `ssl_verify` credential as a "Verify TLS certificates" switch
 * plus an optional CA bundle path. The stored value stays a single string —
 * blank or a true-equivalent word (verify), a false-equivalent word (don't), or
 * a CA path — which is what the backend's `resolve_ssl_verify` reads.
 */
function TlsVerificationSettings({
  value,
  onValueChange,
  idPrefix,
  verifiedValue,
  switchHelp,
  caPathHelperText,
  caPathPlaceholder,
}: {
  value?: string;
  onValueChange: (value: string) => void;
  idPrefix: string;
  /**
   * Written when verification is on with no CA path, unless the field already
   * held a verify-equivalent value — that one is restored instead, so turning
   * the switch off and on again is not a credential-target change.
   */
  verifiedValue: string;
  /** Shown under the switch label (`description`) or behind an info icon. */
  switchHelp: { text: string; as: "description" | "tooltip" };
  caPathHelperText: string;
  caPathPlaceholder: string;
}) {
  const { enabled, caPath } = parseTlsSetting(value);
  const lastCaPath = useRef(caPath);
  if (caPath) lastCaPath.current = caPath;
  const lastVerifiedValue = useRef(verifiedValue);
  if (isDefaultTlsSetting(value)) {
    lastVerifiedValue.current = (value ?? "").trim();
  }

  const switchId = `${idPrefix}-tls-verify`;
  const descriptionId = `${switchId}-description`;
  const caPathId = `${idPrefix}-tls-ca-path`;

  const toggle = (
    <Switch
      id={switchId}
      checked={enabled}
      aria-describedby={
        switchHelp.as === "description" ? descriptionId : undefined
      }
      onCheckedChange={(checked) =>
        onValueChange(
          checked
            ? lastCaPath.current.trim() || lastVerifiedValue.current
            : "false",
        )
      }
    />
  );

  return (
    <div className="space-y-4">
      {switchHelp.as === "description" ? (
        <div className="flex items-center justify-between gap-4 py-1">
          <div className="space-y-1">
            <Label htmlFor={switchId} className="text-mmd font-medium">
              {SWITCH_LABEL}
            </Label>
            <p id={descriptionId} className="text-sm text-muted-foreground">
              {switchHelp.text}
            </p>
          </div>
          {toggle}
        </div>
      ) : (
        <LabelWrapper
          flex
          id={switchId}
          label={SWITCH_LABEL}
          helperText={switchHelp.text}
        >
          {toggle}
        </LabelWrapper>
      )}

      {enabled ? (
        <LabelWrapper
          id={caPathId}
          label={CA_PATH_LABEL}
          helperText={caPathHelperText}
        >
          <Input
            id={caPathId}
            value={caPath}
            placeholder={caPathPlaceholder}
            autoComplete="off"
            onChange={(event) => {
              const next = event.target.value;
              if (next) lastCaPath.current = next;
              onValueChange(next || lastVerifiedValue.current);
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

type TlsPresetProps = {
  value?: string;
  onValueChange: (value: string) => void;
  idPrefix: string;
};

/** watsonx.ai on-prem: the backend seeds `"true"` as its default. */
export function WatsonxTlsSettings(props: TlsPresetProps) {
  return (
    <TlsVerificationSettings
      {...props}
      verifiedValue="true"
      switchHelp={{
        as: "description",
        text: "Recommended. Validates the cluster certificate before sending credentials or model traffic.",
      }}
      caPathHelperText="Optional backend filesystem path to a mounted CA bundle. Include public roots too if this OpenRAG deployment also calls public providers."
      caPathPlaceholder="/etc/ssl/certs/openrag-ca.pem"
    />
  );
}

/**
 * Red Hat OpenShift AI: blank means "verify", so verification on with no CA
 * path is stored blank rather than as `"true"`.
 */
export function RhoaiTlsSettings(props: TlsPresetProps) {
  return (
    <TlsVerificationSettings
      {...props}
      verifiedValue=""
      switchHelp={{
        as: "tooltip",
        text: "Validates the cluster certificate before sending credentials or model traffic.",
      }}
      caPathHelperText="Path to the CA bundle that signs the endpoint's certificate. In-cluster this is OpenShift's projected service CA."
      caPathPlaceholder="/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"
    />
  );
}
