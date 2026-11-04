/**
 * Ana Panel (master dashboard) — API tipleri ve çağrısı (KARARLAR 2026-11-04 §4).
 *
 * Sunucu: `backend/app/api/ana_panel.py`, iş kuralı
 * `backend/app/services/teknik_servis/ana_panel.py`.
 *
 * KURAL "sayı = liste": kartlardaki sayılar sunucudan gelir ve `liste_yolu`
 * aynı süzgeçle açılan listenin toplamıdır; ön yüz sayı HESAPLAMAZ (yalnız
 * grafik oranlarını çizer). SLA durumu/kalan süre de yalnız sunucudan gelir.
 */
import { api } from "./client";

const TS = "/api/teknik-servis";

export interface AnaPanelSuzgeci {
  birim?: string;
  durum_grubu?: string;
  sef_id?: number;
  personel_id?: number;
  lokasyon_id?: number;
  /** YYYY-AA-GG; dönem başı (varsayılan: bu ayın 1'i). */
  bas?: string;
  /** YYYY-AA-GG; dönem sonu (varsayılan: bugün). */
  bit?: string;
}

export interface AnaPanelKpi {
  kod: string;
  ad: string;
  tanim: string | null;
  deger: number;
  /** Yalnız "sahadaki ekip": aktif / toplam. */
  toplam: number | null;
  onceki_deger: number | null;
  degisim_yuzde: number | null;
  /** "dönem başına göre" | "hedefe göre" | null */
  karsilastirma: string | null;
  vurgu: string;
  /** Tıklanınca açılan liste; null = tıklanamaz. */
  liste_yolu: string | null;
}

export interface BirimOzeti {
  birim: string;
  ad: string;
  acik: number;
  sahada: number;
  atolyede: number;
  tamamlanan: number;
  donem_is_emri: number;
  tamamlanma_yuzde: number | null;
  yollar: Record<"acik" | "sahada" | "atolyede" | "tamamlanan" | "donem_is_emri", string>;
}

export interface KisiAdi {
  id: number;
  ad: string | null;
  sorumlu: boolean;
}

export interface AktifIs {
  id: number;
  no: string;
  tur: string;
  tur_adi: string;
  birim: string;
  birim_adi: string;
  ekipman: string | null;
  alt_sistem: string | null;
  musteri: string | null;
  lokasyon: string | null;
  tayin_edilen_sef: KisiAdi[];
  tayin_edilen_personel: KisiAdi[];
  arac: string | null;
  durum: string;
  durum_adi: string;
  oncelik: string;
  son_guncelleme: string;
  sla: { durum: string | null; ad: string | null; kalan_dk: number | null; olculur: boolean };
  yol: string;
}

export interface EkipSatiri {
  user_id: number;
  ad: string | null;
  saha_rolu: string | null;
  birimler: string[];
  /** SAHADA | UZAKTAN | ATOLYEDE | MUSAIT | IZINLI */
  durum: string;
  durum_adi: string;
  is_: { id: number | null; no: string; lokasyon: string | null } | null;
  aciklama: string | null;
  sure_dk: number | null;
}

export interface BekleyenAksiyon {
  kayit_id: number;
  kayit_no: string;
  aciklama: string | null;
  kaynak_birim: string;
  hedef_birim: string;
  bekleme_baslangic: string | null;
  bekleme_dk: number | null;
  yol: string;
}

export interface GrafikDilimi {
  kod: string;
  ad: string;
  deger: number;
  liste_yolu: string | null;
}

export interface AnaPanelYaniti {
  guncelleme_zamani: string;
  donem: { bas: string; bit: string; aralik: string };
  suzgec: AnaPanelSuzgeci;
  kpiler: AnaPanelKpi[];
  birim_ozeti: BirimOzeti[];
  aktif_isler: { satirlar: AktifIs[]; liste_yolu: string };
  ekip_durumu: {
    gorunur: boolean;
    satirlar: EkipSatiri[];
    ozet: { durum: string; ad: string; adet: number }[];
    liste_yolu: string | null;
  };
  bekleyen_aksiyonlar: {
    satirlar: BekleyenAksiyon[];
    ozet: { hedef_birim: string; adet: number }[];
    toplam: number;
  };
  grafikler: {
    durum_dagilimi: GrafikDilimi[];
    acik_toplam: number;
    bolum_is_yuku: { birim: string; ad: string; deger: number; liste_yolu: string }[];
    planli_bakim: {
      toplam: number;
      tamamlanan: number;
      yuzde: number | null;
      parcalar: GrafikDilimi[];
      liste_yolu: string;
    };
    haftalik_plan: { tarih: string; gun_adi: string; adet: number; bugun: boolean; liste_yolu: string }[];
    aylik_bakim: {
      ay: string;
      planlanan: number;
      tamamlanan: number;
      kalan: number;
      yuzde: number | null;
      yaklasan: { tarih: string; id: number; no: string; musteri: string | null; aciklama: string | null; yol: string }[];
    };
  };
  secenekler: {
    birimler: { kod: string; ad: string }[];
    durum_gruplari: { kod: string; ad: string }[];
    sefler: { id: number; ad: string | null }[];
    personel: { id: number; ad: string | null }[];
    lokasyonlar: { id: number; ad: string | null }[];
  };
}

/** Boş/undefined alanları atlayan sorgu dizgesi (sorgu anahtarı ile aynı süzgeç). */
export function anaPanelParametreleri(s: AnaPanelSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  return p;
}

export const anaPanelApi = {
  getir: (s: AnaPanelSuzgeci) => {
    const p = anaPanelParametreleri(s).toString();
    return api.get<AnaPanelYaniti>(`${TS}/ana-panel${p ? `?${p}` : ""}`);
  },
};
