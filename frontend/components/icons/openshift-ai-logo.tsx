export default function OpenShiftAILogo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      {...props}
    >
      <title>Red Hat OpenShift AI</title>
      {/* The OpenShift mark: a hexagonal ring around a solid core. Drawn with
          evenodd so the ring reads as a ring at 16px rather than filling in. */}
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 1.5 2.9 6.75v10.5L12 22.5l9.1-5.25V6.75L12 1.5Zm0 2.31 7.1 4.1v8.18l-7.1 4.1-7.1-4.1V7.91l7.1-4.1Z"
      />
      <circle cx="12" cy="12" r="3.35" />
    </svg>
  );
}
