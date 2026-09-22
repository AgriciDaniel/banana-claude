'use client';

import type { ModuleFeed, WeatherData } from '@/modules/types';
import { Bar, FeedState, Line, Provenance, Section, Spark } from './shared';
import { useLocaleTag, useT } from '@/i18n';

/** Live conditions, the 24-hour curve and the week. */
export function WeatherPanel({ feed }: { feed: ModuleFeed<WeatherData> }) {
  const t = useT();
  const tag = useLocaleTag();
  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const temps = d.hourly.map((h) => h.temp);
  const rain = d.hourly.reduce((sum, h) => sum + h.precip, 0);

  return (
    <div>
      <div className="flex items-end justify-between">
        <span className="font-sans text-[44px] font-extralight leading-none text-lumen">
          {Math.round(d.temperature)}°
        </span>
        <div className="text-right">
          <p className="font-mono text-[10px] tracking-[0.16em] text-signal">
            {d.description.toUpperCase()}
          </p>
          <p className="mt-1 font-mono text-[9px] tracking-[0.14em] text-ghost">
            {d.place.toUpperCase()}
          </p>
        </div>
      </div>

      <Section title={t('weather.now')}>
        <Line label={t('weather.feels')} value={`${Math.round(d.feelsLike)}°`} />
        <Line label={t('weather.wind')} value={`${Math.round(d.wind)} km/h`} />
        <Line label={t('weather.humidity')} value={`${d.humidity}%`} />
        <Line label={t('weather.pressure')} value={`${Math.round(d.pressure)} hPa`} />
        <Line
          label={t('weather.cloud')}
          value={`${Math.round(d.cloudCover)}%`}
          tone={d.cloudCover > 80 ? 'muted' : 'default'}
        />
      </Section>

      <Section title={t('weather.next24')}>
        <Spark values={temps} tone={d.condition === 'storm' ? 'ember' : 'signal'} />
        <div className="mt-1 flex justify-between font-mono text-[9px] text-ghost">
          <span>{Math.round(Math.min(...temps))}°</span>
          <span>
            {rain > 0.05 ? `${rain.toFixed(1)} mm` : t('weather.dry')}
          </span>
          <span>{Math.round(Math.max(...temps))}°</span>
        </div>
      </Section>

      <Section title={t('weather.forecast')}>
        {d.daily.slice(0, 5).map((day) => {
          const label = new Date(day.day).toLocaleDateString(tag, { weekday: 'short' });
          return (
            <div key={day.day} className="flex items-center gap-3 py-[3px]">
              <span className="w-9 font-mono text-[10px] uppercase text-ghost">{label}</span>
              <span className="w-8 text-right font-mono text-[10px] text-ghost">
                {Math.round(day.min)}°
              </span>
              <div className="flex-1">
                <Bar
                  value={(day.max - day.min) / 22}
                  tone={day.condition === 'storm' || day.condition === 'rain' ? 'ember' : 'signal'}
                />
              </div>
              <span className="w-8 text-right hud-value">{Math.round(day.max)}°</span>
            </div>
          );
        })}
      </Section>

      <p className="mt-1 font-mono text-[9px] leading-[15px] tracking-[0.1em] text-signal/70">
        {t('weather.envNote')}
      </p>
      <Provenance feed={feed} />
    </div>
  );
}
