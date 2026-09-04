/**
 * Azure OpenAI Service, as Microsoft draws it (az-icons.com/icon/azure-openai).
 *
 * Distinct from `ai-foundry-logo`: Microsoft draws the two Azure model services
 * differently. Painted with `currentColor`, like `anthropic-logo`/`openai-logo`,
 * so it can go from grayscale to full color by changing the parent's text color.
 */
export default function AzureOpenAILogo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      {...props}
    >
      <title>Azure OpenAI Logo</title>
      <path
        d="M0 2.4V13.6C0 14.9253 1.07467 16 2.4 16H13.6C14.9253 16 16 14.9253 16 13.6V2.4C16 1.07467 14.9253 0 13.6 0H2.4C1.07467 0 0 1.07467 0 2.4ZM9.6 0V3.2C9.6 6.73422 12.4658 9.6 16 9.6H12.8C9.26578 9.6 6.40089 12.464 6.4 15.9982V12.8C6.4 9.26578 3.53422 6.4 0 6.4H3.2C6.73422 6.4 9.6 3.53422 9.6 0Z"
        fill="currentColor"
      />
    </svg>
  );
}
