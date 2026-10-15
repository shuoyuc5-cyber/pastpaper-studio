import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PastPaper Studio — 真题学习工作台",
  description: "在本地整理、浏览和配对 Cambridge 真题。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
