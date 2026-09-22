import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ['three', '@react-three/drei', '@react-three/postprocessing'],
  experimental: {
    optimizePackageImports: ['@react-three/drei', 'framer-motion'],
  },
  headers: async () => [
    {
      // MediaPipe's WASM backend benefits from a cross-origin isolated context
      // (enables SharedArrayBuffer / threaded inference where available).
      source: '/(.*)',
      headers: [
        { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
        { key: 'Cross-Origin-Embedder-Policy', value: 'credentialless' },
      ],
    },
  ],
};

export default nextConfig;
