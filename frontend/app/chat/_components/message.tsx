import { ReactNode } from "react";

interface MessageProps {
  icon: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  isAssistant?: boolean;
  unstyledContent?: boolean;
}

export function Message({
  icon,
  children,
  actions,
  isAssistant,
  unstyledContent = false,
}: MessageProps) {
  return (
    <div className="flex gap-3">
      {icon}
      <div
        className={
          isAssistant && !unstyledContent
            ? "px-5 py-4 bg-secondary/20 rounded-2xl flex-1"
            : "flex-1"
        }
      >
        <div className="flex-1 min-w-0">{children}</div>
        {actions && <div className="flex-shrink-0 ml-2">{actions}</div>}
      </div>
    </div>
  );
}
