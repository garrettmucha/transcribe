'use client';

import { useCallback, useEffect, useState } from 'react';
import { Header } from './Header';
import { Form } from './Form';
import { Preview, ResumeFormValues } from './Preview';
import type { DiffEntry } from './DiffOverlay';
import type { ResumeData } from '@/types';

interface Props {
  initialData: ResumeData;
  aiGenerationsUsed: number;
  aiLimit: number;
  signedIn: boolean;
}

export function MainShell({ initialData, aiGenerationsUsed, aiLimit, signedIn }: Props) {
  const [data, setData] = useState<ResumeData>(initialData);
  const [usage, setUsage] = useState(aiGenerationsUsed);

  useEffect(() => {
    setData(initialData);
  }, [initialData]);

  useEffect(() => {
    setUsage(aiGenerationsUsed);
  }, [aiGenerationsUsed]);

  const handleChange = useCallback((values: ResumeFormValues) => {
    setData(values);
  }, []);

  const handleTailored = useCallback(
    (payload: { summary: string; diffs: DiffEntry[]; updated: ResumeData }) => {
      setData(payload.updated);
      setUsage((prev) => Math.min(aiLimit, prev + 1));
    },
    [aiLimit]
  );

  return (
    <div className="flex h-screen flex-col bg-white">
      <Header signedIn={signedIn} />
      <main className="flex flex-1 flex-col gap-6 px-6 pb-6 pt-4 lg:flex-row">
        <div className="flex-1 lg:max-w-lg">
          <Form
            initialValues={initialData}
            aiGenerationsUsed={usage}
            aiLimit={aiLimit}
            onChange={handleChange}
            onTailored={handleTailored}
          />
        </div>
        <div className="flex-1">
          <Preview data={data} />
          <div className="mt-4 flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">Export PDF</h3>
              <p className="text-xs text-slate-500">Generate pixel-perfect PDFs with Playwright—no limits in the free launch.</p>
            </div>
            <form action="/api/pdf/export" method="post">
              <button
                type="submit"
                className="rounded-md bg-white px-4 py-2 text-sm font-semibold text-accent shadow-sm ring-1 ring-inset ring-accent/30 transition hover:bg-accent hover:text-white"
              >
                Export PDF
              </button>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
}
