import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { api, ApiError, type User } from "./api";

export function useCurrentUser() {
  return useQuery<User | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.me();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: Infinity,
  });
}

export function useAuthActions() {
  const qc = useQueryClient();
  const onAuth = (user: User | null) => {
    qc.clear();
    qc.setQueryData(["me"], user);
  };
  return {
    login: useMutation({
      mutationFn: (v: { email: string; password: string }) => api.login(v.email, v.password),
      onSuccess: onAuth,
    }),
    signup: useMutation({
      mutationFn: (v: { name: string; email: string; password: string }) =>
        api.signup(v.name, v.email, v.password),
      onSuccess: onAuth,
    }),
    logout: useMutation({ mutationFn: api.logout, onSuccess: () => onAuth(null) }),
  };
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: user, isPending } = useCurrentUser();
  const location = useLocation();
  if (isPending) return <div className="p-8 font-mono text-[12px] tracking-wider text-mute">LOADING…</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}
