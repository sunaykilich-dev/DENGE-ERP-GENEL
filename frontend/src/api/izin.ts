/** Personel izin talebi (KARARLAR 2026-11-20 §7). */
import { api } from "./client";

export const IZIN_TURLERI = [
  { value: "YILLIK", label: "Yıllık izin" },
  { value: "MAZERET", label: "Mazeret izni" },
  { value: "UCRETSIZ", label: "Ücretsiz izin" },
  { value: "RAPOR", label: "Raporlu" },
  { value: "DIGER", label: "Diğer" },
] as const;

export const ONAY_DURUM_ADLARI: Record<string, string> = {
  SIRADA: "Sırada",
  BEKLIYOR: "Bekliyor",
  ONAYLANDI: "Onayladı",
  REDDEDILDI: "Reddetti",
  SURE_ASIMI: "Süre aşımı (üste geçti)",
  IPTAL: "—",
};

export interface IzinOnayBasamagi {
  id: number;
  sira: number;
  onaylayici_id: number;
  onaylayici: string | null;
  durum: string;
  aktif_at: string | null;
  karar_at: string | null;
  aciklama: string | null;
}

export interface IzinTalebi {
  id: number;
  version: number;
  personel_id: number;
  personel: string | null;
  tur: string;
  tur_adi: string;
  baslangic: string;
  bitis: string;
  gun_sayisi: number;
  vekil_id: number;
  vekil: string | null;
  izin_ili: string;
  iletisim_tel: string | null;
  aciklama: string | null;
  durum: "BEKLIYOR" | "ONAYLANDI" | "REDDEDILDI" | "IPTAL";
  durum_adi: string;
  created_at: string;
  sonuc_at: string | null;
  onaylar: IzinOnayBasamagi[];
}

export interface IzinGirdisi {
  tur: string;
  baslangic: string;
  bitis: string;
  vekil_id: number;
  izin_ili: string;
  iletisim_tel: string;
  aciklama?: string | null;
  personel_id?: number | null;
}

export interface IzinKararOzeti {
  personel: string | null;
  tur_adi: string;
  baslangic: string;
  bitis: string;
  gun_sayisi: number;
  vekil: string | null;
  izin_ili: string;
  onaylayici: string | null;
  basamak: number;
  basamak_sayisi: number;
}

const URL_ = "/api/izin";

export const izinApi = {
  benim: () => api.get<IzinTalebi[]>(`${URL_}/benim`),
  onayimda: (hepsi = false) => api.get<IzinTalebi[]>(`${URL_}/onayimda?hepsi=${hepsi}`),
  tum: () => api.get<IzinTalebi[]>(`${URL_}/tum`),
  vekilAdaylari: () => api.get<{ id: number; ad: string; unvan: string | null }[]>(`${URL_}/vekil-adaylari`),
  ozet: () => api.get<{ onayimda: number }>(`${URL_}/ozet`),
  olustur: (g: IzinGirdisi) => api.post<IzinTalebi>(URL_, g),
  iptal: (id: number) => api.post<IzinTalebi>(`${URL_}/${id}/iptal`, {}),
  karar: (onayId: number, karar: "ONAY" | "RED", aciklama?: string | null) =>
    api.post<IzinTalebi>(`${URL_}/onay/${onayId}/karar`, { karar, aciklama }),
  // E-posta bağlantısı (oturumsuz).
  publicGetir: (token: string) => api.get<IzinKararOzeti>(`/api/public/izin/${encodeURIComponent(token)}`),
  publicKarar: (token: string, karar: "ONAY" | "RED", aciklama?: string | null) =>
    api.post<{ durum: string; durum_adi: string }>(`/api/public/izin/${encodeURIComponent(token)}/karar`, {
      karar,
      aciklama,
    }),
};
