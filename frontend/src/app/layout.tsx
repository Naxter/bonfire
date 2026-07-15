import type { Metadata } from "next";
import { Inter, Manrope } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { AppShell } from "@/components/shell/AppShell";
import { DataProvider, FiltersProvider, JobsProvider } from "@/lib/app-state";
import { I18nProvider } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope" });

export const metadata: Metadata = {
  title: "Bonfire",
  description: "Self-hosted analytics for your grocery receipts.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={cn(
          "min-h-screen bg-background font-sans antialiased app-grid-bg",
          inter.variable,
          manrope.variable
        )}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          themes={["light", "dark", "hc"]}
          enableSystem
          disableTransitionOnChange
        >
          <I18nProvider>
            <DataProvider>
              <JobsProvider>
                <FiltersProvider>
                  <AppShell>{children}</AppShell>
                  <Toaster position="bottom-right" richColors />
                </FiltersProvider>
              </JobsProvider>
            </DataProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
