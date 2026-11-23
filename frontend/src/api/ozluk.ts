/**
 * Personel özlük dosyası (2026-11-20). Sunucu: `backend/app/api/ozluk.py`.
 * İK yönetir; personel kendi belgesini görür; saha şefi/koordinatör iş
 * bazlı (işe atanmış personelin "işte paylaşılabilir" türdeki belgeleri).
 * 2026-11-23: personel kendi dosyasına yükler; belge İK onaylayana dek
 * `ONAY_BEKLIYOR`dır (geçerli sayılmaz, işte paylaşılmaz).
 */
import { api } from "./client";
import { cokParcali } from "./ikBelgeler";

const K = "/api/ozluk";

export interface OzlukTuru {
  id: number;
  ad: string;
  sira: number;
  aktif: boolean;
  is_paylasimi: boolean;
  version: number;
}

export type OzlukDurumu = "ONAY_BEKLIYOR" | "ONAYLANDI" | "REDDEDILDI";

export interface OzlukBelgesi {
  id: number;
  user_id: number;
  tur_id: number;
  dosya_adi: string;
  mime_type: string;
  size_bytes: number;
  gecerlilik_bitis: string | null;
  aciklama: string | null;
  created_at: string;
  durum: OzlukDurumu;
  red_gerekcesi: string | null;
  karar_at: string | null;
  version: number;
}

/** İK'nın onay bekleyenler listesindeki satır. */
export interface BekleyenOzlukBelgesi extends OzlukBelgesi {
  kisi_adi: string;
  tur_adi: string;
}

function belgeFormu(turId: number, dosya: File, gecerlilikBitis?: string, aciklama?: string): FormData {
  const f = new FormData();
  f.append("tur_id", String(turId));
  f.append("dosya", dosya);
  if (gecerlilikBitis) f.append("gecerlilik_bitis", gecerlilikBitis);
  if (aciklama) f.append("aciklama", aciklama);
  return f;
}

export interface OzlukDosyasi {
  turler: OzlukTuru[];
  belgeler: OzlukBelgesi[];
}

export interface IsEkibiBelgeleri {
  turler: OzlukTuru[];
  kisiler: { user_id: number; ad: string; belgeler: OzlukBelgesi[] }[];
}

export const ozlukApi = {
  turler: (tumu = false) => api.get<OzlukTuru[]>(`${K}/turler${tumu ? "?tumu=true" : ""}`),
  turEkle: (ad: string, is_paylasimi: boolean) => api.post<OzlukTuru>(`${K}/turler`, { ad, is_paylasimi }),
  turDegistir: (t: OzlukTuru, degisiklik: Partial<Pick<OzlukTuru, "ad" | "aktif" | "is_paylasimi" | "sira">>) =>
    api.patch<OzlukTuru>(`${K}/turler/${t.id}`, { version: t.version, ...degisiklik }),
  benim: () => api.get<OzlukDosyasi>(`${K}/benim`),
  kisi: (kisiId: number) => api.get<OzlukDosyasi>(`${K}/kisi/${kisiId}`),
  /** İK yüklemesi (doğrudan onaylı). */
  yukle: (kisiId: number, turId: number, dosya: File, gecerlilikBitis?: string, aciklama?: string) =>
    cokParcali<OzlukBelgesi>(`${K}/kisi/${kisiId}`, belgeFormu(turId, dosya, gecerlilikBitis, aciklama)),
  /** Personelin kendi yüklemesi (İK onayı bekler). */
  kendiYukle: (turId: number, dosya: File, gecerlilikBitis?: string, aciklama?: string) =>
    cokParcali<OzlukBelgesi>(`${K}/benim`, belgeFormu(turId, dosya, gecerlilikBitis, aciklama)),
  bekleyenler: () => api.get<BekleyenOzlukBelgesi[]>(`${K}/bekleyenler`),
  onayla: (b: OzlukBelgesi) => api.post<OzlukBelgesi>(`${K}/belgeler/${b.id}/onayla`, { version: b.version }),
  reddet: (b: OzlukBelgesi, gerekce: string) =>
    api.post<OzlukBelgesi>(`${K}/belgeler/${b.id}/reddet`, { version: b.version, gerekce }),
  sil: (belgeId: number) => api.delete<void>(`${K}/belgeler/${belgeId}`),
  dosyaUrl: (belgeId: number, isId?: number) =>
    `${K}/belgeler/${belgeId}/dosya${isId != null ? `?is_id=${isId}` : ""}`,
  isEkibi: (soId: number) => api.get<IsEkibiBelgeleri>(`${K}/is/${soId}`),
};
