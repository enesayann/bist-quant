import { useMemo, useSyncExternalStore } from "react";
import { getHistory, getQuote, getScanner } from "./client";
import type { MarketHistory, Quote, ScannerData } from "./types";

interface State<T> {
  data: T | null;
  error: string | null;
  refreshing: boolean;
  receivedAt: number | null;
}
class Resource<T> {
  state: State<T> = {
    data: null,
    error: null,
    refreshing: false,
    receivedAt: null,
  };
  listeners = new Set<() => void>();
  timer: number | undefined;
  active: AbortController | null = null;
  failures = 0;
  constructor(
    private fetcher: (signal: AbortSignal) => Promise<T>,
    private interval: number,
  ) {}
  snapshot = () => this.state;
  emit(next: Partial<State<T>>) {
    this.state = { ...this.state, ...next };
    this.listeners.forEach((listener) => listener());
  }
  schedule(delay = this.interval) {
    window.clearTimeout(this.timer);
    if (this.listeners.size && !document.hidden)
      this.timer = window.setTimeout(() => void this.refresh(), delay);
  }
  visibility = () => {
    if (document.hidden) window.clearTimeout(this.timer);
    else
      this.schedule(
        Math.max(
          0,
          this.interval - (Date.now() - (this.state.receivedAt ?? 0)),
        ),
      );
  };
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    if (this.listeners.size === 1) {
      document.addEventListener("visibilitychange", this.visibility);
      // Defer first load so React StrictMode's rehearsal causes no duplicate GET.
      this.schedule(
        this.state.receivedAt
          ? Math.max(0, this.interval - (Date.now() - this.state.receivedAt))
          : 0,
      );
    }
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size) {
        window.clearTimeout(this.timer);
        document.removeEventListener("visibilitychange", this.visibility);
        this.active?.abort();
      }
    };
  };
  refresh = async () => {
    if (this.active || document.hidden || !this.listeners.size) return;
    const controller = new AbortController();
    this.active = controller;
    this.emit({ refreshing: true });
    try {
      const data = await this.fetcher(controller.signal);
      if (!controller.signal.aborted) {
        this.failures = 0;
        this.emit({ data, error: null, receivedAt: Date.now() });
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        this.failures++;
        this.emit({ error: (error as Error).message });
      }
    } finally {
      this.active = null;
      this.emit({ refreshing: false });
      this.schedule(
        controller.signal.aborted
          ? 0
          : Math.min(300000, this.interval * 2 ** Math.min(this.failures, 3)),
      );
    }
  };
}
const resources = new Map<string, Resource<unknown>>();
function useResource<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  interval: number,
) {
  const resource = useMemo(() => {
    if (!resources.has(key))
      resources.set(key, new Resource(fetcher, interval));
    return resources.get(key)! as Resource<T>;
    // Stable endpoint key owns its fetcher; renders never initiate requests.
  }, [key]);
  return {
    ...useSyncExternalStore(
      resource.subscribe,
      resource.snapshot,
      resource.snapshot,
    ),
    refresh: resource.refresh,
  };
}
export const useScanner = () =>
  useResource<ScannerData>("scanner", getScanner, 60000);
export const useQuote = (ticker: string) =>
  useResource<Quote>(
    `quote:${ticker}`,
    (signal) => getQuote(ticker, signal),
    45000,
  );
export const useHistory = (ticker: string) =>
  useResource<MarketHistory>(
    `history:${ticker}:1d:1y`,
    (signal) => getHistory(ticker, signal),
    300000,
  );
