import { ReactNode } from "react";

interface MessageProps {
  icon: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}

export function Message({ icon, children, actions }: MessageProps) {
  return (
    <div className="flex gap-3">
      {icon}
      <div className="flex-1 min-w-0">{children}</div>
      {actions && <div className="flex-shrink-0 ml-2">{actions}</div>}
    </div>
  );
}
