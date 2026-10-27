import { useQuery } from "@tanstack/react-query";
import { api, type AppConfig } from "./api";

const fallback: AppConfig = { demo_mode: false, detector: "", video_idle_timeout_s: null };

/**
 * Deployment facts (e.g. demo mode) that never change while the page is open. `loaded` is
 * false until the server has answered; hide account controls until then so the demo doesn't
 * flash a sign-out button.
 */
export function useAppConfig(): AppConfig & { loaded: boolean } {
  const { data } = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });
  return { ...(data ?? fallback), loaded: data !== undefined };
}
