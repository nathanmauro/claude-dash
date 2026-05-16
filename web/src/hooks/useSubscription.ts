import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export function useSubscription() {
  return useQuery({
    queryKey: ["subscription-usage"],
    queryFn: api.subscription,
    staleTime: 60_000,
  });
}
