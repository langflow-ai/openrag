# Processing → Active Click Fix

## Background: the ag-grid stale-cell problem

ag-grid only re-renders a cell when the value of its bound `field` changes. The Source
column is bound to `field: "filename"`. When a row's status flips from `processing` to
`active` after ingestion completes, the filename does not change — so ag-grid skips the
cell re-render entirely. Any value computed inside `cellRenderer` at the previous render
is frozen in the DOM.

This caused **three separate bugs**, each fixed in turn.

---

## Bug 1 — Wrong cursor after status change

**Problem.** `isActive` was computed from `data?.status` at render time, then used to set
`cursor-pointer` vs `cursor-default` via a conditional Tailwind class. After status
changed, the stale `isActive = false` kept `cursor-default` on the button — the row
looked unclickable even though the file was ready.

```ts
// ❌ isActive is frozen from the last render
className={isActive ? "cursor-pointer" : "cursor-default"}
```

**Fix.** Moved cursor style to CSS driven by the row's `ag-row-processing` class. ag-grid
adds and removes row classes independently of cell re-renders via `rowClassRules`:

```ts
// in AgGridReact props
rowClassRules={{ "ag-row-processing": (p) => p.data?.status === "processing" }}
```

```css
/* always pointer (active rows) */
.button { cursor: pointer; }

/* override to default for processing rows */
.ag-row-processing .button { cursor: default; }
```

In Tailwind arbitrary-variant syntax (compiled and verified against the project config):

```
[.ag-row-processing_&]:cursor-default
[.ag-row-processing_&]:hover:text-foreground
```

When ingestion completes, ag-grid removes `ag-row-processing` from the row element and
the CSS override disappears — the pointer cursor restores without any cell re-render.

---

## Bug 2 — Click silently blocked after status change

Even after Bug 1 was fixed and the cursor looked correct, clicking still navigated nowhere.

**Problem.** The `onClick` guard checked a closed-over `isActive`:

```ts
// ❌ isActive stale — was false when cell was rendered as processing
onClick={() => {
  if (!isActive) return;   // always fires, router.push never called
  router.push(...)
}}
```

**First attempt.** Changed the guard to read `data?.status` directly at click time:

```ts
// ❌ still stale — `data` is a destructured snapshot from render params
onClick={() => {
  if ((data?.status || "active") !== "active") return;
  router.push(...)
}}
```

This also failed. `data` is destructured at the top of the renderer function:
`const { data, value } = params`. Even though ag-grid passes fresh params at render time,
once destructured `data` is a plain object reference — a snapshot. Since the cell never
re-rendered, `data.status` was still `"processing"` in the closure.

**Correct fix.** Read `params.node.data` inside `onClick`. `params.node` is a live ag-grid
row node; its `.data` property is always the current row data regardless of whether the
cell has re-rendered:

```ts
// ✅ params.node.data is always the live, current row data
cellRenderer: (params: CustomCellRendererProps<File>) => {
  const { data, value } = params;  // snapshot — fine for rendering JSX only

  return (
    <button
      onClick={() => {
        const liveData = params.node.data;   // live — safe to read at click time
        if ((liveData?.status || "active") !== "active") return;
        router.push(buildChunksUrl(liveData?.filename ?? "", effectiveSearchText));
      }}
    >
      ...
    </button>
  );
}
```

---

## Bug 3 — `rowClassRules` module not registered

ag-grid v36 uses a modular build. `rowClassRules` requires `RowStyleModule` to be
registered. Without it, ag-grid throws error #200 at runtime and `ag-row-processing` is
never stamped on any row — silently breaking both the spacer alignment and the cursor fix.

**Fix.** Added `RowStyleModule` to
[`registerAgGridModules.ts`](../../frontend/components/AgGrid/registerAgGridModules.ts):

```ts
import { RowStyleModule } from "ag-grid-community";

ModuleRegistry.registerModules([
  ...,
  RowStyleModule,
]);
```

---

## Summary

| Layer | Problem | Fix |
|---|---|---|
| Module registry | `rowClassRules` silently no-ops — `RowStyleModule` missing | Register `RowStyleModule` in `registerAgGridModules.ts` |
| CSS — cursor | `cursor-default` frozen after status change (stale render) | Drive cursor via `ag-row-processing` ancestor CSS class |
| JS — click guard | `data?.status` snapshot stale in closure | Read `params.node.data` (live row node) at click time |

The root lesson: any value derived from `data` (destructured params) inside a `cellRenderer`
is a snapshot. For anything that must stay current without a re-render — cursor style,
click guards, navigation targets — either use CSS classes driven by `rowClassRules`, or
read from `params.node.data` at event time.
