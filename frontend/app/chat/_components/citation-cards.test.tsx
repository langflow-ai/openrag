import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { CitedSource } from "@/components/markdown-citations";
import { Popover } from "@/components/ui/popover";
import { CitationCards } from "./citation-cards";

const sources: CitedSource[] = [
  {
    index: 1,
    item: {
      chunk_id: "c1",
      filename: "report.pdf",
      score: 0.91,
      page: 3,
      source_url: "https://example.com/report",
    },
  },
  { index: 2, item: { chunk_id: "c2", filename: "notes.md" } },
];

describe("CitationCards", () => {
  it("renders nothing when there are no cited sources", () => {
    const { container } = render(<CitationCards citedSources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a clickable card per source with page and score", async () => {
    const user = userEvent.setup();
    const onCardClick = vi.fn();
    render(
      <Popover>
        <CitationCards
          citedSources={sources}
          activeCardIndex={1}
          onCardClick={onCardClick}
        />
      </Popover>,
    );

    const cards = screen.getAllByRole("button");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveClass("shadow-xs", "bg-muted", "cursor-pointer");
    expect(cards[0]).toHaveTextContent("page 3 • score 0.91");
    expect(cards[0]).toHaveAttribute(
      "title",
      "View source chunk details (has link: https://example.com/report)",
    );
    expect(cards[1]).toHaveClass("bg-muted/50");

    await user.click(cards[1]);
    expect(onCardClick).toHaveBeenCalledWith(2, cards[1]);
  });

  it("renders static cards when not interactive", () => {
    render(<CitationCards citedSources={sources} interactive={false} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("notes.md").closest(".shadow-xs")).toHaveClass(
      "cursor-default",
    );
  });
});
