'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { ModuleFeed, ProjectsData } from '@/modules/types';
import { FeedState, Line, Provenance, Section } from './shared';
import { useLocaleTag, useT } from '@/i18n';
import { getAudio } from '@/audio/AudioEngine';

/**
 * Each project is its own world.
 *
 * The list is a switcher, not the content: picking one replaces the rail with
 * that project's media, description, prompt history and live repository state.
 */
export function ProjectsPanel({ feed }: { feed: ModuleFeed<ProjectsData> }) {
  const t = useT();
  const tag = useLocaleTag();
  const [openId, setOpenId] = useState<string | null>(null);

  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const project = d.projects.find((p) => p.id === openId) ?? null;

  if (!project) {
    return (
      <div>
        <Section title={t('projects.all')}>
          {d.projects.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setOpenId(p.id);
                getAudio().confirm();
              }}
              className="group w-full border-b border-signal/8 py-2.5 text-left last:border-0"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-sans text-[13px] text-lumen transition-colors group-hover:text-signal">
                  {p.name}
                </span>
                <span
                  className={`font-mono text-[9px] tracking-[0.16em] ${
                    p.status === 'active' ? 'text-lock' : p.status === 'paused' ? 'text-ember' : 'text-ghost'
                  }`}
                >
                  {t(`projects.status.${p.status}` as 'projects.status.active')}
                </span>
              </div>
              <p className="mt-0.5 font-mono text-[9.5px] leading-[15px] text-ghost">{p.tagline}</p>
              {p.repo && (
                <p className="mt-1 font-mono text-[9px] tracking-[0.12em] text-ghost/70">
                  {'\u2605'} {p.repo.stars} · {p.repo.language ?? '—'} · {p.repo.openIssues}{' '}
                  {t('projects.issues')}
                </p>
              )}
            </button>
          ))}
        </Section>
        <Provenance feed={feed} />
      </div>
    );
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={project.id}
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -20 }}
        transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
      >
        <button
          type="button"
          onClick={() => setOpenId(null)}
          className="font-mono text-[9px] tracking-[0.2em] text-ghost transition-colors hover:text-signal"
        >
          {'\u2190'} {t('projects.back')}
        </button>

        <h4 className="mt-2 font-sans text-[20px] font-light leading-tight text-lumen">
          {project.name}
        </h4>
        <p className="mt-1 font-mono text-[9.5px] leading-[15px] tracking-[0.08em] text-signal">
          {project.tagline.toUpperCase()}
        </p>

        <p className="mt-3 font-sans text-[12px] leading-[19px] text-lumen/85">
          {project.description}
        </p>

        {project.tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {project.tags.map((tagName) => (
              <span
                key={tagName}
                className="border border-signal/20 px-1.5 py-0.5 font-mono text-[8.5px] tracking-[0.1em] text-ghost"
              >
                {tagName}
              </span>
            ))}
          </div>
        )}

        {project.assets.length > 0 && (
          <Section title={t('projects.media')}>
            <div className="grid grid-cols-2 gap-1.5">
              {project.assets.map((asset) => (
                <figure key={asset.url} className="overflow-hidden border border-signal/15">
                  {asset.kind === 'video' ? (
                    <video src={asset.url} muted loop autoPlay playsInline className="h-20 w-full object-cover" />
                  ) : (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img src={asset.url} alt={asset.caption ?? project.name} className="h-20 w-full object-cover" />
                  )}
                </figure>
              ))}
            </div>
          </Section>
        )}

        {project.repo && (
          <Section title={t('projects.repo')}>
            <Line label={t('projects.stars')} value={project.repo.stars.toLocaleString('en-US')} />
            <Line label={t('projects.forks')} value={String(project.repo.forks)} tone="muted" />
            <Line label={t('projects.language')} value={project.repo.language ?? '—'} tone="muted" />
            <Line label={t('projects.openIssues')} value={String(project.repo.openIssues)} tone="muted" />
            {project.repo.pushedAt && (
              <Line
                label={t('projects.pushed')}
                value={new Date(project.repo.pushedAt).toLocaleDateString(tag, {
                  day: 'numeric',
                  month: 'short',
                  year: 'numeric',
                })}
                tone="muted"
              />
            )}
            <a
              href={project.repo.url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1.5 inline-block font-mono text-[9px] tracking-[0.18em] text-ghost transition-colors hover:text-signal"
            >
              {t('projects.openRepo')}
            </a>
          </Section>
        )}

        {project.prompts.length > 0 && (
          <Section title={t('projects.prompts')}>
            {project.prompts.map((prompt, i) => (
              <div key={i} className="border-l border-signal/25 py-1.5 pl-2.5">
                <p className="font-mono text-[8.5px] tracking-[0.16em] text-ghost">
                  {prompt.at.toUpperCase()}
                  {prompt.model ? ` · ${prompt.model}` : ''}
                </p>
                <p className="mt-1 font-sans text-[11px] leading-[17px] text-lumen/80">
                  {prompt.text}
                </p>
              </div>
            ))}
          </Section>
        )}

        <Provenance feed={feed} />
      </motion.div>
    </AnimatePresence>
  );
}
