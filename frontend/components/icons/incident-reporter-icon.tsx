import { cn } from "@/lib/utils";

/**
 * Carbon "incident-reporter" glyph (clipboard + alert badge).
 * Inline SVG avoids `@carbon/icons-react` for a single icon.
 * @see https://github.com/carbon-design-system/carbon/tree/main/packages/icons
 */
export function IncidentReporterIcon({
  className,
  ...props
}: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 32"
      fill="currentColor"
      aria-hidden
      className={cn("inline-block", className)}
      {...props}
    >
      <path d="M10,13h12v2h-12v-2ZM10,20h8v-2h-8v2ZM10,25h5v-2h-5v2ZM7,7h3v3h12v-3h3v6h2v-6c0-1.1-0.9-2-2-2h-3v-1c0-1.1-0.9-2-2-2h-8c-1.1,0-2,0.9-2,2v1h-3c-1.1,0-2,0.9-2,2v21c0,1.10.9,2,2,2h5v-2h-5V7ZM12,4h8v4h-8v-4ZM29.91,28.94l-6.28-11.56c-0.27-0.49-0.98-0.49-1.26,0l-6.28,11.56c-0.26.48.09,1.060.63,1.06h12.56c0.55,0,0.89-0.580.63-1.06ZM22.25,21h1.5v4h-1.5v-4ZM23,28c-0.55,0-1-0.45-1-1s0.45-1,1-1,1,0.45,1,1-0.45,1-1,1Z" />
    </svg>
  );
}
