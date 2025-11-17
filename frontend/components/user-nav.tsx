"use client";

import { ChevronsUpDown, LogOut, Moon, Sun, User } from "lucide-react";
import { useTheme } from "next-themes";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/contexts/auth-context";
import ThemeButtons from "./theme-switcher-buttons";

export function UserNav() {
  const { user, isLoading, isAuthenticated, isNoAuthMode, login, logout } =
    useAuth();
  const { theme, setTheme } = useTheme();

  if (isLoading) {
    return <div className="h-8 w-8 rounded-full bg-muted animate-pulse" />;
  }

  // In no-auth mode, show a simple theme switcher instead of auth UI
  if (isNoAuthMode) {
    return (
      <button
        type="button"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        className="flex justify-center items-center gap-2 h-8 w-8 mr-2 rounded-md  hover:bg-muted rounded-lg "
      >
        {theme === "dark" ? (
          <Sun size={16} className="text-muted-foreground" />
        ) : (
          <Moon size={16} className="text-muted-foreground" />
        )}
      </button>
    );
  }

  if (!isAuthenticated) {
    return (
      <button
        type="button"
        onClick={login}
        className="flex items-center gap-2 h-7 px-3 mr-2 rounded-md bg-primary hover:bg-primary/90 text-primary-foreground text-[13px] line-height-[16px]"
      >
        Sign In
      </button>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="hover:bg-accent rounded-lg pl-[4px] p-[3px] flex items-center justify-center"
        >
          <Avatar className="rounded-md w-7 h-7">
            <AvatarImage
              width={16}
              height={16}
              src={user?.picture}
              alt={user?.name}
              className="rounded-md"
            />
            <AvatarFallback className="text-xs rounded-md">
              {user?.name ? (
                user.name.charAt(0).toUpperCase()
              ) : (
                <User className="h-3 w-3" />
              )}
            </AvatarFallback>
          </Avatar>
          <ChevronsUpDown size={16} className="text-muted-foreground mx-2" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56 p-0" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-2 px-1 py-1">
            <p className="text-sm font-medium leading-none">{user?.name}</p>
            <p className="text-xs leading-none text-muted-foreground">
              {user?.email}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator className="m-0" />
        <div className="flex items-center justify-between pl-3 pr-2 h-9">
          <span className="text-sm">Theme</span>
          <ThemeButtons />
        </div>
        <DropdownMenuSeparator className="m-0" />
        <button
          type="button"
          onClick={logout}
          className="flex items-center hover:bg-muted w-full h-9 px-3"
        >
          <LogOut className="mr-2 h-4 w-4 text-muted-foreground" />
          <span className="text-sm">Logout</span>
        </button>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
