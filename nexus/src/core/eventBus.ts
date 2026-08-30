/**
 * Minimal typed event bus. Zero dependencies.
 *
 * Used for cross-layer signals that must NOT trigger React renders — gesture
 * engine -> audio, physics -> shards, carousel -> log.
 */

type Handler<T> = (payload: T) => void;

export function createBus<Events extends object>() {
  const map = new Map<keyof Events, Set<Handler<never>>>();

  return {
    on<K extends keyof Events>(type: K, handler: Handler<Events[K]>): () => void {
      let set = map.get(type);
      if (!set) {
        set = new Set();
        map.set(type, set);
      }
      set.add(handler as Handler<never>);
      return () => {
        set!.delete(handler as Handler<never>);
      };
    },
    emit<K extends keyof Events>(type: K, payload: Events[K]): void {
      const set = map.get(type);
      if (!set) return;
      for (const handler of set) (handler as unknown as Handler<Events[K]>)(payload);
    },
    clear(): void {
      map.clear();
    },
  };
}
