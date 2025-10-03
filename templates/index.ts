import type { ResumeData } from '@/types';
import { TEMPLATE_CLASSIC, renderClassic } from './classic';
import { TEMPLATE_MODERN, renderModern } from './modern';
import { TEMPLATE_ELEGANT, renderElegant } from './elegant';
import { TEMPLATE_COMPACT, renderCompact } from './compact';
import { TEMPLATE_EXECUTIVE, renderExecutive } from './executive';
import { TEMPLATE_CREATIVE, renderCreative } from './creative';

const registry = {
  [TEMPLATE_CLASSIC]: renderClassic,
  [TEMPLATE_MODERN]: renderModern,
  [TEMPLATE_ELEGANT]: renderElegant,
  [TEMPLATE_COMPACT]: renderCompact,
  [TEMPLATE_EXECUTIVE]: renderExecutive,
  [TEMPLATE_CREATIVE]: renderCreative
};

export type TemplateId = keyof typeof registry;

export function renderTemplate(templateId: TemplateId, data: ResumeData) {
  const renderer = registry[templateId] ?? renderClassic;
  return renderer(data);
}

export const TEMPLATE_IDS = Object.keys(registry) as TemplateId[];
