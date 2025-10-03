import type { ResumeData } from '@/types';
import { renderResume } from './base';

export const TEMPLATE_MODERN = 'modern';

export function renderModern(data: ResumeData) {
  return renderResume(data, { accent: '#2563eb', headingCase: 'uppercase', bodyFont: '"Inter", Arial, sans-serif' });
}
