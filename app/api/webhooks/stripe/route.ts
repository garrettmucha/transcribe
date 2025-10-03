import { headers } from 'next/headers';
import { NextResponse } from 'next/server';
import { BILLING_ENABLED } from '@/lib/pricing';
import { getStripeClient } from '@/lib/stripe';
import { prisma } from '@/lib/prisma';

export async function POST(request: Request) {
  if (!BILLING_ENABLED) {
    return NextResponse.json({ message: 'Billing not enabled yet. Coming soon!' }, { status: 503 });
  }

  const stripe = getStripeClient();
  const signature = headers().get('stripe-signature');
  const payload = await request.text();

  if (!signature) {
    return NextResponse.json({ message: 'Missing signature' }, { status: 400 });
  }

  let event;
  try {
    event = stripe.webhooks.constructEvent(payload, signature, process.env.STRIPE_WEBHOOK_SECRET ?? '');
  } catch (error) {
    console.error('Stripe signature verification failed', error);
    return NextResponse.json({ message: 'Invalid signature' }, { status: 400 });
  }

  switch (event.type) {
    case 'checkout.session.completed': {
      const session = event.data.object as { client_reference_id?: string; id: string };
      if (session.client_reference_id) {
        await prisma.payment.upsert({
          where: { stripeCheckoutId: session.id },
          update: { status: 'COMPLETED' },
          create: {
            userId: session.client_reference_id,
            type: 'SUB',
            status: 'COMPLETED',
            stripeCheckoutId: session.id
          }
        });
      }
      break;
    }
    default:
      break;
  }

  return NextResponse.json({ received: true });
}
