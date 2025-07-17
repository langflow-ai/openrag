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
            <header className="sticky top-0 z-50 w-full border-b border-border/40 bg-background">
              <div className="flex h-14 items-center px-4">
                <div className="flex items-center">
                  <h1 className="text-lg font-semibold tracking-tight text-white">
                    GenDB
                  </h1>
                </div>
                <div className="flex flex-1 items-center justify-end space-x-2">
                  <nav className="flex items-center">
                    <ModeToggle />
                  </nav>
                </div>
              </div>
            </header>
            <div className="hidden md:flex md:w-72 md:flex-col md:fixed md:top-14 md:bottom-0 md:left-0 z-[80] border-r border-border/40">
              <Navigation />
            </div>
            <main className="md:pl-72">
              <div className="flex flex-col h-[calc(100vh-3.6rem)]">
                <div className="flex-1 overflow-y-auto">
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
