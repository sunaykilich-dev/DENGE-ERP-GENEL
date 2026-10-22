/**
 * Servis raporları API istemcisi (`/api/teknik-servis/raporlar`) — TS-181…187, TS-201.
 *
 * KURAL: KPI sayısı, oran, kişi-saat ve SLA uyumu YALNIZ sunucudan gelir;
 * istemci hesaplamaz. Kutu tıklanınca açılan liste (`/kpi-liste?kpi=`) aynı
 * sunucu süzgecinden gelir (sayı = liste `X-Toplam-Kayit`).
 */
import { api, type Sayfa } from "./client";

export const SERVIS_RAPORLARI_KOK = "/api/teknik-servis/raporlar";

/** Rapor filtresi — URL sorgusunda taşınır (paylaşılabilir bağlantı). */
export interface RaporFiltresiDegeri {
  baslangic?: string;
  bitis?: string;
  tarih_esasi?: string;
  kategori?: string[];
  birim?: string[];
  durum_grubu?: string[];
  tur?: string[];
  oncelik?: string[];
  musteri_id?: number;
  sef_id?: number;
  teknisyen_id?: number;
  sehir?: string;
  tekrar_gun?: number;
}

const LISTE_ALANLARI = ["kategori", "birim", "durum_grubu", "tur", "oncelik"] as const;
const TEKIL_ALANLAR = [
  "baslangic",
  "bitis",
  "tarih_esasi",
  "musteri_id",
  "sef_id",
  "teknisyen_id",
  "sehir",
  "tekrar_gun",
] as const;

export function filtreSorgusu(f: RaporFiltresiDegeri, ek: Record<string, string | number> = {}) {
  const p = new URLSearchParams();
  for (const ad of TEKIL_ALANLAR) {
    const v = f[ad];
    if (v !== undefined && v !== null && v !== "") p.set(ad, String(v));
  }
  for (const ad of LISTE_ALANLARI) for (const v of f[ad] ?? []) p.append(ad, v);
  for (const [k, v] of Object.entries(ek)) p.set(k, String(v));
  return p;
}

export function filtreOku(p: URLSearchParams): RaporFiltresiDegeri {
  const sayi = (ad: string) => (p.get(ad) ? Number(p.get(ad)) : undefined);
  const liste = (ad: string) => (p.getAll(ad).length ? p.getAll(ad) : undefined);
  return {
    baslangic: p.get("baslangic") ?? undefined,
    bitis: p.get("bitis") ?? undefined,
    tarih_esasi: p.get("tarih_esasi") ?? undefined,
    kategori: liste("kategori"),
    birim: liste("birim"),
    durum_grubu: liste("durum_grubu"),
    tur: liste("tur"),
    oncelik: liste("oncelik"),
    musteri_id: sayi("musteri_id"),
    sef_id: sayi("sef_id"),
    teknisyen_id: sayi("teknisyen_id"),
    sehir: p.get("sehir") ?? undefined,
    tekrar_gun: sayi("tekrar_gun"),
  };
}

export interface KodAd {
  kod: string;
  ad: string;
}

export interface RaporKpi {
  kod: string;
  baslik: string;
  tanim: string;
  bolum: string;
  olcu_birimi: string;
  vurgu: "normal" | "uyari" | "kritik";
  deger: number;
  onceki: number | null;
  fark: number | null;
  fark_yuzde: number | null;
  kpi: string;
  /** Servis İşleri ekranında aynı listeyi açan yol (süzgeç taşınabiliyorsa). */
  isler_yolu: string | null;
}

export interface RaporOlcumu {
  kod: string;
  baslik: string;
  tanim: string;
  olcu_birimi: "yuzde" | "saat" | "kisi_saat";
  deger: number | null;
  onceki: number | null;
  fark: number | null;
  fark_yuzde: number | null;
  pay: string | null;
  payda: string | null;
  eksik: number | null;
}

export interface DonemBilgisi {
  baslangic: string;
  bitis: string;
  donem: string;
}

export interface RaporOzeti {
  generated_at: string;
  kapsam: string;
  donem: DonemBilgisi;
  onceki_donem: DonemBilgisi;
  bolumler: KodAd[];
  kpiler: RaporKpi[];
  olcumler: RaporOlcumu[];
  toplamlar: {
    toplam: number;
    acik: number;
    cozuldu: number;
    iptal: number;
    tanimsiz: number;
    esit: boolean;
  };
  kategoriler: { kategori: string; ad: string; gelen: number; cozulen: number; donem_sonu_acik: number }[];
  eksik_veri_is: number;
  gecmis_degisebilir: boolean;
}

export interface Tanimlar {
  bolumler: KodAd[];
  kpiler: { kod: string; baslik: string; tanim: string; bolum: string }[];
  olculer: { kod: string; baslik: string; tanim: string; olcu_birimi: string }[];
  tarih_esaslari: KodAd[];
  boyutlar: { kod: string; ad: string; kisisel: boolean }[];
  notlar: string[];
}

export interface KirilimSatiri {
  anahtar: string;
  ad: string;
  ikinci_ad?: string | null;
  toplam: number;
  acik: number;
  cozuldu: number;
  iptal: number;
  beklemede: number;
  kritik: number;
  sure_eksik: number;
  kisi_saat: number | null;
  musteri?: string | null;
  sehir?: string | null;
}

export interface Kirilim {
  boyut: string;
  boyut_adi: string;
  satirlar: KirilimSatiri[];
  toplam: number;
  toplam_esit: boolean | null;
}

export interface KpiIsSatiri {
  id: number;
  so_no: string;
  birim_adi: string;
  kategori_adi: string;
  tur_adi: string;
  oncelik: string;
  durum_adi: string;
  musteri: string | null;
  lokasyon: string | null;
  sehir: string | null;
  konu: string;
  acilis: string;
  tamamlanma: string | null;
  kapanis: string | null;
  yol: string;
}

export interface PersonelSatiri {
  user_id: number | null;
  personel: string;
  kisi_saat: number | null;
  farkli_is: number | null;
  kayit: number;
  SAHA: number | null;
  YOL: number | null;
  BEKLEME: number | null;
  UZAKTAN: number | null;
  ATOLYE: number | null;
  TEST: number | null;
  DIGER: number | null;
  not: string | null;
}

export interface KisiSaat {
  satirlar: PersonelSatiri[];
  toplam: { toplam_saat: number | null; farkli_is: number; kayit: number };
}

export interface BasitKpi {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number;
  kpi: string;
  isler_yolu: string | null;
}

export interface SlaRaporu {
  kpiler: BasitKpi[];
  uyum_yuzde: number | null;
  olculen: number;
  geciken_acik: number | null;
  cozum_suresi: { ortalama_saat: number | null; medyan_saat: number | null; olculen: number };
  gecikme_nedenleri: { kod: string | null; ad: string; adet: number }[];
  oncelik_kirilimi: {
    oncelik: string;
    ad: string;
    zamaninda: number;
    asildi: number;
    olculemedi: number;
    damgasiz: number;
    uyum_yuzde: number | null;
  }[];
  bekleme_nedenleri: {
    kod: string;
    ad: string;
    adet: number;
    toplam_saat: number | null;
    sla_durdurur: boolean;
  }[];
}

export interface TekrarArizaRaporu {
  gun: number;
  kpiler: BasitKpi[];
  onayli_oran: number | null;
  aday_oran: number | null;
  satirlar: {
    id: number;
    so_no: string;
    birim: string;
    kategori: string;
    cozum: string | null;
    etiket: string;
    sonraki_isler: string[];
  }[];
}

export interface YenidenAcilanRaporu {
  ilk_cozulen: number;
  yeniden_acilan: number;
  yeniden_acilan_pb: number;
  oran: number | null;
  olay_sayisi: number;
  olaylar: {
    id: number;
    so_no: string;
    kategori: string;
    pb: boolean;
    ilk_cozum: string | null;
    yeniden_acilis: string;
    gun_farki: number | null;
    gerekce: string | null;
  }[];
}

export interface TrendSatiri {
  ay: string;
  ay_adi: string;
  donem: string;
  gelen: number;
  cozulen: number;
  iptal: number;
  donem_sonu_acik: number;
  kisi_saat: number | null;
}

const yol = (uc: string, f: RaporFiltresiDegeri, ek: Record<string, string | number> = {}) =>
  `${SERVIS_RAPORLARI_KOK}/${uc}?${filtreSorgusu(f, ek).toString()}`;

export const servisRaporlariApi = {
  tanimlar: () => api.get<Tanimlar>(`${SERVIS_RAPORLARI_KOK}/tanimlar`),
  ozet: (f: RaporFiltresiDegeri) => api.get<RaporOzeti>(yol("ozet", f)),
  kirilim: (f: RaporFiltresiDegeri, boyut: string) => api.get<Kirilim>(yol("kirilim", f, { boyut })),
  kpiListe: (f: RaporFiltresiDegeri, kpi: string, limit: number, offset: number): Promise<Sayfa<KpiIsSatiri>> =>
    api.getSayfa<KpiIsSatiri>(yol("kpi-liste", f, { kpi, limit, offset })),
  kisiSaat: (f: RaporFiltresiDegeri) => api.get<KisiSaat>(yol("kisi-saat", f)),
  sla: (f: RaporFiltresiDegeri) => api.get<SlaRaporu>(yol("sla", f)),
  tekrarAriza: (f: RaporFiltresiDegeri) => api.get<TekrarArizaRaporu>(yol("tekrar-ariza", f)),
  yenidenAcilan: (f: RaporFiltresiDegeri) => api.get<YenidenAcilanRaporu>(yol("yeniden-acilan", f)),
  trend: (f: RaporFiltresiDegeri) =>
    api.get<{ satirlar: TrendSatiri[]; gecmis_degisebilir: boolean }>(yol("trend", f)),
  /** Excel kitabı adresi (`window.open`; sunucu denetime yazar). */
  kitapAdresi: (f: RaporFiltresiDegeri) => yol("kitap.xlsx", f),
};
