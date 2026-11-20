/** Satış/kiralama talebinin teknik servise yönlendirilmesi (KARARLAR 2026-11-20 §5–6). */
import { api } from "./client";

const URL_ = "/api/teknik-servis/yonlendirmeler";

export interface Yonlendirme {
  id: number;
  version: number;
  kaynak: "SATIS" | "KIRALAMA";
  birim: string;
  durum: "MUDURDE" | "BIRIMDE";
  planlandi: boolean;
  service_order_id: number | null;
  so_no: string | null;
  is_durumu: string | null;
  rental_id: number | null;
  rental_no: string | null;
  kiralama_durumu: string | null;
  konu: string | null;
  musteri: string | null;
  sozlesme_detay: string | null;
  talep_notu: string | null;
  hedef_user_id: number | null;
  hedef_ad: string | null;
  mudur_notu: string | null;
  yonlendirme_at: string | null;
  created_at: string;
}

export interface YonlendirmeAdayi {
  id: number;
  ad: string;
  unvan: string | null;
}

export const yonlendirmeApi = {
  liste: (acik: boolean) => api.get<Yonlendirme[]>(`${URL_}?acik=${acik}`),
  adaylar: (birim: string) => api.get<YonlendirmeAdayi[]>(`${URL_}/adaylar?birim=${encodeURIComponent(birim)}`),
  yonlendir: (id: number, g: { hedef_user_id: number; version: number; not?: string | null }) =>
    api.post<{ id: number; durum: string; version: number }>(`${URL_}/${id}/yonlendir`, g),
  kiralamaTalepOnay: (kiralamaId: number, g: { sozlesme_detay?: string | null; not?: string | null }) =>
    api.post<{ yonlendirme_id: number; durum: string }>(`/api/kiralama/${kiralamaId}/talep-onay`, g),
};
