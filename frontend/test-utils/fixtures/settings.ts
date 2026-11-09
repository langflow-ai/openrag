/**
 * Fixtures for GET /api/settings.
 *
 * Needed by more tests than it looks: `useOnboardingState()` reads
 * `settings.onboarding.current_step`, and both `TaskProvider` and
 * `ChatProvider` call it, so mounting either one hits this endpoint.
 */
import type { Settings } from "@/app/api/queries/useGetSettingsQuery";
import { TOTAL_ONBOARDING_STEPS } from "@/lib/constants";

/**
 * Onboarding finished. This is the default because an *active* onboarding
 * changes behaviour in both providers (task polling, chat routing), and a test
 * should opt into that rather than inherit it.
 */
export function makeSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    langflow_url: "http://localhost:7860",
    flow_id: "flow-1",
    ingest_flow_id: "ingest-flow-1",
    onboarding: { current_step: TOTAL_ONBOARDING_STEPS },
    providers: {},
    knowledge: {},
    agent: {},
    ...overrides,
  };
}

/** Settings with onboarding still in progress at `step`. */
export function makeOnboardingSettings(step = 0): Settings {
  return makeSettings({ onboarding: { current_step: step } });
}
