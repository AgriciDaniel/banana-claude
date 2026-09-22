'use client';

import dynamic from 'next/dynamic';

/**
 * The entire OS is client-side: WebGL, WebAudio and MediaPipe all need a
 * browser. Server rendering it would produce a blank shell and a hydration
 * mismatch, so the root is loaded with SSR off and a matching dark placeholder
 * to avoid a flash before the boot sequence paints.
 */
const NexusApp = dynamic(() => import('@/app/NexusApp').then((m) => m.NexusApp), {
  ssr: false,
  loading: () => <div className="fixed inset-0 bg-void" />,
});

export default function Page() {
  return <NexusApp />;
}
