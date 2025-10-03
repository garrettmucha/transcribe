import { createServerClient } from '@supabase/auth-helpers-nextjs';
import { cookies, headers } from 'next/headers';

type SupabaseClient = ReturnType<typeof createServerClient>;

export function createSupabaseServerClient() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseAnonKey) {
    return {
      auth: {
        async getUser() {
          return { data: { user: null } } as const;
        }
      }
    } as SupabaseClient;
  }

  const cookieStore = cookies();
  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      get(name: string) {
        return cookieStore.get(name)?.value;
      }
    },
    global: {
      headers: {
        'X-Forwarded-For': headers().get('x-forwarded-for') ?? ''
      }
    }
  });
}
