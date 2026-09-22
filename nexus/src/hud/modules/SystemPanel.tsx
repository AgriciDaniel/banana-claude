'use client';

import type { ModuleFeed, SystemData } from '@/modules/types';
import { Bar, FeedState, Line, Provenance, Section } from './shared';
import { useT } from '@/i18n';

/** Everything this tab can actually measure about the machine it is on. */
export function SystemPanel({ feed }: { feed: ModuleFeed<SystemData> }) {
  const t = useT();
  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const heap = d.heapUsedMb && d.heapLimitMb ? d.heapUsedMb / d.heapLimitMb : null;
  const disk = d.storage ? d.storage.usedMb / Math.max(1, d.storage.quotaMb) : null;

  return (
    <div>
      <Section title={t('system.render')}>
        <Line label={t('system.fps')} value={`${d.fps} fps`} tone={d.fps >= 50 ? 'good' : 'warn'} />
        <div className="py-1">
          <Bar value={d.fps / 60} tone={d.fps >= 50 ? 'lock' : 'ember'} />
        </div>
        <Line label={t('system.frame')} value={`${d.frameMs} ms`} tone="muted" />
        <Line label={t('system.draws')} value={String(d.drawCalls)} tone="muted" />
        <Line label={t('system.tris')} value={d.triangles.toLocaleString('en-US')} tone="muted" />
      </Section>

      <Section title={t('system.hardware')}>
        <Line label={t('system.gpu')} value={d.gpu} />
        <Line label={t('system.api')} value={d.renderer} tone="muted" />
        <Line label={t('system.cores')} value={String(d.cores)} tone="muted" />
        {d.memoryGb > 0 && <Line label={t('system.ram')} value={`${d.memoryGb} GB`} tone="muted" />}
        <Line label={t('system.platform')} value={d.platform} tone="muted" />
      </Section>

      {heap !== null && (
        <Section title={t('system.memory')}>
          <Line label={t('system.heap')} value={`${d.heapUsedMb} / ${d.heapLimitMb} MB`} />
          <div className="py-1">
            <Bar value={heap} tone={heap > 0.8 ? 'ember' : 'signal'} />
          </div>
        </Section>
      )}

      {d.battery && (
        <Section title={t('system.power')}>
          <Line
            label={d.battery.charging ? t('system.charging') : t('system.battery')}
            value={`${Math.round(d.battery.level * 100)}%`}
            tone={d.battery.level < 0.2 && !d.battery.charging ? 'warn' : 'good'}
          />
          <div className="py-1">
            <Bar
              value={d.battery.level}
              tone={d.battery.level < 0.2 && !d.battery.charging ? 'ember' : 'lock'}
            />
          </div>
        </Section>
      )}

      {d.network && (
        <Section title={t('system.network')}>
          <Line label={t('system.link')} value={d.network.type.toUpperCase()} />
          <Line label={t('system.down')} value={`${d.network.downlink} Mb/s`} tone="muted" />
          <Line label={t('system.rtt')} value={`${d.network.rtt} ms`} tone="muted" />
        </Section>
      )}

      {disk !== null && d.storage && (
        <Section title={t('system.storage')}>
          <Line
            label={t('system.used')}
            value={`${(d.storage.usedMb / 1000).toFixed(2)} / ${(d.storage.quotaMb / 1000).toFixed(1)} GB`}
          />
          <div className="py-1">
            <Bar value={disk} />
          </div>
        </Section>
      )}

      <Section title={t('system.session')}>
        <Line
          label={t('system.uptime')}
          value={`${Math.floor(d.uptimeSec / 60)}m ${d.uptimeSec % 60}s`}
          tone="muted"
        />
      </Section>

      <Provenance feed={feed} />
    </div>
  );
}
