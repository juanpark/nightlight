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
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Returning visitor: show the loading screen (in their app theme) instead of the landing page before the first paint; AppGate clears this. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{if(localStorage.getItem("nl-session")){var d=document.documentElement.dataset,t=localStorage.getItem("nl_theme");d.session="1";d.theme=t==="night"?"night":"day"}}catch(e){}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
