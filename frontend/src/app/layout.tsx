import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Chivo } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthProvider } from "@/contexts/auth-context";
import { TaskProvider } from "@/contexts/task-context";
import { KnowledgeFilterProvider } from "@/contexts/knowledge-filter-context";
import { ChatProvider } from "@/contexts/chat-context";
import { LayoutWrapper } from "@/components/layout-wrapper";
import { Toaster } from "@/components/ui/sonner";
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
        className={`${inter.variable} ${jetbrainsMono.variable} ${chivo.variable} antialiased`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <Providers>
            <AuthProvider>
              <TaskProvider>
                <KnowledgeFilterProvider>
                  <ChatProvider>
                    <LayoutWrapper>{children}</LayoutWrapper>
                  </ChatProvider>
                </KnowledgeFilterProvider>
              </TaskProvider>
            </AuthProvider>
          </Providers>
        </ThemeProvider>
        <Toaster />
      </body>
    </html>
  );
}
