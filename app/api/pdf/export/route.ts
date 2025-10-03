import { NextResponse } from 'next/server';
import { z } from 'zod';
import { renderPdfFromHtml } from '@/lib/pdf';
import { renderTemplate, TEMPLATE_CLASSIC } from '@/templates';
import type { TemplateId } from '@/templates';
import { prisma } from '@/lib/prisma';
import { createSupabaseServerClient } from '@/lib/auth';
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
  templateId: z.string().optional()
});

export async function POST(request: Request) {
  const supabase = createSupabaseServerClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  const body = await request.json();
  const parsed = requestSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json({ message: 'Invalid request', issues: parsed.error.flatten() }, { status: 400 });
  }

  const resumePayload: ResumeData = parsed.data.resumeData;
  const templateId = (parsed.data.templateId as TemplateId | undefined) ?? TEMPLATE_CLASSIC;

  const html = renderTemplate(templateId, resumePayload);
  const pdf = await renderPdfFromHtml(html);
  const url = `data:application/pdf;base64,${Buffer.from(pdf).toString('base64')}`;

  if (user) {
    const resumeId = `${user.id}-primary`;
    await prisma.$transaction([
      prisma.resume.upsert({
        where: { id: resumeId },
        update: { data: { ...resumePayload, templateId } },
        create: {
          id: resumeId,
          userId: user.id,
          template: templateId,
          data: resumePayload
        }
      }),
      prisma.exportLog.create({
        data: {
          userId: user.id,
          resumeId,
          format: 'pdf'
        }
      })
    ]);
  }

  return NextResponse.json({ url });
}
