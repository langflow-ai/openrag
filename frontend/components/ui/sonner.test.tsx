import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorIcon, SuccessIcon, WarningIcon } from "./sonner";

// Stub next-themes — not available in jsdom.
vi.mock("next-themes", () => ({ useTheme: () => ({ theme: "light" }) }));
// Stub sonner's Toaster — it injects a <style> tag using browser APIs not in jsdom.
vi.mock("sonner", () => ({ Toaster: () => null }));

describe("Sonner toast icon components", () => {
  it("SuccessIcon renders a circle span with an svg checkmark", () => {
    const { container } = render(<SuccessIcon />);
    const span = container.querySelector("span");
    expect(span).not.toBeNull();
    expect(span?.className).toContain("rounded-full");
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("WarningIcon renders a circle span with an svg exclamation", () => {
    const { container } = render(<WarningIcon />);
    const span = container.querySelector("span");
    expect(span).not.toBeNull();
    expect(span?.className).toContain("rounded-full");
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("ErrorIcon renders a circle span with an svg backslash", () => {
    const { container } = render(<ErrorIcon />);
    const span = container.querySelector("span");
    expect(span).not.toBeNull();
    expect(span?.className).toContain("rounded-full");
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
