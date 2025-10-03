'use client';

import { useMemo } from 'react';
import type { ResumeData } from '@/types';

export type ResumeFormValues = ResumeData;

export function Preview({ data }: { data: ResumeFormValues }) {
  const formatted = useMemo(() => {
    return {
      ...data,
      skills: data.skills.filter(Boolean),
      roles: data.roles.map((role) => ({
        ...role,
        bullets: role.bullets.filter(Boolean)
      }))
    };
  }, [data]);

  return (
    <section className="h-full overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50 px-6 py-5">
        <h2 className="text-lg font-semibold text-slate-900">Resume Preview</h2>
        <p className="text-xs text-slate-500">Live preview updates as you tailor content.</p>
      </div>
      <div className="space-y-6 px-6 py-6 text-sm leading-relaxed text-slate-700">
        <section>
          <h3 className="text-base font-semibold text-slate-900">Professional Summary</h3>
          <p className="mt-2 text-sm text-slate-700">{formatted.summary || 'Start by entering a concise summary that highlights your differentiators.'}</p>
        </section>
        <section className="space-y-4">
          <h3 className="text-base font-semibold text-slate-900">Experience</h3>
          {formatted.roles.map((role) => (
            <div key={role.id} className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-900">{role.title || 'Role title'}</p>
                  <p className="text-xs text-slate-500">{role.company || 'Company'} · {role.startDate || 'Start'} – {role.endDate || 'Present'}</p>
                </div>
              </div>
              <ul className="list-outside space-y-1 pl-4">
                {role.bullets.map((bullet, idx) => (
                  <li key={idx} className="marker:text-accent text-sm text-slate-700">
                    {bullet || 'Impact-driven bullet that quantifies success.'}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
        <section>
          <h3 className="text-base font-semibold text-slate-900">Core Skills</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {formatted.skills.length > 0 ? (
              formatted.skills.map((skill) => (
                <span key={skill} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600">
                  {skill}
                </span>
              ))
            ) : (
              <p className="text-sm text-slate-500">Add targeted keywords that mirror the job description.</p>
            )}
          </div>
        </section>
      </div>
    </section>
  );
}
