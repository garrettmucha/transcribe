import { test, expect } from '@playwright/test';
import { renderTemplate, TEMPLATE_CLASSIC } from '@/templates';
import type { ResumeData } from '@/types';

const SAMPLE_RESUME: ResumeData = {
  summary: 'Seasoned engineer.',
  roles: [
    {
      id: '1',
      title: 'Engineer',
      company: 'Acme',
      startDate: '2020',
      endDate: '2024',
      bullets: ['Shipped stuff.']
    }
  ],
  skills: ['TypeScript']
};

test('templates render html with doctype', () => {
  const html = renderTemplate(TEMPLATE_CLASSIC, SAMPLE_RESUME);
  expect(html.startsWith('<!DOCTYPE html>')).toBeTruthy();
  expect(html).toContain('Engineer');
});
