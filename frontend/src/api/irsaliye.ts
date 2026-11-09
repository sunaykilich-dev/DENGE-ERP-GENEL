/**
 * İrsaliye ve muhasebe devri (KARARLAR 2026-11-09 S4.3/S4.4).
 *
 * İrsaliye bu uçlardan açılmaz; sevkiyatla (sipariş sevki, Stok ekranındaki
 * dış transfer) aynı işlemde üretilir. Fiyat anahtarları yalnız sipariş/teklif
 * fiyatı görme yetkisi olana döner (yoksa anahtar YOK). Logo entegrasyonu
 * değil: Excel/CSV dökümü ve "muhasebeye devredildi" işareti.
 */
import { api } from "./client";

const URL_ = "/api/irsaliyeler";

export interface IrsaliyeKalemi {
  id: number;
  sira: number;
  product_id: number | null;
  urun_kodu: string | null;
  aciklama: string;
  miktar: number;
  birim: string;
  seri_nolar: string | null;
  birim_fiyat?: number | null;
  iskonto_yuzde?: number | null;
  kdv_orani?: number | null;
}

export interface Irsaliye {
  id: number;
  irsaliye_no: string;
  durum: "DUZENLENDI" | "IPTAL";
  transfer_id: number;
  order_id: number | null;
  alici_unvan: string;
  alici_vkn: string | null;
  alici_adres: string | null;
  hedef_konum: string;
  cikis_depo_adi: string | null;
  duzenleme_tarihi: string;
  sevk_tarihi: string;
  teslim_eden: string | null;
  notlar: string | null;
  iptal_at: string | null;
  iptal_nedeni: string | null;
  muhasebe_devri_at: string | null;
  muhasebe_devreden: string | null;
  muhasebe_notu: string | null;
  toplam_miktar: number;
  fiyatli: boolean;
  version: number;
  kalemler: IrsaliyeKalemi[];
}

export interface IrsaliyeSuzgeci {
  order_id?: number;
  devir?: "bekleyen" | "devredildi";
  durum?: "DUZENLENDI" | "IPTAL";
  donem?: string;
  ara?: string;
}

function sorgu(s: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const q = p.toString();
  return q ? `?${q}` : "";
}

export const HEDEF_ADLARI: Record<string, string> = {
  MUSTERI: "Müşteri",
  BAYI: "Bayi",
  MONTAJ_NOKTASI: "Montaj noktası",
  SERVIS: "Dış servis",
};

/** Depodan şirket dışına çıkış irsaliye ister (sunucuyla aynı kural). */
export const DIS_HEDEFLER = ["MUSTERI", "BAYI", "MONTAJ_NOKTASI", "SERVIS"];
export const DEPO_KAYNAKLARI = ["MERKEZ_DEPO", "BOLGE_DEPO"];

export const irsaliyeApi = {
  liste: (s: IrsaliyeSuzgeci = {}) => api.get<Irsaliye[]>(`${URL_}${sorgu({ ...s })}`),
  getir: (id: number) => api.get<Irsaliye>(`${URL_}/${id}`),
  pdfYolu: (id: number, fiyatli = false) => `${URL_}/${id}/pdf${fiyatli ? "?fiyatli=true" : ""}`,
  iptal: (id: number, neden: string, version: number) =>
    api.post<Irsaliye>(`${URL_}/${id}/iptal`, { neden, version }),
  devret: (irsaliye_idler: number[], not?: string) =>
    api.post<{ devredilen: number[] }>(`${URL_}/muhasebe-devri`, { irsaliye_idler, not }),
  devriGeriAl: (id: number, gerekce: string) =>
    api.post<Irsaliye>(`${URL_}/${id}/muhasebe-devri/geri-al`, { gerekce }),
  logoYolu: (devir: string | undefined, bicim: "xlsx" | "csv", donem?: string) =>
    `${URL_}/logo-aktarim${sorgu({ devir, bicim, donem })}`,
};

export const siparisBelgeApi = {
  onayPdfYolu: (id: number) => `/api/siparisler/${id}/onay.pdf`,
  devret: (siparis_idler: number[], not?: string) =>
    api.post<{ devredilen: number[] }>(`/api/siparisler/muhasebe-devri`, { siparis_idler, not }),
  devriGeriAl: (id: number, gerekce: string) =>
    api.post(`/api/siparisler/${id}/muhasebe-devri/geri-al`, { gerekce }),
  logoYolu: (devir: string, bicim: "xlsx" | "csv", donem?: string) =>
    `/api/siparisler/muhasebe-aktarim${sorgu({ devir, bicim, donem })}`,
};
