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

  // --- TS-192: servis kartı, kapsam bilgisi, birleştirme ---
  servisKarti: (hesapId: number) => api.get<ServisKarti>(`${ANA}/musteriler/${hesapId}/servis-karti`),
  kapsamBilgisi: (p: { hesap_id?: number; lokasyon_id?: number; ekipman_id?: number }) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(p)) if (v != null) q.set(k, String(v));
    return api.get<KapsamBilgisi>(`${ANA}/kapsam-bilgisi?${q}`);
  },
  birlestirmeOnizle: (govde: BirlestirmeGovdesi) =>
    detayliIstek<BirlestirmeOnizleme>(`${ANA}/birlestirme/onizle`, "POST", govde),
  birlestirmeUygula: (
    govde: BirlestirmeGovdesi & { gerekce: string; beklenen: Record<string, number> },
  ) => detayliIstek<BirlestirmeKaydi>(`${ANA}/birlestirme/uygula`, "POST", govde),
  birlestirmeler: (limit: number, offset: number) =>
    api.getSayfa<BirlestirmeKaydi>(`${ANA}/birlestirmeler?limit=${limit}&offset=${offset}`),
};

export interface ServisKarti {
  hesap_id: number;
  unvan: string;
  acik_is_sayisi: number;
  lokasyonsuz_acik_is: number;
  lokasyonlar: { id: number; tesis_adi: string | null; il: string | null; aktif: boolean; acik_is: number }[];
  servis_isleri: {
    id: number;
    so_no: string;
    birim: string;
    tur: string;
    durum: string;
    konu: string;
    lokasyon_id: number | null;
    tarih: string;
  }[];
  /** İzne bağlı bloklar: izin yoksa anahtar hiç gelmez. */
  sozlesmeler?: {
    id: number;
    no: string;
    birim: string;
    tesis: string | null;
    donem: string;
    durum: string;
    /** Yalnız `maliyet.gor`. */
    ucret?: number | null;
  }[];
  ekipman_sayisi?: number;
  ekipman_turleri?: { tip: string; adet: number }[];
  kiralamalar?: { id: number; no: string; birim: string; durum: string; baslangic: string; bitis: string }[];
  teklifler?: { id: number; no: string; birim: string; durum: string; tarih: string }[];
  aciklama: string | null;
}

export interface KapsamBilgisi {
  kapsam_durumu: "SOZLESMELI" | "GARANTILI" | "KAPSAM_DISI" | "BILINMIYOR";
  aktif_sozlesmeler: { id: number; no: string; tesis: string | null; donem: string; durum: string; yururlukte: boolean }[];
  garanti: { bitis: string; kaynak: string | null } | null;
  son_isler: { id: number; so_no: string; durum: string; konu: string; tarih: string }[];
}

export type BirlestirmeTuru = "HESAP" | "LOKASYON";

export interface BirlestirmeGovdesi {
  tur: BirlestirmeTuru;
  kaynak_id: number;
  hedef_id: number;
}

export interface BirlestirmeOnizleme {
  tur: BirlestirmeTuru;
  kaynak: { id: number; ad: string | null };
  hedef: { id: number; ad: string | null };
  tasinacak: Record<string, number>;
  hakedis_referanslari: Record<string, number>;
  cakisan_tesisler: { id: number; tesis_adi: string | null }[];
  engeller: string[];
  uyarilar: string[];
  doldurulacak: Record<string, unknown>;
  eklenen_roller: string[];
}

export interface BirlestirmeKaydi {
  id: number;
  tur: BirlestirmeTuru;
  kaynak_id: number;
  hedef_id: number;
  gerekce: string;
  onizleme: Record<string, number> | null;
  tasinan: Record<string, number> | null;
  created_by: number | null;
  created_at: string;
}
