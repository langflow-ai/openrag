import type { ConnectorIconProps } from "@/lib/connectors/types";

export default function DropboxLogo({ className }: ConnectorIconProps) {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path d="M9.4 3.8 1.6 8.9l7.8 5.1 7.8-5.1-7.8-5.1Z" fill="#0061FF" />
      <path d="m22.6 3.8 7.8 5.1-7.8 5.1-7.8-5.1 7.8-5.1Z" fill="#0061FF" />
      <path d="m9.4 15.9-7.8 5.1 7.8 5.2 7.8-5.2-7.8-5.1Z" fill="#0061FF" />
      <path d="m22.6 15.9 7.8 5.1-7.8 5.2-7.8-5.2 7.8-5.1Z" fill="#0061FF" />
      <path d="M16 22.7 9.4 27l6.6 4.2 6.6-4.2-6.6-4.3Z" fill="#0061FF" />
    </svg>
  );
}
