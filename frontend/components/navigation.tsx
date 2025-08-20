"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Library, Database, MessageSquare, Settings2 } from "lucide-react"
import { cn } from "@/lib/utils"

export function Navigation() {
  const pathname = usePathname()

  const routes = [
    {
      label: "Chat",
      icon: MessageSquare,
      href: "/chat",
      active: pathname === "/" || pathname === "/chat",
    },
    {
      label: "Knowledge",
      icon: Library,
      href: "/search",
      active: pathname === "/search",
    },
    {
      label: "Settings",
      icon: Settings2,
      href: "/knowledge-sources",
      active: pathname === "/knowledge-sources",
    },
  ]

  return (
    <div className="space-y-4 py-4 flex flex-col h-full bg-background">
      <div className="px-3 py-2 flex-1">
        <div className="space-y-1">
          {routes.map((route, index) => (
            <div key={route.href}>
              <Link
                href={route.href}
                className={cn(
                  "text-sm group flex p-3 w-full justify-start font-medium cursor-pointer hover:bg-accent hover:text-accent-foreground rounded-lg transition-all",
                  route.active 
                    ? "bg-accent text-accent-foreground shadow-sm" 
                    : "text-foreground hover:text-accent-foreground",
                )}
              >
                <div className="flex items-center flex-1">
                  <route.icon className={cn("h-4 w-4 mr-3 shrink-0", route.active ? "text-accent-foreground" : "text-muted-foreground group-hover:text-foreground")} />
                  {route.label}
                </div>
              </Link>
              {route.label === "Settings" && (
                <div className="mx-3 my-2 border-t border-border/40" />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}