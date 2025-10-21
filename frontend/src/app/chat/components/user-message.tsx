import { User } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useAuth } from "@/contexts/auth-context";
import { cn } from "@/lib/utils";
import { Message } from "./message";

interface UserMessageProps {
	content: string;
	isCompleted?: boolean;
}

export function UserMessage({ content, isCompleted }: UserMessageProps) {
	const { user } = useAuth();

	return (
		<Message
			icon={
				<Avatar className="w-8 h-8 rounded-lg flex-shrink-0 select-none">
					<AvatarImage draggable={false} src={user?.picture} alt={user?.name} />
					<AvatarFallback
						className={cn(
							isCompleted ? "text-placeholder-foreground" : "text-primary",
							"text-sm bg-accent/20 rounded-lg",
						)}
					>
						{user?.name ? user.name.charAt(0).toUpperCase() : <User className="h-4 w-4" />}
					</AvatarFallback>
				</Avatar>
			}
		>
			<p
				className={cn(
					"text-foreground text-sm py-1.5 whitespace-pre-wrap break-words overflow-wrap-anywhere",
					isCompleted ? "text-placeholder-foreground" : "text-foreground",
				)}
			>
				{content}
			</p>
		</Message>
	);
}
