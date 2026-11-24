/**
 * Planlama (takvim, havuz, KPI, plan/toplu plan/yeniden plan, araç havuzu) —
 * API tipleri ve çağrıları (TS-040…049; sunucu: `backend/app/api/teknik_servis_planlama.py`).
 *
 * Kurallar sunucudadır; ekran yalnız yansıtır:
 * - grup anahtarı (havuz) sunucuda üretilir, istemci normalizasyon YAZMAZ;
 * - KPI sayısı = `/kpi-liste?kod=` `X-Toplam-Kayit`;
 * - irtibat alanları izinsiz kullanıcıya `null` gelir;
 * - çakışma 409'u `ApiError.govde.kod === "PLAN_CAKISMA"` ile ayırt edilir;
 * - geçmiş tarihe gerekçesiz plan 409 `kod=GECMIS_TARIH` (tekli/toplu/yeniden;
 *   KARARLAR 2026-11-04 §6.9): aynı istek `gecmis_tarih_gerekcesi` (≥10
 *   karakter) ile yinelenince kabul edilir.
 */
import { api, ApiError, type Sayfa } from "./client";

const ON = "/api/teknik-servis/planlama";

export const PLAN_NEDENLERI: Record<string, string> = {
  MUSTERI_TALEBI: "Müşteri talebi",
  PERSONEL_YOK: "Personel yok",
  ARAC_YOK: "Araç yok",
  MALZEME_BEKLENIYOR: "Malzeme bekleniyor",
  HAVA_ERISIM: "Hava / erişim",
  ONCEKI_IS_UZADI: "Önceki iş uzadı",
  DIGER: "Diğer",
};

export const DEGISIM_ETIKETLERI: Record<string, string> = {
  ILK_PLAN: "İlk plan",
  ERTELEME: "Erteleme",
  EKIP_DEGISIMI: "Ekip/araç değişimi",
  YENIDEN_PLAN: "Yeniden plan",
};

export const DURUM_ETIKETLERI: Record<string, string> = {
  MUSTERI_TALEBI: "Müşteri Talebi",
  PLANLAMADA: "Planlamada",
  PLANLANDI: "Planlandı",
  YOLA_CIKILDI: "Yola Çıkıldı",
  SAHADA: "Sahada",
  ISLEMDE: "İşlemde",
  ATOLYEDE: "Atölyede",
  BEKLEMEDE: "Beklemede",
  TAMAMLANDI: "Tamamlandı",
  KAPATILDI: "Kapatıldı",
  TEKRAR_ACILDI: "Tekrar Açıldı",
  IPTAL: "İptal",
};

export interface EkipUyesi {
  user_id: number;
  ad: string | null;
  rol: "SEF" | "TEKNISYEN";
  sahaya_gidiyor: boolean;
}

/** İş + müşteri + lokasyon ortak alanları (takvim ve havuz satırı). */
export interface IsOzeti {
  is_id: number;
  so_no: string;
  birim: string;
  tur: string;
  kategori: string;
  oncelik: string;
  durum: string;
  kapali: boolean;
  konu: string;
  musteri_id: number | null;
  musteri: string | null;
  lokasyon_id: number | null;
  lokasyon: string | null;
  il: string | null;
  ilce: string | null;
  /** İzinsizde null (E02-24). */
  acik_adres: string | null;
  irtibat_adi: string | null;
  irtibat_telefon: string | null;
}

/** Aktif planı olmayan iş (takvimde başlangıç–bitiş günleri boyunca soluk kart). */
export interface PlansizIs {
  is_id: number;
  so_no: string;
  birim: string;
  tur: string;
  konu: string;
  musteri: string | null;
  durum: string;
  durum_adi: string;
  kapali: boolean;
  baslangic: string;
  bitis: string;
}

export interface TakvimSatiri extends IsOzeti {
  plan_id: number;
  plan_tarihi: string;
  baslangic_saati: string | null;
  sure_dk: number;
  starts_at: string | null;
  ends_at: string | null;
  ziyaret_id: number | null;
  ziyaret_no: string | null;
  /** Ziyaret kartı anahtarı (`Z<id>` ya da tekli planda `I<is_id>`). */
  kart_anahtari: string;
  arac_id: number | null;
  arac_plaka: string | null;
  ekip: EkipUyesi[];
  saha_bolgesi: string | null;
  saha_notu: string | null;
  plan_notu: string | null;
  degisim: string;
  cakisma: boolean;
  cakisma_gecildi: boolean;
  erteleme_sayisi: number;
}

export interface HavuzSatiri extends IsOzeti {
  acilis: string | null;
  yas_gun: number | null;
  grup_anahtari: string;
  grup_etiketi: string;
}

export interface PlanKpi {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number;
}

export interface Plan {
  id: number;
  is_id: number;
  aktif: boolean;
  ziyaret_id: number | null;
  plan_tarihi: string;
  baslangic_saati: string | null;
  sure_dk: number;
  arac_id: number | null;
  saha_bolgesi: string | null;
  saha_notu: string | null;
  plan_notu: string | null;
  degisim: string;
  degisim_nedeni: string | null;
  degisim_notu: string | null;
  cakisma_gerekcesi: string | null;
  iptal_at: string | null;
  iptal_nedeni: string | null;
  iptal_notu: string | null;
  olusturma: string | null;
  planlayan: string | null;
  ekip: EkipUyesi[];
}

export interface IsPlani {
  is_id: number;
  so_no: string;
  birim: string;
  durum: string;
  kapali: boolean;
  plan: Plan | null;
}

export interface EkipGirdisi {
  sef_idler: number[];
  sahaya_giden_sefler: number[];
  teknisyen_idler: number[];
  sorumlu_id?: number | null;
}

export interface PlanGirdisi {
  plan_tarihi: string;
  baslangic_saati: string | null;
  sure_dk: number;
  ekip?: EkipGirdisi | null;
  arac_id?: number | null;
  saha_bolgesi?: string | null;
  saha_notu?: string | null;
  plan_notu?: string | null;
  degisim_nedeni?: string | null;
  degisim_notu?: string | null;
  cakisma_gerekcesi?: string | null;
  /** Geçmiş tarihe plan gerekçesi (≥10 karakter); yoksa 409 `GECMIS_TARIH`. */
  gecmis_tarih_gerekcesi?: string | null;
  beklenen_aktif_plan_id?: number | null;
}

export interface Cakisma {
  tur: "KISI" | "ARAC" | "MUSAITLIK";
  baslangic: string;
  bitis: string;
  saat_araligi: string;
  user_id: number | null;
  arac_id: number | null;
  plan_id: number | null;
  so_no: string | null;
  birim: string | null;
  /** Kapsam dışı iş: iş no ve müşteri gizli. */
  maskeli: boolean;
}

export interface SahaOnerisi {
  is_id: number;
  alanlar: { alan: string; deger: string | number; kaynak: string }[];
}

export interface Arac {
  id: number;
  plaka: string;
  birim: string | null;
  zimmetli_id: number | null;
  zimmetli: string | null;
  mobilite_arac_id: number | null;
  notlar: string | null;
  is_active: boolean;
  version: number;
}

export interface Suzgec {
  birim?: string;
  tur?: string;
}

function parametre(s: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v !== undefined && v !== "" && v !== null) p.set(k, String(v));
  }
  return p.toString();
}

/** 409 planlama çakışması mı (gerekçeyle geçilebilir)? */
export function planCakismasi(e: unknown): Cakisma[] | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const g = e.govde as { kod?: string; cakismalar?: Cakisma[] } | undefined;
  return g?.kod === "PLAN_CAKISMA" ? (g.cakismalar ?? []) : null;
}

/** 409 `GECMIS_TARIH` mı? Sunucunun mesajını döner (gerekçeyle geçilir); değilse null. */
export function gecmisTarihHatasi(e: unknown): string | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const g = e.govde as { kod?: string; detail?: string } | undefined;
  return g?.kod === "GECMIS_TARIH" ? (g.detail ?? e.message) : null;
}

/** En az uzunluk: geçmiş tarih ve çakışma gerekçesi (sunucuyla aynı). */
export const GEREKCE_ALT = 10;

/** Toplu işlemde kurala takılan işlerin numaraları (409 `PLAN_KURAL`). */
export function sorunluIsler(e: unknown): string[] {
  if (!(e instanceof ApiError)) return [];
  const g = e.govde as { is_nolari?: string[] } | undefined;
  return g?.is_nolari ?? [];
}

export const planlamaApi = {
  plansiz: (baslangic: string, bitis: string, s: Suzgec) =>
    api.get<PlansizIs[]>(`${ON}/takvim/plansiz?${parametre({ baslangic, bitis, ...s })}`),
  takvim: (baslangic: string, bitis: string, s: Suzgec) =>
    api.get<TakvimSatiri[]>(`${ON}/takvim?${parametre({ baslangic, bitis, ...s })}`),
  havuz: (
    s: Suzgec & { gruplama?: string; q?: string },
    limit = 200,
    offset = 0,
  ): Promise<Sayfa<HavuzSatiri>> =>
    api.getSayfa<HavuzSatiri>(`${ON}/havuz?${parametre({ ...s, limit, offset })}`),
  kpi: (gun: string, s: Suzgec) => api.get<PlanKpi[]>(`${ON}/kpi?${parametre({ gun, ...s })}`),
  kpiListe: (kod: string, gun: string, s: Suzgec, limit = 200) =>
    api.getSayfa<TakvimSatiri | HavuzSatiri>(
      `${ON}/kpi-liste?${parametre({ kod, gun, ...s, limit })}`,
    ),
  excelYolu: (baslangic: string, bitis: string, s: Suzgec) =>
    `${ON}/takvim.xlsx?${parametre({ baslangic, bitis, ...s })}`,
  isPlani: (isId: number) => api.get<IsPlani>(`${ON}/isler/${isId}/plan`),
  planla: (isId: number, g: PlanGirdisi) =>
    api.put<{ plan: Plan; durum: string; uyarilar?: string[] }>(`${ON}/isler/${isId}/plan`, g),
  geriAl: (isId: number, neden: string, not?: string | null) =>
    api.delete<{ plan: Plan; durum: string }>(`${ON}/isler/${isId}/plan`, {
      neden,
      not: not || null,
    }),
  gecmis: (isId: number) => api.get<Plan[]>(`${ON}/isler/${isId}/plan-gecmisi`),
  sahaOnerisi: (isId: number) => api.get<SahaOnerisi>(`${ON}/isler/${isId}/saha-onerisi`),
  topluPlan: (isIdler: number[], g: PlanGirdisi) =>
    api.post<{ ziyaret_id: number; ziyaret_no: string; is_sayisi: number; uyarilar?: string[] }>(
      `${ON}/toplu-plan`,
      { ...g, is_idler: isIdler },
    ),
  yenidenPlan: (isIdler: number[], g: PlanGirdisi) =>
    api.post<{ plan_idler: number[]; ziyaret_id: number | null; uyarilar?: string[] }>(`${ON}/yeniden-plan`, {
      ...g,
      is_idler: isIdler,
    }),
  araclar: (birim?: string, aktif?: boolean) =>
    api.get<Arac[]>(
      `${ON}/araclar?${parametre({ birim, aktif: aktif === undefined ? undefined : String(aktif) })}`,
    ),
  aracEkle: (g: { plaka: string; birim?: string | null; zimmetli_id?: number | null; notlar?: string | null }) =>
    api.post<Arac>(`${ON}/araclar`, g),
  aracGuncelle: ({
    id,
    ...g
  }: {
    id: number;
    version: number;
    plaka?: string;
    birim?: string | null;
    ortak_havuz?: boolean;
    zimmetli_id?: number | null;
    zimmet_kaldir?: boolean;
    notlar?: string | null;
    is_active?: boolean;
  }) => api.patch<Arac>(`${ON}/araclar/${id}`, g),
};

// --- Planlama P3 (TS-190) --------------------------------------------------------

export const MUSAITLIK_TURLERI: Record<string, string> = {
  IZIN: "İzin",
  EGITIM: "Eğitim",
  OFIS: "Ofis",
  DIGER: "Diğer",
};

/** KVKK m.6 (E02 K-11): not alanına sağlık bilgisi yazılmaz; sunucu reddeder. */
export const SAGLIK_UYARISI =
  "Nota sağlık bilgisi (hastalık, teşhis, rapor nedeni) yazmayın; 'İzin' türünü seçmek yeterli.";

export interface MusaitlikBlogu {
  id: number;
  version?: number;
  user_id: number;
  ad?: string;
  baslangic: string;
  bitis: string;
  tur: string;
  /** Yalnız planlayıcıya ve kişinin kendisine. */
  not: string | null;
}

export interface KaynakHucresi {
  gun: string;
  /** Planlanan dakika — gerçek süre DEĞİL. */
  plan_dk: number;
  ziyaret_sayisi: number;
  is_sayisi: number;
  cakisma: boolean;
  musaitlik: MusaitlikBlogu[];
  egitim: { kurs: string; sure_saat: number }[];
}

export interface KaynakSatiri {
  user_id: number;
  ad: string;
  saha_rolu: string | null;
  toplam_plan_dk: number;
  hucreler: KaynakHucresi[];
}

export interface KaynakGorunumu {
  hafta_baslangic: string;
  gunler: string[];
  satirlar: KaynakSatiri[];
}

export interface UyumKirilimi {
  anahtar: string;
  etiket: string;
  uyumlu: number;
  kaydi: number;
  eksik: number;
  oran: number | null;
}

export interface PlanUyumu {
  suzgec: { baslangic: string; bitis: string; degerlendirilen_son_gun: string };
  ozet: {
    uyumlu: number;
    kaydi: number;
    eksik: number;
    oran: number | null;
    ziyaret_sayisi: number;
    is_sayisi: number;
    ziyaret_basina_is: number | null;
    tekrar_ziyaret_30: number;
  };
  kirilimlar: Record<string, UyumKirilimi[]>;
  erteleme: { toplam: number; nedenler: { neden: string | null; ad: string; adet: number }[] };
  bekleyen_yasi: { aralik: string; adet: number }[];
}

export interface UyumSatiri {
  anahtar: string;
  ziyaret: string;
  is_nolari: string[];
  plan_tarihi: string;
  ilk_kayit_gunu: string | null;
  sinif: "UYUMLU" | "KAYDI" | "EKSIK";
  birim: string;
  tur: string;
  il: string | null;
  sefler?: string[];
  teknisyenler?: string[];
}

export interface BolgeZiyareti {
  kart_anahtari: string;
  ziyaret_no: string | null;
  plan_tarihi: string;
  musteri: string | null;
  lokasyon: string | null;
  il: string | null;
  ilce: string | null;
  is_nolari: string[];
  baslangic_saati: string | null;
  bitis_saati: string | null;
  onerilen_baslangic: string | null;
  ekip: EkipUyesi[];
  arac_id: number | null;
  arac_plaka: string | null;
}

export interface BolgeOnerisi {
  is_id: number;
  il: string | null;
  ilce: string | null;
  duzey: "ilce" | "il" | null;
  gun_araligi?: number;
  mesaj: string | null;
  plansiz_isler: (IsOzeti & { yas_gun: number | null })[];
  ziyaretler: BolgeZiyareti[];
}

export interface UyumSuzgeci {
  baslangic?: string;
  bitis?: string;
  birim?: string;
  tur?: string;
}

export const planlamaP3Api = {
  musaitlik: (baslangic: string, bitis: string, birim?: string) =>
    api.get<MusaitlikBlogu[]>(`${ON}/musaitlik?${parametre({ baslangic, bitis, birim })}`),
  musaitlikEkle: (g: { kisi_id: number; baslangic: string; bitis: string; tur: string; not?: string | null }) =>
    api.post<MusaitlikBlogu & { plan_uyarilari: Cakisma[] }>(`${ON}/musaitlik`, g),
  musaitlikSil: (kisiId: number, blokId: number) =>
    api.delete<{ id: number; silindi: boolean }>(`${ON}/musaitlik/personel/${kisiId}/bloklar/${blokId}`),
  kaynak: (hafta: string, birim?: string) =>
    api.get<KaynakGorunumu>(`${ON}/kaynak-gorunumu?${parametre({ hafta, birim })}`),
  planUyumu: (s: UyumSuzgeci) => api.get<PlanUyumu>(`${ON}/plan-uyumu?${parametre({ ...s })}`),
  planUyumuAyrinti: (s: UyumSuzgeci & { sinif?: string }, limit = 500) =>
    api.getSayfa<UyumSatiri>(`${ON}/plan-uyumu/ayrinti?${parametre({ ...s, limit })}`),
  planUyumuExcelYolu: (s: UyumSuzgeci) => `${ON}/plan-uyumu.xlsx?${parametre({ ...s })}`,
  bolgeOnerisi: (isId: number, tarih: string) =>
    api.get<BolgeOnerisi>(`${ON}/bolge-onerisi?${parametre({ is_id: isId, tarih })}`),
};