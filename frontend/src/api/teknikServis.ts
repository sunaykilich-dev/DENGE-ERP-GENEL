/**
 * Servis işleri (liste, detay, durum, bekleme, sonuç, tayin, onay, panel) — API tipleri ve çağrıları.
 *
 * Sözleşme: `backend/app/api/teknik_servis.py` (D1-B Pydantic şemaları) ve
 * panel/onay iş kuralı `services/teknik_servis/panel.py`, `onay.py` (D1-C).
 * Ortak istemci: `./client`. 409 gövdesi (ör. mükerrer seri: `kod:
 * "MUKERRER"`, `mevcut_isler`) `ApiError.govde.detail` içinde taşınır.
 *
 * Sözlük adları (durum, tür, kanal ...) sunucudan `/isler/form-verileri` ile
 * gelir; buradaki sabitler yalnız renk ve sıralama içindir.
 */
import { api, type Sayfa } from "./client";

const TS = "/api/teknik-servis";

// --- Sözlük ----------------------------------------------------------------

export interface KodAd {
  kod: string;
  ad: string;
}

export interface FormVerileri {
  birimler: KodAd[];
  turler: (KodAd & { kategori: string; seri_zorunlu: boolean; ekrandan: boolean })[];
  kategoriler: KodAd[];
  durumlar: KodAd[];
  durum_gruplari: Record<string, string[]>;
  oncelikler: string[];
  talep_kanallari: KodAd[];
  iliski_turleri: KodAd[];
  sonuclar: KodAd[];
  cozum_kanallari: KodAd[];
  bekleme_nedenleri: (KodAd & { aciklama_zorunlu: boolean })[];
  olay_turleri: KodAd[];
}

export const DURUM_RENKLERI: Record<string, string> = {
  MUSTERI_TALEBI: "default",
  PLANLAMADA: "gold",
  PLANLANDI: "blue",
  YOLA_CIKILDI: "cyan",
  SAHADA: "cyan",
  ISLEMDE: "geekblue",
  ATOLYEDE: "purple",
  BEKLEMEDE: "orange",
  TAMAMLANDI: "green",
  KAPATILDI: "default",
  TEKRAR_ACILDI: "magenta",
  IPTAL: "red",
};

export const ONCELIK_RENKLERI: Record<string, string> = {
  KRITIK: "red",
  YUKSEK: "orange",
  NORMAL: "default",
};

export const ONCELIK_ADLARI: Record<string, string> = {
  KRITIK: "Kritik",
  YUKSEK: "Yüksek",
  NORMAL: "Normal",
};

export const ONAY_TURLERI = [
  { kod: "IMZA", ad: "Müşteri imzası (ekranda)" },
  { kod: "BASILI_FORM", ad: "İmzalı basılı form (fotoğraf)" },
  { kod: "SOZLU", ad: "Sözlü onay" },
  { kod: "ALINAMADI", ad: "Onay alınamadı" },
] as const;

// --- Liste / detay ---------------------------------------------------------

export interface IsSatiri {
  id: number;
  so_no: string;
  birim: string;
  tur: string;
  kategori: string;
  status: string;
  durum_grubu: string;
  oncelik: string;
  musteri: { id: number; title: string } | null;
  customer_name_raw: string | null;
  lokasyon: { id: number; ad: string | null; il: string | null } | null;
  konu: string;
  seriler: string[];
  talep_kanali: string | null;
  reported_at: string | null;
  created_at: string;
  completed_at: string | null;
  closed_at: string | null;
  sorumlu: { id: number; ad: string | null } | null;
  ekip_sayisi: number;
  iletisim_ad: string | null;
  iletisim_telefon: string | null;
  aktif_bekleme: string | null;
  reopen_count: number;
  /** M1.7: kapanmış işin devamı olarak açıldıysa önceki iş. */
  onceki_is_id: number | null;
  /** Faz A kalite onayı anı (null = verilmedi). */
  kalite_onay_at: string | null;
  version: number;
}

/** Bağlı iş satırı; kapsam dışı işin numarası maskelidir (`id` null). */
export interface BagliIsSatiri {
  id: number | null;
  so_no: string;
  iliski_turu: string | null;
  status: string | null;
  kapsam_disi: boolean;
}

export interface BagliIsler {
  ust: BagliIsSatiri | null;
  alt: BagliIsSatiri[];
  onceki: BagliIsSatiri | null;
  sonrakiler: BagliIsSatiri[];
}

export interface KaliteDurumu {
  onay_at: string | null;
  onaylayan: { id: number; ad: string | null } | null;
  notu: string | null;
  /** İş tamamlanmış ve onay verilmemiş. */
  bekliyor: boolean;
  /** Bu kullanıcı şimdi onay verebilir mi (izin + görevler ayrılığı). */
  verebilir: boolean;
  engel: string | null;
}

export interface EkipUyesi {
  user_id: number;
  ad: string;
  giris_acik: boolean;
  saha_rolu?: string | null;
  rol: "SEF" | "TEKNISYEN";
  is_lead: boolean;
  assigned_at: string;
}

export interface Gecis {
  hedef: string;
  ad: string;
  uc: string;
  yetkili: boolean;
}

export interface IsDetayi extends Omit<IsSatiri, "seriler"> {
  address_id: number | null;
  customer_id: number | null;
  contact_id: number | null;
  irtibat: { id: number; full_name: string; unvan: string | null; telefon: string | null } | null;
  proje: string | null;
  sistem: string | null;
  aciklama: string | null;
  seriler: { id: number; seri_no: string; seri_norm: string }[];
  ekip: EkipUyesi[];
  bekleme: {
    id: number;
    neden: string;
    neden_adi: string;
    aciklama: string | null;
    onceki_durum: string;
    started_at: string;
    beklenen_bitis_at: string | null;
    sla_durdurur: boolean;
  } | null;
  bekleme_dk_toplam: number;
  sonuc: {
    id: number;
    sonuc: string;
    cozum_kanali: string;
    yapilan_islem: string;
    ariza_nedeni_id: number | null;
    ariza_nedeni: string | null;
    saha_seri_no: string | null;
    saha_bolge: string | null;
    created_at: string;
  } | null;
  first_completed_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  equipment_id: number | null;
  iliskili_isler: BagliIsler;
  kalite: KaliteDurumu;
  /** TAM / KISMI / EKSIK / BEKLENMIYOR — kayıt yoksa EKSIK (0 değil). */
  sure_durumu: string;
  sonraki_durumlar: string[];
  gecisler: Gecis[];
  updated_at: string;
  /**
   * Açılış uyarıları. `AYNI_LOKASYON` tek kayıt döner: `adet` + `isler`
   * (KARARLAR 2026-11-04 §6.10); `so_no`/`id` ilk iş (geri uyum).
   */
  uyarilar?: AcilisUyarisi[];
}

export interface AcilisUyarisi {
  kod: string;
  so_no: string;
  id: number;
  adet?: number;
  isler?: { id: number; so_no: string }[];
}

export interface IsSuzgeci {
  birim?: string;
  kategori?: string;
  tur?: string;
  durum?: string[];
  durum_grubu?: string;
  oncelik?: string;
  musteri_id?: number;
  adres_id?: number;
  teknisyen_id?: number;
  /** Ana Panel: aktif ŞEF tayini olan işler. */
  sef_id?: number;
  atanmamis?: boolean;
  bas?: string;
  bit?: string;
  q?: string;
  kapali_dahil?: boolean;
  kpi?: string;
  donem?: string;
  siralama?: string;
  /** Faz A: "BEKLEYEN" = kalite onayı bekleyenler, "ONAYLI". */
  kalite?: string;
}

export function suzgecParametreleri(s: IsSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.set(k, String(v));
  }
  return p;
}

export interface IsGirdisi {
  birim: string;
  tur: string;
  konu: string;
  customer_id: number;
  address_id?: number | null;
  contact_id?: number | null;
  oncelik?: string;
  talep_kanali?: string | null;
  reported_at?: string | null;
  iletisim_ad?: string | null;
  iletisim_telefon?: string | null;
  proje?: string | null;
  sistem?: string | null;
  aciklama?: string | null;
  seriler?: string[];
  iliskili_is_id?: number | null;
  iliski_turu?: string | null;
  mukerrer_gec?: boolean;
  /**
   * Geçiş/içe aktarma kaydı (`servis.gecis_kaydi`, KARARLAR 2026-11-04 §6.11):
   * bildirim tarihi 7 günden eski olabilir, SLA ölçülmez; gerekçe ≥10 karakter.
   */
  gecis_kaydi?: boolean;
  gecis_gerekcesi?: string | null;
}

/** Kapanmış işe bağlı yeni iş (M1.7); verilmeyen alan önceki işten gelir. */
export interface BagliIsGirdisi {
  konu?: string;
  aciklama?: string | null;
  tur?: string;
  oncelik?: string;
  talep_kanali?: string;
  iletisim_ad?: string | null;
  iletisim_telefon?: string | null;
  address_id?: number | null;
  contact_id?: number | null;
  seriler?: string[];
  mukerrer_gec?: boolean;
}

export interface UzaktanGirdisi extends IsGirdisi {
  cozum_kanali: "TELEFON" | "UZAKTAN";
  yapilan_islem: string;
  ariza_nedeni_id?: number | null;
}

export interface MukerrerSonucu {
  mukerrer: { id: number; so_no: string; konu?: string; status?: string }[];
  kapsam_disi_var: boolean;
  ayni_lokasyon: { id: number; so_no: string }[];
}

// --- Geçmiş, bekleme, onay --------------------------------------------------

export interface Olay {
  id: number;
  olay_turu: string;
  olay_adi: string;
  eski_durum: string | null;
  yeni_durum: string | null;
  ozet: string;
  veri: Record<string, unknown> | null;
  kisiler: Record<string, unknown> | null;
  kullanici: { id: number; ad: string | null } | null;
  olusma_zamani: string;
}

export interface BeklemeSatiri {
  id: number;
  neden: string;
  neden_adi: string;
  aciklama: string | null;
  onceki_durum: string;
  started_at: string;
  beklenen_bitis_at: string | null;
  released_at: string | null;
  sure_dk: number | null;
  sla_durdurur: boolean;
  otomatik_kapandi: boolean;
  kapanis_notu: string | null;
}

export interface Onay {
  id: number;
  service_order_id: number;
  tur: string;
  imzalayan_ad: string | null;
  imzalayan_unvan: string | null;
  ek_id: number | null;
  eksik_nedeni: string | null;
  gecersiz_kilan_id: number | null;
  onay_grubu: string | null;
  approved_at: string;
}

export interface OnayGirdisi {
  tur: string;
  imzalayan_ad?: string | null;
  imzalayan_unvan?: string | null;
  ek_id?: number | null;
  eksik_nedeni?: string | null;
}

export interface SonucGirdisi {
  sonuc: string;
  cozum_kanali: string;
  yapilan_islem: string;
  ariza_nedeni_id?: number | null;
  saha_seri_no?: string | null;
  saha_bolge?: string | null;
  sure_eksik_onay?: boolean;
}

export interface AtamaSatiri {
  user_id: number;
  rol: "SEF" | "TEKNISYEN";
  is_lead: boolean;
}

export interface ArizaNedeni {
  id: number;
  birim: string;
  ad: string;
  sira: number;
  is_active: boolean;
}

// --- Panel -----------------------------------------------------------------

export interface PanelKutusu {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number;
  yol: string;
  grup: "SERVIS" | "DONEM" | "BAKIM";
  donemsel: boolean;
  vurgu: "normal" | "uyari" | "kritik";
}

export interface PanelOzeti {
  donem: string;
  donem_adi: string;
  donem_baslangic: string;
  donem_bitis: string;
  birim: string | null;
  kutular: PanelKutusu[];
  olcumler: {
    uzaktan_oran_yuzde: number | null;
    ortalama_cozum_saat: number | null;
    cozum_olculen: number;
    cozum_tahmini: number;
  };
}

export const DONEMLER = [
  { kod: "bugun", ad: "Bugün" },
  { kod: "hafta", ad: "Bu hafta" },
  { kod: "ay", ad: "Bu ay" },
  { kod: "son30", ad: "Son 30 gün" },
] as const;

/** Liste başlığında gösterilen KPI adları (panel tanımlarıyla aynı kodlar). */
export const KPI_ADLARI: Record<string, string> = {
  acik: "Açık işler",
  plan_bekleyen: "Plan bekleyen",
  planlandi: "Planlandı",
  sahada: "Sahada",
  atolyede: "Atölyede",
  beklemede: "Beklemede",
  atanmamis: "Tayin Edilmemiş",
  kritik_acik: "Kritik açık",
  bugun_acilan: "Bugün açılan",
  bugun_planli: "Bugün planlı",
  kapanis_bekleyen: "Kapanış bekleyen",
  kritik_atanmamis: "Tayin edilmemiş kritik iş",
  kapanis_gecikmis: "Kapanışı gecikmiş iş",
  uzun_beklemede: "Uzun süredir beklemede",
  tamamlanan: "Tamamlanan",
  uzaktan_cozulen: "Telefon/uzaktan çözülen",
  tekrar_ariza: "Tekrar arıza",
  sure_eksik: "Süre kaydı eksik",
  bakim_acik: "Açık bakım",
  bakim_bu_ay_planli: "Bu ay planlı bakım",
  bakim_geciken: "Geciken bakım",
  bakim_tamamlanan: "Tamamlanan bakım",
  // Dalga 3 rapor KPI'ları (Servis Raporları → "Servis İşleri'nde aç").
  rapor_gelen: "Gelen iş",
  rapor_cozulen: "Çözülen iş",
  rapor_iptal: "İptal edilen",
  rapor_donem_sonu_acik: "Dönem sonu açık",
  rapor_kritik_acik: "Kritik açık",
  rapor_uzaktan_cozulen: "Telefon/uzaktan çözülen",
  rapor_sure_girilen: "Süre girilen iş",
  rapor_sure_eksik: "Süre kaydı eksik",
  rapor_ilk_cozulen: "İlk kez çözülen",
  rapor_yeniden_acilan: "Yeniden açılan",
  rapor_yeniden_acilan_pb: "Yeniden açılan (PB)",
  rapor_tekrar_payda: "Tekrar arıza paydası",
  rapor_tekrar_ariza_onayli: "Tekrar arıza (onaylı)",
  rapor_tekrar_ariza_aday: "Tekrar arıza adayı (onaysız)",
  rapor_tekrar_ziyaret: "Tekrar ziyaret",
  rapor_ziyaret_kaydi_yok: "Ziyaret kaydı eksik",
  rapor_sla_zamaninda: "SLA zamanında",
  rapor_sla_asildi: "SLA aşıldı",
  rapor_sla_olculemedi: "SLA ölçülemedi",
  rapor_sla_damgasiz: "SLA damgası yok",
  rapor_bakim_acik_pb: "Açık PB",
  rapor_bakim_tamamlanan_pb: "Tamamlanan PB cihazı",
  rapor_bakim_sure_eksik_pb: "Süre kaydı eksik PB",
  rapor_bakim_aksiyon_acik: "Bakım yapıldı, aksiyon açık",
  rapor_bakim_bakimi_yapilan: "Bakımı yapılan PB",
  rapor_bakim_onaysiz_kapanis: "Onaysız PB kapanışı",
};

/** Serbest dönem aralığı (`YYYYAAGG-YYYYAAGG`) → "GG.AA.YYYY – GG.AA.YYYY"; değilse null. */
export const donemAraligiMetni = (donem: string): string | null => {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{4})(\d{2})(\d{2})$/.exec(donem);
  return m ? `${m[3]}.${m[2]}.${m[1]} – ${m[6]}.${m[5]}.${m[4]}` : null;
};

// --- Çağrılar ---------------------------------------------------------------

const isYolu = (id: number) => `${TS}/isler/${id}`;

export const teknikServisApi = {
  formVerileri: () => api.get<FormVerileri>(`${TS}/isler/form-verileri`),
  liste: (s: IsSuzgeci, limit: number, offset: number): Promise<Sayfa<IsSatiri>> => {
    const p = suzgecParametreleri(s);
    p.set("limit", String(limit));
    p.set("offset", String(offset));
    return api.getSayfa<IsSatiri>(`${TS}/isler?${p}`);
  },
  excelYolu: (s: IsSuzgeci) => `${TS}/isler.xlsx?${suzgecParametreleri(s)}`,
  mukerrerKontrol: (p: { seri: string[]; musteri_id?: number; adres_id?: number; haric_id?: number }) => {
    const q = new URLSearchParams();
    p.seri.forEach((s) => q.append("seri", s));
    if (p.musteri_id) q.set("musteri_id", String(p.musteri_id));
    if (p.adres_id) q.set("adres_id", String(p.adres_id));
    if (p.haric_id) q.set("haric_id", String(p.haric_id));
    return api.get<MukerrerSonucu>(`${TS}/isler/mukerrer-kontrol?${q}`);
  },
  getir: (id: number) => api.get<IsDetayi>(isYolu(id)),
  ac: (g: IsGirdisi) => api.post<IsDetayi>(`${TS}/isler`, g),
  uzaktanCozuldu: (g: UzaktanGirdisi) => api.post<IsDetayi>(`${TS}/isler/uzaktan-cozuldu`, g),
  /** Kütükten toplu "Servis işi aç": seçili her ekipman için bir iş (E03-11). */
  ekipmandanAc: (g: {
    ekipman_idler: number[];
    tur: string;
    konu: string;
    talep_kanali: string;
    oncelik?: string;
    aciklama?: string | null;
    iletisim_ad?: string | null;
    iletisim_telefon?: string | null;
    mukerrer_gec?: boolean;
  }) =>
    api.post<{ acilan: number; isler: { id: number; so_no: string; equipment_id: number }[] }>(
      `${TS}/isler/ekipmandan`,
      g,
    ),
  guncelle: (id: number, g: Record<string, unknown>) => api.patch<IsDetayi>(isYolu(id), g),
  seriler: (id: number, seriler: string[], gerekce?: string) =>
    api.put<IsDetayi>(`${isYolu(id)}/seriler`, { seriler, gerekce }),
  durum: (id: number, hedef: string, beklenen_durum?: string, gerekce?: string) =>
    api.post<IsDetayi>(`${isYolu(id)}/durum`, { hedef, beklenen_durum, gerekce }),
  kapat: (id: number, beklenen_durum?: string, gerekce?: string) =>
    api.post<IsDetayi>(`${isYolu(id)}/kapat`, { beklenen_durum, gerekce }),
  iptal: (id: number, gerekce: string, beklenen_durum?: string) =>
    api.post<IsDetayi>(`${isYolu(id)}/iptal`, { gerekce, beklenen_durum }),
  /** M1.7: kapanmış iş yeniden açılmaz; bu işe bağlı YENİ iş açılır. */
  bagliYeniIs: (id: number, g: BagliIsGirdisi) =>
    api.post<IsDetayi>(`${isYolu(id)}/bagli-yeni-is`, g),
  /** D3.4/G4.6: tamamlanan işe kalite onayı (kendi çalıştığı işe verilemez). */
  kaliteOnayi: (id: number, version: number, not?: string) =>
    api.post<IsDetayi>(`${isYolu(id)}/kalite-onayi`, { version, not }),
  beklet: (id: number, g: { neden: string; aciklama?: string; beklenen_bitis_at?: string | null }) =>
    api.post<IsDetayi>(`${isYolu(id)}/bekleme`, g),
  beklemeyiBitir: (id: number, not?: string) =>
    api.post<IsDetayi>(`${isYolu(id)}/bekleme/bitir`, { not }),
  beklemeler: (id: number) =>
    api.get<{ beklemeler: BeklemeSatiri[]; toplam_dk: number }>(`${isYolu(id)}/beklemeler`),
  sonuc: (id: number, g: SonucGirdisi) => api.post<IsDetayi>(`${isYolu(id)}/sonuc`, g),
  gecmis: (id: number) => api.get<Olay[]>(`${isYolu(id)}/gecmis`),
  notEkle: (id: number, metin: string) => api.post<Olay>(`${isYolu(id)}/notlar`, { metin }),
  ekip: (id: number) => api.get<EkipUyesi[]>(`${isYolu(id)}/ekip`),
  ata: (id: number, atamalar: AtamaSatiri[]) =>
    api.put<EkipUyesi[]>(`${isYolu(id)}/atama`, { atamalar }),
  /** Tekli tayin + yetkinlik uyarıları (TS-198; uyarı tayini engellemez). */
  ataUyarili: (id: number, atamalar: AtamaSatiri[]) =>
    api
      .putBaslikli<EkipUyesi[]>(`${isYolu(id)}/atama`, { atamalar }, "X-Atama-Uyarilari")
      .then(({ veri, ek }) => ({ ekip: veri, uyarilar: ek })),
  topluAta: (is_idler: number[], atamalar: AtamaSatiri[], mod: "EKLE" | "DEGISTIR") =>
    api.put<{ guncellenen: number; uyarilar?: string[] }>(`${TS}/isler/toplu-atama`, {
      is_idler,
      atamalar,
      mod,
    }),
  onaylar: (id: number) => api.get<Onay[]>(`${isYolu(id)}/onaylar`),
  onayAl: (id: number, g: OnayGirdisi) => api.post<Onay>(`${isYolu(id)}/onay`, g),
  ziyaretOnayi: (is_idler: number[], g: OnayGirdisi) =>
    api.post<Onay[]>(`${TS}/isler/ziyaret-onayi`, { ...g, is_idler }),
  servisFormuYolu: (id: number) => `${isYolu(id)}/servis-formu.pdf`,
  ziyaretFormuYolu: (idler: number[]) =>
    `${TS}/isler/ziyaret-formu.pdf?${idler.map((i) => `is_id=${i}`).join("&")}`,
  arizaNedenleri: (birim: string) =>
    api.get<ArizaNedeni[]>(`${TS}/tanimlar/ariza-nedenleri?${new URLSearchParams({ birim })}`),
  panel: (donem: string) =>
    api.get<PanelOzeti>(`${TS}/panel?${new URLSearchParams({ donem })}`),
};

/**
 * Ekranda çizilen imzayı (canvas PNG) işin eki olarak yükler; ek kimliğini
 * döner. Ek türü canlı `IMZA` (`MUSTERI_IMZASI` açılmaz). Onay ayrı istekte
 * bu kimlikle kaydedilir — ek ile onay ayrı tutulur ki onay değişmez kalsın.
 */
export async function imzaYukle(soId: number, png: Blob): Promise<number> {
  const govde = new FormData();
  govde.append("file", new File([png], "imza.png", { type: "image/png" }));
  const res = await fetch(`/api/ekler/service_orders/${soId}?kind=IMZA`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Requested-With": "fetch" },
    body: govde,
  });
  if (!res.ok) {
    let mesaj = `İmza yüklenemedi (${res.status})`;
    try {
      const g = await res.json();
      if (typeof g?.detail === "string") mesaj = g.detail;
    } catch {
      /* gövde JSON değil */
    }
    throw new Error(mesaj);
  }
  return ((await res.json()) as { id: number }).id;
}
