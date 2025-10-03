import { NextResponse } from 'next/server';
import { z } from 'zod';
import { createSupabaseServerClient } from '@/lib/auth';
import { prisma } from '@/lib/prisma';
import { MAX_FREE_AI_GENERATIONS } from '@/lib/pricing';
import type { ResumeData } from '@/types';
import { generateCoverLetter } from '@/lib/ai';

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

  try {
    const content = await generateCoverLetter({ resumeData: resumePayload, jobDescription: parsed.data.jobDescription });

    await prisma.$transaction([
      prisma.user.update({
        where: { id: user.id },
        data: { aiGenerationsUsed: { increment: 1 } }
      }),
      prisma.coverLetter.create({
        data: {
          userId: user.id,
          resumeId: null,
          content
        }
      })
    ]);

    return NextResponse.json({ content });
  } catch (error) {
    console.error(error);
    return NextResponse.json({ message: 'Unable to generate cover letter.' }, { status: 500 });
  }
}
