"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(Boolean(path));
  const current = useRef(path);
  current.current = path;

  const reload = useCallback(async () => {
    if (!current.current) return null;
    const requested = current.current;
    setLoading(true);
    try {
      const value = await api<T>(requested);
      if (current.current === requested) {
        setData(value);
        setError("");
      }
      return value;
    } catch (err) {
      if (current.current === requested) setError(err instanceof ApiError ? err.message : "Something went wrong");
      return null;
    } finally {
      if (current.current === requested) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (path) reload();
  }, [path, reload]);

  return { data, setData, error, loading, reload };
}

export function useLocalState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw) setValue(JSON.parse(raw));
    } catch {
      /* storage unavailable */
    }
  }, [key]);
  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* storage unavailable */
      }
    },
    [key],
  );
  return [value, update] as const;
}

export function errorMessage(err: unknown, fallback = "Something went wrong") {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}
