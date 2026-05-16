import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export function useDashboard(q: { from?: string; to?: string; date?: string }) {
  return useQuery({
    queryKey: ["dashboard", q.from ?? null, q.to ?? null, q.date ?? null],
    queryFn: () => api.dashboard(q),
    staleTime: 5_000,
  });
}
