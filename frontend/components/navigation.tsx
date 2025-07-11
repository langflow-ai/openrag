"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Search, Settings } from "lucide-react"

export function Navigation() {
  const pathname = usePathname()

  return (
    <aside className="h-screen w-56 bg-card border-r flex flex-col items-center py-8 gap-4">
      <nav className="flex flex-col gap-2 w-full px-4">
        <Button
          variant={pathname === "/" ? "default" : "ghost"}
          size="sm"
          asChild
          className="justify-start w-full"
        >
          <Link href="/">
            <Search className="h-4 w-4 mr-2" />
            Search
          </Link>
        </Button>
        <Button
          variant={pathname === "/admin" ? "default" : "ghost"}
          size="sm"
          asChild
          className="justify-start w-full"
        >
          <Link href="/admin">
            <Settings className="h-4 w-4 mr-2" />
            Admin
          </Link>
        </Button>
      </nav>
    </aside>
  )
}