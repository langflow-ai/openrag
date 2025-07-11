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
          <div className="min-h-screen bg-background flex">
            <Navigation />
            <div className="flex-1 flex flex-col min-h-screen">
              <header className="w-full py-6 border-b flex items-center justify-center relative">
                <h1 className="text-3xl font-bold text-primary mx-auto">GenDB</h1>
                <div className="absolute right-8 top-1/2 -translate-y-1/2">
                  <ModeToggle />
                </div>
              </header>
              <main className="flex-1 container mx-auto px-4 py-8 flex flex-col items-center justify-center">
                {children}
              </main>
            </div>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
