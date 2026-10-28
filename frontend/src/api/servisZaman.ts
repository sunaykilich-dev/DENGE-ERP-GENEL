/**
 * Saha zaman kaydı ve Benim İşlerim — API tipleri ve çağrıları (TS-070…078).
 *
 * Sözleşme: `backend/app/api/servis_zaman.py` Pydantic şemaları.
 *
 * **Sunucu saati tek kaynaktır** (E09-16): her zaman yanıtı `sunucu_zamani`
 * taşır; `saatFarkiniGuncelle` istemci ile sunucu arasındaki farkı saklar ve
 * geçen süre / 5 dk geri alma sayacı bu farkla hesaplanır. Telefon saati
 * 10 dk ileri olsa da bant doğru süreyi gösterir.
 *
 * Bölüm uçları iş altındadır (`/isler/{is_id}/zaman/bolumler/{bolum_id}/…`)
 * ve her eylem `version` ister: çift basışta ikinci istek 409 alır.
 */
import { api, type Sayfa } from "./client";
import type { SlaBlogu } from "./servisOperasyon";

const TS = "/api/teknik-servis";

export type Faaliyet =
  | "YOL"
  | "SAHA"
  | "UZAKTAN"
  | "ATOLYE"
  | "TEST"
  | "BEKLEME"
  | "MOLA"
  | "DIGER";

export const FAALIYET_ADLARI: Record<Faaliyet, string> = {
  YOL: "Yol",
  SAHA: "Saha",
  UZAKTAN: "Uzaktan",
  ATOLYE: "Atölye",
  TEST: "Test",
  BEKLEME: "Bekleme",
  MOLA: "Mola",
  DIGER: "Diğer",
};

/** Bekleme nedeni — iş bekleme kataloğuyla aynı kodlar (K24). */
export const BEKLEME_NEDENLERI: { kod: string; ad: string }[] = [
  { kod: "MALZEME", ad: "Malzeme bekleniyor" },
  { kod: "MUSTERI_ONAYI", ad: "Müşteri onayı bekleniyor" },
  { kod: "TEKLIF", ad: "Teklif onayı bekleniyor" },
  { kod: "MUSTERI_ERISIMI", ad: "Müşteri/saha erişimi yok" },
  { kod: "PERSONEL", ad: "Personel bekleniyor" },
  { kod: "DIS_SERVIS", ad: "Dış servis/üretici bekleniyor" },
  { kod: "DIGER", ad: "Diğer" },
];

export const SURE_DURUMU_ADLARI: Record<string, string> = {
  TAM: "Tam",
  KISMI: "Kısmi",
  EKSIK: "Süre kaydı eksik",
  BEKLENMIYOR: "Beklenmiyor",
};

export type Dugme =
  | "YOLA_CIKTIM"
  | "SAHAYA_VARDIM"
  | "DIGER"
  | "MOLA"
  | "BEKLEME"
  | "DEVAM"
  | "SONRAKI_ISE_GEC"
  | "DEGISTIR"
  | "BITIR"
  | "UNUTTUM"
  | "GERI_AL";

export interface AcikBolum {
  id: number;
  version: number;
  service_order_id: number;
  so_no: string | null;
  faaliyet: Faaliyet;
  bekleme_nedeni: string | null;
  started_at: string;
}

export interface BenimSayacim {
  sunucu_zamani: string;
  acik_bolum: AcikBolum | null;
  izinli_dugmeler: Dugme[];
  geri_alma_bitis: string | null;
  uzun_sayac: boolean;
}

export interface Bolum {
  id: number;
  version: number;
  service_order_id: number;
  so_no: string | null;
  user_id: number | null;
  kisi_adi: string | null;
  faaliyet: Faaliyet;
  bekleme_nedeni: string | null;
  started_at: string;
  ended_at: string | null;
  sure_dk: number | null;
  kaynak: "CANLI" | "MANUEL" | "KULLANICI_DUZELTMESI" | "YONETICI_DUZELTMESI";
  kapanis_turu: string | null;
  gerekce: string | null;
  onceki_bolum_id: number | null;
  girildi_at: string;
  giren_id: number | null;
  giren_adi: string | null;
  konum_notu: string | null;
  aciklama: string | null;
  iptal_turu: string | null;
  iptal_gerekcesi: string | null;
  iptal_eden_id: number | null;
  iptal_at: string | null;
  iptal: boolean;
  /** G7.8: iş başlat/bitir konumu; koordinat yalnız sahibi/planlayıcıya gelir. */
  bas_konum?: KonumBilgisi | null;
  bit_konum?: KonumBilgisi | null;
}

export interface KonumBilgisi {
  durum: "ALINDI" | "ALINAMADI";
  /** "Konum alındı" / "Konum bilgisi alınamadı" (sunucu metni). */
  metin: string;
  enlem?: number | null;
  boylam?: number | null;
  dogruluk_m?: number | null;
}

/** Sunucuya giden konum okuması; koordinatsız = "alınamadı". */
export interface KonumOkumasi {
  enlem?: number;
  boylam?: number;
  dogruluk_m?: number;
  hata?: string;
}

/**
 * İş başlat/bitir anında konumu okur (G7.8). Kısa zaman aşımı; izin reddi,
 * zaman aşımı ya da tarayıcı desteği yoksa `{hata}` döner — işlem ASLA
 * engellenmez, sunucu "Konum bilgisi alınamadı" yazar. Sürekli izleme yok.
 */
export function konumAl(zamanAsimiMs = 5000): Promise<KonumOkumasi> {
  return new Promise((coz) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      coz({ hata: "DESTEK_YOK" });
      return;
    }
    let bitti = false;
    // Tarayıcı izin penceresinde beklerse de işlem bekletilmez.
    const yedek = window.setTimeout(() => {
      if (!bitti) {
        bitti = true;
        coz({ hata: "ZAMAN_ASIMI" });
      }
    }, zamanAsimiMs + 500);
    try {
      navigator.geolocation.getCurrentPosition(
        (p) => {
          if (bitti) return;
          bitti = true;
          window.clearTimeout(yedek);
          coz({ enlem: p.coords.latitude, boylam: p.coords.longitude, dogruluk_m: p.coords.accuracy });
        },
        (e) => {
          if (bitti) return;
          bitti = true;
          window.clearTimeout(yedek);
          coz({ hata: e.code === 1 ? "IZIN_YOK" : e.code === 3 ? "ZAMAN_ASIMI" : "ALINAMADI" });
        },
        { enableHighAccuracy: true, timeout: zamanAsimiMs, maximumAge: 60_000 },
      );
    } catch {
      bitti = true;
      window.clearTimeout(yedek);
      coz({ hata: "ALINAMADI" });
    }
  });
}

export interface BolumSonucu {
  sunucu_zamani: string;
  bolum: Bolum;
  yeni_bolum: Bolum | null;
  is_durumu: string | null;
}

export interface SureOzeti {
  /** Kayıt yoksa `null` — "Süre kaydı eksik" yazılır, 0 DEĞİL. */
  kisi_saat_dk: number | null;
  sure_durumu: "TAM" | "KISMI" | "EKSIK" | "BEKLENMIYOR";
  eksik_kisiler: string[];
  mola_dk: number | null;
  faaliyet_kirilimi?: Record<string, number>;
  kisi_bazli?: Record<string, number>;
  ilk_yol_at?: string | null;
  ilk_varis_at?: string | null;
  son_bitis_at?: string | null;
  sapma_dk?: number | null;
  acik_bolum_sayisi?: number;
}

export interface IsZamani {
  sunucu_zamani: string;
  bolumler: Bolum[];
  sure_ozeti: SureOzeti;
}

export interface MobilIs {
  id: number;
  so_no: string;
  tur: string;
  birim: string;
  durum: string;
  oncelik: string;
  konu: string;
  plan_baslangic: string | null;
  plan_sure_dk: number | null;
  bana_atanmis: boolean;
  sayac_acilabilir: boolean;
  kisi_saat_dk: number | null;
  sure_durumu: string | null;
  /** Sunucunun SLA bloğu (TS-085); ekran hesaplamaz, yalnız gösterir. */
  sla?: SlaBlogu | null;
}

/** "İş beklemesi" / "personel beklemesi" gibi ekran başlıkları (sunucudan, TS-085). */
export type SlaTerimleri = Record<string, string>;

export interface Ziyaret {
  anahtar: string;
  plan_tarihi: string | null;
  musteri: string | null;
  lokasyon: string | null;
  il: string | null;
  ilce: string | null;
  isler: MobilIs[];
}

export interface IsGrubu {
  kod: "GECIKEN" | "BUGUN" | "YARIN" | "SONRA" | "PLANSIZ";
  baslik: string;
  ziyaretler: Ziyaret[];
}

export interface BenimIslerim extends BenimSayacim {
  bugun: string;
  gorunum: "benim" | "tumu";
  kesildi: boolean;
  gruplar: IsGrubu[];
}

export interface MobilKart extends Omit<BenimSayacim, "sunucu_zamani"> {
  sunucu_zamani: string;
  sla?: SlaBlogu | null;
  terimler?: SlaTerimleri;
  id: number;
  so_no: string;
  tur: string;
  birim: string;
  durum: string;
  oncelik: string;
  konu: string;
  aciklama: string | null;
  musteri: string | null;
  lokasyon: string | null;
  adres: string | null;
  il: string | null;
  ilce: string | null;
  ulasim_notu: string | null;
  irtibat_ad: string | null;
  irtibat_telefon: string | null;
  telefon_maskeli: boolean;
  seriler: string[];
  equipment_id: number | null;
  bakim_formu: boolean;
  plan: {
    plan_tarihi: string;
    baslangic: string | null;
    sure_dk: number;
    plan_notu: string | null;
    saha_alani: string | null;
    saha_notu: string | null;
  } | null;
  bana_atanmis: boolean;
  sayac_acilabilir: boolean;
  sure_ozeti: SureOzeti;
  acik_bolum_bu_iste: boolean;
}

export interface Bugunum {
  sunucu_zamani: string;
  gun: string;
  bolumler: {
    id: number;
    service_order_id: number;
    so_no: string;
    faaliyet: Faaliyet;
    started_at: string;
    ended_at: string | null;
    sure_dk: number | null;
    kaynak: string;
    iptal_turu: string | null;
  }[];
  kisi_saat_dk: number | null;
  faaliyet_dk: Record<string, number>;
  mola_dk: number | null;
  sure_eksik_isler: { id: number; so_no: string; durum: string; konu: string }[];
}

// --- Sunucu saati farkı -------------------------------------------------------------

let saatFarkiMs = 0;

/** Yanıttaki `sunucu_zamani` ile istemci saati arasındaki farkı saklar. */
export function saatFarkiniGuncelle(sunucuZamani: string | undefined | null): void {
  if (!sunucuZamani) return;
  const t = Date.parse(sunucuZamani);
  if (!Number.isNaN(t)) saatFarkiMs = t - Date.now();
}

/** Sunucu saatine göre "şimdi" (ms). */
export function sunucuSimdi(): number {
  return Date.now() + saatFarkiMs;
}

/** "1 sa 05 dk" biçimi; null → null (çağıran "Süre kaydı eksik" yazar). */
export function sureMetni(dk: number | null | undefined): string | null {
  if (dk === null || dk === undefined) return null;
  const sa = Math.floor(dk / 60);
  const kalan = dk % 60;
  return sa > 0 ? `${sa} sa ${String(kalan).padStart(2, "0")} dk` : `${kalan} dk`;
}

/** Geçen süre "SS:DD:ss" — sunucu saatine göre. */
export function gecenSure(baslangic: string): string {
  const fark = Math.max(0, Math.floor((sunucuSimdi() - Date.parse(baslangic)) / 1000));
  const sa = Math.floor(fark / 3600);
  const dk = Math.floor((fark % 3600) / 60);
  const sn = fark % 60;
  return `${String(sa).padStart(2, "0")}:${String(dk).padStart(2, "0")}:${String(sn).padStart(2, "0")}`;
}

async function zamanli<T extends { sunucu_zamani?: string }>(p: Promise<T>): Promise<T> {
  const sonuc = await p;
  saatFarkiniGuncelle(sonuc?.sunucu_zamani);
  return sonuc;
}

const bolumYolu = (isId: number, bolumId: number, eylem: string) =>
  `${TS}/isler/${isId}/zaman/bolumler/${bolumId}/${eylem}`;

export const servisZaman = {
  benim: () => zamanli(api.get<BenimSayacim>(`${TS}/zaman/benim`)),
  bugunum: (gun?: string) =>
    zamanli(api.get<Bugunum>(`${TS}/zaman/bugunum${gun ? `?gun=${gun}` : ""}`)),
  benimIslerim: (gorunum: "benim" | "tumu" = "benim") =>
    zamanli(api.get<BenimIslerim>(`${TS}/benim-islerim?gorunum=${gorunum}`)),
  kart: (isId: number) => zamanli(api.get<MobilKart>(`${TS}/benim-islerim/${isId}`)),
  isZamani: (isId: number) => zamanli(api.get<IsZamani>(`${TS}/isler/${isId}/zaman`)),

  baslat: (govde: {
    is_id: number;
    eylem: "YOLA_CIKTIM" | "SAHAYA_VARDIM" | "DIGER";
    faaliyet?: Faaliyet;
    bekleme_nedeni?: string;
    konum_notu?: string;
  }) =>
    konumAl().then((konum) => zamanli(api.post<BolumSonucu>(`${TS}/zaman/baslat`, { ...govde, konum }))),
  gecis: (
    b: AcikBolum,
    govde: { faaliyet: Faaliyet; bekleme_nedeni?: string; hedef_is_id?: number },
  ) =>
    konumAl().then((konum) =>
      zamanli(
        api.post<BolumSonucu>(bolumYolu(b.service_order_id, b.id, "gecis"), {
          version: b.version,
          ...govde,
          konum,
        }),
      ),
    ),
  mola: (b: AcikBolum) =>
    konumAl().then((konum) =>
      zamanli(
        api.post<BolumSonucu>(bolumYolu(b.service_order_id, b.id, "mola"), { version: b.version, konum }),
      ),
    ),
  devam: (b: AcikBolum) =>
    konumAl().then((konum) =>
      zamanli(
        api.post<BolumSonucu>(bolumYolu(b.service_order_id, b.id, "devam"), { version: b.version, konum }),
      ),
    ),
  bitir: (b: AcikBolum, aciklama?: string) =>
    konumAl().then((konum) =>
      zamanli(
        api.post<BolumSonucu>(bolumYolu(b.service_order_id, b.id, "bitir"), {
          version: b.version,
          aciklama,
          konum,
        }),
      ),
    ),
  geriAl: (b: AcikBolum) =>
    zamanli(
      api.post<BolumSonucu>(bolumYolu(b.service_order_id, b.id, "geri-al"), { version: b.version }),
    ),
  unuttum: (b: AcikBolum, gercekBitis: string, gerekce: string) =>
    zamanli(
      api.post<BolumSonucu>(bolumYolu(b.service_order_id, b.id, "unuttum"), {
        version: b.version,
        gercek_bitis: gercekBitis,
        gerekce,
      }),
    ),
  yoneticiKapat: (b: Bolum, gerekce: string, gercekBitis?: string) =>
    zamanli(
      api.post<BolumSonucu>(bolumYolu(b.service_order_id, b.id, "yonetici-kapat"), {
        version: b.version,
        gerekce,
        gercek_bitis: gercekBitis,
      }),
    ),
  manuel: (
    isId: number,
    govde: {
      faaliyet: Faaliyet;
      started_at: string;
      ended_at: string;
      user_id?: number;
      bekleme_nedeni?: string;
      gerekce?: string;
      konum_notu?: string;
      aciklama?: string;
    },
  ) => zamanli(api.post<BolumSonucu>(`${TS}/isler/${isId}/zaman`, govde)),
  kayitIptal: (b: Bolum, gerekce: string) =>
    zamanli(
      api.post<BolumSonucu>(`${TS}/isler/${b.service_order_id}/zaman/kayitlar/${b.id}/iptal`, {
        gerekce,
      }),
    ),
};

/** Sayaç değişince yenilenecek sorgu anahtarları (bant, liste, kart, Bugünüm). */
export const ZAMAN_SORGULARI = [["zaman-benim"], ["benim-islerim"], ["mobil-kart"], ["bugunum"]];

// --- Zaman Takibi yönetim ekranı (TS-189, E09-14/15) -------------------------
//
// Sayı = liste: KPI kutusu `adet`i açılan listenin `X-Toplam-Kayit`'ıdır;
// istemci sayı HESAPLAMAZ. Kişi alanları (`user_id`, `kisi_adi`, `konum_notu`,
// `gerekce`, `personel`) `servis_rapor.personel` yoksa yanıtta hiç yoktur.

export interface ZamanKpi {
  kod: string;
  baslik: string;
  tanim: string;
  birim: "dk" | "adet" | "oran";
  /** null = ölçülemedi / kayıt yok (0 DEĞİL). */
  deger: number | null;
  adet: number | null;
  /** Kutu tıklanınca açılan liste: bölümler ya da işler; oranın listesi yok. */
  liste: "kayitlar" | "isler" | null;
}

export interface PersonelSatiri {
  user_id: number | null;
  ad: string;
  kisi_saat_dk: number | null;
  yol_dk: number | null;
  saha_dk: number | null;
  bekleme_dk: number | null;
  mola_dk: number | null;
  is_sayisi: number;
  canli_orani: number | null;
  manuel_sayisi: number;
  gecikmeli_manuel_sayisi: number;
  duzeltilen_sayisi: number;
  iptal_sayisi: number;
  geri_alinan_sayisi: number;
}

export interface ZamanOzeti {
  sunucu_zamani: string;
  suzgec: { bas: string; bit: string; birim: string | null; kullanici_id: number | null; faaliyet: string | null };
  kpi: ZamanKpi[];
  /** Yalnız `servis_rapor.personel`. */
  personel?: PersonelSatiri[];
}

export interface ZamanKaydi {
  id: number;
  version: number;
  service_order_id: number;
  so_no: string;
  birim: string | null;
  faaliyet: Faaliyet;
  bekleme_nedeni: string | null;
  started_at: string;
  ended_at: string | null;
  sure_dk: number | null;
  gecen_dk: number | null;
  uzun: boolean;
  kaynak: string;
  kapanis_turu: string | null;
  girildi_at: string;
  gecikmeli: boolean;
  iptal_turu: string | null;
  user_id?: number | null;
  kisi_adi?: string | null;
  konum_notu?: string | null;
  gerekce?: string | null;
  aciklama?: string | null;
}

export interface ZamanIsi {
  id: number;
  so_no: string;
  birim: string;
  tur: string;
  durum: string;
  konu: string;
  completed_at: string | null;
  kisi_saat_dk: number | null;
  sure_durumu: string | null;
}

export interface ZamanSuzgeci {
  bas?: string;
  bit?: string;
  birim?: string;
  kullanici_id?: number;
  faaliyet?: string;
}

function sorgu(s: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  return p.toString();
}

export const zamanTakibi = {
  ozet: (s: ZamanSuzgeci) => zamanli(api.get<ZamanOzeti>(`${TS}/zaman/ozet?${sorgu({ ...s })}`)),
  aktif: (s: Pick<ZamanSuzgeci, "birim" | "kullanici_id">) =>
    zamanli(
      api.get<{ sunucu_zamani: string; sayaclar: ZamanKaydi[] }>(`${TS}/zaman/aktif?${sorgu({ ...s })}`),
    ),
  kayitlar: (s: ZamanSuzgeci & { kpi?: string }, limit: number, offset: number): Promise<Sayfa<ZamanKaydi>> =>
    api.getSayfa<ZamanKaydi>(`${TS}/zaman/kayitlar?${sorgu({ ...s, limit, offset })}`),
  isler: (s: ZamanSuzgeci & { kpi: string }, limit: number, offset: number): Promise<Sayfa<ZamanIsi>> =>
    api.getSayfa<ZamanIsi>(`${TS}/zaman/isler?${sorgu({ ...s, faaliyet: undefined, limit, offset })}`),
  excelYolu: (s: ZamanSuzgeci & { kpi?: string }) => `${TS}/zaman/kayitlar.xlsx?${sorgu({ ...s })}`,
};