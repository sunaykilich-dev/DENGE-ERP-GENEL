/**
 * Planlı bakım (sözleşme, dönem, eşleştirme, PB üretimi, dijital form) —
 * API tipleri ve çağrıları (TS-060…069). Sunucu: `backend/app/api/bakim.py`.
 *
 * Kural ihlalinin ek verisi (çakışan sözleşmeler, açık PB'ler, bekleyen
 * maddeler) 409 gövdesinde `{detail: {mesaj, kod, ...}}` olarak gelir; ortak
 * istemci yalnız metin `detail` okuduğu için bu modül kendi `BakimHatasi`
 * sınıfıyla veriyi de taşır.
 */
import { api, ApiError } from "./client";

export const ONEK = "/api/teknik-servis/bakim";

export const CIHAZ_TURLERI: Record<string, string> = {
  XRAY: "X-Ray",
  KAPI_DEDEKTORU: "Kapı Dedektörü",
};

export const SOZLESME_DURUMLARI: Record<string, string> = {
  TASLAK: "Taslak",
  TEYIT_BEKLIYOR: "Teyit Bekliyor",
  AKTIF: "Aktif",
  PASIF: "Pasif",
};

export const KONTROL_SONUCLARI: Record<string, string> = {
  BEKLIYOR: "Bekliyor",
  UYGUN: "Uygun",
  UYGUNSUZ: "Uygunsuz",
  KONTROL_EDILEMEDI: "Kontrol Edilemedi",
};

export const BAKIM_SONUCLARI: Record<string, string> = {
  TAMAMLANDI: "Tamamlandı",
  UYGUNSUZLUK_VAR: "Uygunsuzluk Var",
  KONTROL_EDILEMEDI: "Kontrol Edilemedi",
  TEKRAR_GIDILECEK: "Tekrar Gidilecek",
};

export const KAPSAM_DISI_NEDENLERI: Record<string, string> = {
  SOKULMUS: "Cihaz sökülmüş",
  ERISIM_YOK: "Erişim yok",
  TASINMIS: "Cihaz taşınmış",
  MUSTERI_IPTAL: "Müşteri iptal etti",
};

export const AKSIYON_TURLERI: Record<string, string> = {
  YERINDE_GIDERILDI: "Yerinde giderildi",
  TEKLIF: "Teklif (Dalga 2)",
  ARIZA_IS_EMRI: "Arıza işi",
  MUSTERI_KAYNAKLI: "Müşteri kaynaklı",
};

export const ONAY_TURLERI: Record<string, string> = {
  SOZLU: "Sözlü onay",
  BASILI_FORM: "Basılı form",
  IMZA: "İmza",
  ALINAMADI: "Alınamadı",
};

// --- Tipler -------------------------------------------------------------------

export interface Sozlesme {
  id: number;
  contract_no: string;
  birim: string;
  status: string;
  sonraki_durumlar: string[];
  account_id: number | null;
  musteri: string | null;
  address_id: number | null;
  tesis: string | null;
  il: string | null;
  contact_id: number | null;
  responsible_user_id: number | null;
  baslangic: string | null;
  bitis: string | null;
  annual_frequency: number | null;
  fixed_months: number[] | null;
  suresi_doldu: boolean;
  teyit_gerekcesi: string | null;
  notes: string | null;
  version: number;
  kapsam: Record<string, number>;
  eslesen_kalem: number;
  toplam_kalem: number;
  sayac: { yapilan: number; frekans: number | null; sonraki_hedef?: string | null };
  sorumlu?: string | null;
  acik_pb?: number;
  toplam_pb?: number;
  acik_pb_isleri?: string[];
  /** Yalnız `maliyet.gor` sahibine gelir; diğerlerinde anahtar YOK. */
  fee_per_visit?: string | null;
  contract_total?: string | null;
  currency?: string;
}

export interface SozlesmeGirdisi {
  birim: string;
  account_id: number | null;
  address_id: number | null;
  responsible_user_id?: number | null;
  baslangic: string | null;
  bitis: string | null;
  annual_frequency: number | null;
  fixed_months?: number[] | null;
  kapsam?: Record<string, number>;
  notes?: string | null;
  cakisma_onayi?: boolean;
  cakisma_gerekcesi?: string | null;
  version?: number;
}

export interface Ekipman {
  id: number;
  equipment_type: string;
  serial_no: string | null;
  brand: string | null;
  model: string | null;
  zone: string | null;
  address_id: number | null;
}

export interface EslestirmeKalemi {
  kalem_id: number;
  equipment_type: string;
  sira: number;
  pb_uygun: boolean;
  equipment_id: number | null;
  ekipman: Ekipman | null;
  oneri_id: number | null;
  adaylar: Ekipman[];
}

export interface Oran {
  toplam: number;
  eslesen: number;
  yuzde: number;
}

export interface Eslestirme {
  oran: Oran;
  kalemler: EslestirmeKalemi[];
}

export interface Donem {
  id: number;
  contract_id: number;
  contract_no: string;
  musteri: string | null;
  birim: string;
  dongu_baslangici: string;
  sequence_no: number;
  frekans: number | null;
  target_date: string;
  target_manual: boolean;
  target_change_reason: string | null;
  closed_at: string | null;
  closing_kind: string | null;
  gecikmis: boolean;
  pb_toplam: number;
  pb_acik: number;
  pb_tamamlanan: number;
  pb_iptal: number;
}

export interface DonemCihazi {
  so_id: number;
  so_no: string;
  status: string;
  kapali: boolean;
  equipment_type: string;
  sira: number;
  serial_no: string | null;
  zone: string | null;
  form_durumu: string | null;
  kapsam_disi_talebi: boolean;
  address_id: number | null;
}

export interface Atlanan {
  contract_id: number;
  contract_no: string;
  source_ref: string | null;
  musteri: string | null;
  neden_kodu: string;
  neden: string;
}

export interface UretimSonucu {
  run_id: number;
  generated: number;
  uretilen: string[];
  skipped: Atlanan[];
}

export interface Onizleme {
  uretilecek: {
    contract_id: number;
    contract_no: string;
    musteri: string | null;
    donem_id: number;
    hedef: string;
    pb_sayisi: number;
  }[];
  atlanacak: Atlanan[];
}

export interface UretimKaydi {
  id: number;
  tetik: string;
  created_at: string;
  created_by: number | null;
  generated_count: number | null;
  skipped: Atlanan[];
}

export interface OtomatikUretim {
  acik: boolean;
  oran: Oran;
  degistirebilir: boolean;
}

export interface KpiKutusuVerisi {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number | null;
  yol: string;
  /** adet | yuzde | gun (TS-185). */
  birim?: string;
  /** Yüzde KPI'da pay/payda; payda = açılan listenin toplamı. */
  pay?: number;
  payda?: number;
}

export interface Ozet {
  kutular: KpiKutusuVerisi[];
  eslestirme: Oran;
}

export interface Uygunsuzluk {
  id: number;
  so_id?: number;
  so_no?: string;
  check_code: string;
  check_label: string;
  description: string | null;
  action_type: string | null;
  responsible_user_id: number | null;
  due_date: string | null;
  linked_service_order_id: number | null;
  linked_so_no?: string | null;
  status: string;
  closing_note: string | null;
  yas_gun?: number;
  version: number;
}

export interface KapsamDisiTalebi {
  id: number;
  so_id?: number;
  so_no?: string;
  reason_code: string;
  description: string;
  requested_by: number;
  talep_eden?: string;
  kendi_talebi?: boolean;
  status: string;
  decision_note: string | null;
  created_at?: string;
}

export interface FormMaddesi {
  kod: string;
  etiket: string;
  sira: number;
  sonuc: string;
  not: string | null;
}

export interface Ziyaret {
  visit_no: number;
  tur: string;
  visited_at: string;
  technician_user_id: number | null;
  bakim_sonucu: string | null;
  serial_no: string | null;
  zone: string | null;
  gerekce: string | null;
}

export interface BakimFormu {
  so: {
    id: number;
    so_no: string;
    status: string;
    birim: string;
    konu: string;
    musteri: string | null;
    tesis: string | null;
    il: string | null;
    ilce: string | null;
    adres: string | null;
  };
  sozlesme: { id: number; contract_no: string } | null;
  donem: { id: number; target_date: string; closing_kind: string | null } | null;
  ekipman: Ekipman | null;
  form: {
    id: number;
    status: string;
    template_code: string;
    baslik: string;
    seri_no: string | null;
    zone: string | null;
    performed_work: string | null;
    technician_note: string | null;
    parts_text: string | null;
    bakim_sonucu: string | null;
    kutuk_fark_durumu: string | null;
    completed_at: string | null;
    version: number;
  };
  maddeler: FormMaddesi[];
  ziyaretler: Ziyaret[];
  uygunsuzluklar: Uygunsuzluk[];
  kapsam_disi: KapsamDisiTalebi[];
  onay: { id: number; tur: string; approved_at: string } | null;
  onay_zorunlu: boolean;
  uyarilar?: string[];
  acilan_uygunsuzluk?: number;
  ariza_isi?: { id: number; so_no: string };
}

export interface FormGirdisi {
  version?: number;
  zone?: string | null;
  seri_no?: string | null;
  performed_work?: string | null;
  technician_note?: string | null;
  parts_text?: string | null;
  bakim_sonucu?: string | null;
  kontroller?: { kod: string; sonuc: string; not: string | null }[];
  /** Yalnız tamamlamada: süre kaydı eksik olduğu bilinerek kapatılıyor (TS-076). */
  sure_eksik_onay?: boolean;
}

// --- Hata -----------------------------------------------------------------------

/** 409 gövdesindeki ek veriyi (`kod`, `cakisanlar`, `isler`, …) taşır. */
export class BakimHatasi extends ApiError {
  constructor(
    status: number,
    message: string,
    readonly veri: Record<string, unknown> = {},
  ) {
    super(status, message);
  }

  get kod(): string | undefined {
    return typeof this.veri.kod === "string" ? this.veri.kod : undefined;
  }
}

async function istek<T>(yol: string, method: string, govde?: unknown): Promise<T> {
  const res = await fetch(yol, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
    body: govde === undefined ? undefined : JSON.stringify(govde),
  });
  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    let veri: Record<string, unknown> = {};
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") mesaj = j.detail;
      else if (Array.isArray(j?.detail)) mesaj = j.detail[0]?.msg ?? mesaj;
      else if (j?.detail && typeof j.detail === "object") {
        veri = j.detail as Record<string, unknown>;
        if (typeof veri.mesaj === "string") mesaj = veri.mesaj;
      }
    } catch {
      /* gövde JSON değil */
    }
    throw new BakimHatasi(res.status, mesaj, veri);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** Kullanıcıya gösterilecek hata metni (409'da yenileme önerisi). */
export function hataMetni(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 409 && !(e instanceof BakimHatasi && e.kod)) {
      return `${e.message} — gerekiyorsa sayfayı yenileyip tekrar deneyin.`;
    }
    return e.message;
  }
  return "Beklenmeyen hata";
}

function sorgu(p: Record<string, string | number | boolean | null | undefined>): string {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    s.set(k, v === true ? "true" : String(v));
  }
  return s.toString();
}

// --- Çağrılar -----------------------------------------------------------------

export const bakimApi = {
  ozet: () => api.get<Ozet>(`${ONEK}/ozet`),

  sozlesmeler: (p: Record<string, string | number | boolean | null | undefined>) =>
    api.getSayfa<Sozlesme>(`${ONEK}/sozlesmeler?${sorgu(p)}`),
  sozlesme: (id: number) => api.get<Sozlesme>(`${ONEK}/sozlesmeler/${id}`),
  sozlesmeEkle: (g: SozlesmeGirdisi) => istek<Sozlesme>(`${ONEK}/sozlesmeler`, "POST", g),
  sozlesmeDuzenle: (id: number, g: SozlesmeGirdisi) =>
    istek<Sozlesme>(`${ONEK}/sozlesmeler/${id}`, "PATCH", g),
  durum: (id: number, hedef: string, cakisma?: { onay: boolean; gerekce: string }) =>
    istek<Sozlesme>(`${ONEK}/sozlesmeler/${id}/durum`, "POST", {
      hedef,
      cakisma_onayi: cakisma?.onay ?? false,
      cakisma_gerekcesi: cakisma?.gerekce ?? null,
    }),
  kapsam: (id: number, kapsam: Record<string, number>, version?: number) =>
    istek<{ kapsam: Record<string, number> }>(`${ONEK}/sozlesmeler/${id}/kapsam`, "PUT", {
      kapsam,
      version,
    }),
  ucret: (
    id: number,
    g: { fee_per_visit: string | null; contract_total: string | null; currency: string },
  ) => istek<Sozlesme>(`${ONEK}/sozlesmeler/${id}/ucret`, "PUT", g),

  eslestirme: (id: number) => api.get<Eslestirme>(`${ONEK}/sozlesmeler/${id}/eslestirme`),
  eslestir: (id: number, eslesmeler: { kalem_id: number; equipment_id: number | null }[]) =>
    istek<Eslestirme>(`${ONEK}/sozlesmeler/${id}/eslestirme`, "PUT", { eslesmeler }),

  donemler: (p: Record<string, string | number | boolean | null | undefined>) =>
    api.getSayfa<Donem>(`${ONEK}/donemler?${sorgu(p)}`),
  sozlesmeDonemleri: (id: number) => api.get<Donem[]>(`${ONEK}/sozlesmeler/${id}/donemler`),
  donemCihazlari: (sozlesmeId: number, donemId: number) =>
    api.get<DonemCihazi[]>(`${ONEK}/sozlesmeler/${sozlesmeId}/donemler/${donemId}/cihazlar`),
  hedefTarih: (sozlesmeId: number, donemId: number, hedef_tarih: string, gerekce: string) =>
    istek<Donem>(
      `${ONEK}/sozlesmeler/${sozlesmeId}/donemler/${donemId}/hedef-tarih`,
      "PATCH",
      { hedef_tarih, gerekce },
    ),
  eksikPb: (sozlesmeId: number, donemId: number) =>
    istek<UretimSonucu>(`${ONEK}/sozlesmeler/${sozlesmeId}/donemler/${donemId}/eksik-pb`, "POST"),

  onizle: () => istek<Onizleme>(`${ONEK}/uretim/onizleme`, "POST"),
  uret: () => istek<UretimSonucu>(`${ONEK}/uretim`, "POST"),
  uretimKayitlari: (limit = 20, offset = 0) =>
    api.getSayfa<UretimKaydi>(`${ONEK}/uretim-kayitlari?limit=${limit}&offset=${offset}`),
  otomatikUretim: () => api.get<OtomatikUretim>(`${ONEK}/otomatik-uretim`),
  otomatikUretimAyarla: (acik: boolean) =>
    istek<{ acik: boolean; oran: Oran }>(`${ONEK}/otomatik-uretim`, "PUT", { acik }),

  uygunsuzluklar: (p: Record<string, string | number | boolean | null | undefined>) =>
    api.getSayfa<Uygunsuzluk>(`${ONEK}/uygunsuzluklar?${sorgu(p)}`),
  kapsamDisiTalepleri: (p: Record<string, string | number | boolean | null | undefined>) =>
    api.getSayfa<KapsamDisiTalebi>(`${ONEK}/kapsam-disi?${sorgu(p)}`),

  form: (soId: number) => api.get<BakimFormu>(`${ONEK}/formlar/${soId}`),
  formKaydet: (soId: number, g: FormGirdisi) =>
    istek<BakimFormu>(`${ONEK}/formlar/${soId}`, "PUT", g),
  formTamamla: (soId: number, g?: FormGirdisi) =>
    istek<BakimFormu>(`${ONEK}/formlar/${soId}/tamamla`, "POST", g),
  onayAl: (
    soId: number,
    g: {
      tur: string;
      imzalayan_ad?: string | null;
      imzalayan_unvan?: string | null;
      eksik_nedeni?: string | null;
    },
  ) => istek<BakimFormu>(`${ONEK}/formlar/${soId}/onay`, "POST", g),
  kapsamDisiTalep: (soId: number, neden: string, aciklama: string) =>
    istek<BakimFormu>(`${ONEK}/formlar/${soId}/kapsam-disi`, "POST", { neden, aciklama }),
  kapsamDisiKarar: (soId: number, talepId: number, onay: boolean, not?: string) =>
    istek<BakimFormu>(`${ONEK}/formlar/${soId}/kapsam-disi/${talepId}/karar`, "POST", {
      onay,
      not: not ?? null,
    }),
  uygunsuzlukDuzenle: (
    soId: number,
    id: number,
    g: {
      version: number;
      action_type?: string | null;
      responsible_user_id?: number | null;
      due_date?: string | null;
    },
  ) => istek<BakimFormu>(`${ONEK}/formlar/${soId}/uygunsuzluklar/${id}`, "PATCH", g),
  uygunsuzlukArizaIsi: (soId: number, id: number) =>
    istek<BakimFormu>(`${ONEK}/formlar/${soId}/uygunsuzluklar/${id}/ariza-isi`, "POST"),
  uygunsuzlukKapat: (soId: number, id: number, not: string) =>
    istek<BakimFormu>(`${ONEK}/formlar/${soId}/uygunsuzluklar/${id}/kapat`, "POST", { not }),
  // M1.7 (Faz A): yeniden açma ucu kaldırıldı; kapanmış PB işine bağlı yeni
  // iş `teknikServisApi.bagliYeniIs` ile açılır.

  // --- Raporlar (TS-185) ------------------------------------------------------
  donemTamamlama: (p: RaporSuzgeci) =>
    api.getSayfa<DonemTamamlamaSatiri>(`${ONEK}/raporlar/donem-tamamlama?${sorgu({ ...p })}`),
  pbIsleri: (p: RaporSuzgeci) =>
    api.getSayfa<PbRaporSatiri>(`${ONEK}/raporlar/pb-isleri?${sorgu({ ...p })}`),
  uygunsuzlukAnalizi: (p: RaporSuzgeci) =>
    api.get<UygunsuzlukAnalizi>(`${ONEK}/raporlar/uygunsuzluk?${sorgu({ ...p })}`),
  /** Excel indirme adresi (tarayıcı `window.open`; denetime sunucu yazar). */
  raporExcelAdresi: (p: RaporSuzgeci) =>
    `${ONEK}/raporlar/bakim.xlsx?${sorgu({ ...p, kpi: undefined, limit: undefined, offset: undefined })}`,
};

// --- Rapor tipleri (TS-185) ----------------------------------------------------

/** PB listesine düşen KPI kodları (kutu → rapor sekmesi). */
export const PB_KPILERI = [
  "ACIK_PB",
  "TAMAMLANAN_PB",
  "SURE_EKSIK_PB",
  "BAKIM_YAPILDI_AKSIYON_ACIK",
  "UYGUNSUZLUK_ORANI",
  "ONAYSIZ_KAPANIS",
] as const;

export interface RaporSuzgeci {
  baslangic?: string | null;
  bitis?: string | null;
  birim?: string | null;
  kpi?: string | null;
  limit?: number;
  offset?: number;
}

export interface DonemTamamlamaSatiri {
  donem_id: number;
  contract_id: number;
  contract_no: string;
  musteri: string | null;
  birim: string;
  sozlesme_durumu: string;
  dongu_baslangici: string;
  sequence_no: number;
  target_date: string;
  pb_toplam: number;
  pb_tamamlanan: number;
  pb_acik: number;
  pb_iptal: number;
  oran: number | null;
  oran_metni: string;
  durum: string;
  closing_kind: string | null;
  tamamlanma_tarihi: string | null;
  gecikmis: boolean;
  uyumlu: boolean;
}

export interface PbRaporSatiri {
  so_id: number;
  so_no: string;
  status: string;
  birim: string;
  musteri: string | null;
  contract_id: number;
  contract_no: string;
  donem_id: number;
  target_date: string;
  completed_at: string | null;
  /** Süre kaydı yoksa null ("eksik"); tahmini süre yerine konmaz. */
  kisi_saat_dk: number | null;
  sure_durumu: string | null;
  uygunsuzluk_var: boolean;
  onay_var: boolean;
}

export interface UygunsuzlukAnalizi {
  generated_at: string;
  uygunsuzluk_orani: { deger: number | null; pay: number; payda: number };
  en_sik: { check_code: string; madde: string; adet: number; acik: number }[];
  aksiyon_yasi: {
    adet: number;
    ortalama_gun: number | null;
    en_eski_gun: number | null;
    kovalar: { kova: string; adet: number }[];
  };
  onaysiz_kapanis: number;
}
