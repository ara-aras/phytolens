import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PhytoLens — research shortlist",
  description:
    "In-silico prioritisation for herbal formulations. Hypotheses for laboratory validation only.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
