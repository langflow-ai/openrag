"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Search, Settings } from "lucide-react"
import { cn } from "@/lib/utils"

export function Navigation() {
  const pathname = usePathname()

  const routes = [
    {
      label: "Search",
      icon: Search,
      href: "/",
      active: pathname === "/",
    },
    {
      label: "Admin",
      icon: Settings,
      href: "/admin",
      active: pathname === "/admin",
    },
  ]

  return (
    <div className="space-y-4 py-4 flex flex-col h-full bg-card">
      <div className="px-3 py-2 flex-1">
        <Link href="/" className="flex items-center pl-3 mb-8">
          <h1 className="text-2xl font-bold tracking-tight">
            GenDB
          </h1>
        </Link>
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