import type { ResumeData } from '@/types';
import { renderResume } from './base';

export const TEMPLATE_CLASSIC = 'classic';

export function renderClassic(data: ResumeData) {
  return renderResume(data, { accent: '#4f46e5' });
}
