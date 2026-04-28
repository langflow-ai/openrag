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
  analytics.page(undefined, pageTitle, {
    ...getRequiredStaticProperties(),
    ...properties,
  });
};

export const track = (
  eventName: string,
  properties: Record<string, unknown> = {},
) => {
  if (!analytics) return;
  try {
    analytics.track(eventName, {
      ...getRequiredStaticProperties(),
      ...properties,
    });
  } catch (e) {
    console.error("Analytics tracking error:", e);
  }
};

interface ButtonEventParams {
  action?: string;
  channel?: string;
  CTA?: string;
  elementId?: string;
  namespace?: string;
  payload?: string | Record<string, unknown>;
  platformTitle?: string;
}

export const trackButton = <T = Record<string, unknown>>({
  action = "clicked",
  ...rest
}: T & ButtonEventParams): void =>
  track("Button Clicked", { action, ...rest } as Record<string, unknown>);

interface EndProcessParams {
  processType: string;
  process?: string;
  successFlag?: boolean;
  resultValue?: string;
  category?: string;
}

export const trackEndProcess = <T = Record<string, unknown>>(
  props: T & EndProcessParams,
): void => track("Ended Process", props as Record<string, unknown>);

export const trackProcessSuccess = <T = Record<string, unknown>>(
  props: T & Omit<EndProcessParams, "successFlag">,
): void =>
  trackEndProcess({ ...props, successFlag: true } as T & EndProcessParams);

export const trackProcessFailure = <T = Record<string, unknown>>(
  props: T & Omit<EndProcessParams, "successFlag">,
): void =>
  trackEndProcess({ ...props, successFlag: false } as T & EndProcessParams);

interface LLMCallParams {
  model?: string;
  objectType?: string;
  taskId?: string;
  mode?: string;
  inputTokens?: number;
  outputTokens?: number;
}

export const trackLLMCall = <T = Record<string, unknown>>(
  props: T & LLMCallParams,
): void => track("LLM Call", props as Record<string, unknown>);
