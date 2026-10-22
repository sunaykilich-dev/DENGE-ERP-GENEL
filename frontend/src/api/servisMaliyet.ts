/**
 * Servis maliyet — API tipleri ve çağrıları (TS-145…149).
 *
 * Sunucu: `backend/app/api/servis_maliyet.py`. Bütün uçlar `maliyet.gor`
 * ister; yazanlar ayrıca `maliyet.yaz`, analiz ayrıca `servis_rapor.gor`.
 * Eksik tutar `null` gelir — ekranda "—" basılır, ASLA 0 yazılmaz (NULL ≠ 0).
 */
import { api } from "./client";

export const MALIYET_ONEK = "/api/teknik-servis/maliyet";

export type Tutar = string | number | null;

export interface Tarife {
  id: number;
  version: number;
  birim: string;
  valid_from: string;
  valid_to: string | null;
  hourly_cost: string | number;
  gerekce: string | null;
  created_at: string;
  created_by: number | null;
  giren: string | null;
  kapatildi: boolean;
}

export interface IsFinansi {
  so_id: number;
  so_no: string;
  birim: string;
  tur: string;
  sure_dk: number | null;
  iscilik: Tutar;
  iscilik_durumu: string;
  malzeme: Tutar;
  malzeme_durumu: string;
  diger: Tutar;
  diger_maliyet: Tutar;
  diger_maliyet_notu: string | null;
  gelir: Tutar;
  gelir_kaynagi: string | null;
  gelir_durumu: string;
  gelir_notu: string | null;
  fark: Tutar;
  fark_durumu: string;
  durum: string;
  fatura_iletildi_at: string | null;
  finans_version: number | null;
}

export interface AnalizSatiri extends Omit<IsFinansi, "diger_maliyet_notu" | "gelir_notu"> {
  musteri_id: number | null;
  musteri: string | null;
  kapanis_tarihi: string | null;
}

export interface AnalizOzeti {
  birim?: string;
  tur?: string;
  adet: number;
  tam_adet: number;
  gelir: Tutar;
  malzeme: Tutar;
  iscilik: Tutar;
  diger: Tutar;
  fark: Tutar;
  sure_eksik: number;
  tarife_eksik: number;
  maliyet_eksik: number;
  gelir_yok: number;
  sozlesme_kapsami: number;
}

export interface Analiz {
  baslangic: string;
  bitis: string;
  satirlar: AnalizSatiri[];
  ozet: AnalizOzeti[];
  genel: AnalizOzeti;
}

export interface AnalizSuzgeci {
  donem?: string;
  baslangic?: string;
  bitis?: string;
  birim?: string;
  tur?: string;
  musteri_id?: number;
  durum?: string;
}

export interface GecmisSatiri {
  zaman: string;
  eylem: string;
  kullanici: string | null;
  eski: Record<string, unknown>;
  yeni: Record<string, unknown>;
}

export const GELIR_KAYNAK_ADLARI: Record<string, string> = {
  ELLE: "Elle",
  TEKLIF: "Teklif",
  SOZLESME: "Sözleşme kapsamı",
  UCRETSIZ_GARANTI: "Ücretsiz / garanti",
  YOK: "Gelir yok (kaydı sil)",
};

export const DURUM_ADLARI: Record<string, string> = {
  TAM: "Tam",
  SURE_EKSIK: "Süre eksik",
  TARIFE_EKSIK: "Tarife eksik",
  MALIYET_EKSIK: "Maliyet eksik",
  GELIR_YOK: "Gelir kaydı yok",
  KAYIT_YOK: "Gelir kaydı yok",
  SOZLESME_KAPSAMI: "Sözleşme kapsamı",
};

export const DURUM_RENKLERI: Record<string, string> = {
  TAM: "green",
  SURE_EKSIK: "orange",
  TARIFE_EKSIK: "orange",
  MALIYET_EKSIK: "orange",
  GELIR_YOK: "gold",
  SOZLESME_KAPSAMI: "blue",
};

/** Analiz KPI kutuları — sunucunun `durum` süzgeç kodlarıyla aynı. */
export const ANALIZ_KPI = [
  { kod: "TAM", baslik: "Tam veri", alan: "tam_adet" },
  { kod: "SURE_EKSIK", baslik: "Süre eksik", alan: "sure_eksik" },
  { kod: "TARIFE_EKSIK", baslik: "Tarife eksik", alan: "tarife_eksik" },
  { kod: "MALIYET_EKSIK", baslik: "Parça maliyeti eksik", alan: "maliyet_eksik" },
  { kod: "GELIR_YOK", baslik: "Gelir kaydı yok", alan: "gelir_yok" },
  { kod: "SOZLESME_KAPSAMI", baslik: "Sözleşme kapsamı", alan: "sozlesme_kapsami" },
] as const;

function parametreler(s: AnalizSuzgeci): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  return p.toString();
}

export const servisMaliyetApi = {
  tarifeler: (birim?: string) =>
    api.get<Tarife[]>(`${MALIYET_ONEK}/tarifeler${birim ? `?birim=${birim}` : ""}`),
  tarifeEkle: (g: { birim: string; valid_from: string; hourly_cost: number; gerekce?: string | null }) =>
    api.post<Tarife>(`${MALIYET_ONEK}/tarifeler`, g),
  tarifeKapat: (g: { tarife_id: number; version: number; gerekce: string }) =>
    api.post<Tarife>(`${MALIYET_ONEK}/tarifeler/kapat`, g),
  isFinansi: (soId: number) => api.get<IsFinansi>(`${MALIYET_ONEK}/isler/${soId}`),
  gelirYaz: (
    soId: number,
    g: { kaynak: string; tutar: number | null; not?: string | null; version: number | null },
  ) => api.put<IsFinansi>(`${MALIYET_ONEK}/isler/${soId}/gelir`, g),
  digerMaliyetYaz: (
    soId: number,
    g: { tutar: number | null; not?: string | null; version: number | null },
  ) => api.put<IsFinansi>(`${MALIYET_ONEK}/isler/${soId}/diger-maliyet`, g),
  gecmis: (soId: number) => api.get<GecmisSatiri[]>(`${MALIYET_ONEK}/isler/${soId}/gecmis`),
  analiz: (s: AnalizSuzgeci) => api.get<Analiz>(`${MALIYET_ONEK}/analiz?${parametreler(s)}`),
};

/** Tutar biçimi: `null` → "—" (eksik veri sıfır gibi gösterilmez). */
export function tl(v: Tutar | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₺`;
}
