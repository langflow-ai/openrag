/**
 * Azure AI Foundry, as Microsoft draws it (az-icons.com/icon/ai-foundry).
 *
 * Distinct from `azure-openai-logo`: Microsoft draws the two Azure model
 * services differently. Gradient ids are fixed rather than generated: every
 * instance defines the
 * same stops, so when several render on one page and the browser resolves
 * `url(#...)` to the first match, they all paint identically.
 */
export default function AiFoundryLogo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 18 18"
      fill="none"
      {...props}
    >
      <title>Azure AI Foundry Logo</title>
      <defs>
        <linearGradient
          id="ai-foundry-flame-base"
          x1="10.91"
          x2="13.62"
          y1="13.66"
          y2="13.66"
          gradientTransform="matrix(1 0 0 -1 0 20)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#302ec9" />
          <stop offset=".12" stopColor="#151698" />
          <stop offset=".25" stopColor="#0a0b7e" />
          <stop offset=".43" stopColor="#090c7f" />
          <stop offset=".51" stopColor="#141698" />
          <stop offset=".61" stopColor="#282ac4" />
          <stop offset=".77" stopColor="#8e8ff4" />
          <stop offset=".85" stopColor="#a7a6f7" />
          <stop offset=".91" stopColor="#cacafb" />
          <stop offset="1" stopColor="#fff" />
        </linearGradient>
        <linearGradient
          id="ai-foundry-flame-overlay"
          x1="12.26"
          x2="12.26"
          y1="8.32"
          y2="18.23"
          gradientTransform="matrix(1 0 0 -1 0 20)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset=".02" stopColor="#201ba6" />
          <stop offset=".64" stopColor="#2d29c7" />
          <stop offset="1" stopColor="#201ba6" />
        </linearGradient>
        <linearGradient
          id="ai-foundry-crucible"
          x1="14.19"
          x2="14.19"
          y1="8.27"
          y2="14.47"
          gradientTransform="matrix(1 0 0 -1 0 20)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#3530c3" />
          <stop offset=".5" stopColor="#6d71d1" />
          <stop offset=".97" stopColor="#c0bff5" />
          <stop offset="1" stopColor="#e3e4ff" />
        </linearGradient>
        <linearGradient
          id="ai-foundry-body"
          x1="6.51"
          x2="6.51"
          y1="3"
          y2="19.15"
          gradientTransform="matrix(1 0 0 -1 0 20)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#302ec9" />
          <stop offset=".45" stopColor="#302ec9" />
          <stop offset=".95" stopColor="#cacafb" />
          <stop offset="1" stopColor="#7f7eaf" />
        </linearGradient>
      </defs>
      <path
        fill="url(#ai-foundry-flame-base)"
        d="M11.96 11.68s.07-.1.07-.24V7.57c0-.85.66-1.76 1.59-2.03-.06-.19-.64-2.11-.81-2.65-.17-.56-.67-1.9-1.29-1.9h-.01s-.09.05-.13.13c-.32.58-.46 3.02-.46 4.84v2.26c.27.97.91 3.22.96 3.35 0 0 .05.1.09.1Z"
      />
      <path
        fill="url(#ai-foundry-flame-overlay)"
        d="M11.96 11.68s.07-.1.07-.24V7.57c0-.85.66-1.76 1.59-2.03-.06-.19-.64-2.11-.81-2.65-.17-.56-.67-1.9-1.29-1.9h-.01s-.09.05-.13.13c-.32.58-.46 3.02-.46 4.84v2.26c.27.97.91 3.22.96 3.35 0 0 .05.1.09.1Z"
      />
      <path
        fill="url(#ai-foundry-crucible)"
        d="M16.01 5.46H14.2c-1.21 0-2.17 1.09-2.17 2.11v3.87c0 .14-.04.24-.07.24s-.09-.1-.09-.1.07.21.17.21h1.98c.62 0 2.48-.61 2.48-2.52V6.02c0-.41-.24-.55-.49-.55Z"
      />
      <path
        fill="url(#ai-foundry-body)"
        d="M2.34 17h5.38c2.35 0 3.2-2.03 3.2-3.81V5.96c0-2.08.19-4.97.61-4.97H8.3c-.77 0-1.43.82-2.18 2.48S1.76 15.34 1.6 15.83c-.26.79-.02 1.16.74 1.16Z"
      />
    </svg>
  );
}
