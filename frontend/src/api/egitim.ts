/**
 * Eğitim — API tipleri ve çağrıları (TS-150…160).
 *
 * Sunucu: `backend/app/api/egitim.py`. Kişiye ait kayıtlar (plan, gözlem,
 * faaliyet, belge) kişinin altında adreslenir (`/kisiler/{id}/...`); katalog
 * öğelerinin kimliği gövdede taşınır. Detay alanları (`notlar`, `maddeler`,
 * `kanit`, `belge_no` ...) yalnız `egitim.detay` sahibine döner — tiplerde
 * isteğe bağlıdır ve YOKSA arayüz o bölümü çizmez.
 */
import { api, type Sayfa } from "./client";

export const EGITIM_ONEK = "/egitim";
const E = "/api/egitim";

export const KATEGORI_ETIKETLERI: Record<string, string> = {
  TEKNIK: "Teknik",
  ISG: "İSG",
  KISISEL_GELISIM: "Kişisel Gelişim",
  IS_SURECI: "İş Süreci",
};
export const PLAN_DURUM_ETIKETLERI: Record<string, string> = {
  PLANLANDI: "Planlandı",
  ERTELENDI: "Ertelendi",
  BASARISIZ_TEKRAR: "Tekrar gerekli",
  TAMAMLANDI: "Tamamlandı",
  IPTAL: "İptal",
};
export const PLAN_DURUM_RENKLERI: Record<string, string> = {
  PLANLANDI: "blue",
  ERTELENDI: "orange",
  BASARISIZ_TEKRAR: "volcano",
  TAMAMLANDI: "green",
  IPTAL: "default",
};
export const SONUC_ETIKETLERI: Record<string, string> = {
  KRITIK: "KRİTİK",
  EKSIK_GOZLEM: "Eksik gözlem",
  BASARILI: "Başarılı",
  GELISIM_GEREKLI: "Gelişim gerekli",
};
export const SONUC_RENKLERI: Record<string, string> = {
  KRITIK: "red",
  EKSIK_GOZLEM: "orange",
  BASARILI: "green",
  GELISIM_GEREKLI: "gold",
};
export const ASAMALAR = [0, 30, 60, 90] as const;
export const asamaEtiketi = (a: number) => (a === 0 ? "İlk gözlem" : `${a}. gün`);
export const MADDE_PUANLARI = [
  { deger: 2, ad: "Uygun" },
  { deger: 1, ad: "Kısmen" },
  { deger: 0, ad: "Yapmadı" },
  { deger: -1, ad: "Gözlenmedi" },
];

// --- Tipler ----------------------------------------------------------------------

export interface KpiKutusuVerisi {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number;
  yol: string;
  vurgu: "normal" | "uyari" | "kritik";
}

export interface EgitimOzeti {
  yil: number;
  kutular: KpiKutusuVerisi[];
  gerceklesme: {
    toplam: number;
    tamamlanan: number;
    zamaninda: number;
    gec: number;
    acik: number;
    yuzde: number | null;
  };
  gozlem: { toplam: number; basarili: number; basari_orani: number | null; ortalama_puan: number | null };
  birim_ilerleme: { birim: string; toplam: number; tamamlanan: number }[];
}

export interface Kurs {
  id: number;
  kod: string;
  baslik: string;
  kategori: string;
  birim: string | null;
  sure_saat: string;
  zorunlu: boolean;
  neden: string | null;
  hedef_davranis: string | null;
  basari_olcutu: string | null;
  gozlem_esik_yuzde: string | null;
  sinav_gecme_puani: number | null;
  yenileme_ay: number | null;
  is_active: boolean;
  version: number;
}

export interface Kriter {
  id: number;
  course_id: number;
  sira: number;
  metin: string;
  is_critical: boolean;
  is_active: boolean;
  version: number;
}

export interface Plan {
  id: number;
  user_id: number;
  ad: string;
  course_id: number;
  kurs_kod: string;
  kurs: string;
  plan_yili: number;
  hedef_tarih: string;
  onceki_hedef_tarih: string | null;
  status: string;
  durum_gerekcesi: string | null;
  gelisim_hedefi: string | null;
  completed_on: string | null;
  gec: boolean;
  geciken: boolean;
  sonraki_durumlar: string[];
  version: number;
}

export interface Oturum {
  id: number;
  course_id: number;
  kurs: string | null;
  oturum_tarihi: string;
  egitmen_ad: string | null;
  sure_saat: string;
  yer: string | null;
  notlar: string | null;
  katilimci: number;
  version: number;
}

export interface KatilimAdayi {
  user_id: number;
  ad: string;
  plan_id: number | null;
  planli: boolean;
  katilim_id: number | null;
  katildi: boolean | null;
  on_puan: number | null;
  son_puan: number | null;
  notlar: string | null;
}

export interface MaddeSonucu {
  criterion_id: number;
  sira: number;
  metin: string;
  kritik: boolean;
  puan: number;
  gozlenmedi_gerekcesi: string | null;
}

export interface Gozlem {
  id: number;
  user_id: number;
  ad: string;
  course_id: number;
  kurs: string;
  plan_id: number | null;
  asama: number;
  gozlem_tarihi: string;
  puan: string | number | null;
  sonuc: string;
  kritik: boolean;
  observer_user_id: number | null;
  gozlemci_ad: string | null;
  service_order_id: number | null;
  birim: string | null;
  gordu_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  version: number;
  // Yalnız `egitim.detay` (ya da kişinin kendisi):
  notlar?: string | null;
  aksiyon_plani?: string | null;
  sonraki_izleme?: string | null;
  personel_yorumu?: string | null;
  maddeler?: MaddeSonucu[];
}

export interface Faaliyet {
  id: number;
  observation_id: number;
  user_id: number;
  ad: string;
  kurs: string;
  gozlem_tarihi: string;
  gozlem_iptal: boolean;
  termin: string;
  status: string;
  gecikmis: boolean;
  kapanis_turu: string | null;
  closed_at: string | null;
  version: number;
  kapanis_kaniti?: string | null;
}

export interface Takip {
  plan_id: number;
  user_id: number;
  ad: string;
  course_id: number;
  kurs: string;
  asama: number;
  completed_on: string;
  vade: string;
  durum: "GECIKTI" | "ZAMANI_GELDI" | "YAKLASAN";
}

export interface Gecerlilik {
  kaynak: "PLAN" | "BELGE";
  kayit_id: number;
  user_id: number;
  kisi: string;
  ad: string;
  baslangic: string;
  bitis: string;
  durum: "DOLDU" | "DOLACAK" | "GECERLI";
  belge_no?: string | null;
  aciklama?: string | null;
}

export interface Yetkinlik {
  id: number;
  kod: string;
  ad: string;
  birim: string | null;
  onerilen_hedef: number;
  is_critical: boolean;
  is_active: boolean;
  version: number;
}

export interface MatrisSatiri {
  id: number;
  user_id: number;
  ad: string;
  competency_id: number;
  kod: string;
  yetkinlik: string;
  kritik: boolean;
  mevcut_seviye: number;
  hedef_seviye: number;
  hedef_alti: boolean;
  degerlendirme_tarihi: string;
}

export interface YetkinlikGecmisi {
  id: number;
  kod: string;
  yetkinlik: string;
  mevcut_seviye: number;
  hedef_seviye: number;
  degerlendirme_tarihi: string;
  assessed_by_ad: string | null;
  kaynak: string;
  kanit?: string | null;
}

export interface EgitimKisi {
  id: number;
  ad: string;
  unvan: string | null;
  saha_rolu: string | null;
  birimler: string[];
  birincil_birim: string | null;
  calisiyor: boolean;
}

export interface KisiKarti {
  kisi: EgitimKisi;
  kendi: boolean;
  bos?: boolean;
  planlar: Plan[];
  katilimlar: {
    id: number;
    session_id: number;
    kurs: string;
    oturum_tarihi: string;
    katildi: boolean;
    on_puan: number | null;
    son_puan: number | null;
  }[];
  gozlemler: Gozlem[];
  faaliyetler: Faaliyet[];
  gecerlilik: Gecerlilik[];
  belgeler: {
    id: number;
    belge_adi: string;
    verilis_tarihi: string;
    gecerlilik_bitis: string | null;
    cancelled_at: string | null;
    cancel_reason: string | null;
    belge_no?: string | null;
  }[];
  yetkinlikler: {
    competency_id: number;
    kod: string;
    yetkinlik: string;
    kritik: boolean;
    mevcut_seviye: number;
    hedef_seviye: number;
    degerlendirme_tarihi: string;
  }[];
}

export interface GozlemGirdisi {
  user_id: number;
  course_id: number;
  asama: number;
  gozlem_tarihi: string;
  plan_id?: number | null;
  service_order_id?: number | null;
  puanlar: { criterion_id: number; puan: number; gozlenmedi_gerekcesi?: string | null }[];
  notlar?: string | null;
  aksiyon_plani?: string | null;
  sonraki_izleme?: string | null;
}

type Parametre = Record<string, string | number | boolean | null | undefined>;

function sorgu(p: Parametre): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

const kisiYolu = (kisiId: number) => `${E}/kisiler/${kisiId}`;

export const egitimApi = {
  ozet: (yil: number, birim?: string) => api.get<EgitimOzeti>(`${E}/ozet${sorgu({ yil, birim })}`),

  kurslar: (p: Parametre = {}) => api.get<Kurs[]>(`${E}/kurslar${sorgu({ limit: 200, ...p })}`),
  kursOlustur: (g: Partial<Kurs>) => api.post<Kurs>(`${E}/kurslar`, g),
  kursGuncelle: (g: Partial<Kurs> & { id: number; version: number }) => api.patch<Kurs>(`${E}/kurslar`, g),
  kriterler: (kursId: number) => api.get<Kriter[]>(`${E}/kriterler${sorgu({ kurs_id: kursId })}`),
  kriterEkle: (g: { kurs_id: number; metin: string; is_critical: boolean }) =>
    api.post<Kriter>(`${E}/kriterler`, g),
  kriterGuncelle: (g: Partial<Kriter> & { id: number; version: number }) =>
    api.patch<Kriter>(`${E}/kriterler`, g),

  planlar: (p: Parametre, limit: number, offset: number): Promise<Sayfa<Plan>> =>
    api.getSayfa<Plan>(`${E}/planlar${sorgu({ ...p, limit, offset })}`),
  planExcelYolu: (p: Parametre) => `${E}/plan.xlsx${sorgu(p)}`,
  topluPlan: (g: {
    course_id: number;
    plan_yili: number;
    hedef_tarih?: string | null;
    gelisim_hedefi?: string | null;
    user_ids: number[];
  }) => api.post<{ olusan: number; atlanan: number }>(`${E}/planlar/toplu`, g),
  planErtele: (p: Plan, yeni_tarih: string, gerekce: string) =>
    api.post<Plan>(`${kisiYolu(p.user_id)}/planlar/${p.id}/ertele`, { yeni_tarih, gerekce, version: p.version }),
  planIptal: (p: Plan, gerekce: string) =>
    api.post<Plan>(`${kisiYolu(p.user_id)}/planlar/${p.id}/iptal`, { gerekce, version: p.version }),

  oturumlar: (p: Parametre, limit: number, offset: number) =>
    api.getSayfa<Oturum>(`${E}/oturumlar${sorgu({ ...p, limit, offset })}`),
  oturumOlustur: (g: { course_id: number; oturum_tarihi: string; egitmen_ad?: string | null; yer?: string | null }) =>
    api.post<Oturum>(`${E}/oturumlar`, g),
  oturumGuncelle: (g: Partial<Oturum> & { id: number; version: number }) => api.patch<Oturum>(`${E}/oturumlar`, g),
  oturumSil: (o: Oturum) => api.post<void>(`${E}/oturumlar/sil`, { id: o.id, version: o.version }),
  katilimcilar: (oturumId: number) =>
    api.get<KatilimAdayi[]>(`${E}/oturumlar/katilimcilar${sorgu({ oturum_id: oturumId })}`),
  topluKatilim: (
    oturumId: number,
    satirlar: { user_id: number; katildi: boolean; on_puan?: number | null; son_puan?: number | null }[],
  ) => api.put<{ yazilan: number }>(`${E}/oturumlar/katilim/toplu`, { oturum_id: oturumId, satirlar }),

  gozlemler: (p: Parametre, limit: number, offset: number) =>
    api.getSayfa<Gozlem>(`${E}/gozlemler${sorgu({ ...p, limit, offset })}`),
  gozlem: (kisiId: number, gozlemId: number) => api.get<Gozlem>(`${kisiYolu(kisiId)}/gozlemler/${gozlemId}`),
  gozlemKaydet: (g: GozlemGirdisi) =>
    api.post<{ gozlem: Gozlem; uyarilar: string[]; faaliyet_id: number | null }>(`${E}/gozlemler`, g),
  gozlemIptal: (g: Gozlem, gerekce: string) =>
    api.post<Gozlem>(`${kisiYolu(g.user_id)}/gozlemler/${g.id}/iptal`, { gerekce, version: g.version }),

  takipler: (p: Parametre, limit: number, offset: number) =>
    api.getSayfa<Takip>(`${E}/takipler${sorgu({ ...p, limit, offset })}`),
  faaliyetler: (p: Parametre, limit: number, offset: number) =>
    api.getSayfa<Faaliyet>(`${E}/duzeltici-faaliyetler${sorgu({ ...p, limit, offset })}`),
  faaliyetKapat: (f: Faaliyet, kanit: string) =>
    api.post<Faaliyet>(`${kisiYolu(f.user_id)}/duzeltici-faaliyetler/${f.id}/kapat`, { kanit, version: f.version }),

  belgeler: (p: Parametre, limit: number, offset: number) =>
    api.getSayfa<Gecerlilik>(`${E}/belgeler${sorgu({ ...p, limit, offset })}`),
  belgeOlustur: (g: {
    user_id: number;
    belge_adi: string;
    verilis_tarihi: string;
    gecerlilik_bitis?: string | null;
    belge_no?: string | null;
    course_id?: number | null;
  }) => api.post<{ id: number }>(`${E}/belgeler`, g),
  belgeIptal: (kisiId: number, belgeId: number, gerekce: string) =>
    api.post<{ id: number }>(`${kisiYolu(kisiId)}/belgeler/${belgeId}/iptal`, { gerekce }),

  yetkinlikler: (aktif?: boolean) => api.get<Yetkinlik[]>(`${E}/yetkinlikler${sorgu({ aktif })}`),
  yetkinlikOlustur: (g: Partial<Yetkinlik>) => api.post<Yetkinlik>(`${E}/yetkinlikler`, g),
  yetkinlikGuncelle: (g: Partial<Yetkinlik> & { id: number; version: number }) =>
    api.patch<Yetkinlik>(`${E}/yetkinlikler`, g),
  matris: (p: Parametre, limit: number, offset: number) =>
    api.getSayfa<MatrisSatiri>(`${E}/yetkinlik-matrisi${sorgu({ ...p, limit, offset })}`),
  degerlendir: (g: {
    user_id: number;
    competency_id: number;
    mevcut_seviye: number;
    hedef_seviye?: number | null;
    kanit?: string | null;
  }) => api.post<{ id: number; uyarilar: string[] }>(`${E}/yetkinlik-degerlendirmeleri`, g),
  yetkinlikGecmisi: (kisiId: number) => api.get<YetkinlikGecmisi[]>(`${kisiYolu(kisiId)}/yetkinlik-gecmisi`),

  kisiler: (p: Parametre, limit = 50, offset = 0) =>
    api.getSayfa<EgitimKisi>(`${E}/kisiler${sorgu({ ...p, limit, offset })}`),
  kart: (kisiId: number) => api.get<KisiKarti>(`${kisiYolu(kisiId)}/kart`),
  kendim: () => api.get<KisiKarti>(`${E}/kendim`),
  gordum: (gozlemId: number, yorum?: string) =>
    api.post<{ id: number; gordu_at: string }>(`${E}/kendim/gordum`, { gozlem_id: gozlemId, yorum: yorum || null }),
};
