import type { ResumeData } from '@/types';
import { renderResume } from './base';

export const TEMPLATE_ELEGANT = 'elegant';

export function renderElegant(data: ResumeData) {
  return renderResume(data, { accent: '#7c3aed', bodyFont: '"Playfair Display", Georgia, serif', borderStyle: '#c4b5fd' });
}
