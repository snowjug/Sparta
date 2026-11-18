import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import "./globals.css";
import { Providers } from "@/components/providers";
import { AppShell } from "@/components/shell/app-shell";

// A nonce-based Content-Security-Policy needs every page rendered per request (src/proxy.ts). The app is client-rendered and
// authenticated, so there is nothing worth statically caching.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: "Sparta · Your calls. Your voice. Your shield.", template: "%s · Sparta" },
  description:
    "Sparta is a multilingual AI call-screening assistant: it introduces itself as an AI, finds out who is calling and why, refuses protected information, and tells you what matters.",
  applicationName: "Sparta",
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0c0d0f" },
    { media: "(prefers-color-scheme: light)", color: "#f4f2ed" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // src/proxy.ts creates a fresh CSP nonce per request; Next.js stamps it on its own scripts, and we stamp it on ours.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    // data-theme is written by /theme-init.js before first paint, so the attribute differs between server and client.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Intentionally a blocking same-origin script: it sets data-theme before first paint (no flash) and never needs an inline script. */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/theme-init.js" nonce={nonce} />
      </head>
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
