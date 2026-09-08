/**
 * Azure OpenAI Service, as Microsoft draws it (az-icons.com/icon/azure-openai).
 *
 * Distinct from `ai-foundry-logo`: Microsoft draws the two Azure model services
 * differently. The gradient id is fixed rather than generated: every instance
 * defines the same stops, so when a page renders several of these and the
 * browser resolves `url(#...)` to the first one, they all paint identically.
 */
export default function AzureOpenAILogo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 18 18"
      fill="none"
      {...props}
    >
      <title>Azure OpenAI Logo</title>
      <defs>
        <radialGradient
          id="azure-openai-mark"
          cx="-67.981"
          cy="793.199"
          r=".45"
          gradientTransform="translate(-17939.03 20368.029) rotate(45) scale(25.091 -34.149)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#83b9f9" />
          <stop offset="1" stopColor="#0078d4" />
        </radialGradient>
      </defs>
      <path
        d="m0,2.7v12.6c0,1.491,1.209,2.7,2.7,2.7h12.6c1.491,0,2.7-1.209,2.7-2.7V2.7c0-1.491-1.209-2.7-2.7-2.7H2.7C1.209,0,0,1.209,0,2.7ZM10.8,0v3.6c0,3.976,3.224,7.2,7.2,7.2h-3.6c-3.976,0-7.199,3.222-7.2,7.198v-3.598c0-3.976-3.224-7.2-7.2-7.2h3.6c3.976,0,7.2-3.224,7.2-7.2Z"
        fill="url(#azure-openai-mark)"
        strokeWidth="0"
      />
    </svg>
  );
}
