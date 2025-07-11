import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Navigation } from "@/components/navigation";
import { ModeToggle } from "@/components/mode-toggle";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "GenDB",
  description: "Document search and management system",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <div className="h-full relative">
            <div className="hidden h-full md:flex md:w-72 md:flex-col md:fixed md:inset-y-0 z-[80] border-r border-border/40">
              <Navigation />
            </div>
            <main className="md:pl-72">
              <div className="flex flex-col min-h-screen">
                <header className="sticky top-0 z-40 w-full border-b border-border/40 bg-background">
                  <div className="container flex h-14 max-w-screen-2xl items-center">
                    <div className="mr-4 hidden md:flex">
                      <h1 className="text-lg font-semibold tracking-tight">
                        GenDB
                      </h1>
                    </div>
                    <div className="flex flex-1 items-center justify-between space-x-2 md:justify-end">
                      <div className="w-full flex-1 md:w-auto md:flex-none">
                        {/* Search component could go here */}
                      </div>
                      <nav className="flex items-center">
                        <ModeToggle />
                      </nav>
                    </div>
                  </div>
                </header>
                <div className="flex-1">
                  <div className="container py-6 lg:py-8">
                    {children}
                  </div>
                </div>
              </div>
            </main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
