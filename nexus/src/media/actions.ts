import { useMediaStore } from "@/stores/useMediaStore";
import { getAudio } from "@/audio/AudioEngine";
import { log } from "@/stores/useLogStore";
import { t } from "@/i18n";
import type { MediaItem, ShapeSpec } from "./types";

/**
 * Placing things in the room.
 *
 * One entry point per verb, callable from the assistant, from a module, or
 * from a click. Keeping them here rather than in the store means the sound,
 * the log line and the proxying happen once, however the request arrived.
 */

/** Remote media always goes through the proxy; data URIs never do. */
export function proxied(url: string): string {
  if (url.startsWith("data:") || url.startsWith("/")) return url;
  return `/api/media?url=${encodeURIComponent(url)}`;
}

export function showImage(
  url: string,
  options: {
    title?: string;
    caption?: string;
    origin?: MediaItem["origin"];
  } = {},
): string {
  const id = useMediaStore.getState().show({
    kind: "image",
    src: proxied(url),
    title: options.title,
    caption: options.caption,
    origin: options.origin ?? "assistant",
  });
  getAudio().expand();
  log.ok(
    t("log.mediaShown", { what: options.title ?? options.caption ?? "image" }),
  );
  return id;
}

export function showVideo(
  url: string,
  options: {
    title?: string;
    caption?: string;
    origin?: MediaItem["origin"];
  } = {},
): string {
  const id = useMediaStore.getState().show({
    kind: "video",
    src: proxied(url),
    title: options.title,
    caption: options.caption,
    origin: options.origin ?? "assistant",
  });
  getAudio().expand();
  log.ok(
    t("log.mediaShown", { what: options.title ?? options.caption ?? "video" }),
  );
  return id;
}

export function showShape(spec: ShapeSpec, title?: string): string {
  const id = useMediaStore.getState().show({
    kind: "shape",
    shape: spec,
    title: title ?? spec.kind,
    origin: "assistant",
  });
  getAudio().confirm();
  log.ok(t("log.mediaShape", { shape: spec.kind.toUpperCase() }));
  return id;
}

/**
 * Ask the model for a picture.
 *
 * Fire-and-forget on purpose: generation takes several seconds and the command
 * layer is synchronous, so the assistant acknowledges immediately and the image
 * lands when it lands. The store carries the pending state so the room can show
 * that something is coming.
 */
export function generateImage(prompt: string): void {
  const store = useMediaStore.getState();
  store.setGenerating(true);
  log.sys(t("log.mediaGenerating"));
  getAudio().arcane();

  void (async () => {
    try {
      const response = await fetch("/api/imagine", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const body = (await response.json()) as { src?: string; error?: string };

      if (!response.ok || !body.src) {
        useMediaStore.getState().setError(body.error ?? "Generation failed");
        log.warn(
          t("log.mediaFailed", {
            error: (body.error ?? "").slice(0, 40).toUpperCase(),
          }),
        );
        getAudio().deny();
        return;
      }

      useMediaStore.getState().setGenerating(false);
      useMediaStore.getState().show({
        kind: "image",
        src: body.src,
        title: prompt.slice(0, 60),
        caption: t("media.generated"),
        origin: "generated",
      });
      getAudio().expand();
      log.ok(t("log.mediaShown", { what: prompt.slice(0, 24) }));
    } catch (error) {
      useMediaStore.getState().setError(String(error));
      getAudio().deny();
    }
  })();
}

export function clearMedia(): void {
  if (useMediaStore.getState().stack.length === 0) return;
  useMediaStore.getState().clear();
  getAudio().collapse();
  log.sys(t("log.mediaCleared"));
}
