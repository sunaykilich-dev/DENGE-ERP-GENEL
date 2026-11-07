/**
 * Ekipman kütüğü — API tipleri ve çağrıları (TS-050…057).
 *
 * Sunucu: `backend/app/api/servis_ekipman.py`. Okuma `ekipman.gor`, yazma
 * `ekipman.yaz`, Excel `ekipman.gor` + `servis_rapor.disaaktar`.
 *
 * Mükerrer seri 409'u gövdesinde mevcut kayıtları taşır; form "farklı cihaz"
 * onayını açabilsin diye bu çağrılar gövdeyi taşıyan hata sınıfını kullanır.
 */
import { api, ApiError, type Sayfa } from "./client";

export const EKIPMAN_TIPLERI = [
  "XRAY",
  "KAPI_DEDEKTORU",
  "EL_DEDEKTORU",
  "DIGER_GUVENLIK",
  "TELSIZ",
  "ROLE_TEKRARLAYICI",
  "TELSIZ_DIGER",
  "DIGER",
] as const;

export const TIP_ETIKETLERI: Record<string, string> = {
  XRAY: "X-Ray",
  KAPI_DEDEKTORU: "Kapı Tipi Metal Dedektörü",
  EL_DEDEKTORU: "El Dedektörü",
  DIGER_GUVENLIK: "Diğer Güvenlik Cihazı",
  TELSIZ: "Telsiz",
  ROLE_TEKRARLAYICI: "Röle / Tekrarlayıcı",
  TELSIZ_DIGER: "Diğer Haberleşme",
  DIGER: "Diğer",
};

export const DURUM_ETIKETLERI: Record<string, string> = {
  KURULU: "Kurulu",
  KURULUM_BEKLIYOR: "Kurulum bekliyor",
  DEVRE_DISI: "Devre dışı",
  HURDA: "Hurda",
  BILINMIYOR: "Bilinmiyor",
};

export const DURUM_RENKLERI: Record<string, string> = {
  KURULU: "green",
  KURULUM_BEKLIYOR: "blue",
  DEVRE_DISI: "default",
  HURDA: "red",
  BILINMIYOR: "gold",
};

/** Yeni kayıtta seçilebilen durumlar (makinenin başlangıçları). */
export const BASLANGIC_DURUMLARI = ["BILINMIYOR", "KURULUM_BEKLIYOR", "KURULU"] as const;

export const GARANTI_ETIKETLERI: Record<string, string> = {
  GECERLI: "Garantide",
  BITTI: "Garanti bitti",
  BILINMIYOR: "Bilinmiyor",
};

export const GARANTI_KAYNAKLARI: Record<string, string> = {
  BELGE: "Belge",
  HESAPLANDI: "Hesaplandı",
  BILINMIYOR: "Bilinmiyor",
};

export interface EkipmanSatiri {
  id: number;
  birim: string;
  equipment_type: string;
  brand: string | null;
  model: string | null;
  serial_no: string | null;
  seri_eksik: boolean;
  account_id: number | null;
  hesap_unvan: string | null;
  address_id: number | null;
  lokasyon_adi: string | null;
  il: string | null;
  zone: string | null;
  lifecycle_status: string;
  is_active: boolean;
  install_date: string | null;
  warranty_end: string | null;
  garanti_durumu: "GECERLI" | "BITTI" | "BILINMIYOR";
  serviste: boolean;
  sozlesme_sayisi: number;
  version: number;
}

export interface SozlesmeBagi {
  kalem_id: number;
  sozlesme_id: number;
  sozlesme_no: string;
}

export interface EkipmanKarti extends EkipmanSatiri {
  product_id: number | null;
  product_raw: string | null;
  customer_name_raw: string | null;
  location_raw: string | null;
  irtibat_adi: string | null;
  contact_id: number | null;
  contact_name_raw: string | null;
  delivery_date: string | null;
  delivery_date_raw: string | null;
  warranty_start: string | null;
  warranty_source: string | null;
  duplicate_ack_reason: string | null;
  notes: string | null;
  /** Kayıtlı frekans (Haberleşme; KARARLAR §12): role_tx, role_rx, calisma_modu ... */
  frekans: Record<string, string> | null;
  merged_into_id: number | null;
  sonraki_durumlar: string[];
  aktif_sozlesmeler: SozlesmeBagi[];
  ek_sayisi: number;
  acik_is_sayisi: number;
  created_at: string;
  updated_at: string;
  uyarilar: string[];
}

export interface EkipmanKpi {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number;
}

export interface GecmisOlayi {
  tarih: string;
  tur: "SERVIS_ISI" | "PB" | "BAKIM" | "KUTUK" | string;
  baslik: string;
  durum?: string | null;
  kaynak: string;
  kaynak_id: number;
  sure_dakika?: number | null;
  sure_eksik?: boolean;
  eslesme?: "KIMLIK" | "METIN";
  /** Yalnız `maliyet.gor` olana gelir; yoksa anahtar hiç yoktur. */
  maliyet?: number | null;
}

export interface Degisiklik {
  id: number;
  zaman: string;
  eylem: string;
  etiket: string;
  kullanici_id: number | null;
  kullanici: string | null;
  kisisel: boolean;
  eski: Record<string, unknown>;
  yeni: Record<string, unknown>;
}

export interface GarantiSonucu {
  uygulandi: boolean;
  satir_sayisi: number;
  baslangic_tarihsiz: number;
  ornekler: { id: number; seri: string | null; baslangic: string; bitis: string; ay: number }[];
}

export interface OneriSonucu {
  durum: "TEK" | "BELIRSIZ" | "YOK";
  ekipman: EkipmanSatiri | null;
}

export interface EkipmanSuzgeci {
  q?: string;
  birim?: string;
  tip?: string;
  durum?: string;
  garanti?: string;
  seri_eksik?: boolean;
  lokasyonsuz?: boolean;
  sozlesmesiz?: boolean;
  serviste?: boolean;
  pasifler_dahil?: boolean;
  kpi?: string;
  /** Veri kalitesi listesi (TS-188): seri_eksik, lokasyonsuz, hesapsiz, … */
  kalite?: string;
  hesap_id?: number;
  sozlesme_id?: number;
}

/** Ekipman veri kalitesi kutusu; `liste` kutunun açtığı listeyi söyler. */
export interface KaliteKutusu {
  kod: string;
  baslik: string;
  tanim: string;
  liste: "liste" | "mukerrer" | "saha";
  deger: number;
}

export interface MukerrerGrup {
  tip: string;
  seri_anahtari: string;
  adet: number;
  kayitlar: {
    id: number;
    birim: string;
    brand: string | null;
    model: string | null;
    serial_no: string | null;
    hesap_unvan: string | null;
    lokasyon_adi: string | null;
    il: string | null;
    lifecycle_status: string;
    created_at: string;
  }[];
}

export interface SahaFarki {
  sonuc_id: number;
  so_id: number;
  so_no: string;
  birim: string;
  tur: string;
  ekipman_id: number | null;
  kutuk_seri: string | null;
  kutuk_bolge: string | null;
  saha_seri: string | null;
  saha_bolge: string | null;
  teknisyen_id: number | null;
  teknisyen: string | null;
  tarih: string;
}

export interface BirlestirmeEngelleri {
  sozlesme_kalemleri: { id: number; sozlesme_no: string }[];
  servis_isleri: { id: number; so_no: string }[];
  atolye_kayitlari: { id: number; atolye_no: string }[];
}

/** 409/400 gövdesindeki nesneyi (mükerrer listesi, geçersiz geçiş) taşıyan hata. */
export class EkipmanHatasi extends ApiError {
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
    throw new EkipmanHatasi(res.status, mesaj, detay);
  }
  return (await res.json()) as T;
}

export function suzgecParametreleri(s: EkipmanSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  return p;
}

const URL_ = "/api/teknik-servis/ekipman";

export const ekipmanApi = {
  liste: (s: EkipmanSuzgeci, limit: number, offset: number): Promise<Sayfa<EkipmanSatiri>> => {
    const p = suzgecParametreleri(s);
    p.set("limit", String(limit));
    p.set("offset", String(offset));
    return api.getSayfa<EkipmanSatiri>(`${URL_}?${p}`);
  },
  ozet: () => api.get<EkipmanKpi[]>(`${URL_}/ozet`),
  excelYolu: (s: EkipmanSuzgeci, idler?: number[]) => {
    const p = suzgecParametreleri(s);
    if (idler && idler.length) p.set("ids", idler.join(","));
    return `${URL_}/liste.xlsx?${p}`;
  },
  oneri: (seri: string) =>
    api.get<OneriSonucu>(`${URL_}/oneri?${new URLSearchParams({ seri })}`),
  getir: (id: number) => api.get<EkipmanKarti>(`${URL_}/${id}`),
  gecmis: (id: number) => api.get<GecmisOlayi[]>(`${URL_}/${id}/gecmis`),
  degisiklikler: (id: number) => api.get<Degisiklik[]>(`${URL_}/${id}/degisiklikler`),
  olustur: (govde: Record<string, unknown>) => detayli<EkipmanKarti>(URL_, "POST", govde),
  guncelle: (id: number, govde: Record<string, unknown>) =>
    detayli<EkipmanKarti>(`${URL_}/${id}`, "PATCH", govde),
  pasif: (id: number, gerekce: string) =>
    detayli<EkipmanKarti>(`${URL_}/${id}/pasif`, "POST", { gerekce }),
  aktif: (id: number, gerekce: string, mukerrer_gerekcesi?: string) =>
    detayli<EkipmanKarti>(`${URL_}/${id}/aktif`, "POST", { gerekce, mukerrer_gerekcesi }),
  durum: (id: number, govde: { hedef: string; gerekce: string; tarih?: string | null }) =>
    detayli<EkipmanKarti>(`${URL_}/${id}/durum`, "POST", govde),
  /** KVKK (TS-057): irtibat adını ve geçmişteki irtibat değerlerini imha eder (`kvkk.yonet`). */
  irtibatImha: (id: number, gerekce: string) =>
    detayli<{ ekipman_id: number; maskelenen_denetim_satiri: number }>(
      `${URL_}/${id}/irtibat-imha`,
      "POST",
      { gerekce },
    ),
  topluDurum: (govde: { idler: number[]; hedef: string; gerekce: string }) =>
    detayli<EkipmanSatiri[]>(`${URL_}/toplu-durum`, "POST", govde),
  topluGaranti: (govde: { idler?: number[] | null }, uygula: boolean) =>
    detayli<GarantiSonucu>(`${URL_}/garanti/toplu-hesapla?uygula=${uygula}`, "POST", govde),

  // --- Veri kalitesi, birleştirme, saha farkı (TS-188 / TS-191) ---
  veriKalitesi: () => api.get<KaliteKutusu[]>(`${URL_}/veri-kalitesi`),
  mukerrerGruplar: (limit: number, offset: number) =>
    api.getSayfa<MukerrerGrup>(`${URL_}/mukerrer-gruplar?limit=${limit}&offset=${offset}`),
  sahaFarklari: (limit: number, offset: number) =>
    api.getSayfa<SahaFarki>(`${URL_}/saha-farklari?limit=${limit}&offset=${offset}`),
  sahaUygula: (soId: number) =>
    detayli<EkipmanKarti>(`${URL_}/saha-farklari/${soId}/uygula`, "POST", {}),
  sahaYoksay: async (soId: number, gerekce: string) => {
    await api.post<void>(`${URL_}/saha-farklari/${soId}/yoksay`, { gerekce });
  },
  birlestirmeEngelleri: (id: number) =>
    api.get<BirlestirmeEngelleri>(`${URL_}/${id}/birlestirme-engelleri`),
  birlestir: (ikincilId: number, anaId: number, gerekce: string) =>
    detayli<EkipmanKarti>(`${URL_}/${ikincilId}/birlestir`, "POST", { ana_id: anaId, gerekce }),
};
