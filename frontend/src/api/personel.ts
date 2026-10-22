/**
 * Personel kartı, birim üyeliği ve atanabilir personel — API tipleri ve çağrıları
 * (TS-002 / TS-008 / TS-009; sunucu: `backend/app/api/personel.py`).
 *
 * Personel = kullanıcı: rol, izin, parola ve giriş aç/kapat burada YOK
 * (Kullanıcılar ekranı, `sistem.kullanici`). `email`, `username`,
 * `personel_notu`, `ayrilis_nedeni` yalnız `personel.yaz` sahibine gelir;
 * diğerlerinde anahtar hiç yoktur — tiplerde bu yüzden isteğe bağlı.
 */
import { api } from "./client";

/** `permissions.BIRIMLER` ile aynı kodlar (sözlük tutarlılık testi sunucuda). */
export const BIRIM_ETIKETLERI: Record<string, string> = {
  GUVENLIK: "Güvenlik Sistemleri",
  HABERLESME: "Haberleşme",
  POC: "POC",
  MOBILITE: "Mobilite",
  ARAC_TAKIP: "Araç Takip",
};
export const BIRIM_KODLARI = Object.keys(BIRIM_ETIKETLERI);

export const SAHA_ROLU_ETIKETLERI: Record<string, string> = {
  SEF: "Şef",
  TEKNISYEN: "Teknisyen",
  STAJYER: "Stajyer",
  OFIS: "Ofis",
  YOK: "Sahaya çıkmaz",
};

export interface PersonelBirimi {
  birim: string;
  birincil: boolean;
}

export interface Personel {
  id: number;
  full_name: string;
  sicil_no: string | null;
  unvan: string | null;
  saha_rolu: string | null;
  ise_giris_tarihi: string | null;
  ayrilis_tarihi: string | null;
  is_active: boolean;
  calisiyor: boolean;
  giris_acik: boolean;
  birimler: PersonelBirimi[];
  birincil_birim: string | null;
  rol: { code: string; name: string };
  version: number;
  /** TS-199: doğrudan yönetici; kapsamınız dışındaysa `id: null`, ad "Kapsam dışı kişi". */
  yonetici?: { id: number | null; ad: string } | null;
  /** Yalnız "Ekibim" listesinde: kişinin şu an açık sayacı var mı. */
  acik_sayac_var?: boolean;
  // Yalnız personel.yaz:
  email?: string | null;
  username?: string;
  personel_notu?: string | null;
  ayrilis_nedeni?: string | null;
}

export interface PersonelSuzgeci {
  q?: string;
  birim?: string;
  birimsiz?: boolean;
  saha_rolu?: string;
  durum?: string;
  giris?: string;
  /** Yalnız doğrudan bağlılarım — süzgeçtir, yetki genişletmez (TS-199). */
  ekibim?: boolean;
}

export interface PersonelKpi {
  kod: string;
  baslik: string;
  adet: number;
  suzgec: PersonelSuzgeci;
}

export interface AtanabilirKisi {
  id: number;
  ad: string;
  saha_rolu: string;
  birimler: string[];
  birincil_birim: string | null;
  giris_acik: boolean;
}

export interface PersonelGirdisi {
  full_name: string;
  sicil_no?: string | null;
  unvan?: string | null;
  saha_rolu?: string | null;
  ise_giris_tarihi?: string | null;
  personel_notu?: string | null;
  birimler?: PersonelBirimi[];
}

export function suzgecParametreleri(s: PersonelSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  if (s.q) p.set("q", s.q);
  if (s.birim) p.set("birim", s.birim);
  if (s.birimsiz) p.set("birimsiz", "true");
  if (s.saha_rolu) p.set("saha_rolu", s.saha_rolu);
  if (s.durum) p.set("durum", s.durum);
  if (s.giris) p.set("giris", s.giris);
  if (s.ekibim) p.set("ekibim", "true");
  return p;
}

export const personelApi = {
  liste: (s: PersonelSuzgeci, limit: number, offset: number) => {
    const p = suzgecParametreleri(s);
    p.set("limit", String(limit));
    p.set("offset", String(offset));
    return api.getSayfa<Personel>(`/api/personel?${p}`);
  },
  ozet: () => api.get<PersonelKpi[]>("/api/personel/ozet"),
  getir: (id: number) => api.get<Personel>(`/api/personel/${id}`),
  olustur: (g: PersonelGirdisi) => api.post<Personel>("/api/personel", g),
  guncelle: (id: number, g: Partial<PersonelGirdisi> & { version: number }) =>
    api.patch<Personel>(`/api/personel/${id}`, g),
  yoneticiYaz: (id: number, yonetici_id: number | null, version: number) =>
    api.put<Personel>(`/api/personel/${id}/yonetici`, { yonetici_id, version }),
  birimleriYaz: (id: number, birimler: PersonelBirimi[]) =>
    api.put<PersonelBirimi[]>(`/api/personel/${id}/birimler`, { birimler }),
  aktiflestir: (id: number) =>
    api.post<{ personel: Personel; giris_acik: boolean; mesaj: string }>(
      `/api/personel/${id}/aktiflestir`,
    ),
  atanabilir: (birim: string, sahaRolleri?: string[]) => {
    const p = new URLSearchParams({ birim });
    for (const r of sahaRolleri ?? []) p.append("saha_rolu", r);
    return api.get<AtanabilirKisi[]>(`/api/personel/atanabilir?${p}`);
  },
  excelYolu: (s: PersonelSuzgeci) => `/api/personel/liste.xlsx?${suzgecParametreleri(s)}`,
};
