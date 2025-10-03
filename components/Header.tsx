'use client';

import Link from 'next/link';
import { useState } from 'react';
import { PricingDrawer } from './PricingDrawer';

export function Header({ signedIn }: { signedIn: boolean }) {
  const [open, setOpen] = useState(false);

  return (
    <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
      <div className="flex items-center gap-2">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent text-white font-semibold">AI</div>
        <div>
          <p className="text-sm font-semibold">Akash Resume Studio</p>
          <p className="text-xs text-slate-500">Craft laser-focused resumes in minutes.</p>
        </div>
      </div>
      <nav className="flex items-center gap-4 text-sm">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-md px-3 py-2 font-medium text-slate-600 transition hover:text-accent"
        >
          Pricing
        </button>
        <Link
          href={signedIn ? '/api/auth/signout' : '/api/auth/signin'}
          className="rounded-md border border-slate-200 px-3 py-2 font-medium text-slate-700 transition hover:border-accent hover:text-accent"
        >
          {signedIn ? 'Sign out' : 'Sign in'}
        </Link>
      </nav>
      <PricingDrawer open={open} onClose={() => setOpen(false)} />
    </header>
  );
}
