/**
 * The RBAC affordance wrapper. It is a UX gate only — the backend still 403s —
 * but getting it wrong hides working features from users who do have access,
 * which reads as a broken product.
 *
 * The cases that matter are the two where a user holds no permissions and must
 * still see everything: no-auth mode, and RBAC not enforced.
 */
import { describe, expect, it } from "vitest";
import { RequirePermission } from "@/components/require-permission";
import { type AuthScenario, authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, screen } from "@/test-utils/render";

function renderGate(ui: React.ReactElement, auth: AuthScenario) {
  return renderWithProviders(ui, { providers: ["auth"], auth });
}

describe("RequirePermission", () => {
  it("renders children when the user holds the permission", async () => {
    renderGate(
      <RequirePermission perm="config:write">
        <button type="button">Save</button>
      </RequirePermission>,
      authPresets.admin,
    );

    expect(await screen.findByRole("button", { name: "Save" })).toBeVisible();
  });

  it("renders the fallback when the user does not", async () => {
    renderGate(
      <RequirePermission perm="config:write" fallback={<p>Read only</p>}>
        <button type="button">Save</button>
      </RequirePermission>,
      authPresets.viewer,
    );

    expect(await screen.findByText("Read only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("hides children by default when there is no fallback", async () => {
    renderGate(
      <>
        <p>Page</p>
        <RequirePermission perm="config:write">
          <button type="button">Save</button>
        </RequirePermission>
      </>,
      authPresets.viewer,
    );

    await screen.findByText("Page");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("requires every permission listed in allOf", async () => {
    renderGate(
      <RequirePermission
        allOf={["config:read", "config:write"]}
        fallback={<p>Denied</p>}
      >
        <button type="button">Save</button>
      </RequirePermission>,
      authPresets.viewer,
    );

    expect(await screen.findByText("Denied")).toBeInTheDocument();
  });

  it("requires only one permission listed in anyOf", async () => {
    renderGate(
      <RequirePermission anyOf={["config:write", "config:read"]}>
        <button type="button">Edit</button>
      </RequirePermission>,
      authPresets.viewer,
    );

    expect(await screen.findByRole("button", { name: "Edit" })).toBeVisible();
  });

  it("grants everything in no-auth mode despite an empty permission set", async () => {
    renderGate(
      <RequirePermission perm="config:write">
        <button type="button">Save</button>
      </RequirePermission>,
      authPresets.noAuthMode,
    );

    expect(await screen.findByRole("button", { name: "Save" })).toBeVisible();
  });

  it("grants everything when the backend is not enforcing RBAC", async () => {
    renderGate(
      <RequirePermission perm="config:write">
        <button type="button">Save</button>
      </RequirePermission>,
      authPresets.rbacDisabled,
    );

    expect(await screen.findByRole("button", { name: "Save" })).toBeVisible();
  });

  it("renders the fallback when no criterion is given at all", async () => {
    // A misconfigured gate must fail closed, not silently allow. The prop
    // union makes this unreachable from TypeScript — hence the cast — but the
    // defensive branch exists, and this pins it in case the union is ever
    // loosened.
    const Gate = RequirePermission as unknown as React.ComponentType<{
      children: React.ReactNode;
      fallback?: React.ReactNode;
    }>;

    renderGate(
      <Gate fallback={<p>Denied</p>}>
        <button type="button">Save</button>
      </Gate>,
      authPresets.admin,
    );

    expect(await screen.findByText("Denied")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});
