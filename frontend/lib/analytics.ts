import { AnalyticsBrowser } from "@segment/analytics-next";

let analytics: AnalyticsBrowser | null = null;
let _environment = "";

export function initAnalytics(writeKey: string, environment = "") {
  _environment = environment;
  if (!writeKey || analytics) return;
  analytics = AnalyticsBrowser.load({ writeKey });
}

interface RequiredSegmentStaticProperties {
  UT30: string;
  environment: string;
  productCode: string;
  productCodeType: string;
  productTitle: string;
}

// These properties are required by IBM Segment event schema for all events or they will be blocked
// See: https://w3.ibm.com/w3publisher/instrumentation-at-ibm/required-properties
export const getRequiredStaticProperties =
  (): RequiredSegmentStaticProperties => ({
    UT30: "30AW0",
    environment: _environment,
    productCode: "WW1544",
    productCodeType: "WWPC",
    productTitle: "OpenRAG",
  });

export const page = (
  pageTitle?: string,
  properties: Record<string, unknown> = {},
) => {
  if (!analytics) return;
  analytics.page(undefined, pageTitle, properties);
};
