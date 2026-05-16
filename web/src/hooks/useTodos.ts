import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export function useTodos() {
  return useQuery({
    queryKey: ["todos"],
    queryFn: api.todos,
    staleTime: 30_000,
  });
}
