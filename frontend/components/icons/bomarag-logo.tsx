export default function BomaragLogo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="41"
      height="41"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <title>BomaRAG Logo</title>
      {/* Placeholder Bomalogic mark: a retrieval graph feeding a document.
          Replace with the official Bomalogic asset — see branding/README.md. */}
      <rect
        x="26"
        y="4"
        width="18"
        height="24"
        rx="2.5"
        stroke="currentColor"
        strokeWidth="2.75"
      />
      <path
        d="M31 12h8M31 17h8M31 22h5"
        stroke="currentColor"
        strokeWidth="2.75"
        strokeLinecap="round"
      />
      <path
        d="M10 16v8a6 6 0 0 0 6 6h10"
        stroke="currentColor"
        strokeWidth="2.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="10" r="6" fill="currentColor" />
      <circle cx="10" cy="38" r="6" fill="currentColor" />
      <path
        d="M10 32v-8a6 6 0 0 1 6-6h10"
        stroke="currentColor"
        strokeWidth="2.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
