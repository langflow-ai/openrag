import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProviderHealthBanner } from "./provider-health-banner";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/app/api/queries/useProviderHealthQuery", () => ({
  useProviderHealthQuery: vi.fn(),
}));

vi.mock("@/contexts/chat-context", () => ({
  useChat: () => ({ hasChatError: false }),
}));

vi.mock("@/hooks/use-narrow-layout", () => ({
  useNarrowLayout: vi.fn().mockReturnValue(false),
}));

import { useProviderHealthQuery } from "@/app/api/queries/useProviderHealthQuery";
import { useNarrowLayout } from "@/hooks/use-narrow-layout";

describe("ProviderHealthBanner", () => {
  it("renders unhealthy state and navigates to fix setup", async () => {
    const user = userEvent.setup();
    vi.mocked(useProviderHealthQuery).mockReturnValue({
      data: {
        status: "unhealthy",
        provider: "openai",
        llm_error: "Invalid API Key",
      },
      isLoading: false,
      isFetching: false,
      error: null,
      isError: false,
    } as any);

    render(<ProviderHealthBanner />);

    expect(
      screen.getByText(/OpenAI error - Invalid API Key/i),
    ).toBeInTheDocument();
    const fixButton = screen.getByRole("button", { name: "Fix Setup" });
    await user.click(fixButton);
    expect(mockPush).toHaveBeenCalledWith("/settings?setup=openai");
  });

  it("renders in narrow mode", () => {
    vi.mocked(useNarrowLayout).mockReturnValue(true);
    vi.mocked(useProviderHealthQuery).mockReturnValue({
      data: {
        status: "unhealthy",
        provider: "openai",
        llm_error: "Invalid API Key",
      },
      isLoading: false,
      isFetching: false,
      error: null,
      isError: false,
    } as any);

    render(<ProviderHealthBanner />);
    expect(
      screen.getByText(/OpenAI error - Invalid API Key/i),
    ).toBeInTheDocument();
  });

  const staleSpace = {
    code: "stale_embedding_space",
    provider: "rhoai",
    message:
      "Documents are indexed with 'old-model', which this endpoint no longer serves",
  };

  function mockHealth(data: object) {
    vi.mocked(useProviderHealthQuery).mockReturnValue({
      data,
      isLoading: false,
      isFetching: false,
      error: null,
      isError: false,
    } as unknown as ReturnType<typeof useProviderHealthQuery>);
  }

  it("renders a healthy provider with warnings as a warning that points at Knowledge", async () => {
    const user = userEvent.setup();
    mockPush.mockClear();
    mockHealth({ status: "healthy", message: "ok", warnings: [staleSpace] });

    render(<ProviderHealthBanner />);

    expect(
      screen.getByText(/warning - Documents are indexed with 'old-model'/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fix Setup" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open Knowledge" }));
    expect(mockPush).toHaveBeenCalledWith("/knowledge");
  });

  it("lets an unhealthy verdict outrank a warning", () => {
    mockHealth({
      status: "unhealthy",
      provider: "openai",
      llm_error: "Invalid API Key",
      warnings: [staleSpace],
    });

    render(<ProviderHealthBanner />);

    expect(
      screen.getByText(/OpenAI error - Invalid API Key/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Knowledge" })).toBeNull();
  });

  it("renders nothing for a healthy provider without warnings", () => {
    mockHealth({ status: "healthy", message: "ok", warnings: [] });

    const { container } = render(<ProviderHealthBanner />);

    expect(container).toBeEmptyDOMElement();
  });
});
