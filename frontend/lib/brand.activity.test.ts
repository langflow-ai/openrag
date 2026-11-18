import { describe, expect, it } from "vitest";
import { buildSettingsTabAccess, canAccessActivityTab } from "./brand";

const access = (
  over: Partial<Parameters<typeof buildSettingsTabAccess>[0]> = {},
) =>
  buildSettingsTabAccess({
    isIbmAuthMode: false,
    cloudContext: false,
    isNoAuthMode: false,
    permissions: new Set(["audit:read"]),
    rbacEnforced: true,
    activityAccess: true,
    useClientBrandPolicy: false,
    ...over,
  });

describe("canAccessActivityTab", () => {
  it("requires the server-reported capability", () => {
    expect(canAccessActivityTab(access())).toBe(true);
    expect(canAccessActivityTab(access({ activityAccess: false }))).toBe(false);
  });

  it("defaults to denied when the server does not report it", () => {
    expect(canAccessActivityTab(access({ activityAccess: undefined }))).toBe(
      false,
    );
  });

  it("is denied with RBAC off or no-auth even if the flag were stale", () => {
    expect(canAccessActivityTab(access({ rbacEnforced: false }))).toBe(false);
    expect(canAccessActivityTab(access({ isNoAuthMode: true }))).toBe(false);
  });

  it("ignores a permissions set that merely contains audit:read", () => {
    expect(
      canAccessActivityTab(
        access({ activityAccess: false, permissions: new Set(["audit:read"]) }),
      ),
    ).toBe(false);
  });
});
