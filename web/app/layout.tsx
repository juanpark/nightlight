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
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Returning visitor: show the loading screen (in their app theme) instead of the landing page before the first paint; AppGate clears this. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{if(localStorage.getItem("nl-session")){var d=document.documentElement.dataset,t=localStorage.getItem("nl_theme");d.session="1";d.theme=t==="day"||t==="night"?t:matchMedia("(prefers-color-scheme: dark)").matches?"night":"day"}}catch(e){}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
