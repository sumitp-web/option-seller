import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "Option Seller", description: "Live option-selling positions and risk" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
