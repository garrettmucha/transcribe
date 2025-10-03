import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'AI Resume on Akash',
  description: 'Generate ATS-optimized resumes tailored to your dream role.'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="bg-white">
      <body className={`${inter.className} min-h-screen bg-white text-slate-900`}>{children}</body>
    </html>
  );
}
