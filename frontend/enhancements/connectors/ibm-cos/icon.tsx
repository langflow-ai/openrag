export default function IBMCOSIcon(props: React.SVGProps<SVGSVGElement>) {
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
      <mask
        id="mask0_40_3996"
        style={{ maskType: "luminance" }}
        maskUnits="userSpaceOnUse"
        x="2"
        y="19"
        width="28"
        height="11"
      >
        <path
          d="M7 26C7.55228 26 8 25.5523 8 25C8 24.4477 7.55228 24 7 24C6.44772 24 6 24.4477 6 25C6 25.5523 6.44772 26 7 26Z"
          fill="white"
        />
        <path
          d="M28 20H26V22H28V28H4V22H14V20H4C3.46957 20 2.96086 20.2107 2.58579 20.5858C2.21071 20.9609 2 21.4696 2 22V28C2 28.5304 2.21071 29.0391 2.58579 29.4142C2.96086 29.7893 3.46957 30 4 30H28C28.5304 30 29.0391 29.7893 29.4142 29.4142C29.7893 29.0391 30 28.5304 30 28V22C30 21.4696 29.7893 20.9609 29.4142 20.5858C29.0391 20.2107 28.5304 20 28 20Z"
          fill="white"
        />
        <path d="M15 23H4V19H15V23Z" fill="url(#paint0_linear_40_3996)" />
      </mask>
      <g mask="url(#mask0_40_3996)">
        <rect width="32" height="32" fill="url(#paint1_linear_40_3996)" />
      </g>
      <path
        d="M18 10H10V2H18V10ZM12 8H16V4H12V8ZM22 14H16V22H24V16H30V8H22V14ZM22 20H18V16H22V20ZM28 10V14H24V10H28Z"
        fill="currentColor"
      />
      <defs>
        <linearGradient
          id="paint0_linear_40_3996"
          x1="15"
          y1="21"
          x2="4"
          y2="21"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0.1" />
          <stop offset="0.888" stopOpacity="0" />
        </linearGradient>
        <linearGradient
          id="paint1_linear_40_3996"
          x1="32"
          y1="0"
          x2="0"
          y2="32"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0.1" stopColor="#0F62FE" />
          <stop offset="0.9" stopColor="#A56EFF" />
        </linearGradient>
      </defs>
    </svg>
  );
}
