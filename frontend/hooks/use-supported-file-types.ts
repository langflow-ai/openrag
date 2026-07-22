import { useMemo } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import {
  getSupportedExtensions,
  getSupportedFileTypes,
} from "@/lib/supported-file-types";

export function useSupportedFileTypes() {
  const { data: settings } = useGetSettingsQuery();
  const ocrEnabled = settings?.knowledge?.ocr ?? false;

  const supportedFileTypes = useMemo(
    () => getSupportedFileTypes(ocrEnabled),
    [ocrEnabled],
  );
  const supportedExtensions = useMemo(
    () => getSupportedExtensions(ocrEnabled),
    [ocrEnabled],
  );
  const supportedExtensionSet = useMemo(
    () => new Set(supportedExtensions),
    [supportedExtensions],
  );

  return { supportedFileTypes, supportedExtensions, supportedExtensionSet };
}
