import type { Metadata } from "next";
import { Chivo, IBM_Plex_Sans, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { LayoutWrapper } from "@/components/layout-wrapper";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/contexts/auth-context";
import { BrandProvider } from "@/contexts/brand-context";
import { ChatProvider } from "@/contexts/chat-context";
import { KnowledgeFilterProvider } from "@/contexts/knowledge-filter-context";
import { TaskProvider } from "@/contexts/task-context";
import Providers from "./providers";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

const chivo = Chivo({
  variable: "--font-chivo",
  subsets: ["latin"],
});

const ibmPlexSans = IBM_Plex_Sans({
  variable: "--font-ibm-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "OpenRAG",
  description: "Open source RAG (Retrieval Augmented Generation) system",
};
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} ${chivo.variable} ${ibmPlexSans.variable} antialiased overflow-hidden bg-white dark:bg-black`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <Providers>
            <TooltipProvider>
              <AuthProvider>
                <BrandProvider>
                  <TaskProvider>
                    <KnowledgeFilterProvider>
                      <ChatProvider>
                        <LayoutWrapper>{children}</LayoutWrapper>
                      </ChatProvider>
                    </KnowledgeFilterProvider>
                  </TaskProvider>
                </BrandProvider>
              </AuthProvider>
            </TooltipProvider>
          </Providers>
        </ThemeProvider>
        <Toaster />
      </body>
    </html>
  );
}
