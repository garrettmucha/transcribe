import type { ResumeData } from '@/types';
import { renderResume } from './base';

export const TEMPLATE_COMPACT = 'compact';

export function renderCompact(data: ResumeData) {
  return renderResume(data, { accent: '#0f766e', borderStyle: '#99f6e4', bodyFont: '"Inter", Arial, sans-serif' });
}
