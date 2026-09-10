/**
 * Test render helper.
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
 * Each render therefore gets a fresh QueryClient with retries off, so a test
 * asserting an error state fails fast instead of waiting out react-query's
 * default retry/backoff.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type RenderOptions, render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

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

interface RenderWithProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  queryClient?: QueryClient;
}

/**
 * Renders `ui` inside a fresh react-query provider.
 *
 * Returns the QueryClient alongside RTL's usual result so a test can seed or
 * inspect the cache directly when it needs to.
 */
export function renderWithProviders(
  ui: ReactElement,
  {
    queryClient = createTestQueryClient(),
    ...options
  }: RenderWithProvidersOptions = {},
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  return {
    queryClient,
    ...render(ui, { wrapper: Wrapper, ...options }),
  };
}

/**
 * Wrapper for `renderHook`, which takes a component rather than a render call.
 *
 * Each call builds its own QueryClient, so hooks under test never share cache.
 */
export function createQueryWrapper(queryClient = createTestQueryClient()) {
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

export * from "@testing-library/react";
export { default as userEvent } from "@testing-library/user-event";
