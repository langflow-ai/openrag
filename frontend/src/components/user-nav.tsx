"use client"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useAuth } from "@/contexts/auth-context"
import { LogIn, LogOut, User, Moon, Sun, ChevronsUpDown } from "lucide-react"
import { useTheme } from "next-themes"

export function UserNav() {
  const { user, isLoading, isAuthenticated, isNoAuthMode, login, logout } = useAuth()
  const { theme, setTheme } = useTheme()

  if (isLoading) {
    return (
      <div className="h-8 w-8 rounded-full bg-muted animate-pulse" />
    )
  }

  // In no-auth mode, show a simple theme switcher instead of auth UI
  if (isNoAuthMode) {
    return (
      <Button 
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        variant="outline" 
        size="sm"
        className="flex items-center gap-2"
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>
    )
  }

  if (!isAuthenticated) {
    return (
      <Button 
        onClick={login} 
        variant="outline" 
        size="sm"
        className="flex items-center gap-2"
      >
        <LogIn className="h-4 w-4" />
        Sign In
      </Button>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="flex items-center gap-1 h-8 px-1 rounded-full">
          <Avatar className="h-6 w-6">
            <AvatarImage src={user?.picture} alt={user?.name} />
            <AvatarFallback className="text-xs">
              {user?.name ? user.name.charAt(0).toUpperCase() : <User className="h-3 w-3" />}
            </AvatarFallback>
          </Avatar>
          <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="end" forceMount>
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col space-y-1">
            <p className="text-sm font-medium leading-none">{user?.name}</p>
            <p className="text-xs leading-none text-muted-foreground">
              {user?.email}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
          {theme === "light" ? (
            <Moon className="mr-2 h-4 w-4" />
          ) : (
            <Sun className="mr-2 h-4 w-4" />
          )}
          <span>Toggle Theme</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={logout} className="text-red-600 focus:text-red-600">
          <LogOut className="mr-2 h-4 w-4" />
          <span>Log out</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
} 