import { Funnel_Display, Funnel_Sans } from "next/font/google";

// The wordmark is Funnel Display; the page sets its headlines in it too, and
// everything else in its sister face.
export const display = Funnel_Display({ subsets: ["latin"], variable: "--font-display", display: "swap" });
export const sans = Funnel_Sans({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
