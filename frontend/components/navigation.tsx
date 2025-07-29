"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Search, Settings, MessageCircle, PlugZap } from "lucide-react"
import { cn } from "@/lib/utils"

export function Navigation() {
  const pathname = usePathname()

  const routes = [
    {
      label: "Ingest",
      icon: Settings,
      href: "/admin",
      active: pathname === "/admin",
    },
    {
      label: "Search",
      icon: Search,
      href: "/",
      active: pathname === "/",
    },
    {
      label: "Chat",
      icon: MessageCircle,
      href: "/chat",
      active: pathname === "/chat",
    },
    {
      label: "Connectors",
      icon: PlugZap,
      href: "/connectors",
      active: pathname.startsWith("/connectors"),
    },
  ]

  return (
    <div className="space-y-4 py-4 flex flex-col h-full bg-card">
      <div className="px-3 py-2 flex-1">
        <div className="space-y-1">
          {routes.map((route) => (
            <Link
              key={route.href}
              href={route.href}
              className={cn(
                "text-sm group flex p-3 w-full justify-start font-medium cursor-pointer hover:bg-accent hover:text-accent-foreground rounded-lg transition-all",
                route.active 
                  ? "bg-accent text-accent-foreground shadow-sm" 
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <div className="flex items-center flex-1">
                <route.icon className={cn("h-4 w-4 mr-3 shrink-0", route.active ? "text-accent-foreground" : "text-muted-foreground group-hover:text-foreground")} />
                {route.label}
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}