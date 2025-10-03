import type { User as SupabaseUser } from '@supabase/supabase-js';
import { createSupabaseServerClient } from '@/lib/auth';
import { prisma } from '@/lib/prisma';
import { MAX_FREE_AI_GENERATIONS } from '@/lib/pricing';
import { MainShell } from '@/components/MainShell';
import type { ResumeData } from '@/types';

const DEFAULT_RESUME: ResumeData = {
  summary:
    'Growth-focused product leader with 8+ years driving B2B SaaS adoption, blending experimentation, customer research, and rigorous analytics to accelerate ARR.',
  roles: [
    {
      id: 'role-1',
      title: 'Head of Product',
      company: 'Nimbus Analytics',
      startDate: '2019',
      endDate: 'Present',
      bullets: [
        'Shipped experimentation platform adopted by 120+ enterprise customers, cutting feature rollout time by 35%.',
        'Built cross-functional growth pod (PM + eng + design + data) that lifted activation by 22% in six months.'
      ]
    },
    {
      id: 'role-2',
      title: 'Senior Product Manager',
      company: 'Beacon Labs',
      startDate: '2016',
      endDate: '2019',
      bullets: [
        'Led go-to-market for analytics module, achieving $4.2M ARR within first year.',
        'Institutionalized customer discovery rituals that reduced churn by 18% YoY.'
      ]
    }
  ],
  skills: ['Product strategy', 'Experimentation', 'SQL', 'Cross-functional leadership', 'Customer discovery']
};

async function getViewer() {
  const supabase = createSupabaseServerClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  return user;
}

async function getInitialData(user: SupabaseUser | null): Promise<{ data: ResumeData; usage: number; signedIn: boolean }> {
  if (!user) {
    return { data: DEFAULT_RESUME, usage: 0, signedIn: false };
  }

  const [resume, dbUser] = await Promise.all([
    prisma.resume.findFirst({ where: { userId: user.id }, orderBy: { updatedAt: 'desc' } }),
    prisma.user.findUnique({ where: { id: user.id } })
  ]);

  if (!dbUser) {
    await prisma.user.upsert({
      where: { id: user.id },
      update: {},
      create: {
        id: user.id,
        email: user.email ?? `${user.id}@placeholder.local`,
        plan: 'FREE'
      }
    });
    return { data: DEFAULT_RESUME, usage: 0, signedIn: true };
  }

  if (!resume) {
    return { data: DEFAULT_RESUME, usage: dbUser.aiGenerationsUsed, signedIn: true };
  }

  const payload = resume.data as Record<string, unknown> | null;

  return {
    data: {
      summary: typeof payload?.summary === 'string' ? (payload.summary as string) : DEFAULT_RESUME.summary,
      roles: Array.isArray(payload?.roles) ? (payload.roles as ResumeData['roles']) : DEFAULT_RESUME.roles,
      skills: Array.isArray(payload?.skills) ? (payload.skills as ResumeData['skills']) : DEFAULT_RESUME.skills
    },
    usage: dbUser.aiGenerationsUsed,
    signedIn: true
  };
}

export default async function Page() {
  const user = await getViewer();
  const initial = await getInitialData(user ?? null);

  return (
    <MainShell initialData={initial.data} aiGenerationsUsed={initial.usage} aiLimit={MAX_FREE_AI_GENERATIONS} signedIn={initial.signedIn} />
  );
}
