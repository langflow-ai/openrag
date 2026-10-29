import type { File } from "@/app/api/queries/useGetSearchQuery";

/** Keep user-disabled pages at the end after AG Grid applies its own sort. */
export function moveDisabledPagesLast(nodes: Array<{ data?: File }>) {
  const enabled = nodes.filter((node) => node.data?.status !== "disabled");
  const disabled = nodes.filter((node) => node.data?.status === "disabled");
  nodes.splice(0, nodes.length, ...enabled, ...disabled);
}
