/**
 * Etkin şirket (DENGE TELEKOM / DENGE ELEKTRONİK / DENGE MOBİLİTE) — KARARLAR
 * 2026-11-04 §1.
 *
 * Etkin şirket SUNUCUDA, oturumda tutulur; ekran yalnız okur ve değiştirir:
 *  - `GET /api/oturum/sirketler` → `{aktif, sirketler: [{kod, ad, birimler}]}`
 *  - `PUT /api/oturum/aktif-sirket` `{kod}` → aynı şekil (403: üye değil).
 * Şirket değişince TanStack Query önbelleğinin TAMAMI sıfırlanır (başka
 * şirketin verisi bir an bile görünmesin) ve Ana Panel'e gidilir.
 *
 * Uç henüz yoksa (404/405, arka uç paketi gelmeden) `destekleniyor=false`:
 * seçici gizlenir, menü şirket süzgeçsiz çizilir. Bu yalnız görsel
 * kısıtlamadır; veri ayrımını sunucu kapsamı yapar.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import { createContext, useCallback, useContext, useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { ANA_PANEL_YOLU } from "../fiori/menu";
import { useAuth } from "./AuthContext";

export interface Sirket {
  kod: string;
  ad: string;
  birimler: string[];
}

export interface SirketYaniti {
  aktif: string | null;
  sirketler: Sirket[];
}

interface SirketDurumu {
  /** Uç var mı (yoksa seçici gizli, menü süzgeçsiz). */
  destekleniyor: boolean;
  sirketler: Sirket[];
  aktif: Sirket | null;
  /** Menü süzgeci; null = şirket süzgeci uygulanmaz. */
  aktifBirimler: ReadonlySet<string> | null;
  degistir: (kod: string) => void;
  degisiyor: boolean;
}

const SORGU_ANAHTARI = "oturum-sirketler";

/** Şirketi ayırt eden renk (üst çubuktaki küçük işaret). */
const SIRKET_RENKLERI: Record<string, string> = {
  TELEKOM: "#2f80ed",
  ELEKTRONIK: "#f2994a",
  MOBILITE: "#27ae60",
};
const YEDEK_RENKLER = ["#9b51e0", "#eb5757", "#00a3a3", "#bdbd00"];

export function sirketRengi(kod: string | undefined): string {
  if (!kod) return "#8c99a6";
  if (SIRKET_RENKLERI[kod]) return SIRKET_RENKLERI[kod];
  let h = 0;
  for (const c of kod) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return YEDEK_RENKLER[h % YEDEK_RENKLER.length];
}

/** `/api/auth/me` şirket alanları nesne dizisiyse ilk çizimde kullanılır. */
function oturumdanBaslangic(k: unknown): SirketYaniti | undefined {
  const o = k as { aktif_sirket?: unknown; sirketler?: unknown } | null;
  if (!o || !Array.isArray(o.sirketler) || !o.sirketler.length) return undefined;
  const sirketler = o.sirketler.filter(
    (s): s is Sirket =>
      !!s && typeof s === "object" && typeof (s as Sirket).kod === "string" && Array.isArray((s as Sirket).birimler),
  );
  if (!sirketler.length) return undefined;
  return { aktif: typeof o.aktif_sirket === "string" ? o.aktif_sirket : null, sirketler };
}

const Ctx = createContext<SirketDurumu | null>(null);

export function SirketProvider({ children }: { children: React.ReactNode }) {
  const { kullanici } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const anahtar = useMemo(() => [SORGU_ANAHTARI, kullanici?.id], [kullanici?.id]);

  const sorgu = useQuery({
    queryKey: anahtar,
    queryFn: async (): Promise<SirketYaniti | null> => {
      try {
        return await api.get<SirketYaniti>("/api/oturum/sirketler");
      } catch (e) {
        // Uç yok (arka uç paketi gelmedi): seçici gizli, menü süzgeçsiz.
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) return null;
        throw e;
      }
    },
    enabled: !!kullanici,
    placeholderData: oturumdanBaslangic(kullanici),
    staleTime: 5 * 60_000,
  });

  const degisim = useMutation({
    mutationFn: (kod: string) => api.put<SirketYaniti>("/api/oturum/aktif-sirket", { kod }),
    onSuccess: async (veri) => {
      navigate(ANA_PANEL_YOLU);
      // Önceki şirketin bütün önbelleği silinir; açık sorgular yeniden çekilir.
      await qc.resetQueries({ predicate: (q) => q.queryKey[0] !== SORGU_ANAHTARI });
      qc.setQueryData(anahtar, veri);
      const ad = veri.sirketler.find((s) => s.kod === veri.aktif)?.ad ?? veri.aktif;
      message.success(`Etkin şirket: ${ad}`);
    },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.status === 403) message.error("Bu şirketin üyesi değilsiniz.");
      else message.error(e.message);
    },
  });

  const { mutate } = degisim;
  const degistir = useCallback(
    (kod: string) => {
      if (kod !== sorgu.data?.aktif) mutate(kod);
    },
    [mutate, sorgu.data?.aktif],
  );

  const deger = useMemo<SirketDurumu>(() => {
    const veri = sorgu.data ?? null;
    const sirketler = veri?.sirketler ?? [];
    const aktif = sirketler.find((s) => s.kod === veri?.aktif) ?? null;
    return {
      destekleniyor: !!veri && sirketler.length > 0,
      sirketler,
      aktif,
      // Etkin şirketi bilinmiyorsa süzme yok (boş menü göstermektense sunucuya bırak).
      aktifBirimler: aktif ? new Set(aktif.birimler) : null,
      degistir,
      degisiyor: degisim.isPending,
    };
  }, [sorgu.data, degistir, degisim.isPending]);

  return <Ctx.Provider value={deger}>{children}</Ctx.Provider>;
}

export function useSirket(): SirketDurumu {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSirket, SirketProvider içinde kullanılmalı");
  return ctx;
}
