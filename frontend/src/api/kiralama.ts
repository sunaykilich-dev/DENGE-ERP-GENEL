/**
 * Kiralama — API tipleri ve çağrıları (TS-110…122, TS-102 kiralama tarafı).
 *
 * Sunucu: `backend/app/api/kiralamalar.py` (`/api/kiralama`).
 *
 * İzinler: okuma `kiralama.gor`; talep/kalem/irtibat/planla/iptal/kapat
 * `kiralama.yaz`; envanter/tahsis/kontrol/katalog `kiralama.envanter`;
 * sevk/iade/aşama/geri alma `kiralama.asama`; servis işi açma ayrıca
 * `servis.yaz`; Excel `kiralama.gor` + `servis_rapor.disaaktar`.
 *
 * Fiyat/maliyet alanı YOKTUR (kiralama bedeli ERP'de tutulmaz). Durum yalnız
 * aşama uçlarıyla değişir; PUT durum/birim kabul etmez. Hareket defteri
 * ekleme-yalnızdır — düzeltme ters hareketle yapılır.
 */
import { api, ApiError, type Sayfa } from "./client";

export const KIRALAMA_ONEK = "/kiralama";
const URL_ = `/api${KIRALAMA_ONEK}`;

// --- Sözlükler (sunucu sabitleriyle aynı kodlar) ---------------------------------

export const KIRALAMA_DURUM_ADLARI: Record<string, string> = {
  TALEP: "Talep",
  PLANLANDI: "Planlandı",
  HAZIRLANIYOR: "Hazırlanıyor",
  SEVK_EDILDI: "Sevk edildi",
  KURULUM_YAPILDI: "Kurulum yapıldı",
  DEVREYE_ALINDI: "Devreye alındı",
  TOPLANDI: "Toplandı",
  DEPOYA_ALINDI: "Depoya alındı",
  KAPANDI: "Kapandı",
  IPTAL: "İptal",
};

export const KIRALAMA_DURUM_RENKLERI: Record<string, string> = {
  TALEP: "default",
  PLANLANDI: "blue",
  HAZIRLANIYOR: "geekblue",
  SEVK_EDILDI: "orange",
  KURULUM_YAPILDI: "gold",
  DEVREYE_ALINDI: "green",
  TOPLANDI: "cyan",
  DEPOYA_ALINDI: "purple",
  KAPANDI: "default",
  IPTAL: "red",
};

/** `/asama` ucunun kabul ettiği hedefler; sevk/iade/iptal/kapanışın kendi ucu var. */
export const ASAMA_HEDEFLERI = ["KURULUM_YAPILDI", "DEVREYE_ALINDI", "TOPLANDI"] as const;

export const KIRALIK_DURUM_ADLARI: Record<string, string> = {
  HAZIR: "Hazır",
  HAZIR_DEGIL: "Hazır değil",
  KONTROLDE: "Kontrolde",
  KIRADA: "Kirada",
  KAYIP: "Kayıp",
  ATOLYEDE: "Atölyede",
  HURDA: "Hurda",
};

export const KIRALIK_DURUM_RENKLERI: Record<string, string> = {
  HAZIR: "green",
  HAZIR_DEGIL: "volcano",
  KONTROLDE: "gold",
  KIRADA: "blue",
  KAYIP: "red",
  ATOLYEDE: "purple",
  HURDA: "default",
};

/** Girişte seçilebilen durumlar (sunucu `GIRIS_DURUMLARI`). */
export const GIRIS_DURUMLARI = ["HAZIR", "KONTROLDE", "HAZIR_DEGIL"] as const;
/** Kontrol edilebilen kaynak durumlar (sunucu `KONTROL_KAYNAK_DURUMLARI`). */
export const KONTROL_KAYNAK_DURUMLARI = ["KONTROLDE", "HAZIR_DEGIL"] as const;
/** Hurdaya ayrılabilen kaynak durumlar (sunucu `HURDA_KAYNAK_DURUMLARI`). */
export const HURDA_KAYNAK_DURUMLARI = ["HAZIR_DEGIL", "KONTROLDE", "KAYIP", "ATOLYEDE"] as const;

export const KONTROL_SONUC_ADLARI: Record<string, string> = {
  UYGUN: "Uygun",
  EKSIK: "Eksik",
  ARIZALI: "Arızalı",
};

export const IADE_SONUC_ADLARI: Record<string, string> = {
  IADE_ALINDI: "Depoya iade",
  KAYIP: "Kayıp",
  MUSTERIDE: "Müşteride (not)",
};

export const IRTIBAT_ROL_ADLARI: Record<string, string> = {
  SATIN_ALMA: "Satın alma",
  SAHA_OPERASYON: "Saha operasyon",
  TEKNIK_SORUMLU: "Teknik sorumlu",
  DIGER: "Diğer",
};

export const HAREKET_ADLARI: Record<string, string> = {
  GIRIS: "Giriş",
  TRANSFER: "Transfer",
  TAHSIS: "Tahsis",
  TAHSIS_COZ: "Tahsis çözme",
  SEVK: "Sevk",
  IADE: "İade",
  KAYIP: "Kayıp",
  BULUNDU: "Bulundu",
  KONTROL: "Kontrol",
  ATOLYE: "Atölye",
  DUZENLEME: "Düzenleme",
  SAYIM: "Sayım",
  DUZELTME: "Düzeltme (ters)",
  DEGISIM: "Değişim",
  HURDA: "Hurda",
};

export const OLAY_ADLARI: Record<string, string> = {
  OLUSTUR: "Oluşturuldu",
  DURUM: "Durum",
  ASAMA: "Aşama",
  TAHSIS: "Tahsis",
  SEVK: "Sevk",
  IADE: "İade",
  KONTROL: "Kontrol",
  IPTAL: "İptal",
  DUZELTME: "Geri alma",
  TARIH: "Tarih",
  SORUMLU: "Sorumlu",
  KALEM: "Kalem",
  IRTIBAT: "İrtibat",
  NOT: "Not",
};

export const SERVIS_ISI_TURLERI: Record<string, string> = {
  KURULUM: "Kurulum",
  TOPLAMA: "Toplama",
};

/** Kiralama ve kiralık envanter bu birimlerde YOK (E06-D05). */
export const KIRALAMA_DISI_BIRIMLER = ["MOBILITE", "ARAC_TAKIP"];

// --- Tipler ------------------------------------------------------------------------

export interface KiralamaSatiri {
  id: number;
  rental_no: string;
  birim: string;
  customer_id: number;
  musteri: string | null;
  proje_adi: string | null;
  lokasyon_metni: string | null;
  baslangic: string;
  bitis: string;
  status: string;
  kalem_ozeti: string[];
  kalem_adet: number;
  tahsis_adet: number;
  iade_gosterimi: "YOK" | "KISMI" | "TAM";
  geciken: boolean;
  version: number;
}

export interface KalemOut {
  id: number;
  product_id: number;
  urun_kodu: string | null;
  urun_adi: string | null;
  seri_takipli: boolean;
  qty: number;
  note: string | null;
  tahsisli: number;
  sevk: number;
  iade: number;
  kayip: number;
}

export interface TahsisOut {
  id: number;
  rental_item_id: number;
  product_id: number;
  urun_kodu: string | null;
  kiralik_id: number | null;
  seri: string | null;
  depo_id: number;
  depo_adi: string | null;
  qty: number;
  sevk_adet: number;
  iade_adet: number;
  kayip_adet: number;
  musteride: number;
  durum: "AKTIF" | "KAPANDI" | "COZULDU";
  shipped_at: string | null;
  replaced_allocation_id: number | null;
}

export interface IrtibatOut {
  id: number;
  contact_id: number;
  ad: string | null;
  unvan: string | null;
  rol: string;
}

export interface BagliIs {
  id: number;
  so_no: string;
  tur: string;
  status: string;
}

export interface KiralamaKarti extends KiralamaSatiri {
  address_id: number | null;
  lokasyon: string | null;
  sorumlu_user_id: number | null;
  sorumlu_adi: string | null;
  quote_id: number | null;
  notes: string | null;
  iptal_gerekcesi: string | null;
  kapanis_at: string | null;
  created_at: string;
  kalemler: KalemOut[];
  tahsisler: TahsisOut[];
  /** Yalnız yazan/aşama sahibine ya da `servis.irtibat_gor`'e gelir (KVKK). */
  irtibatlar?: IrtibatOut[] | null;
  sonraki_durumlar: string[];
  servis_isleri: BagliIs[];
  onerilen_asama: string | null;
  geri_alinabilir_olay_id: number | null;
}

export interface OlayOut {
  id: number;
  at: string;
  tur: string;
  onceki_durum: string | null;
  yeni_durum: string | null;
  alan: string | null;
  eski: Record<string, unknown> | null;
  yeni: Record<string, unknown> | null;
  service_order_id: number | null;
  ekip_user_ids: number[] | null;
  gerekce: string | null;
  geri_alinan_event_id: number | null;
  geri_alindi: boolean;
  kullanici: string | null;
}

export interface Kpi {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number;
}

export interface CihazSatiri {
  id: number;
  product_id: number;
  urun_kodu: string | null;
  urun_adi: string | null;
  serial_no: string;
  birim: string;
  depo_id: number | null;
  depo_adi: string | null;
  durum: string;
  eksik_notu: string | null;
  notes: string | null;
  kiralama_id: number | null;
  kontrolde_gun: number | null;
  version: number;
}

export interface HareketOut {
  id: number;
  at: string;
  kind: string;
  product_id: number;
  kiralik_id: number | null;
  qty: number;
  from_depo_id: number | null;
  to_depo_id: number | null;
  from_depo: string | null;
  to_depo: string | null;
  from_durum: string | null;
  to_durum: string | null;
  rental_id: number | null;
  rental_no: string | null;
  allocation_id: number | null;
  check_id: number | null;
  reverses_id: number | null;
  note: string | null;
}

export interface CihazKarti extends CihazSatiri {
  hareketler: HareketOut[];
}

export interface KatalogOut {
  id: number;
  product_id: number;
  urun_kodu: string | null;
  urun_adi: string | null;
  seri_takipli: boolean;
  birim: string;
  kategori: string | null;
  sira: number;
  is_active: boolean;
  version: number;
}

export interface Depo {
  id: number;
  code: string;
  name: string;
  birim: string | null;
}

export interface BakiyeSatiri {
  product_id: number;
  urun_kodu: string | null;
  urun_adi: string | null;
  depo_id: number | null;
  depo_adi: string | null;
  durum: string;
  adet: number;
  seri_takipli: boolean;
}

export interface Musaitlik {
  product_id: number;
  baslangic: string;
  bitis: string;
  toplam: number;
  hazir: number;
  kirada: number;
  kontrolde: number;
  hazir_degil: number;
  kayip: number;
  atolyede: number;
  rezerve: number;
  geciken: number;
  musait: number;
  urun_kodu: string;
  seri_takipli: boolean;
}

export interface TopluOnizlemeSatiri {
  satir_no: number;
  urun_kodu: string | null;
  seri_no: string | null;
  adet: number | null;
  depo_kodu: string | null;
  durum: string | null;
  not: string | null;
  hatalar: string[];
}

export interface TopluOnizleme {
  sha256: string;
  toplam: number;
  gecerli: number;
  hatali: number;
  satirlar: TopluOnizlemeSatiri[];
}

export interface TopluSonuc {
  yazilan_satir: number;
  atlanan_satir: number;
  toplam_adet: number;
  hatalar: { satir_no: number; hatalar: string[] }[];
}

// --- Girdiler ----------------------------------------------------------------------

export interface KalemGirdisi {
  id?: number | null;
  product_id: number;
  qty: number;
  note?: string | null;
}

export interface IrtibatGirdisi {
  id?: number | null;
  contact_id: number;
  rol: string;
}

export interface KiralamaGirdisi {
  birim: string;
  customer_id: number | null;
  address_id?: number | null;
  lokasyon_metni?: string | null;
  proje_adi?: string | null;
  baslangic: string;
  bitis: string;
  sorumlu_user_id?: number | null;
  notes?: string | null;
  kalemler: KalemGirdisi[];
  irtibatlar: IrtibatGirdisi[];
}

/**
 * M10.1 (KARARLAR 2026-10-28): seri cihazın başka kiralamayla tarih çakışması
 * engel değil uyarıdır. İlk istek 409 + `kod: "KIRALAMA_CAKISMA"` alır;
 * kullanıcı gerekçe yazınca istek bu alanlarla yeniden gönderilir.
 */
export interface CakismaOnayi {
  cakisma_onay: true;
  cakisma_gerekcesi: string;
}

export interface KiralamaCakismasi {
  seri_no: string;
  kiralik_id: number;
  tahsis_id: number;
  kiralama_id: number;
  kiralama_no: string | null;
  kiralama_durumu: string | null;
  baslangic: string;
  bitis: string;
}

export type KiralamaGuncelleme = Partial<Omit<KiralamaGirdisi, "birim">> & {
  version: number;
} & Partial<CakismaOnayi>;

export interface KiralamaSuzgeci {
  q?: string;
  durum?: string;
  birim?: string;
  musteri?: number;
  kpi?: string;
}

export interface EnvanterSuzgeci {
  q?: string;
  durum?: string;
  depo_id?: number;
  product_id?: number;
  birim?: string;
  uzun?: boolean;
}

export interface TahsisSatiri {
  kalem_id: number;
  kiralik_idler?: number[] | null;
  depo_id?: number | null;
  adet?: number | null;
}

export interface IadeSatiri {
  tahsis_id: number;
  sonuc: string;
  adet?: number | null;
  depo_id?: number | null;
  not?: string | null;
}

export interface KontrolSatiri {
  sonuc: string;
  kiralik_id?: number | null;
  product_id?: number | null;
  depo_id?: number | null;
  adet?: number | null;
  kaynak_durum?: string;
  aciklama?: string | null;
  rental_id?: number | null;
  atolye_kaydi_ac?: boolean;
}

// --- Yardımcılar ------------------------------------------------------------------

function sorgu(s: object, ek: Record<string, string | number | undefined> = {}): string {
  const p = new URLSearchParams();
  const hepsi: Record<string, unknown> = { ...s, ...ek };
  for (const [k, v] of Object.entries(hepsi)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  const m = p.toString();
  return m ? `?${m}` : "";
}

async function dosyaGonder<T>(yol: string, dosya: File, alanlar: Record<string, string> = {}): Promise<T> {
  const fd = new FormData();
  fd.append("file", dosya);
  for (const [k, v] of Object.entries(alanlar)) fd.append(k, v);
  const res = await fetch(yol, {
    method: "POST",
    body: fd,
    credentials: "same-origin",
    headers: { "X-Requested-With": "fetch" },
  });
  if (!res.ok) {
    let mesaj = `Beklenmeyen hata (${res.status})`;
    try {
      const g = await res.json();
      if (typeof g?.detail === "string") mesaj = g.detail;
    } catch {
      /* gövde JSON değil */
    }
    throw new ApiError(res.status, mesaj);
  }
  return (await res.json()) as T;
}

// --- Çağrılar ---------------------------------------------------------------------

export const kiralamaApi = {
  liste: (s: KiralamaSuzgeci, limit: number, offset: number): Promise<Sayfa<KiralamaSatiri>> =>
    api.getSayfa<KiralamaSatiri>(`${URL_}${sorgu(s, { limit, offset })}`),
  ozet: () => api.get<Kpi[]>(`${URL_}/ozet`),
  excelYolu: (s: KiralamaSuzgeci) => `${URL_}/liste.xlsx${sorgu(s)}`,
  getir: (id: number) => api.get<KiralamaKarti>(`${URL_}/${id}`),
  gecmis: (id: number) => api.get<OlayOut[]>(`${URL_}/${id}/gecmis`),
  olustur: (g: KiralamaGirdisi) => api.post<KiralamaKarti>(URL_, g),
  guncelle: (id: number, g: KiralamaGuncelleme) => api.put<KiralamaKarti>(`${URL_}/${id}`, g),
  planla: (id: number) => api.post<KiralamaKarti>(`${URL_}/${id}/planla`),
  tahsis: (id: number, satirlar: TahsisSatiri[], onay?: CakismaOnayi) =>
    api.post<KiralamaKarti>(`${URL_}/${id}/tahsis`, { satirlar, ...onay }),
  tahsisCoz: (id: number, tahsisId: number) =>
    api.post<KiralamaKarti>(`${URL_}/${id}/tahsis/${tahsisId}/coz`),
  sevk: (id: number, g: { at?: string | null; satirlar?: { tahsis_id: number; adet?: number }[] | null; not?: string }) =>
    api.post<KiralamaKarti>(`${URL_}/${id}/sevk`, g),
  asama: (id: number, g: { asama: string; at?: string | null; service_order_id?: number | null; not?: string }) =>
    api.post<KiralamaKarti>(`${URL_}/${id}/asama`, g),
  iade: (id: number, g: { at?: string | null; satirlar: IadeSatiri[] }) =>
    api.post<KiralamaKarti>(`${URL_}/${id}/iade`, g),
  geriAl: (id: number, g: { gerekce: string; olay_id?: number | null }) =>
    api.post<KiralamaKarti>(`${URL_}/${id}/geri-al`, g),
  iptal: (id: number, gerekce: string) => api.post<KiralamaKarti>(`${URL_}/${id}/iptal`, { gerekce }),
  kapat: (id: number) => api.post<KiralamaKarti>(`${URL_}/${id}/kapat`),
  servisIsi: (id: number, tur: string) =>
    api.post<BagliIs>(`${URL_}/${id}/servis-isi`, { tur }),
  tutanakYolu: (id: number, tur: "TESLIM" | "IADE") => `${URL_}/${id}/tutanak.pdf?tur=${tur}`,
  musaitlik: (productId: number, baslangic: string, bitis: string, haricKiralama?: number) =>
    api.get<Musaitlik>(
      `${URL_}/musaitlik${sorgu({}, { product_id: productId, baslangic, bitis, haric_kiralama: haricKiralama })}`,
    ),
  depolar: () => api.get<Depo[]>(`${URL_}/depolar`),
  musteriIrtibatlari: (musteriId: number) =>
    api.get<{ id: number; ad: string; unvan: string | null }[]>(
      `${URL_}/musteri-irtibatlari?musteri_id=${musteriId}`,
    ),

  // Katalog (TS-118)
  katalog: (birim?: string, aktif?: boolean) =>
    api.get<KatalogOut[]>(`${URL_}/katalog${sorgu({}, { birim, aktif: aktif === undefined ? undefined : String(aktif) })}`),
  katalogEkle: (g: { product_id: number; birim: string; kategori?: string | null; sira?: number }) =>
    api.post<KatalogOut>(`${URL_}/katalog`, g),
  katalogGuncelle: (
    id: number,
    g: { version?: number; birim?: string; kategori?: string | null; sira?: number; is_active?: boolean },
  ) => api.patch<KatalogOut>(`${URL_}/katalog/${id}`, g),

  // Kiralık envanter (TS-111, 115, 121, 102)
  envanter: (s: EnvanterSuzgeci, limit: number, offset: number): Promise<Sayfa<CihazSatiri>> =>
    api.getSayfa<CihazSatiri>(`${URL_}/envanter${sorgu(s, { limit, offset })}`),
  envanterExcelYolu: (s: EnvanterSuzgeci) => `${URL_}/envanter/liste.xlsx${sorgu(s)}`,
  sablonYolu: () => `${URL_}/envanter/sablon.xlsx`,
  bakiyeler: () => api.get<BakiyeSatiri[]>(`${URL_}/envanter/bakiyeler`),
  topluHareketler: (productId?: number, depoId?: number, limit = 100, offset = 0) =>
    api.getSayfa<HareketOut>(
      `${URL_}/envanter/hareketler${sorgu({}, { product_id: productId, depo_id: depoId, limit, offset })}`,
    ),
  cihaz: (id: number) => api.get<CihazKarti>(`${URL_}/envanter/${id}`),
  cihazGuncelle: (id: number, g: { version: number; serial_no?: string; eksik_notu?: string | null; notes?: string | null }) =>
    api.patch<CihazKarti>(`${URL_}/envanter/${id}`, g),
  giris: (g: { product_id: number; depo_id: number; durum: string; seriler?: string[] | null; adet?: number | null; not?: string }) =>
    api.post<{ adet: number; kiralik_idler: number[]; hareket_idler: number[] }>(`${URL_}/envanter`, g),
  transfer: (g: {
    hedef_depo_id: number;
    kiralik_idler?: number[] | null;
    product_id?: number | null;
    kaynak_depo_id?: number | null;
    adet?: number | null;
    durum?: string;
    not?: string;
  }) => api.post<{ hareket_idler: number[]; adet: number }>(`${URL_}/envanter/transfer`, g),
  kontrol: (satirlar: KontrolSatiri[]) =>
    api.post<{ kontroller: { id: number; kiralik_id: number | null; sonuc: string; workshop_record_id: number | null }[] }>(
      `${URL_}/envanter/kontrol`,
      { satirlar },
    ),
  bulundu: (g: { gerekce: string; depo_id: number; kiralik_id?: number | null; product_id?: number | null; adet?: number | null }) =>
    api.post<{ hareket_id: number }>(`${URL_}/envanter/bulundu`, g),
  hurda: (g: {
    gerekce: string;
    kiralik_id?: number | null;
    product_id?: number | null;
    depo_id?: number | null;
    kaynak_durum?: string;
    adet?: number | null;
  }) => api.post<{ hareket_id: number }>(`${URL_}/envanter/hurda`, g),
  topluOnizleme: (dosya: File) => dosyaGonder<TopluOnizleme>(`${URL_}/envanter/toplu/onizleme`, dosya),
  topluOnayla: (dosya: File, sha256: string) =>
    dosyaGonder<TopluSonuc>(`${URL_}/envanter/toplu/onayla`, dosya, { sha256 }),

  // Sahada cihaz değişimi (TS-195, E06-20) — `kiralama.asama`
  degisim: (
    id: number,
    g: { eski_tahsis_id: number; yeni_kiralik_id: number; iade_depo_id: number; not?: string },
    onay?: CakismaOnayi,
  ) => api.post<KiralamaKarti>(`${URL_}/${id}/degisim`, { ...g, ...onay }),

  // Raporlar (TS-195, E06-21) — `kiralama.gor + servis_rapor.gor`; Excel + `servis_rapor.disaaktar`
  raporDepoDurumu: () => api.get<DepoDurumu>(`${URL_}/raporlar/depo-durumu`),
  raporGecikenIade: () => api.get<GecikenIadeSatiri[]>(`${URL_}/raporlar/geciken-iade`),
  raporKontroldeBekleme: () => api.get<KontroldeBekleme>(`${URL_}/raporlar/kontrolde-bekleme`),
  raporExcelYolu: (rapor: "depo-durumu" | "geciken-iade" | "kontrolde-bekleme") =>
    `${URL_}/raporlar/${rapor}.xlsx`,

  // Depo sayımı (TS-195, E06-22 b) — okuma `kiralama.gor`, yazma `kiralama.envanter`
  sayimlar: (durum?: string, limit = 50, offset = 0) =>
    api.getSayfa<SayimOzeti>(`${URL_}/sayimlar${sorgu({}, { durum, limit, offset })}`),
  sayimAc: (depoId: number, notes?: string) =>
    api.post<SayimDetayi>(`${URL_}/sayimlar`, { depo_id: depoId, notes }),
  sayim: (id: number) => api.get<SayimDetayi>(`${URL_}/sayim?sayim_id=${id}`),
  sayimSatirlari: (id: number, satirlar: SayimSatirGirdisi[]) =>
    api.put<SayimDetayi>(`${URL_}/sayim/satirlar`, { sayim_id: id, satirlar }),
  sayimFarki: (id: number) => api.get<SayimFarki>(`${URL_}/sayim/fark?sayim_id=${id}`),
  sayimOnayla: (id: number, g: { kararlar: string[]; gerekce?: string; degisimi_kabul?: boolean }) =>
    api.post<SayimDetayi & { hareketler: number[] }>(`${URL_}/sayim/onayla`, { sayim_id: id, ...g }),
  sayimIptal: (id: number, gerekce: string) =>
    api.post<SayimOzeti>(`${URL_}/sayim/iptal`, { sayim_id: id, gerekce }),
};

// --- Rapor ve sayım tipleri (TS-195) ---------------------------------------------------

export interface DepoDurumHucreleri {
  hazir: number;
  rezerve: number;
  serbest: number;
  kirada: number;
  kontrolde: number;
  hazir_degil: number;
  kayip: number;
  atolyede: number;
}

export interface DepoDurumu {
  satirlar: (DepoDurumHucreleri & {
    depo_id: number | null;
    depo_adi: string;
    product_id: number;
    urun_kodu: string | null;
    urun_adi: string | null;
    seri_takipli: boolean;
  })[];
  depolar: (DepoDurumHucreleri & { depo_id: number | null; depo_adi: string })[];
}

export interface AsamaSuresi {
  so_no: string | null;
  dk: number | null;
  durum: string;
}

export interface GecikenIadeSatiri {
  id: number;
  rental_no: string;
  birim: string;
  musteri: string | null;
  proje_adi: string | null;
  bitis: string;
  gecikme_gun: number;
  status: string;
  musteride_adet: number;
  seriler: string[];
  asama_sureleri: Record<string, AsamaSuresi>;
}

export interface KontroldeBekleme {
  esik_gun: number;
  seri: {
    kiralik_id: number;
    urun_kodu: string | null;
    urun_adi: string | null;
    serial_no: string;
    depo_adi: string | null;
    giris_at: string | null;
    bekleme_gun: number | null;
    uzun: boolean;
  }[];
  toplu: {
    product_id: number;
    urun_kodu: string | null;
    urun_adi: string | null;
    depo_id: number;
    depo_adi: string | null;
    adet: number;
    son_giris_at: string | null;
    bekleme_gun: number | null;
    uzun: boolean;
  }[];
}

export const SAYIM_DURUM_ADLARI: Record<string, string> = {
  ACIK: "Açık",
  ONAYLANDI: "Onaylandı",
  IPTAL: "İptal",
};

export interface SayimOzeti {
  id: number;
  depo_id: number;
  depo_adi: string | null;
  durum: string;
  baslangic_at: string;
  onay_at: string | null;
  onaylayan_id: number | null;
  iptal_gerekcesi: string | null;
  notes: string | null;
  version: number;
}

export interface SayimSatiri {
  id: number;
  product_id: number;
  urun_kodu: string | null;
  kiralik_id: number | null;
  seri: string | null;
  sistemde: boolean;
  sayilan_adet: number;
  notes: string | null;
}

export interface SayimDetayi extends SayimOzeti {
  satirlar: SayimSatiri[];
}

export interface SayimSatirGirdisi {
  product_id: number;
  seri?: string | null;
  adet?: number | null;
  notes?: string | null;
}

export interface FarkSatiri {
  anahtar: string;
  tur: "SAYILMADI" | "SISTEMDE_YOK" | "BASKA_YERDE" | "EKSIK" | "FAZLA";
  tur_adi: string;
  product_id: number;
  urun_kodu: string | null;
  urun_adi: string | null;
  kiralik_id: number | null;
  seri: string | null;
  sistem_durum: string | null;
  sistem_adet: number;
  sayilan_adet: number;
  fark: number;
  uygulanabilir: boolean;
}

export interface SayimFarki {
  sayim_id: number;
  depo_id: number;
  satirlar: FarkSatiri[];
  sayim_sonrasi_hareket: number;
  ozet: Record<string, number>;
}
