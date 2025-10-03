import Stripe from 'stripe';
import { BILLING_ENABLED } from './pricing';

const stripeSecret = process.env.STRIPE_SECRET_KEY;

export function getStripeClient() {
  if (!BILLING_ENABLED) {
    throw new Error('Stripe disabled');
  }
  if (!stripeSecret) {
    throw new Error('Missing STRIPE_SECRET_KEY');
  }
  return new Stripe(stripeSecret, { apiVersion: '2023-10-16' });
}
