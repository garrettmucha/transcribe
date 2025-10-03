import { config } from 'dotenv';
config({ path: '.env.local', override: false });

const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
    serverActions: true
  },
  env: {
    BILLING_ENABLED: process.env.BILLING_ENABLED,
    MAX_FREE_AI_GENERATIONS: process.env.MAX_FREE_AI_GENERATIONS,
    FREE_MAX_EXPORTS: process.env.FREE_MAX_EXPORTS
  }
};

export default nextConfig;
