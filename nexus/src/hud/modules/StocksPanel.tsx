'use client';

import type { ModuleFeed, StocksData } from '@/modules/types';
import { Bar, FeedState, Line, Provenance, Section, Spark } from './shared';
import { useT } from '@/i18n';

const money = (n: number, currency = 'USD') =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: n >= 1000 ? 0 : 2,
  }).format(n);

const pct = (n: number, digits = 2) => `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;

/** Positions, live prices, P/L and sector exposure. */
export function StocksPanel({ feed }: { feed: ModuleFeed<StocksData> }) {
  const t = useT();
  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const up = d.totalPnl >= 0;
  const dayUp = d.dayChangePct >= 0;

  return (
    <div>
      <div className="flex items-end justify-between">
        <span className="font-sans text-[30px] font-extralight leading-none text-lumen">
          {money(d.totalValue)}
        </span>
        <div className="text-right">
          <p className={`font-mono text-[13px] ${dayUp ? 'text-lock' : 'text-ember'}`}>
            {pct(d.dayChangePct)}
          </p>
          <p className="mt-0.5 font-mono text-[9px] tracking-[0.14em] text-ghost">
            {d.marketOpen ? t('stocks.open') : t('stocks.closed')}
          </p>
        </div>
      </div>

      <Section title={t('stocks.performance')}>
        <Line
          label={t('stocks.pnl')}
          value={`${money(d.totalPnl)} · ${pct(d.totalPnlPct, 1)}`}
          tone={up ? 'good' : 'warn'}
        />
        <Line label={t('stocks.cost')} value={money(d.totalCost)} tone="muted" />
        <Line label={t('stocks.positions')} value={String(d.holdings.length)} tone="muted" />
      </Section>

      <Section title={t('stocks.holdings')}>
        {d.holdings.map((h) => {
          const gain = h.pnl >= 0;
          return (
            <div key={h.symbol} className="border-b border-signal/8 py-2 last:border-0">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-[11px] tracking-[0.1em] text-lumen">{h.symbol}</span>
                <span className="hud-value">{money(h.price, h.currency)}</span>
              </div>
              <div className="mt-0.5 flex items-baseline justify-between">
                <span className="font-mono text-[9px] tracking-[0.1em] text-ghost">
                  {h.units} × {money(h.costBasis, h.currency)}
                </span>
                <span
                  className={`font-mono text-[10px] ${h.changePct >= 0 ? 'text-lock' : 'text-ember'}`}
                >
                  {pct(h.changePct)}
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="w-[92px] shrink-0">
                  <Spark values={h.history} tone={gain ? 'lock' : 'ember'} height={18} />
                </div>
                <span
                  className={`ml-auto font-mono text-[10px] ${gain ? 'text-lock' : 'text-ember'}`}
                >
                  {money(h.pnl, h.currency)} · {pct(h.pnlPct, 1)}
                </span>
              </div>
            </div>
          );
        })}
      </Section>

      <Section title={t('stocks.allocation')}>
        {d.allocation.map((slice) => (
          <div key={slice.label} className="py-[5px]">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-[10px] tracking-[0.08em] text-ghost">
                {slice.label}
              </span>
              <span className="hud-value">{Math.round(slice.weight * 100)}%</span>
            </div>
            <div className="mt-1">
              <Bar value={slice.weight} />
            </div>
          </div>
        ))}
      </Section>

      <Provenance feed={feed} />
    </div>
  );
}
