import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'NEXUS — Spatial Computing Environment',
  description:
    'A gesture-driven spatial operating system for the browser. Hand-tracked holographic modules, volumetric atmosphere, spring physics.',
  applicationName: 'NEXUS',
  authors: [{ name: 'NEXUS' }],
  robots: { index: true, follow: true },
  alternates: { languages: { en: '/', fr: '/' } },
};

export const viewport: Viewport = {
  themeColor: '#03060B',
  colorScheme: 'dark',
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  viewportFit: 'cover',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    /*
     * `lang` starts at "en" and is rewritten by the locale store after
     * detection, so the server render and first client paint agree.
     *
     * `translate="no"` is not optional here. NEXUS ships real translations;
     * left unmarked, Chrome's auto-translate rewrites the interface on top of
     * them — it renamed the product itself from "NEXUS" to "LIEN" and turned
     * the input readout "POINTER" into "AIGUILLE" (a clock hand). Machine
     * translation cannot know that these are instrument labels, so it is
     * declined outright and the language switch is offered instead.
     */
    <html lang="en" className="dark" translate="no">
      <body className="bg-void text-lumen antialiased notranslate">{children}</body>
    </html>
  );
}
