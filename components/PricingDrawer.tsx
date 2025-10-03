'use client';

import { Dialog, Transition } from '@headlessui/react';
import { Fragment } from 'react';
import { BILLING_ENABLED, PLANS } from '@/lib/pricing';

export function PricingDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Transition show={open} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-slate-900/40" />
        </Transition.Child>
        <div className="fixed inset-0 overflow-hidden">
          <div className="absolute inset-y-0 right-0 flex max-w-full pl-10">
            <Transition.Child
              as={Fragment}
              enter="transform transition ease-in-out duration-300"
              enterFrom="translate-x-full"
              enterTo="translate-x-0"
              leave="transform transition ease-in-out duration-200"
              leaveFrom="translate-x-0"
              leaveTo="translate-x-full"
            >
              <Dialog.Panel className="pointer-events-auto w-screen max-w-md bg-white shadow-xl">
                <div className="flex h-full flex-col divide-y divide-slate-200">
                  <div className="flex items-center justify-between px-6 py-4">
                    <Dialog.Title className="text-lg font-semibold">Pricing</Dialog.Title>
                    <button
                      type="button"
                      onClick={onClose}
                      className="rounded-full border border-slate-200 px-3 py-1 text-sm text-slate-600 hover:border-accent hover:text-accent"
                    >
                      Close
                    </button>
                  </div>
                  <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6 text-sm">
                    <p className="text-slate-600">
                      Launching free on Akash. Upgrade plans are in the works—Stripe checkout is wired but inactive until we flip the
                      switch.
                    </p>
                    <div className="space-y-4">
                      {Object.values(PLANS).map((plan) => (
                        <div key={plan.id} className="rounded-lg border border-slate-200 p-4 shadow-sm">
                          <div className="flex items-start justify-between">
                            <div>
                              <h3 className="text-base font-semibold text-slate-900">{plan.name}</h3>
                              <p className="text-xs text-slate-500">{plan.description}</p>
                            </div>
                            <span className="text-sm font-medium text-accent">{plan.price}</span>
                          </div>
                          <button
                            type="button"
                            disabled={!BILLING_ENABLED || plan.id !== 'one_time'}
                            className="mt-4 w-full rounded-md border border-dashed border-accent/40 px-4 py-2 text-sm font-medium text-accent transition disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
                          >
                            {BILLING_ENABLED ? plan.cta : `${plan.cta}`}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}
