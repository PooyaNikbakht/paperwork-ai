"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiUrl, ApiError } from "@/lib/api";
import type { Batch } from "@/lib/types";

/**
 * A batch kept live: server-sent events when they work, polling when they don't.
 */
export function useBatch(id: string | undefined) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [gone, setGone] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      setBatch(await api.batch(id));
      setError(null);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 404) setGone(true);
      setError(err);
    }
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let closed = false;
    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(() => void refresh(), 2000);
    };
    api
      .batch(id)
      .then((b) => {
        if (!closed) setBatch(b);
      })
      .catch((e: ApiError) => {
        if (closed) return;
        if (e.status === 404) setGone(true);
        setError(e);
      });
    let source: EventSource | null = null;
    if (typeof EventSource !== "undefined") {
      source = new EventSource(apiUrl(`/batches/${id}/events`));
      source.addEventListener("batch", (e) => {
        if (closed) return;
        setBatch(JSON.parse((e as MessageEvent).data) as Batch);
        setError(null);
      });
      source.addEventListener("gone", () => {
        setGone(true);
        source?.close();
      });
      source.onerror = () => {
        // EventSource retries by itself; poll as well until it recovers.
        startPolling();
      };
      source.onopen = () => {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      };
    } else {
      startPolling();
    }
    return () => {
      closed = true;
      source?.close();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [id, refresh]);

  return { batch, setBatch, error, gone, refresh };
}
