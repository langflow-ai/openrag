export default function AzureBlobIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <rect width="32" height="32" fill="white" fillOpacity="0.01" />
      <path
        d="M13.6 5.5h6.05l-6.28 18.6a1 1 0 0 1-.95.68H7.2a1 1 0 0 1-.95-1.32L12.65 6.18a1 1 0 0 1 .95-.68Z"
        fill="url(#azblob_a)"
      />
      <path
        d="M22.4 20.1H12.7a.46.46 0 0 0-.31.8l6.23 5.82a1 1 0 0 0 .68.27h5.58l-2.46-6.89Z"
        fill="#0078D4"
      />
      <path
        d="M13.6 5.5a1 1 0 0 0-.95.69L6.26 23.45a1 1 0 0 0 .94 1.33h5.3a1.07 1.07 0 0 0 .82-.7l1.28-3.77 4.57 4.26a1 1 0 0 0 .63.21h5.55l-2.43-6.89-7.09.02 4.34-12.62H13.6Z"
        fill="url(#azblob_b)"
      />
      <defs>
        <linearGradient
          id="azblob_a"
          x1="15.5"
          y1="6.9"
          x2="9.1"
          y2="25.8"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#114A8B" />
          <stop offset="1" stopColor="#0669BC" />
        </linearGradient>
        <linearGradient
          id="azblob_b"
          x1="18.5"
          y1="6"
          x2="22"
          y2="25"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#3CCBF4" />
          <stop offset="1" stopColor="#2892DF" />
        </linearGradient>
      </defs>
    </svg>
  );
}
