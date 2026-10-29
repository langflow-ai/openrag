/** Knowledge date-range filter gate (mirrors the ingest-preview run-mode gate). */

import { IBM_THEME_DEV } from "@/lib/brand";

/**
 * Eligible run modes for showing the Knowledge date-range filter.
 * SaaS omitted until product approval — add "saas" here to restore.
 */
const DATE_RANGE_FILTER_RUN_MODES = new Set(["oss"]);

/**
 * Client-side gate for showing the date-range filter. Pass `isCloudBrand` so the
 * local IBM theme switch hides it the same way real `OPENRAG_RUN_MODE=saas` would.
 *
 * This gate controls date-picker visibility only.
 * Saved date bounds still apply to search and chat when controls are hidden.
 */
export function isDateRangeFilterEnabled(
  runMode: string | null | undefined,
  options?: { isCloudBrand?: boolean },
): boolean {
  if (runMode == null || !DATE_RANGE_FILTER_RUN_MODES.has(runMode)) {
    return false;
  }
  if (IBM_THEME_DEV && options?.isCloudBrand) {
    return false;
  }
  return true;
}
