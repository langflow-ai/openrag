"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { ModeToggle } from "@/components/mode-toggle"
import { Search, Settings } from "lucide-react"

export function Navigation() {
  const pathname = usePathname()

  return (
    <nav className="border-b bg-card">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          <div className="flex items-center space-x-8">
            <Link href="/" className="text-2xl font-bold text-primary">
              GenDB
            </Link>
            <div className="flex items-center space-x-4">
              <Button
                variant={pathname === "/" ? "default" : "ghost"}
                size="sm"
                asChild
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
              >
                <Link href="/admin">
                  <Settings className="h-4 w-4 mr-2" />
                  Admin
                </Link>
              </Button>
            </div>
          </div>
          <ModeToggle />
        </div>
      </div>
    </nav>
  )
}