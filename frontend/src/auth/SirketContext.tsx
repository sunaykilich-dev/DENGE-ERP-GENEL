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
 *
 * Rol testi B-05: yanıt gelene kadar `yukleniyor=true` — kabuk menü ve
 * kırıntı yerine iskelet çizer (bütün şirketlerin bölümleri bir an bile
 * görünmesin). Uç başka bir hatayla düşerse birimli bölümler GİZLENİR
 * (fail-closed, boş birim kümesi).
 *
 * `menuBirimleri` (B-12/Set Bariyer): etkin şirketin birimleri ∩ kullanıcının
 * kapsamındaki birimler. Birim kapsamlı rolde (KENDI_BIRIMI/KENDI_ISLERI)
 * kullanıcının üye olmadığı birimin bölümü menüde çizilmez; sunucu o bölümün
 * listesini zaten boş döndürür (sayı = liste).
 *
 * Rol testi tur 2 (KARARLAR 2026-11-04 §7.17): `/auth/me` `gorunur_birimler`
 * doluysa ve etkin şirketle uyumluysa `menuBirimleri` doğrudan ondan kurulur
 * (sunucu kapsamıyla tek tanım); boşsa (ör. birim üyeliği olmayan satış
 * temsilcisi, sunucuda "etkin şirketin bütün birimleri") eski türetme sürer.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import { createContext, useCallback, useContext, useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
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
  /** Menüde çizilecek birimler: şirket ∩ kullanıcı kapsamı; null = süzgeç yok. */
  menuBirimleri: ReadonlySet<string> | null;
  /** Şirket bilgisi henüz gelmedi (menü/kırıntı iskelet çizer). */
  yukleniyor: boolean;
  degistir: (kod: string) => void;
  degisiyor: boolean;
}

const SORGU_ANAHTARI = "oturum-sirketler";

/**
 * Birim kapsamlı roller (sunucu: `permissions.BIRIM_KAPSAMLARI`). Bu
 * kapsamlarda kullanıcı yalnız üyesi olduğu birimlerin kayıtlarını görür.
 */
const BIRIM_KAPSAMLARI = new Set(["KENDI_BIRIMI", "KENDI_ISLERI"]);

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
      // Açılış sayfası yeni şirketin menüsüne göre seçilir (B-01).
      navigate("/");
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

  const kapsam = kullanici?.role.scope;
  const kullaniciBirimleri = kullanici?.birimler;
  const gorunurBirimler = kullanici?.gorunur_birimler;
  const oturumSirketi = kullanici?.aktif_sirket;
  const deger = useMemo<SirketDurumu>(() => {
    const veri = sorgu.data ?? null;
    const sirketler = veri?.sirketler ?? [];
    const aktif = sirketler.find((s) => s.kod === veri?.aktif) ?? null;
    // Uç yok (null) → süzgeç yok; uç hata verdi → birimli bölümler gizli
    // (fail-closed); etkin şirket biliniyorsa onun birimleri.
    const aktifBirimler: ReadonlySet<string> | null = aktif
      ? new Set(aktif.birimler)
      : sorgu.isError
        ? new Set<string>()
        : null;
    let menuBirimleri = aktifBirimler;
    if (gorunurBirimler?.length && aktif && oturumSirketi === aktif.kod) {
      // Rol testi tur 2 (§7.17): sunucunun `gorunur_birimler`'i tek kaynak. Yalnız
      // /auth/me'nin etkin şirketi bugünkü şirketle aynıysa kullanılır (şirket
      // değişince /auth/me yeniden okunmaz; eski şirketin birimleri uygulanmasın).
      const gorunur = new Set(gorunurBirimler);
      menuBirimleri = new Set([...(aktifBirimler ?? gorunur)].filter((b) => gorunur.has(b)));
    } else if (kapsam && BIRIM_KAPSAMLARI.has(kapsam) && kullaniciBirimleri) {
      const uye = new Set(kullaniciBirimleri);
      menuBirimleri = new Set([...(aktifBirimler ?? uye)].filter((b) => uye.has(b)));
    }
    return {
      destekleniyor: !!veri && sirketler.length > 0,
      sirketler,
      aktif,
      aktifBirimler,
      menuBirimleri,
      yukleniyor: !!kullanici && sorgu.isPending,
      degistir,
      degisiyor: degisim.isPending,
    };
  }, [
    sorgu.data,
    sorgu.isError,
    sorgu.isPending,
    kullanici,
    kapsam,
    kullaniciBirimleri,
    gorunurBirimler,
    oturumSirketi,
    degistir,
    degisim.isPending,
  ]);

  return <Ctx.Provider value={deger}>{children}</Ctx.Provider>;
}

export function useSirket(): SirketDurumu {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSirket, SirketProvider içinde kullanılmalı");
  return ctx;
}
