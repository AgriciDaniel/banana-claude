import { lookup } from "node:dns/promises";
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
 * A proxy is also a classic hole to punch in a network, so the guards run in
 * order: no private address space -- checked against the RESOLVED addresses,
 * not merely the hostname -- no redirect chains, a size ceiling, and content
 * types checked against what the renderer can actually use.
 *
 * The host allowlist used to be the outermost guard. It is off by default now,
 * because an assistant asked to illustrate anything on the web cannot be told
 * in advance which six domains that will involve. Set NEXUS_MEDIA_STRICT=1 to
 * put it back, narrowing the proxy to the module CDNs and nothing else.
 *
 * Opening it moved real weight onto the address check. With an allowlist the
 * hostname could never be attacker-chosen, so resolving it was unnecessary;
 * without one, a perfectly public name pointing at 127.0.0.1 is the obvious
 * move, and the lookup below is what stops it.
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

function strictHosts(): boolean {
  return process.env.NEXUS_MEDIA_STRICT === "1";
}

/** True for any address inside a range this server could reach privately. */
function isPrivateAddress(address: string): boolean {
  const host = address.toLowerCase().replace(/^\[|\]$/g, "");

  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) {
    const [a, b] = host.split(".").map(Number) as [number, number];
    if (a === 10 || a === 127 || a === 0) return true;
    if (a === 192 && b === 168) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 169 && b === 254) return true;
    // Carrier-grade NAT, then everything reserved above unicast.
    if (a === 100 && b >= 64 && b <= 127) return true;
    if (a >= 224) return true;
    return false;
  }

  if (host.includes(":")) {
    if (host === "::1" || host === "::") return true;
    // Unique-local fc00::/7 and link-local fe80::/10.
    if (/^f[cd]/.test(host)) return true;
    if (/^fe[89ab]/.test(host)) return true;
    // An IPv4 address wearing an IPv6 hat.
    const tail = host.split(":").pop() ?? "";
    if (tail.includes(".")) return isPrivateAddress(tail);
    return false;
  }

  return false;
}

/** Reject a literal address, or a name that can only mean this machine. */
function isPrivateHost(hostname: string): boolean {
  const host = hostname.toLowerCase();
  if (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host.endsWith(".local") ||
    host.endsWith(".internal")
  ) {
    return true;
  }
  if (host.startsWith("[") || /^[\d.]+$/.test(host) || host.includes(":")) {
    return isPrivateAddress(host);
  }
  return false;
}

/**
 * Resolve the name and reject if ANY answer is private. Every answer matters
 * rather than the first: a name returning both a public address and a loopback
 * one would otherwise be a coin flip decided by resolver ordering.
 */
async function resolvesPrivately(hostname: string): Promise<boolean> {
  if (/^[\d.]+$/.test(hostname) || hostname.includes(":")) return false;
  try {
    const answers = await lookup(hostname, { all: true });
    if (answers.length === 0) return true;
    return answers.some((a) => isPrivateAddress(a.address));
  } catch {
    // A name that will not resolve is not a name worth fetching.
    return true;
  }
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
  if (strictHosts()) {
    const permitted = allowlist().some(
      (entry) => host === entry || host.endsWith(`.${entry}`),
    );
    if (!permitted) {
      return new Response(`Host not allowed: ${host}`, { status: 403 });
    }
  } else if (await resolvesPrivately(host)) {
    return new Response("Refused", { status: 403 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      // manual: a redirect could land somewhere the checks never approved.
      redirect: "manual",
      signal: request.signal,
      headers: {
        /*
         * A bare "NEXUS/1.0" is rejected outright by several large hosts --
         * Wikimedia answers 400 to it -- so the agent says what this is and
         * where to complain. Identifying honestly is what gets served; the
         * alternative would be impersonating a browser, which is not the same
         * thing and not something to do on the user's behalf.
         */
        "user-agent":
          "NEXUS/1.0 (spatial computing environment; +https://github.com/AgriciDaniel/banana-claude)",
        accept: "image/*,video/*;q=0.9,*/*;q=0.1",
      },
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
