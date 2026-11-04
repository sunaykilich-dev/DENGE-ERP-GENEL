import { api } from "./client";

export interface Kolon {
  id: number;
  title: string;
  sira: number;
  bitis_mi: boolean;
  wip_limit: number | null;
}

export interface Etiket {
  id: number;
  ad: string | null;
  renk: string;
  sira: number;
}

export interface Uye {
  id: number;
  ad: string;
}

export interface Pano {
  id: number;
  title: string;
  description: string | null;
  sira: number;
  arsivlendi: boolean;
  version: number;
  kolonlar: Kolon[];
  etiketler: Etiket[];
  kart_sayisi: number;
}

export interface Baglanti {
  entity: string;
  entity_id: number;
  ad: string;
  etiket: string;
  yol: string;
  var: boolean;
}

/**
 * Bağlı kaydı kullanıcı göremiyor mu? Sunucu etiketi yalnız kaydı görebilene
 * döner; göremeyene `var=false`, `yol=""`, etiket "erişim yok" (KARARLAR
 * 2026-11-04 §6.1). Silinmiş kayıttan ("kaynak kayıt silinmiş") ayrılır:
 * erişim yok gri ve bağlantısız, silinmiş kırmızı gösterilir.
 */
export function baglantiErisimYok(b: Baglanti): boolean {
  return !b.var && !b.yol && b.etiket.trim().toLocaleLowerCase("tr") === "erişim yok";
}

export type Oncelik = "DUSUK" | "NORMAL" | "YUKSEK" | "ACIL";

export interface Kart {
  id: number;
  board_id: number;
  column_id: number;
  title: string;
  description: string | null;
  sira: number;
  uyeler: Uye[];
  etiketler: Etiket[];
  due_date: string | null;
  oncelik: Oncelik;
  tamamlandi_at: string | null;
  version: number;
  baglanti: Baglanti | null;
  yorum_sayisi: number;
}

export interface Yorum {
  id: number;
  user_id: number | null;
  yazan: string | null;
  metin: string;
  created_at: string;
}

export interface KayitTipi {
  kod: string;
  ad: string;
}

export const ONCELIK_ETIKET: Record<Oncelik, string> = {
  DUSUK: "Düşük",
  NORMAL: "Normal",
  YUKSEK: "Yüksek",
  ACIL: "Acil",
};

/** Öncelik rengi. DÜŞÜK ve NORMAL renksiz: her kartı boyamak, gerçekten
 *  acil olanı görünmez yapar. */
export const ONCELIK_RENK: Partial<Record<Oncelik, string>> = {
  YUKSEK: "orange",
  ACIL: "red",
};

export const gorevApi = {
  panolar: (arsiv = false) => api.get<Pano[]>(`/api/gorevler/panolar?arsiv=${arsiv}`),
  panoAc: (govde: { title: string; description?: string; kolonlar?: string[] }) =>
    api.post<Pano>("/api/gorevler/panolar", govde),
  panoGuncelle: (id: number, govde: Record<string, unknown>) =>
    api.patch<Pano>(`/api/gorevler/panolar/${id}`, govde),
  panoSil: (id: number) => api.delete<void>(`/api/gorevler/panolar/${id}`),

  kolonEkle: (panoId: number, govde: { title: string; wip_limit?: number | null }) =>
    api.post<Kolon>(`/api/gorevler/panolar/${panoId}/kolonlar`, govde),
  kolonGuncelle: (id: number, govde: Record<string, unknown>) =>
    api.patch<Kolon>(`/api/gorevler/kolonlar/${id}`, govde),
  kolonSil: (id: number) => api.delete<void>(`/api/gorevler/kolonlar/${id}`),

  etiketEkle: (panoId: number, govde: { ad?: string | null; renk: string }) =>
    api.post<Etiket>(`/api/gorevler/panolar/${panoId}/etiketler`, govde),
  etiketGuncelle: (id: number, govde: { ad?: string | null; renk: string }) =>
    api.patch<Etiket>(`/api/gorevler/etiketler/${id}`, govde),
  etiketSil: (id: number) => api.delete<void>(`/api/gorevler/etiketler/${id}`),

  kartlar: (panoId: number) => api.get<Kart[]>(`/api/gorevler/panolar/${panoId}/kartlar`),
  kaydinKartlari: (entity: string, entityId: number) =>
    api.get<Kart[]>(`/api/gorevler/kayit/${entity}/${entityId}`),
  kartAc: (panoId: number, govde: Record<string, unknown>) =>
    api.post<Kart>(`/api/gorevler/panolar/${panoId}/kartlar`, govde),
  kartGuncelle: (id: number, govde: Record<string, unknown>) =>
    api.patch<Kart>(`/api/gorevler/kartlar/${id}`, govde),
  kartTasi: (id: number, column_id: number, sira: number) =>
    api.post<Kart>(`/api/gorevler/kartlar/${id}/tasi`, { column_id, sira }),
  kartSil: (id: number) => api.delete<void>(`/api/gorevler/kartlar/${id}`),

  yorumlar: (kartId: number) => api.get<Yorum[]>(`/api/gorevler/kartlar/${kartId}/yorumlar`),
  yorumEkle: (kartId: number, metin: string) =>
    api.post<Yorum>(`/api/gorevler/kartlar/${kartId}/yorumlar`, { metin }),

  kayitTipleri: () => api.get<KayitTipi[]>("/api/gorevler/kayit-tipleri"),
};
