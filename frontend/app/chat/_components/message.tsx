import { ReactNode } from "react";

interface MessageProps {
  icon: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  isAssistant?: boolean;
}

export function Message({
  icon,
  children,
  actions,
  isAssistant,
}: MessageProps) {
  return (
    <div className="flex gap-3">
      {icon}
      <div
        className={isAssistant ? "px-5 py-4 bg-secondary/20 rounded-2xl" : ""}
      >
        <div className="flex-1 min-w-0">{children}</div>
        {actions && <div className="flex-shrink-0 ml-2">{actions}</div>}
      </div>
    </div>
  );
}
