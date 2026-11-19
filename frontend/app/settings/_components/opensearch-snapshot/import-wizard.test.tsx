import { waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import type {
  PreflightResult,
  SnapshotImport,
  SnapshotSource,
  SnapshotStatus,
} from "@/lib/opensearch-snapshot";
import { type AuthScenario, authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, screen } from "@/test-utils/render";
import { ImportWizard } from "./import-wizard";
import {
  makeDataset,
  makeImport,
  makeListing,
  makePreflight,
  makeSource,
  makeStatus,
  snapshotAdmin,
} from "./snapshot-fixtures";

const BASE = "/api/connectors/opensearch_snapshot";

interface ServerState {
  status: SnapshotStatus;
  sources: SnapshotSource[];
  preflight: PreflightResult;
  imp: SnapshotImport;
  /** GETs of the import answered as `staging` before it flips to `review`. */
  stagingPolls: number;
  started?: Record<string, unknown>;
  createdSource?: Record<string, unknown>;
  patches: Record<string, unknown>[];
  activate: () => Response;
}

function makeState(overrides: Partial<ServerState> = {}): ServerState {
  const state: ServerState = {
    status: makeStatus(),
    sources: [makeSource()],
    preflight: makePreflight(),
    imp: makeImport(),
    stagingPolls: 0,
    patches: [],
    activate: () => {
      state.imp = { ...state.imp, status: "active" };
      return HttpResponse.json(state.imp);
    },
    ...overrides,
  };
  return state;
}

function handlers(state: ServerState) {
  let polls = 0;
  return [
    http.get(`${BASE}/status`, () => HttpResponse.json(state.status)),
    http.get(`${BASE}/sources`, () =>
      HttpResponse.json({ sources: state.sources }),
    ),
    http.post(`${BASE}/sources`, async ({ request }) => {
      state.createdSource = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(makeSource({ id: "src-new" }), { status: 201 });
    }),
    http.get(`${BASE}/sources/:id/snapshots`, () =>
      HttpResponse.json(makeListing()),
    ),
    http.post(`${BASE}/sources/:id/preflight`, () =>
      HttpResponse.json(state.preflight),
    ),
    http.post(`${BASE}/imports`, async ({ request }) => {
      state.started = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(
        {
          import: makeImport({
            status: "staging",
            job: {
              state: "running",
              kind: "import",
              error: null,
              task_id: "t1",
            },
          }),
          task_id: "t1",
        },
        { status: 202 },
      );
    }),
    http.get(`${BASE}/imports`, () =>
      HttpResponse.json({ imports: [state.imp] }),
    ),
    http.get(`${BASE}/imports/:id`, () => {
      if (polls++ < state.stagingPolls) {
        return HttpResponse.json(
          makeImport({
            status: "staging",
            job: {
              state: "running",
              kind: "import",
              error: null,
              task_id: "t1",
            },
          }),
        );
      }
      return HttpResponse.json(state.imp);
    }),
    http.patch(
      `${BASE}/imports/:id/datasets/:datasetId`,
      async ({ request, params }) => {
        const body = (await request.json()) as Record<string, unknown>;
        state.patches.push(body);
        state.imp = {
          ...state.imp,
          datasets: state.imp.datasets.map((dataset) =>
            dataset.id === params.datasetId
              ? ({ ...dataset, ...body } as typeof dataset)
              : dataset,
          ),
        };
        return HttpResponse.json(
          state.imp.datasets.find((d) => d.id === params.datasetId),
        );
      },
    ),
    http.post(`${BASE}/imports/:id/activate`, () => state.activate()),
  ];
}

function renderWizard(
  state: ServerState,
  options: {
    auth?: AuthScenario;
    resumeImportId?: string;
  } = {},
) {
  return renderWithProviders(
    <ImportWizard
      open
      onOpenChange={vi.fn()}
      resumeImportId={options.resumeImportId}
      pollIntervalMs={20}
    />,
    {
      providers: ["auth"],
      auth: options.auth ?? snapshotAdmin,
      handlers: handlers(state),
    },
  );
}

async function toPreflight(user: UserEvent) {
  await user.click(await screen.findByRole("button", { name: /^Lab bucket/ }));
  await user.click(screen.getByRole("button", { name: /^Continue$/i }));
  await user.click(await screen.findByRole("radio", { name: /scientists-v1/ }));
  await user.click(screen.getByRole("button", { name: /^Continue$/i }));
}

describe("ImportWizard", () => {
  it("walks source → snapshot → preflight → progress → mapping → activate", async () => {
    const user = userEvent.setup();
    const state = makeState({ stagingPolls: 2 });
    renderWizard(state);

    // Source → snapshot
    await user.click(
      await screen.findByRole("button", { name: /^Lab bucket/ }),
    );
    await user.click(screen.getByRole("button", { name: /^Continue$/i }));

    // Snapshot: regular indices pre-checked with sizes, system index not.
    await user.click(
      await screen.findByRole("radio", { name: /scientists-v1/ }),
    );
    expect(
      screen.getByRole("checkbox", { name: "famous_scientists" }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "scientific_discoveries" }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: ".kibana" })).not.toBeChecked();
    expect(screen.getByText("5.0 MB")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Continue$/i }));

    // Preflight → start
    const start = await screen.findByRole("button", {
      name: /^Start import$/i,
    });
    await waitFor(() => expect(start).toBeEnabled());
    await user.click(start);
    await waitFor(() => expect(state.started).toBeDefined());
    expect(state.started).toEqual({
      source_id: "src-1",
      snapshot: "scientists-v1",
      indices: ["famous_scientists", "scientific_discoveries"],
      name: "scientists-v1",
      shared: false,
      analyser_files: [],
    });

    // Progress polling until the import is in review.
    expect(await screen.findByText(/Copying snapshot files/)).toBeVisible();
    const form = await screen.findByRole("region", {
      name: "Dataset famous_scientists",
    });

    // Mapping: edit and save a dataset.
    const nameInput = within(form).getByLabelText(
      "Display name for famous_scientists",
    );
    await user.clear(nameInput);
    await user.type(nameInput, "Famous scientists");
    const save = within(form).getByRole("button", {
      name: "Save famous_scientists",
    });
    await user.click(save);
    await waitFor(() => expect(state.patches).toHaveLength(1));
    expect(state.patches[0]).toMatchObject({
      display_name: "Famous scientists",
      field_map: { text_fields: ["bio"], title_field: "name", url_field: null },
      retrieval: { mode: "lexical" },
    });

    // Activate
    const activate = screen.getByRole("button", { name: /^Activate$/i });
    await waitFor(() => expect(activate).toBeEnabled());
    await user.click(activate);
    expect(
      await screen.findByRole("button", { name: /^Done$/i }),
    ).toBeVisible();
    expect(screen.getByText(/This import is active/)).toBeVisible();
  });

  it("changes the title field through the mapping selects", async () => {
    const user = userEvent.setup();
    const state = makeState();
    renderWizard(state, { resumeImportId: "imp-1" });

    await user.click(
      await screen.findByRole("combobox", {
        name: "Title field for famous_scientists",
      }),
    );
    await user.click(await screen.findByRole("option", { name: "bio (text)" }));
    await user.click(
      screen.getByRole("button", { name: "Save famous_scientists" }),
    );
    await waitFor(() => expect(state.patches).toHaveLength(1));
    expect(state.patches[0]).toMatchObject({
      field_map: { title_field: "bio" },
    });
  });

  it("blocks starting while preflight reports blockers", async () => {
    const user = userEvent.setup();
    const state = makeState({
      preflight: makePreflight({
        ok: false,
        blockers: [
          {
            code: "too_large",
            message: "Import exceeds the size limit",
            index: "scientific_discoveries",
          },
        ],
        warnings: [{ code: "disk_stats_unavailable", message: "Disk unknown" }],
      }),
    });
    renderWizard(state);
    await toPreflight(user);

    expect(
      await screen.findByText("Import exceeds the size limit"),
    ).toBeVisible();
    expect(screen.getByText("Disk unknown")).toBeVisible();
    expect(
      screen.getByRole("button", { name: /^Start import$/i }),
    ).toBeDisabled();
  });

  it("requires every analyser file to be uploaded before starting", async () => {
    const user = userEvent.setup();
    const state = makeState({
      preflight: makePreflight({
        warnings: [
          {
            code: "analyser_file_required",
            message: "scientific_discoveries needs a synonyms file",
            index: "scientific_discoveries",
          },
        ],
        analyser_files: [
          {
            index: "scientific_discoveries",
            setting: "index.analysis.filter.field_synonyms.synonyms_path",
            path: "analysis/field_synonyms.txt",
            inline_setting: "synonyms",
          },
        ],
      }),
    });
    renderWizard(state);
    await toPreflight(user);

    const start = await screen.findByRole("button", {
      name: /^Start import$/i,
    });
    const input = await screen.findByLabelText(
      "Analyser file for scientific_discoveries (analysis/field_synonyms.txt)",
    );
    expect(start).toBeDisabled();

    await user.upload(
      input,
      new File(["dna, deoxyribonucleic acid\n"], "field_synonyms.txt", {
        type: "text/plain",
      }),
    );
    await waitFor(() => expect(start).toBeEnabled());
    await user.click(start);

    await waitFor(() => expect(state.started).toBeDefined());
    expect(state.started?.analyser_files).toEqual([
      {
        index: "scientific_discoveries",
        setting: "index.analysis.filter.field_synonyms.synonyms_path",
        content: "dna, deoxyribonucleic acid\n",
      },
    ]);
  });

  it("forces sharing on and explains why when private imports are unsupported", async () => {
    const user = userEvent.setup();
    const state = makeState({
      status: makeStatus({ private_supported: false, security_managed: false }),
    });
    renderWizard(state);
    await toPreflight(user);

    const share = await screen.findByRole("switch", {
      name: "Share with all OpenRAG users",
    });
    expect(share).toBeDisabled();
    expect(share).toBeChecked();
    expect(
      screen.getByText(/cannot restrict datasets to a single user/),
    ).toBeVisible();

    const start = screen.getByRole("button", { name: /^Start import$/i });
    await waitFor(() => expect(start).toBeEnabled());
    await user.click(start);
    await waitFor(() => expect(state.started?.shared).toBe(true));
  });

  it("lets the user share when private imports are supported", async () => {
    const user = userEvent.setup();
    const state = makeState();
    renderWizard(state);
    await toPreflight(user);

    const share = await screen.findByRole("switch", {
      name: "Share with all OpenRAG users",
    });
    expect(share).toBeEnabled();
    expect(share).not.toBeChecked();
    await user.click(share);
    expect(share).toBeChecked();
  });

  it("shows the role JSON when activation answers 409 role_not_provisioned", async () => {
    const user = userEvent.setup();
    const role = {
      role: "openrag_ds_abcdefghij",
      index_permissions: [{ index_patterns: ["ds_abcdefghij_*"] }],
    };
    const state = makeState({
      activate: () =>
        HttpResponse.json(
          {
            error: "Role is not provisioned",
            code: "role_not_provisioned",
            role_json: role,
          },
          { status: 409 },
        ),
    });
    renderWizard(state, { resumeImportId: "imp-1" });

    await user.click(
      await screen.findByRole("button", { name: /^Activate$/i }),
    );

    expect(await screen.findByText("Role not provisioned")).toBeVisible();
    const pre = screen.getByLabelText("Role JSON");
    expect(JSON.parse(pre.textContent ?? "")).toEqual(role);
    // Still in review: the wizard offers activation again.
    expect(screen.getByRole("button", { name: /^Activate$/i })).toBeEnabled();
  });

  it("offers hybrid search only for datasets that have vector fields", async () => {
    const user = userEvent.setup();
    const state = makeState({
      imp: makeImport({
        datasets: [
          makeDataset({
            vector_fields: [
              {
                name: "embedding",
                type: "knn_vector",
                dims: 4,
                engine: "faiss",
              },
            ],
            fields: [
              { name: "name", type: "text" },
              { name: "bio", type: "text" },
              { name: "embedding", type: "knn_vector", dims: 4 },
            ],
            available_models: ["openai:text-embedding-3-small"],
          }),
          makeDataset({
            id: "ds-2",
            ordinal: 1,
            source_index: "scientific_discoveries",
            display_name: "scientific_discoveries",
          }),
        ],
      }),
    });
    renderWizard(state, { resumeImportId: "imp-1" });

    await screen.findByRole("region", { name: "Dataset famous_scientists" });
    expect(screen.getAllByText("Hybrid search")).toHaveLength(1);
    // Vector fields are not offered as text fields.
    expect(
      screen.queryByRole("checkbox", { name: /embedding/ }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("checkbox", {
        name: "Combine keyword and vector search for famous_scientists",
      }),
    );
    await user.click(
      await screen.findByRole("combobox", {
        name: "Embedding model for famous_scientists",
      }),
    );
    await user.click(
      await screen.findByRole("option", {
        name: "openai:text-embedding-3-small",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Save famous_scientists" }),
    );

    await waitFor(() => expect(state.patches).toHaveLength(1));
    expect(state.patches[0]).toMatchObject({
      retrieval: {
        mode: "hybrid",
        vector_field: "embedding",
        provider: "openai",
        model: "text-embedding-3-small",
        dims: 4,
      },
    });
  });

  it("shows the failure reason when the import fails", async () => {
    const state = makeState({
      imp: makeImport({
        status: "failed",
        job: {
          state: "failed",
          kind: "import",
          error: "restore failed: index is red",
          task_id: "t1",
        },
      }),
    });
    renderWizard(state, { resumeImportId: "imp-1" });
    expect(
      await screen.findByText("restore failed: index is red"),
    ).toBeVisible();
  });

  it("creates a source, showing backend errors first", async () => {
    const user = userEvent.setup();
    const state = makeState({ sources: [] });
    let attempts = 0;
    const base = handlers(state);
    renderWithProviders(
      <ImportWizard open onOpenChange={vi.fn()} pollIntervalMs={20} />,
      {
        providers: ["auth"],
        auth: snapshotAdmin,
        handlers: [
          http.post(`${BASE}/sources`, async ({ request }) => {
            attempts += 1;
            state.createdSource = (await request.json()) as Record<
              string,
              unknown
            >;
            return attempts === 1
              ? HttpResponse.json(
                  {
                    error: "Endpoint is not allowed",
                    code: "endpoint_blocked",
                  },
                  { status: 400 },
                )
              : HttpResponse.json(makeSource({ id: "src-new" }), {
                  status: 201,
                });
          }),
          ...base,
        ],
      },
    );

    await user.type(await screen.findByLabelText("Source name"), "Lab");
    await user.type(screen.getByLabelText("Bucket"), "snapshots");
    await user.type(screen.getByLabelText("Access key"), "AKIATEST");
    await user.type(screen.getByLabelText("Secret key"), "s3cret");
    const save = screen.getByRole("button", {
      name: /^Save and test source$/i,
    });
    await user.click(save);
    expect(await screen.findByText("Endpoint is not allowed")).toBeVisible();

    await user.click(save);
    await waitFor(() => expect(attempts).toBe(2));
    expect(state.createdSource).toMatchObject({
      name: "Lab",
      bucket: "snapshots",
      region: "us-east-1",
      access_key: "AKIATEST",
      secret_key: "s3cret",
      path_style: true,
      verify_tls: true,
    });
    expect(state.createdSource).not.toHaveProperty("endpoint_url");
  });

  it("keeps stored credentials when editing a source without retyping them", async () => {
    const user = userEvent.setup();
    const state = makeState();
    let patched: Record<string, unknown> | undefined;
    renderWithProviders(
      <ImportWizard open onOpenChange={vi.fn()} pollIntervalMs={20} />,
      {
        providers: ["auth"],
        auth: snapshotAdmin,
        handlers: [
          ...handlers(state),
          http.patch(`${BASE}/sources/src-1`, async ({ request }) => {
            patched = (await request.json()) as Record<string, unknown>;
            return HttpResponse.json(makeSource({ name: "Renamed" }));
          }),
        ],
      },
    );

    await user.click(
      await screen.findByRole("button", { name: "Edit Lab bucket" }),
    );
    const name = await screen.findByLabelText("Source name");
    await user.clear(name);
    await user.type(name, "Renamed");
    await user.click(screen.getByRole("button", { name: /^Save source$/i }));

    await waitFor(() => expect(patched).toBeDefined());
    expect(patched).toMatchObject({ name: "Renamed" });
    expect(patched).not.toHaveProperty("access_key");
    expect(patched).not.toHaveProperty("secret_key");
  });

  it("enables Activate after saving a padded name and description", async () => {
    const user = userEvent.setup();
    const state = makeState();
    renderWizard(state, { resumeImportId: "imp-1" });

    const form = await screen.findByRole("region", {
      name: "Dataset famous_scientists",
    });
    await user.type(
      within(form).getByLabelText("Display name for famous_scientists"),
      " ",
    );
    await user.type(
      within(form).getByLabelText("Description for famous_scientists"),
      "  notes  ",
    );
    const activate = screen.getByRole("button", { name: /^Activate$/i });
    expect(activate).toBeDisabled();

    await user.click(
      within(form).getByRole("button", { name: "Save famous_scientists" }),
    );
    await waitFor(() => expect(state.patches).toHaveLength(1));
    expect(state.patches[0]).toMatchObject({
      display_name: "famous_scientists",
      description: "notes",
    });
    await waitFor(() => expect(activate).toBeEnabled());
    await user.click(activate);
    expect(
      await screen.findByRole("button", { name: /^Done$/i }),
    ).toBeVisible();
  });

  it("offers only backend-supported string fields for text, title and URL", async () => {
    const user = userEvent.setup();
    const state = makeState({
      imp: makeImport({
        datasets: [
          makeDataset({
            fields: [
              { name: "name", type: "text" },
              { name: "slug", type: "keyword" },
              { name: "age", type: "long" },
              { name: "born", type: "date" },
              { name: "address", type: "nested" },
            ],
          }),
        ],
      }),
    });
    renderWizard(state, { resumeImportId: "imp-1" });

    expect(
      await screen.findByRole("checkbox", { name: "name (text)" }),
    ).toBeVisible();
    expect(
      screen.getByRole("checkbox", { name: "slug (keyword)" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("checkbox", { name: /^age/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: /^born/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: /^address/ }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("combobox", {
        name: "Title field for famous_scientists",
      }),
    );
    expect(
      await screen.findByRole("option", { name: "slug (keyword)" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("option", { name: /^age/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /^born/ }),
    ).not.toBeInTheDocument();
  });

  it("sends endpoint_url null when a stored endpoint is cleared", async () => {
    const user = userEvent.setup();
    const state = makeState({
      sources: [makeSource({ endpoint_url: "https://s3.example.com" })],
    });
    let patched: Record<string, unknown> | undefined;
    renderWithProviders(
      <ImportWizard open onOpenChange={vi.fn()} pollIntervalMs={20} />,
      {
        providers: ["auth"],
        auth: snapshotAdmin,
        handlers: [
          ...handlers(state),
          http.patch(`${BASE}/sources/src-1`, async ({ request }) => {
            patched = (await request.json()) as Record<string, unknown>;
            return HttpResponse.json(makeSource());
          }),
        ],
      },
    );

    await user.click(
      await screen.findByRole("button", { name: "Edit Lab bucket" }),
    );
    await user.clear(await screen.findByLabelText("Endpoint URL (optional)"));
    await user.click(screen.getByRole("button", { name: /^Save source$/i }));

    await waitFor(() => expect(patched).toBeDefined());
    expect(patched).toHaveProperty("endpoint_url", null);
  });

  it("hides the size of snapshot indices the backend could not measure", async () => {
    const user = userEvent.setup();
    const state = makeState();
    const listing = makeListing();
    listing.snapshots[0].indices = [
      { name: "famous_scientists", size_bytes: 0 },
      { name: "scientific_discoveries", size_bytes: 5 * 1024 * 1024 },
    ];
    renderWithProviders(
      <ImportWizard open onOpenChange={vi.fn()} pollIntervalMs={20} />,
      {
        providers: ["auth"],
        auth: snapshotAdmin,
        handlers: [
          http.get(`${BASE}/sources/:id/snapshots`, () =>
            HttpResponse.json(listing),
          ),
          ...handlers(state),
        ],
      },
    );
    await user.click(
      await screen.findByRole("button", { name: /^Lab bucket/ }),
    );
    await user.click(screen.getByRole("button", { name: /^Continue$/i }));
    await user.click(
      await screen.findByRole("radio", { name: /scientists-v1/ }),
    );
    expect(screen.getByText("5.0 MB")).toBeVisible();
    expect(screen.queryByText("0 B")).not.toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("does not let a viewer create sources", async () => {
    const state = makeState({ sources: [] });
    renderWizard(state, { auth: authPresets.viewer });

    const save = await screen.findByRole("button", {
      name: /^Save and test source$/i,
    });
    expect(save).toBeDisabled();
    expect(save).toHaveAttribute(
      "title",
      "You do not have permission to create connectors",
    );
  });
});
