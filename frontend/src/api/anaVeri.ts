/**
 * Müşteri / lokasyon ana verisi (TS-014, TS-015).
 *
 * Hafif arama uçları yalnız ad + il + doğrulama rozeti döner (VKN/IBAN/irtibat
 * yok); lokasyon kartı `hesap.gor`, yazma `lokasyon.yaz` ister.
 *
 * `api/client.ts` 409 gövdesindeki nesneyi (aday listesi, mevcut kayıt)
 * mesaja indirger; seçici "Bunu mu demek istediniz?" listesini gösterebilsin
 * diye bu dosya o çağrılar için gövdeyi taşıyan kendi hata sınıfını kullanır.
 */

import { api, ApiError } from "./client";

export interface MusteriSatiri {
  id: number;
  unvan: string;
  il: string | null;
  dogrulandi: boolean;
  eslesen: "unvan" | "takma_ad" | "tesis" | "vkn";
}

export interface LokasyonSatiri {
  id: number;
  hesap_id: number;
  tesis_adi: string | null;
  ilce: string | null;
  il: string | null;
  aktif: boolean;
  dogrulandi: boolean;
}

export interface Irtibat {
  id: number;
  ad: string;
  gorev: string | null;
  telefon: string | null;
  eposta: string | null;
  lokasyon_id: number | null;
  birincil: boolean;
}

export const ADRES_TURLERI = ["TESIS", "MERKEZ", "FATURA", "SEVK"] as const;
export type AdresTuru = (typeof ADRES_TURLERI)[number];

export const ADRES_TURU_ETIKET: Record<AdresTuru, string> = {
  TESIS: "Tesis / lokasyon",
  MERKEZ: "Merkez",
  FATURA: "Fatura",
  SEVK: "Sevk",
};

export interface Lokasyon {
  id: number;
  account_id: number;
  hesap_unvan: string | null;
  kind: AdresTuru;
  label: string;
  site_name: string | null;
  line: string | null;
  district: string | null;
  city: string | null;
  access_note: string | null;
  primary_contact_id: number | null;
  is_primary: boolean;
  is_active: boolean;
  is_verified: boolean;
  version: number;
  irtibatlar: Irtibat[] | null;
}

export interface HizliMusteriSonucu {
  hesap: MusteriSatiri;
  lokasyon: LokasyonSatiri | null;
}

/** 409/400 gövdesini (detail nesnesi) taşıyan hata. */
export class AnaVeriHatasi extends ApiError {
  constructor(
    status: number,
    message: string,
    readonly detay: Record<string, unknown> | null,
  ) {
    super(status, message);
  }
}

async function detayliIstek<T>(yol: string, yontem: string, govde: unknown): Promise<T> {
  const res = await fetch(yol, {
    method: yontem,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
    body: JSON.stringify(govde ?? {}),
  });
  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    let detay: Record<string, unknown> | null = null;
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") mesaj = j.detail;
      else if (Array.isArray(j?.detail)) mesaj = j.detail[0]?.msg ?? mesaj;
      else if (j?.detail && typeof j.detail === "object") {
        detay = j.detail as Record<string, unknown>;
        mesaj = String(detay.mesaj ?? mesaj);
      }
    } catch {
      /* gövde JSON değil */
    }
    throw new AnaVeriHatasi(res.status, mesaj, detay);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const ANA = "/api/teknik-servis/ana-veri";

export const anaVeriApi = {
  musteriAra: (q: string) =>
    api.get<MusteriSatiri[]>(`${ANA}/musteri-ara?${new URLSearchParams({ q })}`),
  lokasyonAra: (hesapId: number, q?: string) => {
    const p = new URLSearchParams({ hesap_id: String(hesapId) });
    if (q) p.set("q", q);
    return api.get<LokasyonSatiri[]>(`${ANA}/lokasyon-ara?${p}`);
  },
  hizliMusteri: (govde: { unvan: string; il: string; tesis_adi?: string; onay_benzer?: boolean }) =>
    detayliIstek<HizliMusteriSonucu>(`${ANA}/hizli-musteri`, "POST", govde),

  hesapLokasyonlari: (hesapId: number) =>
    api.get<Lokasyon[]>(`/api/hesaplar/${hesapId}/lokasyonlar`),
  lokasyon: (id: number) => api.get<Lokasyon>(`/api/lokasyonlar/${id}`),
  lokasyonAc: (govde: Record<string, unknown>) =>
    detayliIstek<Lokasyon>("/api/lokasyonlar", "POST", govde),
  lokasyonGuncelle: (id: number, govde: Record<string, unknown>) =>
    detayliIstek<Lokasyon>(`/api/lokasyonlar/${id}`, "PATCH", govde),
  lokasyonAktiflik: (id: number, aktif: boolean) =>
    api.post<Lokasyon>(`/api/lokasyonlar/${id}/${aktif ? "aktif" : "pasif"}`),
  lokasyonDogrula: (id: number) => api.post<Lokasyon>(`/api/lokasyonlar/${id}/dogrula`),
  irtibatEkle: (lokasyonId: number, govde: Record<string, unknown>) =>
    api.post<Irtibat>(`/api/lokasyonlar/${lokasyonId}/kisiler`, govde),
  irtibatGuncelle: (kisiId: number, govde: Record<string, unknown>) =>
    api.patch<Irtibat>(`/api/lokasyonlar/kisiler/${kisiId}`, govde),

  /** Canlı hesap formu: VKN çakışması 409'unu gövdesiyle taşır. */
  hesapKaydet: (id: number | null, govde: Record<string, unknown>) =>
    id === null
      ? detayliIstek<unknown>("/api/hesaplar", "POST", govde)
      : detayliIstek<unknown>(`/api/hesaplar/${id}`, "PATCH", govde),
  hesapDogrula: (id: number) => api.post<unknown>(`/api/hesaplar/${id}/dogrula`),
};
