import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/shell/Sidebar";
import Topbar from "@/components/shell/Topbar";

export const metadata: Metadata = {
  title: "TrustLens Research Studio",
  description: "Evidence-backed clinical research intelligence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Sidebar />
          <div className="main">
            <Topbar />
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
