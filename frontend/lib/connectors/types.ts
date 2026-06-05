import type { UseQueryResult } from "@tanstack/react-query";
import type { ComponentType } from "react";
import type { useSyncConnector } from "@/app/api/mutations/useSyncConnector";

export type ConnectorKind = "oauth" | "bucket";

export interface ConnectorIconProps {
  className?: string;
}

export interface ConnectorSettingsDialogProps {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export interface ConnectorBucketViewProps {
  // Loosely typed to match the existing connector shape from useGetConnectorsQuery.
  connector: any;
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (id: string) => void;
  onBack: () => void;
  onDone: () => void;
}

export interface ConnectorMenuItem {
  label: string;
  route: string;
}

/**
 * Static description of a connector's UI surface. The registry combines
 * builtin descriptors with whatever lives in `frontend/enhancements/`, and
 * shared components consume the merged list instead of hard-coding per-type
 * branches.
 *
 * The optional fields are hook points: a connector only fills in the ones
 * it actually needs (e.g. only bucket connectors set `BucketView`).
 */
export interface ConnectorUIDescriptor {
  /** Matches the backend connector_type string (e.g. "google_drive"). */
  connectorType: string;
  /** Human-readable label used in dialogs, dropdowns, etc. */
  name: string;
  /** Icon component rendered next to the name. */
  Icon: ComponentType<ConnectorIconProps>;
  /**
   * Configure-flow shape. "oauth" connectors trigger the OAuth mutation;
   * "bucket" connectors open a settings dialog and sync entire buckets.
   */
  kind: ConnectorKind;
  /** Modal used to enter credentials for bucket-kind connectors. */
  SettingsDialog?: ComponentType<ConnectorSettingsDialogProps>;
  /** Page-level view rendered on /upload/[provider] for bucket connectors. */
  BucketView?: ComponentType<ConnectorBucketViewProps>;
  /** Hook returning connector-specific defaults (server-side env presence, etc). */
  useDefaultsQuery?: (options?: {
    enabled?: boolean;
  }) => UseQueryResult<unknown>;
  /** Entry in the "add knowledge" dropdown. */
  menuItem?: ConnectorMenuItem;
}
