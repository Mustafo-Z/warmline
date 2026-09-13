import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Warmline — policy layer for AI outbound calling",
  description:
    "A call is placed only if every check passes, and everything the agent says is checked afterwards. Technical demo: fictional data, no calls placed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
