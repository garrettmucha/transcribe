import { NextResponse } from 'next/server';
import { z } from 'zod';
import { tailorResume } from '@/lib/ai';
import { createSupabaseServerClient } from '@/lib/auth';
import { prisma } from '@/lib/prisma';
import { MAX_FREE_AI_GENERATIONS } from '@/lib/pricing';
import type { ResumeData } from '@/types';

const requestSchema = z.object({
  resumeData: z.object({
    summary: z.string(),
    roles: z.array(
      z.object({
        id: z.string(),
        title: z.string(),
        company: z.string(),
        startDate: z.string(),
        endDate: z.string(),
        bullets: z.array(z.string())
      })
    ),
    skills: z.array(z.string())
  }),
  jobDescription: z.string().min(10, 'Job description required')
});

export async function POST(request: Request) {
  const supabase = createSupabaseServerClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ message: 'Sign in required' }, { status: 401 });
  }

  const body = await request.json();
  const parsed = requestSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json({ message: 'Invalid request', issues: parsed.error.flatten() }, { status: 400 });
  }

  const resumePayload: ResumeData = parsed.data.resumeData;
  const dbUser = await prisma.user.upsert({
    where: { id: user.id },
    update: {},
    create: {
      id: user.id,
      email: user.email ?? `${user.id}@placeholder.local`,
      plan: 'FREE'
    }
  });

  if (dbUser.aiGenerationsUsed >= MAX_FREE_AI_GENERATIONS) {
    return NextResponse.json({ message: "You've used 15 AI generations. Unlimited coming soon." }, { status: 429 });
  }

  const baseRoleIds = resumePayload.roles.map((role) => role.id);
  try {
    const tailored = await tailorResume({
      resumeData: resumePayload,
      jobDescription: parsed.data.jobDescription,
      baseRoleIds
    });

    const diff = tailored.roles.map((role) => {
      const existing = resumePayload.roles.find((item) => item.id === role.id);
      return {
        id: role.id,
        original: existing?.bullets.join('\n') ?? '',
        updated: role.bullets.join('\n')
      };
    });

    const updatedResumeData = {
      summary: tailored.summary,
      roles: resumePayload.roles.map((role) => {
        const updated = tailored.roles.find((item) => item.id === role.id);
        return updated ? { ...role, bullets: updated.bullets } : role;
      }),
      skills: resumePayload.skills,
      keywordCoverage: tailored.keywordCoverage,
      gaps: tailored.gaps
    };

    const resumeId = `${user.id}-primary`;

    await prisma.$transaction([
      prisma.user.update({
        where: { id: user.id },
        data: { aiGenerationsUsed: { increment: 1 } }
      }),
      prisma.resume.upsert({
        where: { id: resumeId },
        update: {
          data: updatedResumeData
        },
        create: {
          id: resumeId,
          userId: user.id,
          template: 'classic',
          data: updatedResumeData
        }
      })
    ]);

    return NextResponse.json({
      tailoredResumeData: tailored,
      diff,
      keywordCoverage: tailored.keywordCoverage,
      gaps: tailored.gaps
    });
  } catch (error) {
    console.error(error);
    return NextResponse.json({ message: 'Unable to tailor resume right now.' }, { status: 500 });
  }
}
