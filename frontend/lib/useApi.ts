"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

// GET a path and keep {data, error}. `reload()` refetches; `loading` is true until the current path has answered.
export function useApi<T>(path: string | null) {
  const [state, setState] = useState<{ data: T | null; error: string | null; loaded: string | null }>({
    data: null,
    error: null,
    loaded: null,
  });
  const [version, setVersion] = useState(0);
  const key = path === null ? null : `${path}#${version}`;

  useEffect(() => {
    if (path === null) return;
    let live = true;
    const k = `${path}#${version}`;
    api<T>(path).then((r) => {
      if (!live) return;
      setState((s) => (r.ok ? { data: r.data, error: null, loaded: k } : { data: s.data, error: r.message, loaded: k }));
    });
    return () => {
      live = false;
    };
  }, [path, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data: state.data, error: state.error, loading: key !== null && state.loaded !== key, reload };
}
