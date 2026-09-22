import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import type { ModuleFeed, Project, ProjectsData } from '@/modules/types';

/**
 * Projects.
 *
 * The manifest at content/projects.json is the source of truth - descriptions,
 * media and prompt history are things only you know, and no API can supply
 * them. What IS fetched live is the GitHub side: stars, forks, language, open
 * issues and last push, so a project's card ages by itself.
 *
 * Unauthenticated GitHub allows 60 requests an hour per IP, which is ample at
 * one request per project on a five-minute cache. Set GITHUB_TOKEN to raise it.
 */

interface Manifest {
  projects: Array<Omit<Project, 'repo'> & { repo?: string }>;
}

interface RepoResponse {
  html_url: string;
  stargazers_count: number;
  forks_count: number;
  language: string | null;
  pushed_at: string | null;
  open_issues_count: number;
}

/** "https://github.com/owner/name" or "owner/name" -> "owner/name". */
function repoSlug(value: string): string | null {
  const cleaned = value.trim().replace(/\.git$/, '');
  const match = /github\.com[/:]([^/]+\/[^/]+)/.exec(cleaned);
  if (match) return match[1]!;
  return /^[\w.-]+\/[\w.-]+$/.test(cleaned) ? cleaned : null;
}

async function fetchRepo(slug: string, signal: AbortSignal): Promise<Project['repo']> {
  const headers: Record<string, string> = {
    accept: 'application/vnd.github+json',
    'user-agent': 'NEXUS/1.0',
  };
  if (process.env.GITHUB_TOKEN) headers.authorization = `Bearer ${process.env.GITHUB_TOKEN}`;

  try {
    const response = await fetch(`https://api.github.com/repos/${slug}`, {
      signal,
      headers,
      next: { revalidate: 300 },
    });
    if (!response.ok) return undefined;
    const repo = (await response.json()) as RepoResponse;
    return {
      url: repo.html_url,
      stars: repo.stargazers_count,
      forks: repo.forks_count,
      language: repo.language,
      pushedAt: repo.pushed_at,
      openIssues: repo.open_issues_count,
    };
  } catch {
    return undefined;
  }
}

export async function fetchProjects(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<ProjectsData>> {
  let manifest: Manifest;
  try {
    const path = join(process.cwd(), 'content', 'projects.json');
    manifest = JSON.parse(await readFile(path, 'utf8')) as Manifest;
  } catch {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'content/projects.json',
      setupHint: 'Create content/projects.json to populate this module.',
    };
  }

  const projects = await Promise.all(
    (manifest.projects ?? []).map(async (entry): Promise<Project> => {
      const slug = entry.repo ? repoSlug(entry.repo) : null;
      return {
        ...entry,
        assets: entry.assets ?? [],
        prompts: entry.prompts ?? [],
        tags: entry.tags ?? [],
        repo: slug ? await fetchRepo(slug, signal) : undefined,
      };
    }),
  );

  return {
    status: 'live',
    error: null,
    fetchedAt: Date.now(),
    source: projects.some((p) => p.repo) ? 'Manifest + GitHub' : 'Manifest',
    data: { projects },
  };
}
