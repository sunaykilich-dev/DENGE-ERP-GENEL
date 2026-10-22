/**
 * Yedek parça ve servis stoğu — API tipleri ve çağrıları (TS-130…138).
 *
 * Sunucu: `backend/app/api/yedek_parca.py`.
 *
 * KURALLAR:
 * - Bakiye, az stok durumu, net çıkış ve KPI sayıları YALNIZ sunucudan gelir;
 *   ön yüz stok HESAPLAMAZ (sayı = liste).
 * - `unit_cost` / `tutar` anahtarları yalnız `maliyet.gor` sahibine döner;
 *   tiplerde isteğe bağlıdır. Anahtar yoksa sütun gösterilmez (0 DEĞİL).
 * - 409 gövdeleri makine okunur alan taşıyabilir (`sapmalar`, `hatalar`);
 *   `parcaHatasi` bunları ayıklar.
 */
import { ApiError, api } from "./client";

export const PARCA_ONEK = "/api/teknik-servis/parca";

export const HAREKET_TURU_ADLARI: Record<string, string> = {
  GIRIS: "Giriş",
  ACILIS: "Açılış stoğu",
  CIKIS_SERVIS: "Servis çıkışı",
  IADE_SERVIS: "Servis iadesi",
  ZAYI: "Zayi",
  TERS_KAYIT: "Ters kayıt",
  TRANSFER_CIKIS: "Transfer çıkışı",
  TRANSFER_GIRIS: "Transfer girişi",
  SAYIM_FAZLASI: "Sayım fazlası",
  SAYIM_EKSIGI: "Sayım eksiği",
};

export const STOK_DURUM_ADLARI: Record<string, string> = {
  YOK: "Stok yok",
  AZ: "Az stok",
  YETERLI: "Yeterli",
};

export const STOK_DURUM_RENKLERI: Record<string, string> = {
  YOK: "red",
  AZ: "gold",
  YETERLI: "green",
};

export const TALEP_DURUM_ADLARI: Record<string, string> = {
  ACIK: "Açık",
  KARSILANDI: "Karşılandı",
  IPTAL: "İptal",
};

export const SAYIM_DURUM_ADLARI: Record<string, string> = {
  ACIK: "Açık",
  ONAYLANDI: "Onaylandı",
  IPTAL: "İptal",
};

/** Ölçü birimleri (sunucu `OLCU_BIRIMLERI`; adet daima tam sayı). */
export const OLCU_BIRIMLERI = ["ADET", "METRE", "TAKIM", "LITRE", "PAKET", "KUTU"];

// --- Tipler ------------------------------------------------------------------

export interface Depo {
  id: number;
  code: string;
  name: string;
  birim: string | null;
  location_type: string;
  user_id: number | null;
  is_active: boolean;
  kendi_araci: boolean;
}

export interface DepoGirdisi {
  code?: string;
  name?: string;
  birim?: string | null;
  location_type?: string;
  user_id?: number | null;
  is_active?: boolean;
}

export interface ParcaSecenegi {
  id: number;
  code: string;
  name: string;
  birim: string;
  toplam: number;
}

export interface StokSatiri {
  product_id: number;
  kod: string;
  ad: string;
  marka: string | null;
  model: string | null;
  birim: string;
  min_stok: number | null;
  is_active: boolean;
  version: number;
  toplam: number;
  durum: string;
  depolar: { depo_id: number; depo_kodu: string; depo_adi: string; adet: number }[];
}

export interface StokOzeti {
  az_stok: number;
  stok_yok: number;
  acik_talep: number;
  acik_sayim: number;
  bugun_cikis: number;
}

export interface Hareket {
  id: number;
  created_at: string;
  tur: string;
  tur_adi: string;
  product_id: number;
  kod: string;
  ad: string;
  birim: string;
  depo_id: number;
  depo_kodu: string;
  depo_adi: string;
  adet: number;
  document_no: string | null;
  notes: string | null;
  service_order_id: number | null;
  so_no: string | null;
  reversal_of_id: number | null;
  ters_kaydi_var: boolean;
  transfer_grup: string | null;
  stock_count_id: number | null;
  part_request_id: number | null;
  kullanici: string | null;
  /** Yalnız `maliyet.gor`. */
  unit_cost?: number | null;
  tutar?: number | null;
}

export interface YazilanHareket {
  id: number;
  tur: string;
  product_id: number;
  kod: string | null;
  depo_id: number;
  adet: number;
  service_order_id: number | null;
  transfer_grup: string | null;
  unit_cost?: number | null;
  tutar?: number | null;
}

export interface Talep {
  id: number;
  service_order_id: number;
  so_no: string | null;
  product_id: number;
  kod: string;
  ad: string;
  adet: number;
  durum: string;
  notes: string | null;
  iptal_nedeni: string | null;
  karsilanma_at: string | null;
  beklemeye_bagli: boolean;
  created_at: string;
  created_by: number | null;
  version: number;
}

export interface IsParcaHareketi {
  id: number;
  created_at: string;
  tur: string;
  tur_adi: string;
  product_id: number;
  kod: string;
  ad: string;
  birim: string;
  depo_id: number;
  depo_adi: string;
  adet: number;
  ters_kaydi_var: boolean;
  kullanici: string | null;
  unit_cost?: number | null;
  tutar?: number | null;
}

export interface IsParcaOzeti {
  product_id: number;
  kod: string;
  ad: string;
  birim: string;
  net: number;
  tutar?: number;
  maliyet_eksik?: boolean;
}

export interface IsParcalari {
  service_order_id: number;
  so_no: string;
  acik: boolean;
  hareketler: IsParcaHareketi[];
  ozet: IsParcaOzeti[];
  talepler: Talep[];
}

export interface SayimSatiri {
  product_id: number;
  kod: string;
  ad: string;
  birim: string;
  sistem_adet: number;
  sayilan_adet: number | null;
  onay_anindaki_adet: number | null;
  fark: number | null;
}

export interface Sayim {
  id: number;
  count_no: string;
  depo_id: number;
  depo_adi: string | null;
  durum: string;
  baslangic_at: string;
  onay_at: string | null;
  onaylayan_id: number | null;
  gerekce: string | null;
  notes: string | null;
  version: number;
  satirlar?: SayimSatiri[];
}

export interface Kart {
  id: number;
  code: string;
  name: string;
  brand: string | null;
  model: string | null;
  supplier_code: string | null;
  birim: string | null;
  min_stok: number | null;
  yedek_parca: boolean;
  is_active: boolean;
  version: number;
}

export interface KartGirdisi {
  code: string;
  name: string;
  brand?: string | null;
  model?: string | null;
  supplier_code?: string | null;
  birim?: string | null;
  min_stok?: number | null;
}

export interface SatirGirdisi {
  product_id: number;
  adet: number;
  unit_cost?: number | null;
}

export interface StokSuzgeci {
  q?: string;
  depo_id?: number;
  durum?: string;
  esikli?: boolean;
  pasifler?: boolean;
}

export interface HareketSuzgeci {
  product_id?: number;
  depo_id?: number;
  tur?: string;
  so_no?: string;
  belge?: string;
  bas?: string;
  bit?: string;
}

export interface AcilisSatiri {
  product_id: number;
  depo_id: number;
  adet: number;
  unit_cost?: number | null;
  notes?: string | null;
}

function parametreler(s: object): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  return p;
}

function sayfali(s: object, limit: number, offset: number): URLSearchParams {
  const p = parametreler(s);
  p.set("limit", String(limit));
  p.set("offset", String(offset));
  return p;
}

export const parcaApi = {
  depolar: (pasifler = false) => api.get<Depo[]>(`${PARCA_ONEK}/depolar?pasifler=${pasifler}`),
  depoOlustur: (g: DepoGirdisi) => api.post<Depo>(`${PARCA_ONEK}/depolar`, g),
  depoGuncelle: (id: number, g: DepoGirdisi) =>
    api.patch<Depo>(`${PARCA_ONEK}/depolar`, { depo_id: id, ...g }),

  parcalar: (q?: string) =>
    api.get<ParcaSecenegi[]>(`${PARCA_ONEK}/parcalar?${parametreler({ q })}`),
  kartOlustur: (g: KartGirdisi) => api.post<Kart>(`${PARCA_ONEK}/kartlar`, g),
  kartGuncelle: (g: {
    product_id: number;
    version: number;
    yedek_parca?: boolean;
    birim?: string | null;
    min_stok?: number | null;
  }) => api.patch<Kart>(`${PARCA_ONEK}/kartlar`, g),

  stok: (s: StokSuzgeci, limit: number, offset: number) =>
    api.getSayfa<StokSatiri>(`${PARCA_ONEK}/stok?${sayfali(s, limit, offset)}`),
  ozet: () => api.get<StokOzeti>(`${PARCA_ONEK}/stok/ozet`),
  stokExcelYolu: (s: StokSuzgeci) => `${PARCA_ONEK}/stok.xlsx?${parametreler(s)}`,

  hareketler: (s: HareketSuzgeci, limit: number, offset: number) =>
    api.getSayfa<Hareket>(`${PARCA_ONEK}/hareketler?${sayfali(s, limit, offset)}`),
  hareketExcelYolu: (s: HareketSuzgeci) => `${PARCA_ONEK}/hareketler.xlsx?${parametreler(s)}`,

  giris: (g: { depo_id: number; document_no?: string | null; notes?: string | null; satirlar: SatirGirdisi[] }) =>
    api.post<YazilanHareket[]>(`${PARCA_ONEK}/giris`, g),
  cikis: (g: { service_order_id: number; depo_id: number; notes?: string | null; satirlar: SatirGirdisi[] }) =>
    api.post<YazilanHareket[]>(`${PARCA_ONEK}/cikis`, g),
  iade: (g: { service_order_id: number; depo_id: number; notes?: string | null; satirlar: SatirGirdisi[] }) =>
    api.post<YazilanHareket[]>(`${PARCA_ONEK}/iade`, g),
  zayi: (g: { depo_id: number; gerekce: string; satirlar: SatirGirdisi[] }) =>
    api.post<YazilanHareket[]>(`${PARCA_ONEK}/zayi`, g),
  transfer: (g: {
    kaynak_depo_id: number;
    hedef_depo_id: number;
    notes?: string | null;
    satirlar: SatirGirdisi[];
  }) => api.post<{ transfer_grup: string; hareketler: YazilanHareket[] }>(`${PARCA_ONEK}/transfer`, g),
  tersKayit: (hareketId: number, gerekce: string) =>
    api.post<YazilanHareket[]>(`${PARCA_ONEK}/ters-kayit`, { hareket_id: hareketId, gerekce }),
  acilis: (satirlar: AcilisSatiri[]) => api.post<{ yazilan: number }>(`${PARCA_ONEK}/acilis`, { satirlar }),

  isParcalari: (soId: number) => api.get<IsParcalari>(`${PARCA_ONEK}/isler/${soId}/parcalar`),

  talepler: (
    s: { durum?: string; service_order_id?: number; benim?: boolean },
    limit: number,
    offset: number,
  ) => api.getSayfa<Talep>(`${PARCA_ONEK}/talepler?${sayfali(s, limit, offset)}`),
  talepAc: (g: {
    service_order_id: number;
    product_id: number;
    adet: number;
    notes?: string | null;
    isi_beklet?: boolean;
  }) => api.post<Talep>(`${PARCA_ONEK}/talepler`, g),
  talepIptal: (id: number, neden: string) =>
    api.post<Talep>(`${PARCA_ONEK}/talepler/iptal`, { talep_id: id, neden }),

  sayimlar: (durum: string | undefined, limit: number, offset: number) =>
    api.getSayfa<Sayim>(`${PARCA_ONEK}/sayimlar?${sayfali({ durum }, limit, offset)}`),
  sayim: (id: number) => api.get<Sayim>(`${PARCA_ONEK}/sayim?sayim_id=${id}`),
  sayimAc: (depo_id: number, notes?: string | null) =>
    api.post<Sayim>(`${PARCA_ONEK}/sayimlar`, { depo_id, notes }),
  sayimSatirlari: (id: number, satirlar: { product_id: number; sayilan_adet: number | null }[]) =>
    api.put<Sayim>(`${PARCA_ONEK}/sayim/satirlar`, { sayim_id: id, satirlar }),
  sayimOnayla: (id: number, gerekce: string, degisimi_kabul: boolean) =>
    api.post<Sayim>(`${PARCA_ONEK}/sayim/onayla`, { sayim_id: id, gerekce, degisimi_kabul }),
  sayimIptal: (id: number, gerekce: string) =>
    api.post<Sayim>(`${PARCA_ONEK}/sayim/iptal`, { sayim_id: id, gerekce }),
};

/** 409 gövdesindeki makine okunur alanlar (`{detail: {mesaj, sapmalar|hatalar}}`). */
export interface ParcaHataGovdesi {
  mesaj: string;
  sapmalar?: { product_id: number; sistem_adet: number; onay_anindaki_adet: number }[];
  hatalar?: { satir_no: number; hatalar: string[] }[];
}

export function parcaHatasi(e: unknown): ParcaHataGovdesi {
  if (e instanceof ApiError) {
    const detay = (e.govde as { detail?: unknown } | undefined)?.detail;
    if (detay && typeof detay === "object" && !Array.isArray(detay) && "mesaj" in detay) {
      return detay as ParcaHataGovdesi;
    }
    return { mesaj: e.message };
  }
  return { mesaj: e instanceof Error ? e.message : "Beklenmeyen hata" };
}
