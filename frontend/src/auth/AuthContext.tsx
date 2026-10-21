import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, type GirisSonucu, type Kullanici } from "../api/client";

interface AuthDurumu {
  kullanici: Kullanici | null;
  yukleniyor: boolean;
  girisYap: (username: string, password: string) => Promise<GirisSonucu>;
  mfaDogrula: (pending_token: string, code: string) => Promise<GirisSonucu>;
  cikisYap: () => Promise<void>;
  /** Sunucu her uçta kendi kontrolünü yapar; bu yalnız arayüzü kısmak için. */
  yetkili: (...kodlar: string[]) => boolean;
}

const Ctx = createContext<AuthDurumu | null>(null);

/**
 * Rol kapsamının kısa etiketi (TUMU için boş: kısıt yok, etiket basılmaz).
 *
 * Ekranlar eskiden yalnız `KENDI_MUSTERILERI`'yi tanıyordu; yeni kapsamlı
 * (birim / kendi işleri) rol "tüm kayıtlar" gibi görünüyordu. Seçenek listesi
 * ve uzun açıklama sunucudan (`/api/kapsamlar`) gelir; burası yalnız rozet.
 */
export const KAPSAM_ETIKETLERI: Record<string, string> = {
  TUMU: "",
  KENDI_MUSTERILERI: "yalnız kendi müşterileri",
  KENDI_BIRIMI: "yalnız kendi birimi",
  KENDI_ISLERI: "yalnız kendi işleri",
};

/** Sunucudaki kapsam ve birim kataloğu (`/api/kapsamlar`, `sistem.kullanici`). */
export interface KapsamKatalogu {
  kapsamlar: { kod: string; ad: string; aciklama: string; birim_zorunlu: boolean }[];
  birimler: { kod: string; ad: string }[];
}

export const kapsamKataloguSorgusu = {
  queryKey: ["kapsam-katalogu"],
  queryFn: () => api.get<KapsamKatalogu>("/api/kapsamlar"),
  staleTime: Infinity,
};

export function kapsamEtiketi(scope: string | undefined): string {
  if (!scope) return "";
  return KAPSAM_ETIKETLERI[scope] ?? scope.replaceAll("_", " ").toLocaleLowerCase("tr");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [kullanici, setKullanici] = useState<Kullanici | null>(null);
  const [yukleniyor, setYukleniyor] = useState(true);

  useEffect(() => {
    api
      .get<Kullanici>("/api/auth/me")
      .then(setKullanici)
      .catch(() => setKullanici(null))
      .finally(() => setYukleniyor(false));
  }, []);

  const girisYap = useCallback(async (username: string, password: string) => {
    const sonuc = await api.post<GirisSonucu>("/api/auth/login", { username, password });
    if (sonuc.user) setKullanici(sonuc.user);
    return sonuc;
  }, []);

  const mfaDogrula = useCallback(async (pending_token: string, code: string) => {
    const sonuc = await api.post<GirisSonucu>("/api/auth/login/mfa", { pending_token, code });
    if (sonuc.user) setKullanici(sonuc.user);
    return sonuc;
  }, []);

  const cikisYap = useCallback(async () => {
    await api.post("/api/auth/logout");
    setKullanici(null);
  }, []);

  const yetkili = useCallback(
    (...kodlar: string[]) => kodlar.every((k) => kullanici?.permissions.includes(k) ?? false),
    [kullanici],
  );

  const deger = useMemo(
    () => ({ kullanici, yukleniyor, girisYap, mfaDogrula, cikisYap, yetkili }),
    [kullanici, yukleniyor, girisYap, mfaDogrula, cikisYap, yetkili],
  );

  return <Ctx.Provider value={deger}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthDurumu {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth, AuthProvider içinde kullanılmalı");
  return ctx;
}
