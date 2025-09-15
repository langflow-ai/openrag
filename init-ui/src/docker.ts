import Docker from "dockerode";
export const docker = new Docker({ socketPath: "/var/run/docker.sock" });

export async function listProjectContainers(projectName: string) {
  const all = await docker.listContainers({
    all: true,
    filters: { label: [`com.docker.compose.project=${projectName}`] },
  });
  const items = await Promise.all(
    all.map(async (c) => {
      const cont = docker.getContainer(c.Id);
      const inspect = await cont.inspect();
      const health = inspect?.State?.Health?.Status ?? null;
      return {
        id: c.Id,
        name: (c.Names?.[0] || "").replace(/^\//, ""),
        image: c.Image,
        state: c.State,
        status: c.Status,
        health,
      };
    }),
  );
  return items;
}

export function progressFromHealth(items: Array<{ health: string | null }>) {
  const withHealth = items.filter((i) => i.health);
  if (!withHealth.length) return null;
  const healthy = withHealth.filter((i) => i.health === "healthy").length;
  return Math.round((100 * healthy) / withHealth.length);
}
