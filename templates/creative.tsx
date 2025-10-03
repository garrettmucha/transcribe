import type { ResumeData } from '@/types';
import { renderResume } from './base';

export const TEMPLATE_CREATIVE = 'creative';

export function renderCreative(data: ResumeData) {
  return renderResume(data, { accent: '#ec4899', bodyFont: '"Inter", Arial, sans-serif', borderStyle: '#fbcfe8' });
}
