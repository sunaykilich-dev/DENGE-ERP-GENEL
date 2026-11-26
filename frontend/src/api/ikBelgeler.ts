/**
 * İK "Bordro ve Belgeler" — API tipleri ve çağrıları (KARARLAR 2026-10-28 §11).
 *
 * Sunucu: `backend/app/api/ik_belgeler.py`. İK tarafı `bordro.yonet` /
 * `ik_belge.yonet` ister; `belgelerim` uçları oturumdaki kişinin kendi
 * belgeleridir (izin değil kimlik).
 */
import { ApiError, api } from "./client";

const K = "/api/ik";

export type BelgeTuru = "BORDRO" | "FORM" | "TALIMAT" | "TAAHHUTNAME" | "KVKK" | "DIGER";
export type BelgeDurumu = "GONDERILDI" | "GORULDU" | "ONAYLANDI" | "ITIRAZ" | "GERI_ALINDI";

export const TUR_ETIKETLERI: Record<BelgeTuru, string> = {
  BORDRO: "Bordro",
  FORM: "Form",
  TALIMAT: "Talimat",
  TAAHHUTNAME: "Taahhütname",
  KVKK: "KVKK metni",
  DIGER: "Diğer belge",
};
export const SABLON_TURLERI: BelgeTuru[] = ["FORM", "TALIMAT", "TAAHHUTNAME", "KVKK", "DIGER"];

export const DURUM_ETIKETLERI: Record<BelgeDurumu, { ad: string; renk: string }> = {
  GONDERILDI: { ad: "Gönderildi", renk: "default" },
  GORULDU: { ad: "Görüldü", renk: "processing" },
  ONAYLANDI: { ad: "Onaylandı", renk: "success" },
  ITIRAZ: { ad: "İtiraz edildi", renk: "error" },
  GERI_ALINDI: { ad: "Geri alındı", renk: "default" },
};

export interface Alici {
  id: number;
  ad: string;
  sicil_no: string | null;
  birim: string | null;
  eposta_var: boolean;
}

export interface Eslesme {
  dosya_adi: string;
  user_id: number | null;
  ad: string | null;
  yontem: "SICIL" | "AD" | "BELIRSIZ" | "YOK";
}

export interface Sablon {
  id: number;
  ad: string;
  tur: BelgeTuru;
  aciklama: string | null;
  aktif: boolean;
  dosya_adi: string;
  sha256: string;
  version: number;
}

export interface GonderimOzet {
  id: number;
  tur: BelgeTuru;
  baslik: string;
  donem: string | null;
  son_tarih: string | null;
  created_at: string;
  gonderen: string | null;
  toplam: number;
  sayilar: Partial<Record<BelgeDurumu, number>>;
}

export interface BelgeSatiri {
  id: number;
  user_id: number;
  ad: string;
  sicil_no: string | null;
  durum: BelgeDurumu;
  gonderildi_at: string;
  goruldu_at: string | null;
  yanit_at: string | null;
  itiraz_gerekcesi: string | null;
  hatirlatma_sayisi: number;
  son_hatirlatma_at: string | null;
  gecikti: boolean;
}

export interface GonderimDetay extends GonderimOzet {
  aciklama: string | null;
  belgeler: BelgeSatiri[];
}

export interface GonderimVerisi {
  tur: BelgeTuru;
  baslik: string;
  donem?: string | null;
  aciklama?: string | null;
  son_tarih?: string | null;
  sablon_id?: number | null;
  alicilar: number[];
  bildir?: boolean;
}

export interface Olay {
  id: number;
  olay: string;
  kisi: string | null;
  at: string;
  ip: string | null;
  user_agent: string | null;
  dogrulama: string | null;
  belge_ozeti: string;
  aciklama: string | null;
  kayit_ozeti: string;
}

export interface Kanit {
  belge_id: number;
  belge_ozeti: string;
  zincir_gecerli: boolean;
  olaylar: Olay[];
}

export interface Belgem {
  id: number;
  tur: BelgeTuru;
  tur_adi: string;
  baslik: string;
  donem: string | null;
  aciklama: string | null;
  son_tarih: string | null;
  durum: BelgeDurumu;
  gonderildi_at: string;
  goruldu_at: string | null;
  yanit_at: string | null;
  itiraz_gerekcesi: string | null;
  dosya_adi: string;
  belge_ozeti: string;
}

export interface Dogrulama {
  parola?: string;
  kod?: string;
}

/** Çok parçalı istek (dosya yükleme): Content-Type'ı tarayıcı koyar. */
export async function cokParcali<T>(yol: string, govde: FormData): Promise<T> {
  const res = await fetch(yol, {
    method: "POST",
    body: govde,
    credentials: "same-origin",
    headers: { "X-Requested-With": "fetch" },
  });
  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    let veri: unknown;
    try {
      veri = await res.json();
      const d = (veri as { detail?: unknown }).detail;
      if (typeof d === "string") mesaj = d;
      else if (Array.isArray(d)) mesaj = d[0]?.msg ?? mesaj;
    } catch {
      /* JSON değil */
    }
    throw new ApiError(res.status, mesaj, veri);
  }
  return (await res.json()) as T;
}

export const ikBelgeApi = {
  alicilar: () => api.get<Alici[]>(`${K}/alicilar`),
  eslestir: (dosya_adlari: string[]) => api.post<Eslesme[]>(`${K}/eslestir`, { dosya_adlari }),
  sablonlar: (yalnizAktif = false) =>
    api.get<Sablon[]>(`${K}/sablonlar${yalnizAktif ? "?yalniz_aktif=true" : ""}`),
  sablonEkle: (ad: string, tur: BelgeTuru, aciklama: string | undefined, dosya: File) => {
    const f = new FormData();
    f.append("ad", ad);
    f.append("tur", tur);
    if (aciklama) f.append("aciklama", aciklama);
    f.append("dosya", dosya);
    return cokParcali<Sablon>(`${K}/sablonlar`, f);
  },
  sablonDuzelt: (id: number, govde: { aktif?: boolean; ad?: string; version: number }) =>
    api.patch<Sablon>(`${K}/sablonlar/${id}`, govde),
  sablonDosyaUrl: (id: number) => `${K}/sablonlar/${id}/dosya`,
  gonder: (veri: GonderimVerisi, dosyalar: File[]) => {
    const f = new FormData();
    f.append("veri", JSON.stringify(veri));
    for (const d of dosyalar) f.append("dosyalar", d);
    return cokParcali<{ gonderim: GonderimOzet; bildirilen: number }>(`${K}/gonderimler`, f);
  },
  gonderimler: (tur?: BelgeTuru) =>
    api.get<GonderimOzet[]>(`${K}/gonderimler${tur ? `?tur=${tur}` : ""}`),
  gonderim: (id: number) => api.get<GonderimDetay>(`${K}/gonderimler/${id}`),
  hatirlat: (id: number, belge_idleri?: number[]) =>
    api.post<{ hatirlatilan: number; bildirilen: number }>(`${K}/gonderimler/${id}/hatirlat`, {
      belge_idleri: belge_idleri ?? null,
    }),
  geriAl: (belgeId: number, gerekce: string) =>
    api.post<void>(`${K}/belgeler/${belgeId}/geri-al`, { gerekce }),
  belgeDosyaUrl: (belgeId: number) => `${K}/belgeler/${belgeId}/dosya`,
  kanit: (belgeId: number) => api.get<Kanit>(`${K}/belgeler/${belgeId}/kanit`),

  belgelerim: () => api.get<Belgem[]>(`${K}/belgelerim`),
  belgelerimOzet: () => api.get<{ bekleyen: number }>(`${K}/belgelerim/ozet`),
  belgemDosyaUrl: (id: number) => `${K}/belgelerim/${id}/dosya`,
  onayla: (id: number, d: Dogrulama) => api.post<Belgem>(`${K}/belgelerim/${id}/onayla`, d),
  itiraz: (id: number, gerekce: string, d: Dogrulama) =>
    api.post<Belgem>(`${K}/belgelerim/${id}/itiraz`, { ...d, gerekce }),
};
