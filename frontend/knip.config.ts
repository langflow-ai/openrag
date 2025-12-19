import type { KnipConfig } from 'knip';

const config: KnipConfig = {
  entry: [
    'app/**/*.{ts,tsx}',
    'next.config.ts',
  ],
  project: ['**/*.{ts,tsx}'],
  ignore: [
    '**/*.d.ts',
    '**/node_modules/**',
    '.next/**',
    'public/**',
  ],
};

export default config;

