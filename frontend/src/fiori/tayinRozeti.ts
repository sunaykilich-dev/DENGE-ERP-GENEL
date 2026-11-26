/**
 * Tayin bekleyen iş sayısı (2026-11-18): menüde Operasyon Merkezi rozeti ve
 * tarayıcı sekmesi başlığı. Şef başka bir ekrandayken de tayinsiz iş kaçmasın.
 * Yalnız `operasyon.gor` sahibinde sorgulanır; dakikada bir yenilenir.
 */
import { useQuery } from "@tanstack/react-query";

import { operasyonApi } from "../api/servisOperasyon";
import { useAuth } from "../auth/AuthContext";

export function useTayinSayilari() {
  const { yetkili } = useAuth();
  return useQuery({
    queryKey: ["operasyon-tayin-sayilari"],
    queryFn: operasyonApi.tayinSayilari,
    enabled: yetkili("operasyon.gor"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
