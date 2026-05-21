import { useS3DefaultsQuery } from "@/app/api/queries/useS3DefaultsQuery";
import S3SettingsDialog from "@/app/settings/_components/s3-settings-dialog";
import { S3BucketView } from "@/components/connectors/aws-s3/bucket-view";
import AwsLogo from "@/components/icons/aws-logo";
import GoogleDriveLogo from "@/components/icons/google-drive-logo";
import OneDriveLogo from "@/components/icons/one-drive-logo";
import SharePointLogo from "@/components/icons/share-point-logo";
import { ADDITIONAL_CONNECTORS } from "@/enhancements";
import type { ConnectorUIDescriptor } from "./types";

const BUILTIN_CONNECTORS: ConnectorUIDescriptor[] = [
  {
    connectorType: "google_drive",
    name: "Google Drive",
    Icon: GoogleDriveLogo,
    kind: "oauth",
    menuItem: { label: "Google Drive", route: "/upload/google_drive" },
  },
  {
    connectorType: "onedrive",
    name: "OneDrive",
    Icon: OneDriveLogo,
    kind: "oauth",
    menuItem: { label: "OneDrive", route: "/upload/onedrive" },
  },
  {
    connectorType: "sharepoint",
    name: "SharePoint",
    Icon: SharePointLogo,
    kind: "oauth",
    menuItem: { label: "SharePoint", route: "/upload/sharepoint" },
  },
  {
    connectorType: "aws_s3",
    name: "Amazon S3",
    Icon: AwsLogo,
    kind: "bucket",
    SettingsDialog: S3SettingsDialog,
    BucketView: S3BucketView,
    useDefaultsQuery: useS3DefaultsQuery,
    menuItem: { label: "Amazon S3", route: "/upload/aws_s3" },
  },
];

const ALL_CONNECTORS: ConnectorUIDescriptor[] = [
  ...BUILTIN_CONNECTORS,
  ...ADDITIONAL_CONNECTORS,
];

export function getConnectorDescriptors(): ConnectorUIDescriptor[] {
  return ALL_CONNECTORS;
}

export function getConnectorDescriptor(
  connectorType: string,
): ConnectorUIDescriptor | undefined {
  return ALL_CONNECTORS.find((d) => d.connectorType === connectorType);
}

export function getConnectorLabel(connectorType: string): string | undefined {
  return getConnectorDescriptor(connectorType)?.name;
}
