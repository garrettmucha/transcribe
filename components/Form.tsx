'use client';

import { useCallback, useEffect, useState } from 'react';
import { useForm, useFieldArray } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import type { ResumeData } from '@/types';
import { ResumeFormValues } from './Preview';
import { DiffEntry } from './DiffOverlay';

const roleSchema = z.object({
  id: z.string(),
  title: z.string().min(1, 'Required'),
  company: z.string().min(1, 'Required'),
  startDate: z.string().min(1, 'Required'),
  endDate: z.string().min(1, 'Required'),
  bullets: z.array(z.string().min(1, 'Required')).min(1)
});

const formSchema = z.object({
  summary: z.string().min(1, 'Summary is required'),
  roles: z.array(roleSchema).min(1),
  skills: z.array(z.string()),
  jobDescription: z.string().min(1, 'Paste the job description to tailor your resume')
});

export type FormSchema = z.infer<typeof formSchema>;

export function Form({
  initialValues,
  aiGenerationsUsed,
  aiLimit,
  onChange,
  onTailored
}: {
  initialValues: ResumeData;
  aiGenerationsUsed: number;
  aiLimit: number;
  onChange: (data: ResumeData) => void;
  onTailored: (payload: { summary: string; diffs: DiffEntry[]; updated: ResumeData }) => void;
}) {
  const {
    control,
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors }
  } = useForm<FormSchema>({
    defaultValues: {
      ...initialValues,
      jobDescription: ''
    },
    resolver: zodResolver(formSchema)
  });

  const { fields, append } = useFieldArray({ control, name: 'roles' });

  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [diffs, setDiffs] = useState<DiffEntry[]>([]);
  const [diffSummary, setDiffSummary] = useState('');

  const values = watch();

  useEffect(() => {
    onChange({ summary: values.summary, roles: values.roles, skills: values.skills });
  }, [values.summary, values.roles, values.skills, onChange]);

  useEffect(() => {
    reset({ ...initialValues, jobDescription: '' });
  }, [initialValues, reset]);

  const aiDisabled = aiGenerationsUsed >= aiLimit;

  const submitAi = useCallback(
    async (payload: FormSchema) => {
      if (aiDisabled) {
        setModalOpen(true);
        setDiffSummary("You've used 15 AI generations. Unlimited coming soon.");
        setDiffs([]);
        return;
      }
      setLoading(true);
      try {
        const response = await fetch('/api/ai/tailor', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            resumeData: {
              summary: payload.summary,
              roles: payload.roles,
              skills: payload.skills
            },
            jobDescription: payload.jobDescription
          })
        });
        if (response.status === 429) {
          const data = await response.json();
          setDiffSummary(data.message ?? "You've used 15 AI generations. Unlimited coming soon.");
          setDiffs([]);
          setModalOpen(true);
          return;
        }
        if (!response.ok) {
          throw new Error('Failed to tailor resume');
        }
        const data = await response.json();
        const { tailoredResumeData, diff } = data;
        setDiffSummary('Review adjustments then apply to your resume.');
        setDiffs(diff as DiffEntry[]);
        setModalOpen(true);
        const updatedResume: ResumeData = {
          summary: tailoredResumeData.summary,
          roles: payload.roles.map((role) => {
            const updatedRole = tailoredResumeData.roles.find((item: any) => item.id === role.id);
            return updatedRole ? { ...role, bullets: updatedRole.bullets } : role;
          }),
          skills: payload.skills
        };

        onTailored({
          summary: tailoredResumeData.summary,
          diffs: diff,
          updated: {
            summary: updatedResume.summary,
            roles: updatedResume.roles,
            skills: updatedResume.skills
          }
        });
        reset({ ...updatedResume, jobDescription: payload.jobDescription });
      } catch (error) {
        console.error(error);
        setDiffSummary('Unable to reach AI. Please try again later.');
        setDiffs([]);
        setModalOpen(true);
      } finally {
        setLoading(false);
      }
    },
    [aiDisabled, onTailored, reset]
  );

  return (
    <>
      <form
        className="flex h-full flex-col overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-sm"
        onSubmit={handleSubmit(submitAi)}
      >
      <div className="border-b border-slate-200 bg-slate-50 px-6 py-5">
        <h2 className="text-lg font-semibold text-slate-900">Resume Inputs</h2>
        <p className="text-xs text-slate-500">Provide the essentials and tailor instantly to any role.</p>
      </div>
      <div className="flex-1 space-y-6 overflow-y-auto px-6 py-6 text-sm">
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Job description</h3>
          <textarea
            {...register('jobDescription')}
            rows={5}
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
            placeholder="Paste the role summary here so we can align your resume."
          />
          {errors.jobDescription && <p className="text-xs text-rose-500">{errors.jobDescription.message}</p>}
        </section>
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">Professional Summary</h3>
            <span className="text-xs text-slate-500">{aiGenerationsUsed}/{aiLimit} AI generations used</span>
          </div>
          <textarea
            {...register('summary')}
            rows={4}
            className="w-full resize-none rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
            placeholder="Experienced growth marketer with a track record of accelerating acquisition..."
          />
          {errors.summary && <p className="text-xs text-rose-500">{errors.summary.message}</p>}
        </section>
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">Experience</h3>
            <button
              type="button"
              onClick={() =>
                append({
                  id: crypto.randomUUID(),
                  title: '',
                  company: '',
                  startDate: '',
                  endDate: '',
                  bullets: ['']
                })
              }
              className="rounded-md border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:border-accent hover:text-accent"
            >
              Add role
            </button>
          </div>
          {fields.map((field, index) => (
            <div key={field.id} className="rounded-lg border border-slate-200 p-4">
              <div className="grid gap-3 md:grid-cols-2">
                <label className="space-y-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Title
                  <input
                    {...register(`roles.${index}.title` as const)}
                    className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
                  />
                </label>
                <label className="space-y-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Company
                  <input
                    {...register(`roles.${index}.company` as const)}
                    className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
                  />
                </label>
                <label className="space-y-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Start date
                  <input
                    {...register(`roles.${index}.startDate` as const)}
                    className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
                  />
                </label>
                <label className="space-y-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  End date
                  <input
                    {...register(`roles.${index}.endDate` as const)}
                    className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
                  />
                </label>
              </div>
              <div className="mt-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Impact bullets</p>
                {field.bullets.map((_, bulletIndex) => (
                  <input
                    key={bulletIndex}
                    {...register(`roles.${index}.bullets.${bulletIndex}` as const)}
                    className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
                    placeholder="Scaled MRR by 45% by orchestrating..."
                  />
                ))}
              </div>
            </div>
          ))}
        </section>
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Skills</h3>
          <textarea
            {...register('skills', {
              setValueAs: (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean)
            })}
            rows={2}
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-accent"
            placeholder="Product strategy, SQL, experimentation"
          />
        </section>
      </div>
        <div className="border-t border-slate-200 bg-white px-6 py-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <button
              type="submit"
              disabled={loading || aiDisabled}
              className="inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-accent-700 disabled:cursor-not-allowed disabled:bg-slate-200"
            >
              {aiDisabled ? 'AI limit reached' : loading ? 'Tailoring…' : 'Tailor to Job (AI)'}
            </button>
            <p className="text-xs text-slate-500">
              When you hit the limit we’ll invite you to upgrade—unlimited AI is coming soon.
            </p>
          </div>
        </div>
      </form>
      <DiffOverlay open={modalOpen} onClose={() => setModalOpen(false)} summary={diffSummary} diffs={diffs} />
    </>
  );
}
