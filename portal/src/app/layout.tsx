import type { Metadata } from "next";

import Nav from "@/components/Nav";
import Footer from "@/components/Footer";
import { SITE_NAME, SITE_TAGLINE } from "@/lib/constants";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: `${SITE_NAME} - preliminary ADU, JADU, and SB 9 feasibility`,
    template: `%s - ${SITE_NAME}`,
  },
  description: SITE_TAGLINE,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="flex min-h-screen flex-col">
        <Nav />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
