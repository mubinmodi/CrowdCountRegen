import { useEffect, useState } from "react";

/** useState that remembers its value in localStorage (best effort: storage may be unavailable). */
export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Private mode or blocked storage: keep the in-memory value only.
    }
  }, [key, value]);

  return [value, setValue] as const;
}
