import { AnalyticsBrowser } from "@segment/analytics-next";

const writeKey = process.env.NEXT_PUBLIC_SEGMENT_WRITE_KEY ?? "";

export const analytics = AnalyticsBrowser.load({ writeKey });

interface RequiredSegmentStaticProperties {
  UT30: string;
  environment: string;
  productCode: string;
  productCodeType: string;
  productTitle: string;
}

// These properties are required by IBM Segment event schema for all events or they will be blocked
// See: https://w3.ibm.com/w3publisher/instrumentation-at-ibm/required-properties
export const REQUIRED_STATIC_PROPERTIES: RequiredSegmentStaticProperties = {
  UT30: "30AW0",
  environment: process.env.NEXT_PUBLIC_ENVIRONMENT ?? "",
  productCode: "WW1544",
  productCodeType: "WWPC",
  productTitle: "OpenRAG",
};

export const page = (
  pageTitle?: string,
  properties: Record<string, unknown> = {},
) => {
  if (!writeKey) return;
  analytics.page(undefined, pageTitle, properties);
};
