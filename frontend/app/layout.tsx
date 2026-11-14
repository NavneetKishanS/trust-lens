import type { Metadata } from "next";
import { Lexend, Source_Sans_3 } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/shell/Sidebar";
import Topbar from "@/components/shell/Topbar";

// Lexend (headings) + Source Sans 3 (body): a readable, trustworthy pairing for healthcare tools.
// next/font self-hosts both, so there is no runtime request to Google.
const heading = Lexend({ subsets: ["latin"], variable: "--font-heading", display: "swap" });
const body = Source_Sans_3({ subsets: ["latin"], variable: "--font-body", display: "swap" });

export const metadata: Metadata = {
  title: "TrustLens Research Studio",
  description: "Evidence-backed clinical research intelligence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${heading.variable} ${body.variable}`}>
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <div className="shell">
          <Sidebar />
          <div className="main" id="main-content">
            <Topbar />
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
