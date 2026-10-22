/**
 * Ana veri kalitesi — serbest metin eşleştirme (TS-171, E14-09 Faz 1).
 *
 * Sunucu: `backend/app/api/teknik_servis_ana_veri.py` (`/eslestirme/*`).
 * İki uç da `hesap.birlestir` ister. Aday Excel'i yalnız OKUR; karar dosyası
 * İçe Aktarma ekranından `musteri_eslestirme` profiliyle yüklenir.
 */
import { api } from "./client";

export const ESLESTIRME_ONEK = "/api/teknik-servis/ana-veri/eslestirme";

export type EslestirmeKaynagi = "sozlesme" | "ekipman";

export interface EslestirmeSayilari {
  eslesmemis: number;
  hesapsiz: number;
  musterisiz: number;
  belirsiz: number;
  kesin_oneri: number;
}

export type EslestirmeOzeti = Record<EslestirmeKaynagi, EslestirmeSayilari>;

export const eslestirmeOzeti = () => api.get<EslestirmeOzeti>(`${ESLESTIRME_ONEK}/ozet`);

/** Faz 2 (TS-208) göç aday kaynakları — yalnız `sistem.goc`. */
export type Faz2Kaynagi = "servis_isi" | "ekipman_diger";

export const adayExcelAdresi = (kaynak: EslestirmeKaynagi | Faz2Kaynagi) =>
  `${ESLESTIRME_ONEK}/adaylar.xlsx?kaynak=${kaynak}`;

// --- Veri Kalitesi sayfası (TS-188, E12-16 / E14-18) ---------------------------------
// Ekran `servis_rapor.gor`; kontrol başına ek izin sunucuda. Kutu sayısı =
// `/liste?kontrol=` `X-Toplam-Kayit` = Excel satırı. Sayfa veriyi DEĞİŞTİRMEZ.

const KALITE = "/api/teknik-servis/ana-veri/veri-kalitesi";

export interface KaliteKontrolu {
  kod: string;
  baslik: string;
  tanim: string;
  grup: "servis" | "ana_veri" | "sozlesme" | "ekipman";
  deger: number;
  /** Ekipman kontrolleri Ekipman Kütüğü'ndeki listeye gider. */
  hedef: string | null;
}

export interface KaliteOzeti {
  gruplar: { kod: string; ad: string }[];
  kontroller: KaliteKontrolu[];
  /** Eşleşme oranının paydası (kapsamdaki iptal edilmemiş iş); servis.gor yoksa null. */
  is_paydasi: number | null;
}

export type KaliteSatiri = Record<string, unknown> & { id: number | string; yol?: string };

export const kaliteOzeti = () => api.get<KaliteOzeti>(KALITE);

export const kaliteListesi = (kontrol: string, limit: number, offset: number) =>
  api.getSayfa<KaliteSatiri>(
    `${KALITE}/liste?${new URLSearchParams({ kontrol, limit: String(limit), offset: String(offset) })}`,
  );

export const kaliteExcelAdresi = (kontrol: string) =>
  `${KALITE}/liste.xlsx?${new URLSearchParams({ kontrol })}`;
