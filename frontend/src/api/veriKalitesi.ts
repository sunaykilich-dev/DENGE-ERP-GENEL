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

export const adayExcelAdresi = (kaynak: EslestirmeKaynagi) =>
  `${ESLESTIRME_ONEK}/adaylar.xlsx?kaynak=${kaynak}`;
