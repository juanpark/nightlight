import { Archivo } from "next/font/google";

// One family for the whole night page: Archivo's width axis gives the tall
// condensed capitals for display and the normal width for small Swiss UI type.
export const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-archivo",
  display: "swap",
});
