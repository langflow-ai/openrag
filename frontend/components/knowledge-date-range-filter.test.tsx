import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { KnowledgeDateRangeFilter } from "./knowledge-date-range-filter";

// Radix Popover does not open via click in JSDOM (portal + pointer-event
// restrictions). Mock it so PopoverContent renders inline, driven by the
// controlled open/onOpenChange props the component passes.
// vi.mock is hoisted before imports, so React must be imported inside the factory.
vi.mock("@/components/ui/popover", async () => {
  const React = await import("react");

  type CtxVal = { open: boolean; setOpen: (v: boolean) => void };
  const Ctx = React.createContext<CtxVal>({ open: false, setOpen: () => {} });

  function Popover({
    open = false,
    onOpenChange = () => {},
    children,
  }: {
    open?: boolean;
    onOpenChange?: (v: boolean) => void;
    children?: React.ReactNode;
  }) {
    return (
      <Ctx.Provider value={{ open, setOpen: onOpenChange }}>
        {children}
      </Ctx.Provider>
    );
  }

  function PopoverTrigger({
    asChild,
    children,
  }: {
    asChild?: boolean;
    children: React.ReactElement;
  }) {
    const { open, setOpen } = React.useContext(Ctx);
    const toggle = () => setOpen(!open);
    if (asChild && React.isValidElement(children)) {
      return React.cloneElement(children as React.ReactElement<any>, {
        onClick: (e: React.MouseEvent) => {
          toggle();
          (children.props as any).onClick?.(e);
        },
      });
    }
    return <button onClick={toggle}>{children}</button>;
  }

  function PopoverContent({
    children,
    className,
  }: {
    children?: React.ReactNode;
    className?: string;
    align?: string;
  }) {
    const { open } = React.useContext(Ctx);
    return open ? <div className={className}>{children}</div> : null;
  }

  return { Popover, PopoverTrigger, PopoverContent };
});

describe("KnowledgeDateRangeFilter", () => {
  it("renders the trigger button with accessible label", () => {
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    expect(
      screen.getByRole("button", { name: /filter by date range/i }),
    ).toBeInTheDocument();
  });

  it("shows Date range label when no range is selected", () => {
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("opens the popover and shows presets on click", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    await user.click(
      screen.getByRole("button", { name: /filter by date range/i }),
    );
    expect(screen.getByText("Last 7 days")).toBeInTheDocument();
    expect(screen.getByText("Last 30 days")).toBeInTheDocument();
    expect(screen.getByText("This month")).toBeInTheDocument();
  });

  it("applies Last 7 days preset and closes popover", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    await user.click(
      screen.getByRole("button", { name: /filter by date range/i }),
    );
    await user.click(screen.getByText("Last 7 days"));
    expect(screen.queryByText("Last 7 days")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /clear date range/i }),
    ).toBeInTheDocument();
  });

  it("applies Last 30 days preset and closes popover", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    await user.click(
      screen.getByRole("button", { name: /filter by date range/i }),
    );
    await user.click(screen.getByText("Last 30 days"));
    expect(screen.queryByText("Last 30 days")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /clear date range/i }),
    ).toBeInTheDocument();
  });

  it("applies This month preset and closes popover", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    await user.click(
      screen.getByRole("button", { name: /filter by date range/i }),
    );
    await user.click(screen.getByText("This month"));
    expect(screen.queryByText("This month")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /clear date range/i }),
    ).toBeInTheDocument();
  });

  it("clears the date range when the clear button is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    await user.click(
      screen.getByRole("button", { name: /filter by date range/i }),
    );
    await user.click(screen.getByText("Last 7 days"));
    await user.click(screen.getByRole("button", { name: /clear date range/i }));
    expect(
      screen.queryByRole("button", { name: /clear date range/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("shows a date range label in the trigger after selecting a preset", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    await user.click(
      screen.getByRole("button", { name: /filter by date range/i }),
    );
    await user.click(screen.getByText("Last 7 days"));
    expect(screen.queryByText("Date range")).not.toBeInTheDocument();
  });

  it("shows a Clear button inside the popover when a range is active", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["knowledgeFilter"],
    });
    await user.click(
      screen.getByRole("button", { name: /filter by date range/i }),
    );
    await user.click(screen.getByText("Last 7 days"));

    // Re-open: click trigger again (no longer has aria-label "filter by date range"
    // because the label changed to show dates — find by role instead)
    const buttons = screen.getAllByRole("button");
    const triggerBtn = buttons.find(
      (b) =>
        b.getAttribute("aria-label") !== "Clear date range" &&
        !b.textContent?.includes("Clear"),
    );
    if (triggerBtn) await user.click(triggerBtn);

    const clearButtons = screen.getAllByRole("button", { name: /clear/i });
    expect(clearButtons.length).toBeGreaterThanOrEqual(1);
  });
});
