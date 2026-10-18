import "./globals.css";
import "./needs.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "Nightlight: Go to sleep. It's got this.",
  description: "An agent for the machines you run. Nightlight watches, explains issues in plain words, and gets things fixed.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
