import { NextResponse } from 'next/server';
import { z } from 'zod';
import { BILLING_ENABLED } from '@/lib/pricing';
import { getStripeClient } from '@/lib/stripe';
import { createSupabaseServerClient } from '@/lib/auth';

const requestSchema = z.object({
  priceId: z.string(),
  successUrl: z.string().url(),
  cancelUrl: z.string().url()
});

export async function POST(request: Request) {
  if (!BILLING_ENABLED) {
    return NextResponse.json({ message: 'Billing not enabled yet. Coming soon!' }, { status: 503 });
  }

  const supabase = createSupabaseServerClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ message: 'Sign in required' }, { status: 401 });
  }

  const body = await request.json();
  const parsed = requestSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json({ message: 'Invalid request', issues: parsed.error.flatten() }, { status: 400 });
  }

  const stripe = getStripeClient();
  const session = await stripe.checkout.sessions.create({
    mode: 'subscription',
    line_items: [{ price: parsed.data.priceId, quantity: 1 }],
    success_url: parsed.data.successUrl,
    cancel_url: parsed.data.cancelUrl,
    client_reference_id: user.id
  });

  return NextResponse.json({ url: session.url });
}
