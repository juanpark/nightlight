import "./globals.css";
import "./needs.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: "Nightlight",
  description: "A house-sitter for your home and small-office servers.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
