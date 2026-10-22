/**
 * Atölye — API tipleri ve çağrıları (TS-090…101).
 *
 * Sunucu: `backend/app/api/atolye.py`. Tek kayıt uçları kaydı SERVİS İŞİ
 * kimliğiyle adresler (`/{so_id}`); ekran bağlantısı `/atolye/{so_id}`.
 *
 * İzinler: okuma `atolye.gor`, yazma `atolye.yaz`; iptal/geri alma ayrıca
 * `servis.kapat`; atama `atolye.yaz` + `servis.planla`; Excel `atolye.gor` +
 * `servis_rapor.disaaktar`. `repair_amount` yalnız `maliyet.gor` sahibine
 * gelir (anahtar hiç yoktur) — istemci tutarı hesaplamaz, yalnız gösterir.
 *
 * 409 gövdeleri makine okunur alan taşır (`kod`: ACIK_KAYIT, COKLU_EKIPMAN,
 * ATOLYE_YONLENDIR; `adaylar`); bu yüzden yazma çağrıları gövdeyi taşıyan
 * `AtolyeHatasi` fırlatır.
 */
import { api, ApiError, type Sayfa } from "./client";

export const ATOLYE_ONEK = "/teknik-servis/atolye";
const URL_ = `/api${ATOLYE_ONEK}`;

export const DURUM_RENKLERI: Record<string, string> = {
  KABUL_EDILDI: "blue",
  TESHISTE: "geekblue",
  ONAY_BEKLIYOR: "gold",
  ONARIMDA: "processing",
  PARCA_BEKLIYOR: "orange",
  DIS_SERVISTE: "purple",
  TEST_KONTROL: "cyan",
  TESLIME_HAZIR: "green",
  ONARILMADAN_IADE: "volcano",
  KARGOYA_VERILDI: "lime",
  TESLIM_EDILDI: "default",
  IPTAL: "red",
};

export const GARANTI_RENKLERI: Record<string, string> = {
  GARANTI_ICI: "green",
  GARANTI_DISI: "default",
  ONARIM_GARANTISI: "cyan",
  BELIRSIZ: "gold",
};

export const TEST_ADLARI: Record<string, string> = { GECTI: "Geçti", KALDI: "Kaldı" };
export const ONAY_KARARI_ADLARI: Record<string, string> = {
  ONAYLANDI: "Onaylandı",
  REDDEDILDI: "Reddedildi",
  ONAY_GEREKMEZ: "Onay gerekmez",
};
export const ONAY_KANALI_ADLARI: Record<string, string> = {
  TELEFON: "Telefon",
  EPOSTA: "E-posta",
  YAZILI: "Yazılı",
  TEKLIF: "Teklif",
};
/** Kabul ekranındaki marka listesi (sunucu `ATOLYE_MARKALARI`); kütükte serbest metin. */
export const MARKA_ADLARI: Record<string, string> = {
  HYTERA: "Hytera",
  HYT: "HYT",
  HQT: "HQT",
  MOTOROLA: "Motorola",
  KIRISUN: "Kirisun",
  ASELSAN: "Aselsan",
  DIGER: "Diğer",
};

export interface KodAd {
  kod: string;
  ad: string;
}

export interface FormVerileri {
  durumlar: KodAd[];
  servis_turleri: KodAd[];
  markalar: string[];
  ekipman_tipleri: string[];
  teslim_tipleri: KodAd[];
  aksesuar_turleri: KodAd[];
  onarim_kategorileri: KodAd[];
  test_sonuclari: string[];
  onay_kararlari: string[];
  onay_kanallari: string[];
  garanti_durumlari: KodAd[];
  ariza_nedenleri: { id: number; ad: string }[];
  yas_kovalari: string[];
}

export interface EkipmanOzeti {
  id: number;
  tip: string;
  marka: string | null;
  model: string | null;
  seri: string | null;
}

export interface AtolyeSatiri {
  id: number;
  so_id: number;
  kayit_id: number;
  atolye_no: string;
  so_no: string;
  birim: string;
  servis_durumu: string;
  musteri: { id: number; title: string | null } | null;
  service_type: string;
  status: string;
  acik: boolean;
  ekipman: EkipmanOzeti | null;
  sorumlu: { id: number; ad: string | null } | null;
  ekip: { id: number; ad: string | null }[];
  received_at: string;
  estimated_finish_date: string | null;
  bekleme_gunu: number;
  geciken: boolean;
  warranty_status: string;
  intake_group_no: number | null;
  ariza_nedeni: string | null;
  repair_category: string | null;
  test_result: string | null;
  completed_at: string | null;
  delivered_at: string | null;
  version: number;
  /** Yalnız `maliyet.gor`; yoksa anahtar hiç gelmez. */
  repair_amount?: number | string | null;
}

export interface Aksesuar {
  id: number;
  kind: string;
  description: string | null;
  qty: number;
  returned: boolean | null;
  return_note: string | null;
}

export interface SonrakiDurum {
  hedef: string;
  ad: string;
  yetkili: boolean;
  gerekce_zorunlu: boolean;
  geri_alma: boolean;
  teslim_bilgisi: boolean;
  engel: string | null | false;
}

export interface AtolyeOlayi {
  id: number;
  olay_turu: string;
  alt_tur: string | null;
  ozet: string;
  kullanici: string | null;
  zaman: string;
}

export interface ParcaSatiri {
  id: number;
  urun_kodu: string;
  urun_adi: string;
  miktar: string;
  hareket_turu: string | null;
  created_at: string;
  /** Yalnız `maliyet.gor`. */
  birim_maliyet?: string | null;
}

export interface AtolyeDetay extends AtolyeSatiri {
  customer_id: number | null;
  address_id: number | null;
  contact_id: number | null;
  ekipman: EkipmanOzeti & { warranty_start: string | null; warranty_end: string | null };
  receive_type: string;
  received_by: { id: number | null; ad: string | null };
  customer_complaint: string;
  physical_condition: string | null;
  warranty_end_snapshot: string | null;
  fault_reason_id: number | null;
  diagnosis_note: string | null;
  diagnosed_by: string | null;
  diagnosed_at: string | null;
  is_repairable: boolean | null;
  repair_note: string | null;
  tested_by: string | null;
  tested_at: string | null;
  approval_decision: string | null;
  approval_channel: string | null;
  approved_by_name: string | null;
  approval_at: string | null;
  approval_note: string | null;
  delivery_type: string | null;
  cargo_company: string | null;
  cargo_tracking_no: string | null;
  cargo_sent_at: string | null;
  delivered_to_name: string | null;
  delivery_note: string | null;
  external_vendor: { id: number; title: string } | null;
  external_rma_no: string | null;
  external_sent_at: string | null;
  external_returned_at: string | null;
  logo_form_no: string | null;
  logo_main_service_no: string | null;
  integration_company: string | null;
  project_name: string | null;
  notes: string | null;
  rental_asset_id: number | null;
  aksesuarlar: Aksesuar[];
  bekleme: { neden: string; neden_adi: string; started_at: string } | null;
  sonuc: { sonuc: string; cozum_kanali: string } | null;
  olaylar: AtolyeOlayi[];
  parcalar: ParcaSatiri[];
  sure: {
    kisi_saat_dk: number;
    sure_durumu: string;
    sure_eksik: boolean;
    mola_dk: number;
    faaliyet_kirilimi: Record<string, number>;
    acik_bolum_sayisi: number;
  };
  teklifler: { id: number; quote_no: string; status: string }[];
  tekrar_gelis: boolean;
  sonraki_durumlar: SonrakiDurum[];
  updated_at: string;
  uyarilar?: string[];
}

export interface AtolyeKpi {
  kod: string;
  baslik: string;
  tanim: string;
  sorgu: Record<string, unknown>;
  deger: number;
}

export interface SeriGecmisi {
  ekipmanlar: (EkipmanOzeti & { warranty_end: string | null })[];
  kayitlar: {
    so_id: number;
    atolye_no: string;
    so_no: string;
    received_at: string;
    status: string;
    ariza_nedeni: string | null;
    repair_category: string | null;
    test_result: string | null;
    delivered_at: string | null;
    warranty_status: string;
  }[];
  tekrar_gelis: boolean;
  acik_kayit: { so_id: number; atolye_no: string } | null;
  pencere_gun?: number;
}

export interface AtolyeSuzgeci {
  durum?: string;
  durum_grubu?: string;
  birim?: string;
  teknisyen_id?: number;
  marka?: string;
  servis_turu?: string;
  q?: string;
  yas?: string;
  geciken?: boolean;
  kabul_grubu?: number;
  musteri_id?: number;
  /** TS-194: uyarı ve KPI raporu listeleri. */
  teslim_alinmayan?: boolean;
  dis_servis?: boolean;
  tedarikci_id?: number;
  sure_eksik?: boolean;
  tamamlanma_bas?: string;
  tamamlanma_bit?: string;
}

/** KPI kutusunun/uyarının kendi süzgeci; taban süzgeçle birleşmeden önce silinir. */
export const KPI_SUZGEC_ANAHTARLARI = [
  "durum",
  "durum_grubu",
  "yas",
  "geciken",
  "teslim_alinmayan",
  "sure_eksik",
  "dis_servis",
  "tamamlanma_bas",
  "tamamlanma_bit",
] as const;

/** Sunucunun `sorgu`'sunu (liste süzgeci) ekran adresine çevirir. */
export function atolyeListeYolu(sorgu: Record<string, unknown>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(sorgu)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, Array.isArray(v) ? String(v[0]) : String(v));
  }
  return `/atolye?${p}`;
}

/** KPI raporu göstergesi (TS-194). `sorgu` null ise sayılabilir değildir (ortalama). */
export interface AtolyeRaporKutusu {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number | string | null;
  birim: string;
  sorgu: Record<string, unknown> | null;
}

export interface AtolyeTurKirilimi {
  servis_turu: string;
  ad: string;
  adet: number;
  cevrim_ort_gun: string | null;
  cevrim_medyan_gun: string | null;
  cevrim_dis_haric_ort_gun: string | null;
  dis_servis_adet: number;
  dis_servis_ort_gun: string | null;
  dis_serviste_donmeyen: number;
  sure_eksik: number;
  iscilik_ort_dk: string | null;
  sorgu: Record<string, unknown>;
}

export interface AtolyeKpiRaporu {
  donem: { bas: string; bit: string };
  kutular: AtolyeRaporKutusu[];
  servis_turu_kirilimi: AtolyeTurKirilimi[];
}

export interface EkipmanGirdisi {
  ekipman_id?: number | null;
  tip?: string;
  marka?: string | null;
  marka_diger?: string | null;
  model?: string | null;
  seri?: string | null;
  warranty_start?: string | null;
  warranty_end?: string | null;
  mukerrer_gerekce?: string | null;
}

export interface AksesuarGirdisi {
  kind: string;
  qty: number;
  description?: string | null;
}

export interface KabulOrtak {
  birim?: string;
  customer_id: number;
  address_id?: number | null;
  contact_id?: number | null;
  service_type: string;
  receive_type: string;
  customer_complaint: string;
  oncelik?: string;
  physical_condition?: string | null;
  estimated_finish_date?: string | null;
  notes?: string | null;
  logo_form_no?: string | null;
  logo_main_service_no?: string | null;
  integration_company?: string | null;
  project_name?: string | null;
}

export interface TeslimGirdisi {
  teslim_alan?: string | null;
  teslim_tipi?: string | null;
  kargo_firmasi?: string | null;
  takip_no?: string | null;
  aksesuar_iade?: { id: number; returned: boolean; not?: string | null }[];
  aciklama?: string | null;
}

export interface DurumGirdisi {
  hedef: string;
  gerekce?: string | null;
  beklenen_durum?: string | null;
  teslim?: TeslimGirdisi | null;
  sure_eksik_onay?: boolean;
}

/** 409/400 gövdesindeki nesneyi (açık kayıt, aday listesi, yönlendirme) taşıyan hata. */
export class AtolyeHatasi extends ApiError {
  constructor(
    status: number,
    message: string,
    readonly detay: Record<string, unknown> | null,
  ) {
    super(status, message);
  }
}

async function detayli<T>(yol: string, yontem: string, govde: unknown): Promise<T> {
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
    throw new AtolyeHatasi(res.status, mesaj, detay);
  }
  return (await res.json()) as T;
}

export function suzgecParametreleri(s: AtolyeSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  return p;
}

export const atolyeApi = {
  formVerileri: (birim = "HABERLESME") =>
    api.get<FormVerileri>(`${URL_}/form-verileri?${new URLSearchParams({ birim })}`),
  liste: (s: AtolyeSuzgeci, limit: number, offset: number): Promise<Sayfa<AtolyeSatiri>> => {
    const p = suzgecParametreleri(s);
    p.set("limit", String(limit));
    p.set("offset", String(offset));
    return api.getSayfa<AtolyeSatiri>(`${URL_}?${p}`);
  },
  ozet: (s: AtolyeSuzgeci) => {
    const p = suzgecParametreleri(s);
    for (const k of KPI_SUZGEC_ANAHTARLARI) p.delete(k);
    for (const k of ["tedarikci_id"]) p.delete(k);
    return api.get<AtolyeKpi[]>(`${URL_}/ozet?${p}`);
  },
  /** KPI raporu: `servis_rapor.gor`; dönem Türkiye günü, en çok 24 ay (400). */
  kpiRaporu: (q: { bas?: string; bit?: string; birim?: string; servis_turu?: string }) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v) p.set(k, v);
    return api.get<AtolyeKpiRaporu>(`${URL_}/raporlar/kpi?${p}`);
  },
  kpiExcelYolu: (q: { bas?: string; bit?: string; birim?: string; servis_turu?: string }) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v) p.set(k, v);
    return `${URL_}/raporlar/kpi.xlsx?${p}`;
  },
  excelYolu: (s: AtolyeSuzgeci) => `${URL_}/disaaktar?${suzgecParametreleri(s)}`,
  seriGecmisi: (q: { ekipman_id?: number; tip?: string; marka?: string; seri?: string }) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== "") p.set(k, String(v));
    return api.get<SeriGecmisi>(`${URL_}/seri-gecmisi?${p}`);
  },
  getir: (soId: number) => api.get<AtolyeDetay>(`${URL_}/${soId}`),
  kabul: (g: KabulOrtak & { ekipman: EkipmanGirdisi; aksesuarlar: AksesuarGirdisi[] }) =>
    detayli<AtolyeDetay>(URL_, "POST", g),
  topluKabul: (
    g: KabulOrtak & {
      cihazlar: (EkipmanGirdisi & {
        aksesuarlar?: AksesuarGirdisi[];
        customer_complaint?: string | null;
      })[];
    },
  ) =>
    detayli<{ kabul_grubu: number; kayitlar: AtolyeSatiri[] }>(`${URL_}/toplu-kabul`, "POST", g),
  guncelle: (soId: number, g: Record<string, unknown> & { version: number }) =>
    detayli<AtolyeDetay>(`${URL_}/${soId}`, "PATCH", g),
  aksesuarlar: (soId: number, version: number, aksesuarlar: AksesuarGirdisi[]) =>
    detayli<AtolyeDetay>(`${URL_}/${soId}/aksesuarlar`, "PUT", { version, aksesuarlar }),
  ekipmanDuzelt: (
    soId: number,
    g: { marka?: string | null; model?: string | null; seri?: string | null; gerekce: string },
  ) => detayli<AtolyeDetay>(`${URL_}/${soId}/ekipman`, "PUT", g),
  durum: (soId: number, g: DurumGirdisi) =>
    detayli<AtolyeDetay>(`${URL_}/${soId}/durum`, "POST", g),
  ata: (
    soId: number,
    atamalar: { user_id: number; rol: "SEF" | "TEKNISYEN"; is_lead: boolean }[],
  ) => detayli<AtolyeDetay>(`${URL_}/${soId}/ata`, "POST", { atamalar }),
  topluAta: (
    soIdler: number[],
    atamalar: { user_id: number; rol: "SEF" | "TEKNISYEN"; is_lead: boolean }[],
    mod: "EKLE" | "DEGISTIR",
  ) =>
    detayli<{ guncellenen: number }>(`${URL_}/toplu-ata`, "POST", {
      so_idler: soIdler,
      atamalar,
      mod,
    }),
  kabulFisiYolu: (soId: number) => `${URL_}/${soId}/kabul-fisi.pdf`,
  teslimTutanagiYolu: (soId: number) => `${URL_}/${soId}/teslim-tutanagi.pdf`,
  grupFisiYolu: (grup: number) => `${URL_}/kabul-grubu-fisi.pdf?grup_no=${grup}`,
};
