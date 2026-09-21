/**
 * Test render helpers.
 *
 * ── The problem this solves ─────────────────────────────────────────────────
 * `app/layout.tsx` wraps the app in eight nested contexts, and every one of
 * their hooks throws `"useX must be used within a XProvider"` when absent.
 * 69 of the 124 client components consume at least one of them, so without a
 * shared harness each component test opens by hand-rolling a provider stack —
 * which is why the suite has so far only reached pure helpers in `lib/`.
 *
 * ── The approach ────────────────────────────────────────────────────────────
 * These are the REAL providers, not fake context values. State is driven by
 * MSW payloads, the same way the app drives it, so `AuthProvider`'s mode
 * precedence and permission resolution stay under test in every test that
 * mounts it — consistent with the repo's rule about not mocking away
 * `app/api/queries/`. A component test failing because a provider is broken is
 * the intended behaviour: that is a bug the user would have hit.
 *
 * Deliberately does NOT use `app/providers.tsx` or
 * `app/api/get-query-client.ts`:
 *
 *   - `app/providers.tsx` monkey-patches `window.fetch` to intercept 401s and
 *     redirect. MSW's Node interceptor also patches `globalThis.fetch`, and the
 *     ordering between the two is unpredictable.
 *   - `getQueryClient()` memoizes a single client in browser environments, so
 *     cache would leak between tests in the same file.
 *
 * ── Usage ───────────────────────────────────────────────────────────────────
 *   renderWithProviders(<ConnectorCard />, {
 *     providers: ["auth", "brand", "task"],
 *     auth: authPresets.viewer,
 *     brand: "ibm",
 *   });
 *
 * Provider state resolves asynchronously (auth alone is three fetches), so the
 * first paint is always the loading state. Assert with `await screen.findBy…`
 * or `await waitFor(...)`, never a bare `getBy…` on the first tick.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type RenderOptions, render } from "@testing-library/react";
import type { RequestHandler } from "msw";
import type { ComponentType, ReactElement, ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/contexts/auth-context";
import { BrandProvider } from "@/contexts/brand-context";
import { ChatProvider } from "@/contexts/chat-context";
import { ConsoleStatusProvider } from "@/contexts/console-status-context";
import { KnowledgeFilterProvider } from "@/contexts/knowledge-filter-context";
import { TaskProvider } from "@/contexts/task-context";
import { UnsavedChangesProvider } from "@/contexts/unsaved-changes-context";
import type { Brand } from "@/lib/brand";
import type { AuthScenario } from "@/test-utils/fixtures/auth";
import { authHandlers } from "@/test-utils/msw/auth";
import { server } from "@/test-utils/msw/server";

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 0,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}

export type ProviderName =
  | "tooltip"
  | "auth"
  | "brand"
  | "task"
  | "knowledgeFilter"
  | "consoleStatus"
  | "chat"
  | "unsavedChanges";

/**
 * Which providers each one needs beneath it.
 *
 * Listing a provider pulls its dependencies in automatically, so a test names
 * what the component uses rather than what the tree happens to require —
 * `providers: ["consoleStatus"]` is enough, even though it reads `useAuth`,
 * `useTask`, and `useKnowledgeFilter`.
 */
const PROVIDER_DEPENDENCIES: Record<ProviderName, ProviderName[]> = {
  tooltip: [],
  auth: [],
  brand: ["auth"],
  task: ["auth"],
  knowledgeFilter: [],
  consoleStatus: ["auth", "knowledgeFilter", "task"],
  chat: [],
  unsavedChanges: [],
};

/**
 * Nesting order, outermost first. Matches `app/layout.tsx` exactly — every
 * dependency above happens to be satisfied by that order, and keeping the two
 * in step means a test tree behaves like the real one.
 */
const PROVIDER_ORDER: ProviderName[] = [
  "tooltip",
  "auth",
  "brand",
  "task",
  "knowledgeFilter",
  "consoleStatus",
  "chat",
  "unsavedChanges",
];

const PROVIDER_COMPONENTS: Record<
  ProviderName,
  ComponentType<{ children: ReactNode }>
> = {
  tooltip: TooltipProvider,
  auth: AuthProvider,
  brand: BrandProvider,
  task: TaskProvider,
  knowledgeFilter: KnowledgeFilterProvider,
  consoleStatus: ConsoleStatusProvider,
  chat: ChatProvider,
  unsavedChanges: UnsavedChangesProvider,
};

function resolveProviders(requested: ProviderName[]): ProviderName[] {
  const selected = new Set<ProviderName>();

  const visit = (name: ProviderName) => {
    if (selected.has(name)) return;
    selected.add(name);
    for (const dep of PROVIDER_DEPENDENCIES[name]) visit(dep);
  };
  for (const name of requested) visit(name);

  return PROVIDER_ORDER.filter((name) => selected.has(name));
}

export interface ProviderOptions {
  /**
   * Contexts the component under test needs. Dependencies are added
   * automatically. `"all"` mounts the full `app/layout.tsx` stack — use it for
   * page-level tests; naming the two or three a component actually uses keeps
   * failures readable.
   */
  providers?: ProviderName[] | "all";
  /**
   * Auth scenario, installed as MSW handlers for `/api/auth/me`,
   * `/api/users/me`, and `/api/onboarding-status`. Defaults to whatever
   * `handlers.ts` ships (an admin with RBAC on). See
   * `test-utils/fixtures/auth.ts` for the presets.
   */
  auth?: AuthScenario;
  /**
   * Seeds the brand `BrandProvider` reads from localStorage. Note IBM auth
   * mode forces `"ibm"` regardless — set the auth scenario, not this, when
   * testing that path.
   */
  brand?: Brand;
  /**
   * Extra MSW handlers for this render, applied AFTER the auth scenario so
   * they win over it.
   *
   * Use this rather than calling `server.use()` in the test body: the harness
   * installs the auth scenario at render time, which would otherwise be
   * prepended over an override the test set up earlier. Handlers that have
   * nothing to do with the provider stack can still go through `server.use()`
   * directly.
   */
  handlers?: RequestHandler[];
  queryClient?: QueryClient;
}

interface RenderWithProvidersOptions
  extends Omit<RenderOptions, "wrapper">,
    ProviderOptions {}

function applyProviderOptions({ auth, brand, handlers }: ProviderOptions) {
  // Prepended, so it wins over the defaults in handlers.ts. setup.ts calls
  // server.resetHandlers() after every test, so this does not leak.
  if (auth) server.use(...authHandlers(auth));
  // After the scenario, so a per-render override beats it. MSW resolves with
  // the most recently prepended matching handler.
  if (handlers?.length) server.use(...handlers);
  // Written before render because BrandProvider reads localStorage in its
  // mount effect.
  if (brand) localStorage.setItem("brand", brand);
}

function buildWrapper(
  queryClient: QueryClient,
  providers: ProviderName[] | "all",
) {
  const active = resolveProviders(
    providers === "all" ? PROVIDER_ORDER : providers,
  );

  return function Wrapper({ children }: { children: ReactNode }) {
    // Reduced from the innermost outwards, so `active`'s order is the nesting
    // order in the rendered tree.
    const tree = active.reduceRight<ReactNode>((acc, name) => {
      const Provider = PROVIDER_COMPONENTS[name];
      // Keyed by provider name: these nest rather than sit as siblings, but a
      // stable key keeps React from remounting the whole stack if the set of
      // active providers ever changes between renders.
      return <Provider key={name}>{acc}</Provider>;
    }, children);

    return (
      <QueryClientProvider client={queryClient}>{tree}</QueryClientProvider>
    );
  };
}

/**
 * Renders `ui` inside a fresh react-query provider and the requested contexts.
 *
 * Returns the QueryClient alongside RTL's usual result so a test can seed or
 * inspect the cache directly when it needs to.
 */
export function renderWithProviders(
  ui: ReactElement,
  {
    queryClient = createTestQueryClient(),
    providers = [],
    auth,
    brand,
    handlers,
    ...options
  }: RenderWithProvidersOptions = {},
) {
  applyProviderOptions({ auth, brand, handlers });

  return {
    queryClient,
    ...render(ui, {
      wrapper: buildWrapper(queryClient, providers),
      ...options,
    }),
  };
}

/**
 * Wrapper for `renderHook`, which takes a component rather than a render call.
 *
 * Each call builds its own QueryClient, so hooks under test never share cache.
 * Takes the same provider options as `renderWithProviders`:
 *
 *   renderHook(() => usePermissions(), {
 *     wrapper: createQueryWrapper({ providers: ["auth"], auth: authPresets.viewer }),
 *   });
 */
export function createQueryWrapper(
  options: ProviderOptions | QueryClient = {},
) {
  // Historically this took a QueryClient positionally; keep that working.
  const opts: ProviderOptions =
    options instanceof QueryClient ? { queryClient: options } : options;

  applyProviderOptions(opts);

  return buildWrapper(
    opts.queryClient ?? createTestQueryClient(),
    opts.providers ?? [],
  );
}

export * from "@testing-library/react";
export { default as userEvent } from "@testing-library/user-event";
