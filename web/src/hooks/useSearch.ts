import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";

export function useSearch(q: string, minLen = 3) {
  const [debounced, setDebounced] = useState(q);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(q), 150);
    return () => clearTimeout(id);
  }, [q]);
  return useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.search(debounced),
    enabled: debounced.trim().length >= minLen,
    staleTime: 30_000,
  });
}
