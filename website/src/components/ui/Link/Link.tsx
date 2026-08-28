// Dependencies
import BaseLink from "next/link";
import { PropsWithChildren } from "react";

// Components
import Text from "@/components/ui/Text";

type Props = PropsWithChildren & {
  href: string;
  className?: string;
  target?: string;
};

const Link = ({ href, children, className, target = "_blank" }: Props) => (
  <BaseLink href={href} className={className} target={target}>
    <Text tagName="span" size={300}>
      {children}
    </Text>
  </BaseLink>
);

export default Link;
