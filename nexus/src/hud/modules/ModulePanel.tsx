'use client';

import { useModuleFeed } from '@/modules/useModuleFeed';
import { useFeedStore } from '@/modules/store';
import type { ModuleFeed } from '@/modules/types';
import { WeatherPanel } from './WeatherPanel';
import { StocksPanel } from './StocksPanel';
import { NewsPanel } from './NewsPanel';
import { SportsPanel } from './SportsPanel';
import { CalendarPanel } from './CalendarPanel';
import { ProjectsPanel } from './ProjectsPanel';
import { YoutubePanel } from './YoutubePanel';
import { InstagramPanel } from './InstagramPanel';
import { SystemPanel } from './SystemPanel';
import { MusicPanel } from './MusicPanel';
import { AiPanel } from './AiPanel';
import { emptyFeed } from '@/modules/types';

/**
 * Expanded module content.
 *
 * One switch, ten panels. The alternative - a generic renderer driven by a
 * schema - would make every module look the same, and the whole point of Phase
 * 3 is that a portfolio and a weather forecast are not the same shape of thing.
 *
 * Fetching happens here rather than in each panel so a panel is a pure function
 * of its feed and can be rendered in isolation.
 */
export function ModulePanel({ id }: { id: string }) {
  // Subscribes and, for server-backed modules, polls while expanded.
  useModuleFeed(id, true);
  const feed = (useFeedStore((s) => s.feeds[id]) ?? emptyFeed()) as ModuleFeed<never>;

  switch (id) {
    case 'weather':
      return <WeatherPanel feed={feed} />;
    case 'stocks':
      return <StocksPanel feed={feed} />;
    case 'news':
      return <NewsPanel feed={feed} />;
    case 'sports':
      return <SportsPanel feed={feed} />;
    case 'calendar':
      return <CalendarPanel feed={feed} />;
    case 'projects':
      return <ProjectsPanel feed={feed} />;
    case 'instagram':
      return <InstagramPanel feed={feed} />;
    case 'youtube':
      return <YoutubePanel feed={feed} />;
    case 'system':
      return <SystemPanel feed={feed} />;
    case 'music':
      return <MusicPanel feed={feed} />;
    case 'ai':
      return <AiPanel feed={feed} />;
    default:
      return null;
  }
}
