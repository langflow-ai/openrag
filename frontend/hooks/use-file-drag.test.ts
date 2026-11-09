import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useFileDrag } from "./use-file-drag";

function makeDragEvent(types: string[] = ["Files"], files: File[] = []) {
  return new Event("dragenter") as DragEvent & {
    dataTransfer: { types: string[]; files: FileList };
  };
}

/** Fire a synthetic DragEvent on window with the given type and dataTransfer. */
function fireDrag(
  eventType: string,
  opts: { types?: string[]; files?: File[] } = {},
) {
  const event = Object.assign(new Event(eventType), {
    dataTransfer: {
      types: opts.types ?? ["Files"],
      files: {
        length: opts.files?.length ?? 0,
        0: opts.files?.[0],
        [Symbol.iterator]: function* () {
          yield* opts.files ?? [];
        },
      } as unknown as FileList,
    },
  });
  window.dispatchEvent(event);
  return event;
}

describe("useFileDrag", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts with isDragging = false", () => {
    const { result } = renderHook(() => useFileDrag());
    expect(result.current).toBe(false);
  });

  it("sets isDragging true on dragenter with Files type", () => {
    const { result } = renderHook(() => useFileDrag());

    act(() => {
      fireDrag("dragenter");
    });
    expect(result.current).toBe(true);
  });

  it("ignores dragenter that does not carry Files", () => {
    const { result } = renderHook(() => useFileDrag());

    act(() => {
      fireDrag("dragenter", { types: ["text/plain"] });
    });
    expect(result.current).toBe(false);
  });

  it("sets isDragging false on dragleave after all enters are left", () => {
    const { result } = renderHook(() => useFileDrag());

    act(() => {
      fireDrag("dragenter");
    }); // counter = 1
    act(() => {
      fireDrag("dragenter");
    }); // counter = 2
    expect(result.current).toBe(true);

    act(() => {
      window.dispatchEvent(new Event("dragleave"));
    }); // counter = 1
    expect(result.current).toBe(true);

    act(() => {
      window.dispatchEvent(new Event("dragleave"));
    }); // counter = 0
    expect(result.current).toBe(false);
  });

  it("sets isDragging false on drop and does not call onFileDrop when no files", () => {
    const onFileDrop = vi.fn();
    const { result } = renderHook(() => useFileDrag(onFileDrop));

    act(() => {
      fireDrag("dragenter");
    });
    expect(result.current).toBe(true);

    act(() => {
      fireDrag("drop", { files: [] });
    });
    expect(result.current).toBe(false);
    expect(onFileDrop).not.toHaveBeenCalled();
  });

  it("calls onFileDrop with the first file when files are dropped", () => {
    const onFileDrop = vi.fn();
    renderHook(() => useFileDrag(onFileDrop));

    const file = new File(["hello"], "test.txt", { type: "text/plain" });

    act(() => {
      fireDrag("drop", { files: [file] });
    });
    expect(onFileDrop).toHaveBeenCalledWith(file);
  });

  it("removes all event listeners on unmount", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderHook(() => useFileDrag());

    unmount();

    const removedEvents = removeSpy.mock.calls.map((c) => c[0]);
    expect(removedEvents).toContain("dragenter");
    expect(removedEvents).toContain("dragleave");
    expect(removedEvents).toContain("dragover");
    expect(removedEvents).toContain("drop");
  });
});
