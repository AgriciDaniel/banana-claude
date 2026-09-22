'use client';

import { useSnapshot } from 'valtio';
import { telemetry } from '@/stores/runtime';
import { useSystemStore } from '@/stores/useSystemStore';
import { Divider, Meter, Panel, Pip, Row } from './primitives';
import { useT } from '@/i18n';
import { LocaleSwitch } from './LocaleSwitch';
import type { TranslationKey } from '@/i18n';

type Tone = 'default' | 'good' | 'warn' | 'muted';

/** Tone is presentation, the label is content — so only the tone lives here. */
const TRACKING_TONE: Record<string, Tone> = {
  idle: 'muted',
  requesting: 'default',
  loading: 'default',
  active: 'good',
  lost: 'default',
  denied: 'warn',
  error: 'warn',
};

/** Top left: what the machine is doing and how hard it is working. */
export function StatusCluster() {
  const telem = useSnapshot(telemetry);
  const tracking = useSystemStore((s) => s.tracking);
  const tier = useSystemStore((s) => s.tier);
  const capabilities = useSystemStore((s) => s.capabilities);
  const input = useSystemStore((s) => s.input);
  const t = useT();

  const tone = TRACKING_TONE[tracking] ?? 'muted';
  // 60 fps is the target; the meter is scaled to it rather than to a peak, so
  // a full bar always means "we are hitting the budget".
  const fpsRatio = Math.min(1, telem.fps / 60);
  const fpsTone = telem.fps >= 52 ? 'good' : telem.fps >= 38 ? 'default' : 'warn';

  return (
    <Panel className="w-[236px]" delay={0.1} from="left">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-sans text-[15px] font-medium tracking-[0.34em] text-lumen">
            NEXUS
          </span>
          <span className="hud-label">v1.0</span>
        </div>
        <Pip tone={tracking === 'active' ? 'good' : tracking === 'denied' ? 'warn' : 'idle'} />
      </div>

      <Divider />

      <Row label={t('status.frameRate')} value={`${telem.fps} FPS`} tone={fpsTone} />
      <div className="py-1">
        <Meter value={fpsRatio} segments={18} tone={telem.fps >= 38 ? 'signal' : 'ember'} />
      </div>
      <Row label={t('status.frameTime')} value={`${telem.frameMs.toFixed(1)} MS`} tone="muted" />
      <Row label={t('status.drawCalls')} value={telem.drawCalls} tone="muted" />

      <Divider />

      <Row label={t('status.tracking')} value={t(`tracking.${tracking}` as TranslationKey)} tone={tone} />
      <Row label={t('status.input')} value={t(`input.${input}` as TranslationKey)} tone="muted" />
      <Row label={t('status.quality')} value={t(`tier.${tier}` as TranslationKey)} />

      <Divider />

      <Row
        label={t('status.gpu')}
        value={
          <span className="block max-w-[128px] truncate text-right" title={capabilities?.gpu}>
            {capabilities?.gpu ?? t('status.detecting')}
          </span>
        }
        tone="muted"
      />
      <Row
        label={t('status.renderer')}
        value={capabilities?.webgl === 2 ? 'WEBGL2' : 'WEBGL1'}
        tone="muted"
      />

      <Divider />

      <LocaleSwitch compact />
    </Panel>
  );
}
