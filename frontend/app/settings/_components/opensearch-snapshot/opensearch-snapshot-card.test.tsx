import { act, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type {
  PreflightResult,
  SnapshotImport,
  SnapshotStatus,
} from "@/lib/opensearch-snapshot";
import { type AuthScenario, authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, screen } from "@/test-utils/render";
import OpenSearchSnapshotCard from "./opensearch-snapshot-card";
import {
  makeImport,
  makeListing,
  makePreflight,
  makeSource,
  makeStatus,
  snapshotAdmin,
} from "./snapshot-fixtures";

const BASE = "/api/connectors/opensearch_snapshot";

interface Recorded {
  statusRequests: number;
  shared?: { id: string; body: unknown };
  deleted: string[];
  reimport?: { id: string; body: unknown };
  preflight: { id: string; body: unknown }[];
}

function setup(
  options: {
    status?: SnapshotStatus;
    imports?: SnapshotImport[];
    auth?: AuthScenario;
    preflight?: PreflightResult;
  } = {},
) {
  const recorded: Recorded = { statusRequests: 0, deleted: [], preflight: [] };
  const imports = options.imports ?? [];
  renderWithProviders(<OpenSearchSnapshotCard pollIntervalMs={20} />, {
    providers: ["brand"],
    auth: options.auth ?? snapshotAdmin,
    handlers: [
      http.get(`${BASE}/status`, () => {
        recorded.statusRequests += 1;
        return HttpResponse.json(options.status ?? makeStatus());
      }),
      http.get(`${BASE}/imports`, () => HttpResponse.json({ imports })),
      http.get(`${BASE}/imports/:id`, ({ params }) =>
        HttpResponse.json(imports.find((i) => i.id === params.id)),
      ),
      http.get(`${BASE}/sources`, () =>
        HttpResponse.json({ sources: [makeSource()] }),
      ),
      http.get(`${BASE}/sources/:id/snapshots`, () =>
        HttpResponse.json(makeListing()),
      ),
      http.post(`${BASE}/imports/:id/share`, async ({ request, params }) => {
        const body = await request.json();
        recorded.shared = { id: String(params.id), body };
        return HttpResponse.json({ ...imports[0], shared: true });
      }),
      http.delete(`${BASE}/imports/:id`, ({ params }) => {
        recorded.deleted.push(String(params.id));
        return HttpResponse.json(
          { import: { ...imports[0], status: "deleting" } },
          { status: 202 },
        );
      }),
      http.post(
        `${BASE}/imports/:id/reimport/preflight`,
        async ({ request, params }) => {
          recorded.preflight.push({
            id: String(params.id),
            body: await request.json(),
          });
          return HttpResponse.json(options.preflight ?? makePreflight());
        },
      ),
      http.post(`${BASE}/imports/:id/reimport`, async ({ request, params }) => {
        recorded.reimport = {
          id: String(params.id),
          body: await request.json(),
        };
        return HttpResponse.json(
          { import: imports[0], task_id: "t2" },
          { status: 202 },
        );
      }),
    ],
  });
  return recorded;
}

describe("OpenSearchSnapshotCard", () => {
  it("renders nothing when the feature is disabled", async () => {
    const recorded = setup({
      status: makeStatus({ enabled: false, reason: "disabled" }),
    });
    await waitFor(() => expect(recorded.statusRequests).toBe(1));
    // Let the "disabled" answer render before asserting absence.
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 30);
    await act(() => promise);
    expect(screen.queryByText("OpenSearch Snapshot")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /import snapshot/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the card and opens the wizard when enabled", async () => {
    const user = userEvent.setup();
    setup();
    expect(await screen.findByText("OpenSearch Snapshot")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /import snapshot/i }));
    expect(
      await screen.findByRole("heading", {
        name: "Import an OpenSearch snapshot",
      }),
    ).toBeVisible();
    expect(
      await screen.findByRole("button", { name: /^Lab bucket/ }),
    ).toBeVisible();
  });

  it("disables importing for a viewer without connector permissions", async () => {
    setup({ auth: authPresets.viewer });
    const button = await screen.findByRole("button", {
      name: /import snapshot/i,
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      "title",
      "You do not have permission to create connectors",
    );
  });

  it.each([
    ["rbacDisabled", authPresets.rbacDisabled],
    ["noAuthMode", authPresets.noAuthMode],
  ])("enables importing when permissions are not enforced (%s)", async (_name, auth) => {
    setup({ auth });
    const button = await screen.findByRole("button", {
      name: /import snapshot/i,
    });
    // Permissions resolve after the first paint.
    await waitFor(() => expect(button).toBeEnabled());
  });
});

describe("Imports list", () => {
  const imports = [
    makeImport({ id: "imp-active", name: "Scientists", status: "active" }),
    makeImport({ id: "imp-review", name: "Draft import", status: "review" }),
    makeImport({
      id: "imp-failed",
      name: "Broken import",
      status: "failed",
      job: {
        state: "failed",
        kind: "import",
        error: "restore failed",
        task_id: "t",
      },
    }),
    makeImport({
      id: "imp-running",
      name: "Refreshing import",
      status: "active",
      job: { state: "running", kind: "reimport", error: null, task_id: "t" },
    }),
  ];

  it("shows status and job badges per import", async () => {
    setup({ imports });
    const list = await screen.findByRole("list", { name: "Snapshot imports" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("Active")).toBeVisible();
    expect(within(rows[1]).getByText("Needs review")).toBeVisible();
    expect(within(rows[2]).getByText("Failed")).toBeVisible();
    expect(within(rows[2]).getByText("restore failed")).toBeVisible();
    expect(within(rows[3]).getByText("Re-import running")).toBeVisible();
    // A running job locks sharing and re-import.
    expect(
      within(rows[3]).getByRole("switch", { name: "Share Refreshing import" }),
    ).toBeDisabled();
    expect(
      within(rows[3]).getByRole("button", {
        name: "Re-import Refreshing import",
      }),
    ).toBeDisabled();
  });

  it("toggles sharing", async () => {
    const user = userEvent.setup();
    const recorded = setup({ imports: [imports[0]] });
    await user.click(
      await screen.findByRole("switch", { name: "Share Scientists" }),
    );
    await waitFor(() => expect(recorded.shared).toBeDefined());
    expect(recorded.shared).toEqual({
      id: "imp-active",
      body: { shared: true },
    });
  });

  it("cannot unshare when the deployment has no private imports", async () => {
    setup({
      status: makeStatus({ private_supported: false }),
      imports: [
        makeImport({ name: "Scientists", status: "active", shared: true }),
      ],
    });
    expect(
      await screen.findByRole("switch", { name: "Share Scientists" }),
    ).toBeDisabled();
  });

  it("treats imports owned by someone else as read-only", async () => {
    setup({
      imports: [
        makeImport({
          name: "Theirs",
          status: "active",
          shared: true,
          is_owner: false,
        }),
      ],
    });
    const row = (await screen.findAllByRole("listitem"))[0];
    expect(within(row).getByText("Shared with you")).toBeVisible();
    expect(
      within(row).getByRole("switch", { name: "Share Theirs" }),
    ).toBeDisabled();
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("deletes only after confirmation", async () => {
    const user = userEvent.setup();
    const recorded = setup({ imports: [imports[0]] });
    await user.click(
      await screen.findByRole("button", { name: "Delete Scientists" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Delete Scientists?")).toBeVisible();
    expect(recorded.deleted).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(recorded.deleted).toEqual(["imp-active"]));
  });

  it("lets the owner retry a delete whose cleanup job failed", async () => {
    const user = userEvent.setup();
    let listCalls = 0;
    const failed = makeImport({
      id: "imp-del",
      name: "Stuck",
      status: "deleting",
      job: {
        state: "failed",
        kind: "delete",
        error: "cleanup failed",
        task_id: "t",
      },
    });
    const recorded = setup({ imports: [failed] });
    // Count list polls: a terminal failed delete must not keep polling.
    server.use(
      http.get(`${BASE}/imports`, () => {
        listCalls += 1;
        return HttpResponse.json({ imports: [failed] });
      }),
    );
    const button = await screen.findByRole("button", { name: "Delete Stuck" });
    expect(button).toBeEnabled();
    expect(screen.getByText("Delete failed")).toBeVisible();
    const settled = listCalls;
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(listCalls).toBe(settled);

    await user.click(button);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(recorded.deleted).toEqual(["imp-del"]));
  });

  it("keeps Delete disabled while the delete job is running", async () => {
    setup({
      imports: [
        makeImport({
          name: "Going",
          status: "deleting",
          job: { state: "running", kind: "delete", error: null, task_id: "t" },
        }),
      ],
    });
    expect(
      await screen.findByRole("button", { name: "Delete Going" }),
    ).toBeDisabled();
  });

  it("keeps refreshing while the backend recovers an interrupted re-import", async () => {
    const recovering = makeImport({
      id: "imp-rec",
      name: "Recovering",
      status: "active",
      job: { state: "recovery", kind: "reimport", error: null, task_id: "t" },
    });
    const settled = makeImport({
      ...recovering,
      job: {
        state: "failed",
        kind: "reimport",
        error: "interrupted by restart",
        task_id: "t",
      },
    });
    let listCalls = 0;
    setup({ imports: [recovering] });
    server.use(
      http.get(`${BASE}/imports`, () => {
        listCalls += 1;
        return HttpResponse.json({
          imports: [listCalls < 3 ? recovering : settled],
        });
      }),
    );
    expect(await screen.findByText("Re-import recovering")).toBeVisible();
    // The terminal result arrives through polling, without a remount or focus.
    expect(await screen.findByText("Re-import failed")).toBeVisible();
  });

  it("does not let a viewer delete", async () => {
    setup({ imports: [imports[0]], auth: authPresets.viewer });
    expect(
      await screen.findByRole("button", { name: "Delete Scientists" }),
    ).toBeDisabled();
  });

  it("re-imports through preflight then reimport", async () => {
    const user = userEvent.setup();
    const recorded = setup({ imports: [imports[0]] });
    await user.click(
      await screen.findByRole("button", { name: "Re-import Scientists" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(
      await within(dialog).findByRole("radio", { name: /scientists-v2/ }),
    );

    const confirm = within(dialog).getByRole("button", {
      name: /start re-import/i,
    });
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(recorded.preflight).toEqual([
      { id: "imp-active", body: { snapshot: "scientists-v2" } },
    ]);
    await user.click(confirm);
    await waitFor(() => expect(recorded.reimport).toBeDefined());
    expect(recorded.reimport).toEqual({
      id: "imp-active",
      body: { snapshot: "scientists-v2", analyser_files: [] },
    });
  });

  it("blocks a re-import whose preflight has blockers", async () => {
    const user = userEvent.setup();
    setup({
      imports: [imports[0]],
      preflight: makePreflight({
        ok: false,
        blockers: [
          { code: "index_not_in_snapshot", message: "Index is missing" },
        ],
      }),
    });
    await user.click(
      await screen.findByRole("button", { name: "Re-import Scientists" }),
    );
    const dialog = await screen.findByRole("dialog");
    await user.click(
      await within(dialog).findByRole("radio", { name: /scientists-v2/ }),
    );
    expect(await within(dialog).findByText("Index is missing")).toBeVisible();
    expect(
      within(dialog).getByRole("button", { name: /start re-import/i }),
    ).toBeDisabled();
  });

  it("reopens an import in review at the dataset mapping step", async () => {
    const user = userEvent.setup();
    setup({ imports: [imports[1]] });
    await user.click(
      await screen.findByRole("button", { name: "Review Draft import" }),
    );
    expect(
      await screen.findByRole("region", { name: "Dataset famous_scientists" }),
    ).toBeVisible();
  });
});
