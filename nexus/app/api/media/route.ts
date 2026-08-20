import type { NextRequest } from "next/server";

/**
 * Media proxy.
 *
 * Two reasons this exists rather than pointing a texture straight at a remote
 * URL. First, WebGL refuses to sample a cross-origin image without CORS
 * headers, and Instagram's CDN does not send them. Second, a texture loaded
 * directly would leak the viewer's IP and referrer to whoever hosts it, on
 * every frame of a session they never opted into.
 *
 * A proxy is also a classic SSRF hole, so it is deliberately narrow: an
 * allowlist of hosts, no private address space, no redirect chains, a size
 * ceiling, and content types checked against what the renderer can actually
 * use.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Hosts the modules genuinely need. Suffix match on the hostname. */
const ALLOWED = [
  "cdninstagram.com",
  "fbcdn.net",
  "githubusercontent.com",
  "github.com",
  "ggpht.com",
  "ytimg.com",
];

/** Extra hosts, comma separated, for whatever the manifest points at. */
function allowlist(): string[] {
  const extra = (process.env.NEXUS_MEDIA_HOSTS ?? "")
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean);
  return [...ALLOWED, ...extra];
}

const MAX_BYTES = 12 * 1024 * 1024;

/** Reject anything that resolves inside the network this server sits on. */
function isPrivateHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  if (
    host === "localhost" ||
    host.endsWith(".local") ||
    host.endsWith(".internal")
  )
    return true;
  // Literal IPs only; hostnames are covered by the allowlist.
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) {
    const [a, b] = host.split(".").map(Number) as [number, number];
    if (a === 10 || a === 127 || a === 0) return true;
    if (a === 192 && b === 168) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 169 && b === 254) return true;
  }
  if (host.startsWith("[") || host.includes(":")) return true;
  return false;
}

export async function GET(request: NextRequest) {
  const raw = request.nextUrl.searchParams.get("url");
  if (!raw) return new Response("Missing url", { status: 400 });

  let target: URL;
  try {
    target = new URL(raw);
  } catch {
    return new Response("Malformed url", { status: 400 });
  }

  if (target.protocol !== "https:" && target.protocol !== "http:") {
    return new Response("Unsupported protocol", { status: 400 });
  }
  if (isPrivateHost(target.hostname)) {
    return new Response("Refused", { status: 403 });
  }

  const host = target.hostname.toLowerCase();
  const permitted = allowlist().some(
    (entry) => host === entry || host.endsWith(`.${entry}`),
  );
  if (!permitted) {
    return new Response(`Host not allowed: ${host}`, { status: 403 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      // manual: a redirect could land somewhere the allowlist never approved.
      redirect: "manual",
      signal: request.signal,
      headers: { "user-agent": "NEXUS/1.0" },
    });
  } catch {
    return new Response("Upstream unreachable", { status: 502 });
  }

  if (upstream.status >= 300 && upstream.status < 400) {
    return new Response("Upstream redirected; not followed", { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    // A missing or forbidden asset is the caller's problem, not a gateway
    // failure -- pass 4xx through so the caller can tell "wrong URL" apart
    // from "the remote host is down".
    const status =
      upstream.status >= 400 && upstream.status < 500 ? upstream.status : 502;
    return new Response(`Upstream returned ${upstream.status}`, { status });
  }

  const type = upstream.headers.get("content-type") ?? "";
  if (!type.startsWith("image/") && !type.startsWith("video/")) {
    return new Response(`Refusing content type ${type || "unknown"}`, {
      status: 415,
    });
  }

  const declared = Number(upstream.headers.get("content-length") ?? "0");
  if (declared > MAX_BYTES) {
    return new Response("Too large", { status: 413 });
  }

  return new Response(upstream.body, {
    headers: {
      "content-type": type,
      // Same-origin from the browser's point of view, so the texture loads.
      "cache-control": "public, max-age=3600, immutable",
      "content-security-policy": "default-src 'none'",
      "x-content-type-options": "nosniff",
    },
  });
}
