import type { ConnectorUIDescriptor } from "@/lib/connectors/types";
import { IBMCOSBucketView } from "./connectors/ibm-cos/components/bucket-view";
import IBMCOSIcon from "./connectors/ibm-cos/icon";
import IBMCOSSettingsDialog from "./connectors/ibm-cos/settings-dialog";
import { useIBMCOSDefaultsQuery } from "./connectors/ibm-cos/useIBMCOSDefaultsQuery";

/**
 * Connector descriptors layered on top of the OSS builtins.
 *
 * Downstream builds (e.g. SaaS) overlay this file via the
 * `git checkout --ours enhancements/ frontend/enhancements/` merge strategy.
 * The OSS variant of this file ships with IBM COS registered; strip the
 * imports and reset the array to `[]` for a bare OSS build.
 */
export const ADDITIONAL_CONNECTORS: ConnectorUIDescriptor[] = [
  {
    connectorType: "ibm_cos",
    name: "IBM Cloud Object Storage",
    Icon: IBMCOSIcon,
    kind: "bucket",
    SettingsDialog: IBMCOSSettingsDialog,
    BucketView: IBMCOSBucketView,
    useDefaultsQuery: useIBMCOSDefaultsQuery,
    menuItem: { label: "IBM Cloud Object Storage", route: "/upload/ibm_cos" },
  },
];
