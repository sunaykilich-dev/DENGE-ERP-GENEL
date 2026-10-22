/**
 * Planlama (takvim, havuz, KPI, plan/toplu plan/yeniden plan, araç havuzu) —
 * API tipleri ve çağrıları (TS-040…049; sunucu: `backend/app/api/teknik_servis_planlama.py`).
 *
 * Kurallar sunucudadır; ekran yalnız yansıtır:
 * - grup anahtarı (havuz) sunucuda üretilir, istemci normalizasyon YAZMAZ;
 * - KPI sayısı = `/kpi-liste?kod=` `X-Toplam-Kayit`;
 * - irtibat alanları izinsiz kullanıcıya `null` gelir;
 * - çakışma 409'u `ApiError.govde.kod === "PLAN_CAKISMA"` ile ayırt edilir.
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

/** Toplu işlemde kurala takılan işlerin numaraları (409 `PLAN_KURAL`). */
export function sorunluIsler(e: unknown): string[] {
  if (!(e instanceof ApiError)) return [];
  const g = e.govde as { is_nolari?: string[] } | undefined;
  return g?.is_nolari ?? [];
}

export const planlamaApi = {
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
    api.put<{ plan: Plan; durum: string }>(`${ON}/isler/${isId}/plan`, g),
  geriAl: (isId: number, neden: string, not?: string | null) =>
    api.delete<{ plan: Plan; durum: string }>(`${ON}/isler/${isId}/plan`, {
      neden,
      not: not || null,
    }),
  gecmis: (isId: number) => api.get<Plan[]>(`${ON}/isler/${isId}/plan-gecmisi`),
  sahaOnerisi: (isId: number) => api.get<SahaOnerisi>(`${ON}/isler/${isId}/saha-onerisi`),
  topluPlan: (isIdler: number[], g: PlanGirdisi) =>
    api.post<{ ziyaret_id: number; ziyaret_no: string; is_sayisi: number }>(
      `${ON}/toplu-plan`,
      { ...g, is_idler: isIdler },
    ),
  yenidenPlan: (isIdler: number[], g: PlanGirdisi) =>
    api.post<{ plan_idler: number[]; ziyaret_id: number | null }>(`${ON}/yeniden-plan`, {
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
