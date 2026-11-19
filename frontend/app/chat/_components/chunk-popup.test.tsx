import { describe, expect, it, vi } from "vitest";
import { Popover, PopoverAnchor } from "@/components/ui/popover";
import { renderWithProviders, screen } from "@/test-utils/render";
import { ChunkPopup } from "./chunk-popup";

function renderPopup(item: Parameters<typeof ChunkPopup>[0]["item"]) {
  return renderWithProviders(
    <Popover open>
      <PopoverAnchor>anchor</PopoverAnchor>
      <ChunkPopup
        onClose={vi.fn()}
        chunkNumber={1}
        filename="Photo 51"
        score={0.9}
        sourceText="X-ray diffraction image"
        item={item}
      />
    </Popover>,
  );
}

describe("ChunkPopup", () => {
  it("shows the dataset a result came from", async () => {
    renderPopup({
      chunk_id: "ds-1-abc",
      dataset: { id: "ds-1", name: "Scientists" },
    });
    expect(await screen.findByText("Scientists")).toBeVisible();
    expect(screen.getByTitle("Dataset: Scientists")).toBeVisible();
  });

  it("shows no dataset badge for document results", async () => {
    renderPopup({ chunk_id: "doc-1", dataset: null });
    await screen.findByText("Chunk 1");
    expect(screen.queryByTitle(/^Dataset: /)).not.toBeInTheDocument();
  });
});
