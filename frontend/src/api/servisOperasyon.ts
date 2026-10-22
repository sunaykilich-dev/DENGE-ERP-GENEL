/**
 * Operasyon Merkezi ve SLA — API tipleri ve çağrıları (TS-081…085).
 *
 * Sunucu: `backend/app/api/servis_operasyon.py`.
 *
 * KURAL: SLA durumu, kalan süre, hedef ve vade YALNIZ sunucudan gelir
 * (`sla` bloğu). Ön yüz öncelikten saat/hedef HESAPLAMAZ; yalnız sunucunun
 * verdiği dakikayı okunur metne çevirir (grep testi:
 * `backend/tests/unit/test_on_yuz_sla_hesabi_yok.py`).
 */
import { api } from "./client";

export const OPERASYON_ONEK = "/api/teknik-servis/operasyon";
const SLA_TANIM = "/api/teknik-servis/sla-tanimlari";

export interface KodAd {
  kod: string;
  ad: string;
}

/** Sunucunun hesapladığı SLA bloğu (detay, liste, Benim İşlerim aynı şekil). */
export interface SlaBlogu {
  durum: string;
  ad: string;
  olculur: boolean;
  hedef_at: string | null;
  ilk_hedef_at: string | null;
  kalan_dk: number | null;
  mudahale_durumu: string | null;
  mudahale_hedef_at: string | null;
  ilk_mudahale_at: string | null;
  durdurulan_dk: number | null;
  sonuc: string | null;
  kaynak: string | null;
  gecikme_nedeni: string | null;
  vade: string | null;
  vade_ay: string | null;
}

export interface OperasyonSayaci {
  kod: string;
  baslik: string;
  tanim: string;
  deger: number;
  yol: string;
  grup: string;
  vurgu: "normal" | "uyari" | "kritik";
}

export interface OperasyonOzeti {
  sunucu_zamani: string;
  birim: string | null;
  oncelik: string | null;
  risk_yuzde: number;
  sayaclar: OperasyonSayaci[];
}

export interface OperasyonSatiri {
  id: number;
  so_no: string;
  birim: string;
  tur: string;
  kategori: string;
  status: string;
  oncelik: string;
  konu: string;
  musteri: { id: number; title: string } | null;
  customer_name_raw: string | null;
  sorumlu: { id: number; ad: string } | null;
  ekip_sayisi: number;
  aktif_bekleme: string | null;
  created_at: string;
  tekrar_ariza_aday: boolean;
  sla: SlaBlogu;
  version: number;
}

export interface PersonelYuku {
  user_id: number;
  ad: string;
  saha_rolu: string | null;
  birimler: string[];
  acik_sayac: {
    service_order_id: number | null;
    so_no: string;
    faaliyet: string;
    started_at: string;
  } | null;
  bugun_planli: number;
  yarin_planli: number;
  acik_atanmis: number;
  /** Yalnız `servis_rapor.personel` izniyle gelir; `null` = kayıt yok (eksik), 0 değil. */
  bugun_calisilan_dk?: number | null;
}

export interface PersonelYukuYaniti {
  sunucu_zamani: string;
  kisi_saat_gorunur: boolean;
  personel: PersonelYuku[];
}

export interface Bildirim {
  id: number;
  kod: string;
  kod_adi: string;
  onem: "BILGI" | "UYARI" | "KRITIK";
  baslik: string;
  service_order_id: number;
  so_no: string;
  birim: string;
  acilis_at: string;
  kapanis_at: string | null;
  kapanis_nedeni: string | null;
  goruldu: boolean;
}

export interface IsSlaKarti {
  id: number;
  so_no: string;
  status: string;
  oncelik: string;
  version: number;
  sla: SlaBlogu;
  gecikme_nedeni: string | null;
  gecikme_aciklama: string | null;
  tekrar_ariza: {
    aday: boolean;
    teyit: string | null;
    bagli_is: { id: number | null; so_no: string; kapsam_disi: boolean } | null;
  };
  kapanis_icin_gerekenler: string[];
}

export interface KapanisBilgisi {
  version?: number;
  gecikme_nedeni?: string | null;
  gecikme_aciklama?: string | null;
  tekrar_ariza_teyit?: string | null;
}

export interface SlaSozlugu {
  sla_durumlari: KodAd[];
  mudahale_durumlari: KodAd[];
  gecikme_nedenleri: KodAd[];
  tekrar_ariza_teyitleri: KodAd[];
  bildirim_kodlari: KodAd[];
  oncelikler: string[];
  terimler: Record<string, string>;
  birimler: KodAd[];
  yururluk_at: string | null;
  sla_yururlukte: boolean;
  risk_yuzde: number;
  tekrar_ariza_gun: number;
  operasyon_sayaclari: string[];
}

export interface SlaPolitikasi {
  id: number;
  oncelik: string;
  birim: string | null;
  birim_adi: string;
  cozum_saat: number;
  mudahale_saat: number | null;
  takvim_turu: string;
  is_active: boolean;
  version: number;
  updated_at: string;
}

export interface PolitikaGirdisi {
  id?: number;
  version?: number;
  oncelik: string;
  birim?: string | null;
  cozum_saat: number;
  mudahale_saat?: number | null;
  takvim_turu?: string;
  is_active: boolean;
}

export interface OperasyonSuzgeci {
  kpi?: string;
  birim?: string;
  oncelik?: string;
  teknisyen_id?: number;
}

function parametreler(s: OperasyonSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  if (s.kpi) p.set("kpi", s.kpi);
  if (s.birim) p.set("birim", s.birim);
  if (s.oncelik) p.set("oncelik", s.oncelik);
  if (s.teknisyen_id) p.set("teknisyen_id", String(s.teknisyen_id));
  return p;
}

export const operasyonApi = {
  ozet: (s: OperasyonSuzgeci) => api.get<OperasyonOzeti>(`${OPERASYON_ONEK}/ozet?${parametreler(s)}`),
  isler: (s: OperasyonSuzgeci, limit: number, offset: number) => {
    const p = parametreler(s);
    p.set("limit", String(limit));
    p.set("offset", String(offset));
    return api.getSayfa<OperasyonSatiri>(`${OPERASYON_ONEK}/isler?${p}`);
  },
  personel: (birim?: string) =>
    api.get<PersonelYukuYaniti>(
      `${OPERASYON_ONEK}/personel${birim ? `?birim=${encodeURIComponent(birim)}` : ""}`,
    ),
  bildirimler: (acik: boolean, limit: number, offset: number, kod?: string) => {
    const p = new URLSearchParams({ acik: String(acik), limit: String(limit), offset: String(offset) });
    if (kod) p.set("kod", kod);
    return api.getSayfa<Bildirim>(`${OPERASYON_ONEK}/bildirimler?${p}`);
  },
  goruldu: (bildirim_idler: number[]) =>
    api.post<{ isaretlenen: number; zaten_goruldu: number }>(`${OPERASYON_ONEK}/bildirimler/goruldu`, {
      bildirim_idler,
    }),
  isSla: (soId: number) => api.get<IsSlaKarti>(`${OPERASYON_ONEK}/isler/${soId}/sla`),
  kapanisBilgisi: (soId: number, g: KapanisBilgisi) =>
    api.put<IsSlaKarti>(`${OPERASYON_ONEK}/isler/${soId}/kapanis-bilgisi`, g),
  sozluk: () => api.get<SlaSozlugu>(`${SLA_TANIM}/sozluk`),
  politikalar: () => api.get<SlaPolitikasi[]>(`${SLA_TANIM}/politikalar`),
  politikaKaydet: (g: PolitikaGirdisi) => api.put<SlaPolitikasi>(`${SLA_TANIM}/politikalar`, g),
};

/** SLA durumu → AntD Tag rengi (yalnız görünüm). */
export const SLA_RENKLERI: Record<string, string> = {
  ZAMANINDA: "green",
  RISKTE: "gold",
  ASILDI: "red",
  DURDURULDU: "blue",
  KARSILANDI: "green",
  KARSILANMADI: "volcano",
  OLCULEMEDI: "default",
  SLA_DISI_PB: "purple",
};

/** Sunucunun verdiği dakikayı okunur metne çevirir ("3 sa 20 dk"). Hesap değil, biçim. */
export function sureMetni(dakika: number): string {
  const mutlak = Math.abs(dakika);
  const gun = Math.floor(mutlak / 1440);
  const saat = Math.floor((mutlak % 1440) / 60);
  const dk = mutlak % 60;
  const parca: string[] = [];
  if (gun) parca.push(`${gun} gün`);
  if (saat) parca.push(`${saat} sa`);
  if (dk || parca.length === 0) parca.push(`${dk} dk`);
  return parca.join(" ");
}
