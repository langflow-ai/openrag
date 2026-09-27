import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorIcon, SuccessIcon, WarningIcon } from "./sonner";

// Stub next-themes — not available in jsdom.
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light" }) }));
// Stub sonner's Toaster — it injects a <style> tag using browser APIs not in jsdom.
vi.mock("sonner", () => ({ Toaster: () => null }));

describe("Sonner toast icon components", () => {
  it("SuccessIcon renders an svg with the green circle fill", () => {
    const { container } = render(<SuccessIcon />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(container.innerHTML).toContain("#24a148");
  });

  it("WarningIcon renders an svg with the amber circle fill", () => {
    const { container } = render(<WarningIcon />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(container.innerHTML).toContain("#f1c21b");
  });

  it("ErrorIcon renders an svg with the red circle fill", () => {
    const { container } = render(<ErrorIcon />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(container.innerHTML).toContain("#da1e28");
  });
});
