import { User } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useAuth } from "@/contexts/auth-context";

interface UserMessageProps {
  content: string;
}

export function UserMessage({ content }: UserMessageProps) {
  const { user } = useAuth();

  return (
    <div className="flex gap-3">
      <Avatar className="w-8 h-8 flex-shrink-0 select-none">
        <AvatarImage draggable={false} src={user?.picture} alt={user?.name} />
        <AvatarFallback className="text-sm bg-primary/20 text-primary">
          {user?.name ? (
            user.name.charAt(0).toUpperCase()
          ) : (
            <User className="h-4 w-4" />
          )}
        </AvatarFallback>
      </Avatar>
      <div className="flex-1">
        <p className="text-foreground whitespace-pre-wrap break-words overflow-wrap-anywhere">
          {content}
        </p>
      </div>
    </div>
  );
}
