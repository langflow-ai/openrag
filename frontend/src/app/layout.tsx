import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Chivo } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthProvider } from "@/contexts/auth-context";
import { TaskProvider } from "@/contexts/task-context";
import { KnowledgeFilterProvider } from "@/contexts/knowledge-filter-context";
import { LayoutWrapper } from "@/components/layout-wrapper";
import { Toaster } from "@/components/ui/sonner";

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
          <AuthProvider>
            <TaskProvider>
              <KnowledgeFilterProvider>
                <LayoutWrapper>
                  {children}
                </LayoutWrapper>
              </KnowledgeFilterProvider>
            </TaskProvider>
          </AuthProvider>
        </ThemeProvider>
        <Toaster />
      </body>
    </html>
  );
}
