import { test, expect } from '@playwright/test';
import { MAX_FREE_AI_GENERATIONS } from '@/lib/pricing';

test.describe('AI guardrails', () => {
  test('free tier generation cap matches spec', () => {
    expect(MAX_FREE_AI_GENERATIONS).toBe(15);
  });
});
