import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import { DESCRIPTION, REPO_URL, SITE_URL, TAGLINE } from "../lib/site";
import "./globals.css";

// Self-hosted by next/font.
const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: {
    template: "%s | Zipy",
    default: `Zipy – ${TAGLINE}`,
  },
  description: DESCRIPTION,
  keywords: [
    "adaptive agent harness",
    "per-person adaptation",
    "agent runtime",
    "team operations",
    "tool calling",
    "student organizations",
    "Discord",
    "Slack",
    "Notion",
    "Google Calendar",
    "self-hosted",
    "open source",
  ],
  authors: [{ name: "ashworks1706", url: REPO_URL }],
  creator: "ashworks1706",
  robots: { index: true, follow: true },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: SITE_URL,
    title: `Zipy – ${TAGLINE}`,
    description: DESCRIPTION,
    siteName: "Zipy",
    images: [{ url: "/zipy.png", width: 1727, height: 864, alt: "Zipy" }],
  },
  twitter: {
    card: "summary_large_image",
    title: `Zipy – ${TAGLINE}`,
    description: DESCRIPTION,
    images: ["/zipy.png"],
  },
  metadataBase: new URL(SITE_URL),
  alternates: { canonical: "/" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // Hydration warnings are suppressed on the html element only.
    <html
      lang="en"
      className={`dark ${mono.variable}`}
      suppressHydrationWarning
    >
      <body className="antialiased">{children}</body>
    </html>
  );
}
