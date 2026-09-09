import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Warmline",
  description: "Policy layer for an outbound AI voice agent. This build places no calls.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
