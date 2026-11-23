/** Poll task status only; this utility never submits generation requests. */
interface Scheduler {
  set(callback: () => void, milliseconds: number): unknown;
  clear(handle: unknown): void;
}
interface PollOptions<T> {
  load: (signal: AbortSignal) => Promise<T>;
  pending: (value: T) => boolean;
  onData: (value: T) => void;
  onError: (error: unknown) => void;
  onLoading?: (value: boolean) => void;
  interval?: number;
  timeout?: number;
  scheduler?: Scheduler;
}

export function startTaskPolling<T>(options: PollOptions<T>) {
  const clock = options.scheduler || { set: (callback: () => void, milliseconds: number) => setTimeout(callback, milliseconds), clear: (handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>) };
  let stopped = false;
  let generation = 0;
  let next: unknown;
  let deadline: unknown;
  let controller: AbortController | undefined;

  async function refresh() {
    if (stopped) return;
    const current = ++generation;
    clock.clear(next); clock.clear(deadline); controller?.abort();
    const request = new AbortController(); controller = request;
    const timeout = clock.set(() => request.abort(), options.timeout || 8000); deadline = timeout;
    options.onLoading?.(true);
    try {
      const value = await options.load(request.signal);
      if (stopped || current !== generation) return;
      options.onData(value);
      if (options.pending(value)) next = clock.set(() => { void refresh(); }, options.interval || 3000);
    } catch (error) {
      if (stopped || current !== generation) return;
      options.onError(error);
      // A read failure does not resubmit a task. Let the user refresh rather
      // than keep making requests when the server is unavailable.
    } finally {
      clock.clear(timeout);
      if (!stopped && current === generation) options.onLoading?.(false);
    }
  }

  void refresh();
  return {
    refresh,
    stop() { stopped = true; generation++; clock.clear(next); clock.clear(deadline); controller?.abort(); },
  };
}
