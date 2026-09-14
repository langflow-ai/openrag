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
});
