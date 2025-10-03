import OpenAI from 'openai';
import { z } from 'zod';

const client = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY
});

const ResumeSchema = z.object({
  summary: z.string().min(10),
  roles: z.array(
    z.object({
      id: z.string(),
      bullets: z.array(z.string().min(1)).min(1)
    })
  ),
  keywordCoverage: z.array(z.string()),
  gaps: z.array(z.string())
});

export type TailoredResume = z.infer<typeof ResumeSchema>;

function validateNoHallucinations(baseRoles: string[], tailored: TailoredResume) {
  const unknown = tailored.roles.filter((role) => !baseRoles.includes(role.id));
  if (unknown.length > 0) {
    throw new Error('AI attempted to fabricate experience.');
  }
}

export async function generateCoverLetter({
  resumeData,
  jobDescription
}: {
  resumeData: unknown;
  jobDescription: string;
}): Promise<string> {
  const response = await client.chat.completions.create({
    model: process.env.OPENAI_MODEL ?? 'gpt-5-mini',
    messages: [
      {
        role: 'system',
        content:
          'Expert career coach. Draft a concise, one-page cover letter in markdown paragraphs, grounding every claim in the supplied resume. Highlight ATS keywords from the job description and keep tone confident yet human.'
      },
      {
        role: 'user',
        content: JSON.stringify({ resumeData, jobDescription })
      }
    ],
    temperature: 0.4,
    max_tokens: 900
  });

  const content = response.choices[0]?.message?.content;
  if (!content) {
    throw new Error('No content returned from OpenAI');
  }

  return content.trim();
}

export async function tailorResume({
  resumeData,
  jobDescription,
  baseRoleIds
}: {
  resumeData: unknown;
  jobDescription: string;
  baseRoleIds: string[];
}): Promise<TailoredResume> {
  const response = await client.chat.completions.create({
    model: process.env.OPENAI_MODEL ?? 'gpt-5-mini',
    messages: [
      {
        role: 'system',
        content:
          'Expert resume editor. Keep facts truthful; never fabricate roles/education. Optimize for ATS keywords from the JD. Use concise, outcome-oriented bullets.'
      },
      {
        role: 'user',
        content: JSON.stringify({ resumeData, jobDescription })
      }
    ],
    temperature: 0.3,
    max_tokens: 1200,
    response_format: { type: 'json_object' }
  });

  const content = response.choices[0]?.message?.content;
  if (!content) {
    throw new Error('No content returned from OpenAI');
  }

  const parsed = ResumeSchema.parse(JSON.parse(content));
  validateNoHallucinations(baseRoleIds, parsed);
  return parsed;
}
