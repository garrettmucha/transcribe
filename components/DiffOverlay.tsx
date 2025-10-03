'use client';

import { Dialog, Transition } from '@headlessui/react';
import { Fragment } from 'react';

export interface DiffEntry {
  id: string;
  original: string;
  updated: string;
}

export function DiffOverlay({
  open,
  onClose,
  summary,
  diffs
}: {
  open: boolean;
  onClose: () => void;
  summary: string;
  diffs: DiffEntry[];
}) {
  return (
    <Transition show={open} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child as={Fragment} enter="ease-out duration-200" enterFrom="opacity-0" enterTo="opacity-100">
          <div className="fixed inset-0 bg-slate-900/40" />
        </Transition.Child>
        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-6 text-sm">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-200"
              enterFrom="translate-y-6 opacity-0"
              enterTo="translate-y-0 opacity-100"
            >
              <Dialog.Panel className="w-full max-w-4xl rounded-xl bg-white p-6 shadow-xl">
                <div className="flex items-start justify-between">
                  <Dialog.Title className="text-lg font-semibold text-slate-900">Tailored changes</Dialog.Title>
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-md border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:border-accent hover:text-accent"
                  >
                    Close
                  </button>
                </div>
                <p className="mt-2 text-xs text-slate-500">{summary}</p>
                {diffs.length > 0 ? (
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    {diffs.map((diff) => (
                      <div key={diff.id} className="rounded-lg border border-slate-200 p-4">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{diff.id}</h4>
                        <div className="mt-2 space-y-2">
                          <div>
                            <p className="text-[11px] font-semibold text-slate-500">Original</p>
                            <p className="whitespace-pre-line text-sm text-slate-600">{diff.original}</p>
                          </div>
                          <div>
                            <p className="text-[11px] font-semibold text-accent">Tailored</p>
                            <p className="whitespace-pre-line text-sm text-slate-900">{diff.updated}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 rounded-md border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                    No diff to show—either you hit the free limit or the AI response matched your current resume.
                  </p>
                )}
                <div className="mt-6 flex justify-end">
                  <button
                    type="button"
                    onClick={onClose}
                    className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-accent-700"
                  >
                    Apply changes
                  </button>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}
