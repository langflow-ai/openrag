import { cn } from "@/lib/utils";

interface CardIconProps {
  isActive: boolean;
  activeBgColor: string;
  children: React.ReactNode;
}

export default function CardIcon({
  isActive,
  activeBgColor,
  children,
}: CardIconProps) {
  return (
    <div
      className={cn(
        "w-8 h-8 rounded flex items-center justify-center border",
        isActive
          ? activeBgColor
          : "bg-muted grayscale group-hover:bg-background",
      )}
    >
      {children}
    </div>
  );
}
