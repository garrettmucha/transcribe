export const BILLING_ENABLED = process.env.BILLING_ENABLED === 'true';
export const MAX_FREE_AI_GENERATIONS = Number.parseInt(process.env.MAX_FREE_AI_GENERATIONS ?? '15', 10);
export const FREE_MAX_EXPORTS = Number.parseInt(process.env.FREE_MAX_EXPORTS ?? '0', 10);

export const PLANS = {
  FREE: {
    id: 'free',
    name: 'Free',
    description: 'Unlimited editing & preview, 15 AI generations, unlimited PDFs.',
    price: '$0',
    cta: 'Included'
  },
  ONE_TIME: {
    id: 'one_time',
    name: 'One-time',
    description: 'Unlimited exports forever. Coming soon.',
    price: '$5',
    cta: 'Coming soon'
  },
  SUB_MONTHLY: {
    id: 'sub_monthly',
    name: 'Pro Monthly',
    description: 'Unlimited AI. Coming soon.',
    price: '$2/mo',
    cta: 'Coming soon'
  },
  SUB_ANNUAL: {
    id: 'sub_annual',
    name: 'Pro Annual',
    description: 'Unlimited AI + exports. Coming soon.',
    price: '$20/yr',
    cta: 'Coming soon'
  }
} as const;

export type PlanKey = keyof typeof PLANS;
