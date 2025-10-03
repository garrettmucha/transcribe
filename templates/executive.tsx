import type { ResumeData } from '@/types';
import { renderResume } from './base';

export const TEMPLATE_EXECUTIVE = 'executive';

export function renderExecutive(data: ResumeData) {
  return renderResume(data, { accent: '#1f2937', headingCase: 'uppercase', bodyFont: '"Inter", Arial, sans-serif', borderStyle: '#94a3b8' });
}
