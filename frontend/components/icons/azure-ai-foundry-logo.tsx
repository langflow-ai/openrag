export default function AzureAIFoundryLogo(
  props: React.SVGProps<SVGSVGElement>,
) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      {...props}
    >
      <title>Azure AI Foundry Logo</title>
      <path
        d="M7.5 0.5L14.5 4.25V11.75L7.5 15.5L0.5 11.75V4.25L7.5 0.5Z"
        fill="#0078D4"
      />
      <path
        d="M7.5 3L11.75 5.375V10.125L7.5 12.5L3.25 10.125V5.375L7.5 3Z"
        fill="#50E6FF"
        fillOpacity="0.8"
      />
      <path
        d="M5.5 7.5L7 9L10 6"
        stroke="white"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
