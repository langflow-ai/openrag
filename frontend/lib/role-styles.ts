/**
 * Single source of truth for role visuals.
 *
 * One pill SHAPE/SIZE — only the COLOR tint changes by role. The tint
 * is applied as a TRANSPARENT overlay (`bg-{color}/10`,
 * `border-{color}/30`) so the underlying card/page background shows
 * through. No white is pre-mixed into the colors — that means the same
 * classes work correctly on light AND dark themes:
 *   light theme: red-500 at 10% over white  → soft pink
 *   dark theme:  red-500 at 10% over slate  → muted red ember
 *
 * Sizing matches the modern admin "chip" pattern (Vercel / Linear /
 * Stripe / GitHub): `px-3 py-1 text-sm` ≈ 32px tall, big enough to read
 * without competing with primary action buttons (h-9 / 36px).
 *
 * Industry-standard role colors:
 *   admin     -> red    (high privilege, danger zone — Discord, Auth0)
 *   developer -> blue   (technical/builder — GitHub, VS Code)
 *   user      -> neutral foreground (default, no special status)
 *   viewer    -> emerald (read-only, safe — Slack guest)
 *   custom    -> amber  (visually distinguishable from built-ins)
 */

export const ROLE_PILL_BASE =
  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium capitalize transition-colors";

const ROLE_TINTS: Record<string, string> = {
  admin: "bg-red-500/10 text-red-600 border-red-500/30 dark:text-red-400",
  developer:
    "bg-blue-500/10 text-blue-600 border-blue-500/30 dark:text-blue-400",
  user: "bg-foreground/5 text-foreground/80 border-foreground/15",
  viewer:
    "bg-emerald-500/10 text-emerald-600 border-emerald-500/30 dark:text-emerald-400",
};

const CUSTOM_ROLE_TINT =
  "bg-amber-500/10 text-amber-600 border-amber-500/30 dark:text-amber-400";

export function getRolePillClass(roleName: string): string {
  const tint = ROLE_TINTS[roleName] ?? CUSTOM_ROLE_TINT;
  return `${ROLE_PILL_BASE} ${tint}`;
}
