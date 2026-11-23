/**
 * Sol menü ağacı — göreve göre gruplar (KARARLAR 2026-11-09 S7; önceki kurgu
 * KARARLAR 2026-11-04 §2 birim köklüydü ve kullanıcı karışık buldu).
 *
 * Ana Panel, Benim İşlerim, Servis İşleri, Planlama, Satış, Depo, Kiralama,
 * Raporlar, İnsan Kaynakları, (Mobilite), Yönetim. En fazla iki seviye; boş
 * grup gizlenir. Her yaprak MEVCUT bir ekranı açar ve adresler değişmedi
 * (favoriler/yer imleri bozulmaz). İzin tek kaynaktan gelir: yaprak
 * `uygulamalar.ts` kataloğundaki uygulamaya bağlanır ve onun `izin` alanını
 * kullanır; `izin` (ek) ve `birimler` (şirket) yalnız görünürlüğü daraltır,
 * sunucu kapsamı ayrıca süzer. `scripts/menu-kontrol.mjs` her yaprağın
 * `main.tsx`'te gerçek bir rotaya gittiğini ve katalogdaki her sayfanın
 * menüde bulunduğunu derlemeden önce denetler.
 */
import {
  BarChartOutlined,
  CalendarOutlined,
  ShopOutlined,
  DatabaseOutlined,
  FieldTimeOutlined,
  InboxOutlined,
  SafetyOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";

import {
  UYGULAMALAR,
  type IkonBileseni,
  type Uygulama,
  type Yetkili,
  uygulamaYetkili,
} from "./uygulamalar";

export interface MenuYapragi {
  tur: "yaprak";
  /** Benzersiz anahtar (favori/son açılan kaydı bununla tutulur). */
  anahtar: string;
  baslik: string;
  /** Açılacak yol (sorgu parametreleriyle). */
  yol: string;
  /** İzni veren katalog uygulaması (`uygulamalar.ts` kimliği); null = herkese açık. */
  uygulama: string | null;
  ikon?: IkonBileseni;
  /** Uygulamanın iznine EK olarak bu izinlerden biri de gerekir (aynı sayfanın
   *  ekip görünümü; ör. kalite onayı bekleyenler yalnız onaylayana). */
  izin?: string[];
  /** Doluysa yaprak yalnız etkin şirketin bu birimlerinden biri varsa görünür. */
  birimler?: string[];
}

export interface MenuGrubu {
  tur: "grup";
  anahtar: string;
  baslik: string;
  ikon?: IkonBileseni;
  /** Doluysa bölüm yalnız etkin şirketin bu birimlerinden biri varsa görünür. */
  birimler?: string[];
  /** Doluysa bölüm yalnız bu izinlerden biri varsa görünür (departman bölümü). */
  izin?: string[];
  altlar: MenuOgesi[];
}

export type MenuOgesi = MenuYapragi | MenuGrubu;

/**
 * Ana Panel (`servis.gor`). `/` ve `/baslangic` açılış sayfasını açar: izni
 * olana Ana Panel, olmayana menüdeki ilk yetkili sayfa (rol testi B-01).
 */
export const ANA_PANEL_YOLU = "/ana-panel";

const KATALOG = new Map(UYGULAMALAR.map((u) => [u.id, u]));

function katalog(id: string): Uygulama {
  const u = KATALOG.get(id);
  if (!u) throw new Error(`Menü: katalogda olmayan uygulama "${id}"`);
  return u;
}

/** Katalog uygulamasını olduğu gibi açan yaprak (başlık/yol katalogdan). */
function sayfa(id: string, baslik?: string, anahtar?: string): MenuYapragi {
  const u = katalog(id);
  return { tur: "yaprak", anahtar: anahtar ?? id, baslik: baslik ?? u.baslik, yol: u.yol, uygulama: id, ikon: u.ikon };
}

/** Aynı uygulamanın süzülmüş görünümü (izin yine uygulamadan). */
function suzgecli(anahtar: string, baslik: string, yol: string, uygulama: string): MenuYapragi {
  return { tur: "yaprak", anahtar, baslik, yol, uygulama, ikon: katalog(uygulama).ikon };
}

function grup(
  anahtar: string,
  baslik: string,
  altlar: MenuOgesi[],
  ek: { ikon?: IkonBileseni; birimler?: string[]; izin?: string[] } = {},
): MenuGrubu {
  return { tur: "grup", anahtar, baslik, altlar, ...ek };
}

/** Servis işleri tür süzgeci (birimden bağımsız; birim ekranda süzülür).
 *  `birimler`: tür yalnız bu birimlerde kullanılıyorsa (ör. Keşif → Haberleşme). */
function tur(kod: string, baslik: string, birimler?: string[]): MenuYapragi {
  return {
    ...suzgecli(`servis:${kod}`, baslik, `/servis-isleri?tur=${kod}`, "/servis-isleri"),
    ...(birimler ? { birimler } : {}),
  };
}


/**
 * Menü ağacı (sıra = ekrandaki sıra). KARARLAR 2026-11-09 S7: göreve göre
 * gruplar, en fazla İKİ seviye (grup → yaprak), boş grup gizlenir. Birim
 * (Haberleşme, Güvenlik, POC, Set Bariyer) menü kökü DEĞİL: servis işleri
 * ekranında süzgeçtir (tek birimli kullanıcıda kendiliğinden seçili). Tür
 * yaprakları (Keşif, Toplama ...) yalnız o türü kullanan birim etkin
 * şirketteyse görünür (`birimler`). Yollar (URL) değişmedi.
 */
export const MENU_AGACI: MenuOgesi[] = [
  // Anahtar eski favori/son açılan kayıtları bozulmasın diye "ana-panel".
  sayfa(ANA_PANEL_YOLU, undefined, "ana-panel"),
  { ...sayfa("/benim-islerim"), ikon: FieldTimeOutlined },
  // 2026-11-10: onaya gelen işler Servis İşleri'nden ayrı modül (birim sekmeli).
  sayfa("/is-emri-onayi"),

  grup(
    "servis",
    "Servis İşleri",
    [
      sayfa("/servis-isleri", "Tüm Servis İşleri"),
      sayfa("/yonlendirmeler"),
      tur("ARIZA", "Arıza"),
      tur("KURULUM", "Kurulum"),
      tur("PLANSIZ_BAKIM", "Bakım"),
      tur("KESIF", "Keşif", ["HABERLESME"]),
      tur("TOPLAMA", "Toplama", ["BARIYER"]),
      tur("TASIMA", "Taşıma", ["BARIYER"]),
      sayfa("/atolye", "Atölye / Laboratuvar"),
      // Kapanış Onayı ve Kalite Onayı Bekleyen → İş Emri Onayı modülü (2026-11-10).
      // 2026-11-18 UI/UX: Servis Paneli (Ana Panel'in kopyası) ve yalnız süzgeç
      // olan "Tayin Edilmemiş / Askıdaki İşler" yaprakları kaldırıldı; aynı
      // süzgeçler listedeki durum düğmeleri ve Ana Panel kutucuklarıyla açılır.
    ],
    { ikon: SafetyOutlined },
  ),
  grup(
    "planlama",
    "Planlama",
    [
      sayfa("/servis-planlama"),
      sayfa("/operasyon"),
      sayfa("/zaman-takibi"),
      // 2026-11-18 UI/UX: bakımın tek yaprağı; sözleşme/dönem/açık/geciken
      // görünümleri sayfanın sekmeleri ve Ana Panel kutucuklarıdır.
      sayfa("/bakim"),
      sayfa("/gorevler"),
    ],
    { ikon: CalendarOutlined },
  ),

  // Satış (S7.3): satış ekranları ayrı oturumda eklenecek; bu grup onların
  // yeridir. "Sonuçlanan Arıza İşleri" kaldırıldı (bütün çözülmüş arızaları
  // gösteriyordu); yerine yalnız teklif sunulacak işler.
  grup(
    "satis",
    "Satış",
    [
      sayfa("/hesaplar", "Cari Hesaplar", "satis:hesaplar"),
      sayfa("/teklifler", "Teklifler", "satis:teklifler"),
      sayfa("/tekliflerim", "Tekliflerim", "satis:tekliflerim"),
      sayfa("/satislarim", "Satışlarımın Durumu", "satis:satislarim"),
      suzgecli(
        "satis:teklif-hazirlanacak",
        "Teklif Hazırlanacak İşler",
        "/servis-isleri?sonuc=TEKLIF_SUNULACAK",
        "/servis-isleri",
      ),
      // "Kurulum İşleri" kaldırıldı (2026-11-18): Servis İşleri › Kurulum ile aynı adres.
      suzgecli(
        "satis:kurulum-bekleyen",
        "Kurulum Bekleyen Ekipman",
        "/servis-ekipman?durum=KURULUM_BEKLIYOR",
        "/servis-ekipman",
      ),
      sayfa("/urunler", "Ürün Kataloğu", "satis:urunler"),
    ],
    // Satışın bölümü: teknisyen burada yalnız kendi işlerinin süzülmüş
    // görünümlerini görüyordu (2026-11-09); bölüm satış izni ister.
    // 2026-11-23: üç şirkette de açık (Mobilite bölümü kaldırıldı; cari,
    // teklif ve ürün kataloğu buradan, kayıtlar etkin şirkete göre süzülür).
    { ikon: ShopOutlined, izin: ["hesap.gor", "teklif.gor"] },
  ),
  // 2026-11-23: Stok ve Hatlar Mobilite bölümünden buraya; her şirket kendi
  // cihaz ve hatlarını görür (sunucu etkin şirkete göre süzer).
  grup(
    "depo",
    "Depo",
    [sayfa("/yedek-parca"), sayfa("/servis-ekipman"), sayfa("/stok"), sayfa("/hatlar")],
    { ikon: DatabaseOutlined },
  ),
  grup("kiralama", "Kiralama", [sayfa("/kiralamalar"), sayfa("/kiralik-envanter")], { ikon: InboxOutlined }),
  grup(
    "raporlar",
    "Raporlar",
    [sayfa("/servis-raporlari"), sayfa("/servis-maliyet"), sayfa("/fatura-devri"), sayfa("/servis-ana-veri")],
    { ikon: BarChartOutlined },
  ),
  grup(
    "ik",
    "İnsan Kaynakları",
    // Belgelerim ve Gelişim Kartım kişisel sayfalar: kullanıcı menüsünde
    // (avatar), İK yöneticisinin ekranlarıyla aynı bölümde değil (2026-11-18).
    [sayfa("/personel"), sayfa("/egitim"), sayfa("/ik-belgeler"), sayfa("/izin-talepleri")],
    { ikon: TeamOutlined },
  ),
  // 2026-11-23: "Mobilite" bölümü kaldırıldı (DENGE MOBİLİTE ayrı şirket, kendi
  // ERP'si var). Cari/teklif/ürün Satış'ta, Stok/Hatlar Depo'da; diğer mobilite
  // ekranları menüde yok, adresle açılırsa şirket kapısı çalışır.
  grup(
    "sistem",
    "Yönetim",
    [
      sayfa("/servis-tanimlar"),
      sayfa("/kullanicilar"),
      sayfa("/ayarlar"),
      sayfa("/ice-aktarma"),
      sayfa("/kvkk"),
      sayfa("/denetim"),
      sayfa("/eposta-kutusu"),
      // "Uygulamalar (kutucuklar)" kaldırıldı (2026-11-18): menünün tutarsız
      // bir kopyasıydı; çoğu rolde Yönetim bölümünün tek yaprağıydı.
    ],
    { ikon: SettingOutlined },
  ),
];

// --- Süzme ------------------------------------------------------------------------

export interface MenuSuzgeci {
  yetkili: Yetkili;
  /** Etkin şirketin birimleri; null = şirket süzgeci yok (uç henüz yok). */
  aktifBirimler: ReadonlySet<string> | null;
}

export function yaprakYetkili(y: MenuYapragi, yetkili: Yetkili): boolean {
  if (y.izin && !y.izin.some((i) => yetkili(i))) return false;
  if (y.uygulama === null) return true;
  const u = KATALOG.get(y.uygulama);
  return !!u && uygulamaYetkili(u, yetkili);
}

/** Görünür ağaç: yetkisiz yaprak, şirkete ait olmayan bölüm ve boş grup çıkar. */
export function gorunurMenu(agac: MenuOgesi[], s: MenuSuzgeci): MenuOgesi[] {
  const sonuc: MenuOgesi[] = [];
  for (const o of agac) {
    if (o.tur === "yaprak") {
      if (o.birimler && s.aktifBirimler && !o.birimler.some((b) => s.aktifBirimler!.has(b))) continue;
      if (yaprakYetkili(o, s.yetkili)) sonuc.push(o);
      continue;
    }
    if (o.birimler && s.aktifBirimler && !o.birimler.some((b) => s.aktifBirimler!.has(b))) continue;
    if (o.izin && !o.izin.some((i) => s.yetkili(i))) continue;
    const altlar = gorunurMenu(o.altlar, s);
    // Tek yaprağı kalan bölüm açılır-kapanır başlık olmasın, yaprak olarak
    // çizilsin (ör. teknisyende Planlama › Görevler; UI/UX 2026-11-18).
    if (altlar.length === 1 && altlar[0].tur === "yaprak") sonuc.push({ ...altlar[0], ikon: altlar[0].ikon ?? o.ikon });
    else if (altlar.length) sonuc.push({ ...o, altlar });
  }
  return sonuc;
}

/** Ağacın bütün yaprakları, kök→yaprak yoluyla (ekmek kırıntısı için). */
export function yapraklar(agac: MenuOgesi[], ust: MenuGrubu[] = []): { yaprak: MenuYapragi; atalar: MenuGrubu[] }[] {
  return agac.flatMap((o) =>
    o.tur === "yaprak" ? [{ yaprak: o, atalar: ust }] : yapraklar(o.altlar, [...ust, o]),
  );
}

/** Yolun sorgu dışı kısmı. */
export function yolKismi(yol: string): string {
  return yol.split("?")[0].split("#")[0];
}

/**
 * Şu anki adrese en iyi uyan yaprak. Yaprağın yolu adresle aynı ya da onun
 * ön eki olmalı (`/servis-isleri/12`), sorgu parametrelerinin HEPSİ adreste
 * aynı değerle bulunmalı; en çok parametresi uyan kazanır, eşitlikte ağaçtaki
 * ilk yaprak (ör. Haberleşme › POC ile POC bölümü).
 */
export function aktifYaprak(
  agac: MenuOgesi[],
  adresYolu: string,
  search: string,
): { yaprak: MenuYapragi; atalar: MenuGrubu[] } | undefined {
  const pathname = adresYolu;
  const adres = new URLSearchParams(search);
  let en: { yaprak: MenuYapragi; atalar: MenuGrubu[] } | undefined;
  let enPuan = -1;
  for (const aday of yapraklar(agac)) {
    const [yolu, sorgu = ""] = aday.yaprak.yol.split("?");
    const tam = pathname === yolu;
    if (!tam && !(yolu !== "/" && pathname.startsWith(`${yolu}/`))) continue;
    const p = new URLSearchParams(sorgu);
    let uyan = 0;
    let uymaz = false;
    p.forEach((deger, ad) => {
      if (adres.get(ad) === deger) uyan += 1;
      else uymaz = true;
    });
    if (uymaz) continue;
    const puan = uyan * 10 + (tam ? 1 : 0);
    if (puan > enPuan) {
      en = aday;
      enPuan = puan;
    }
  }
  return en;
}

/** Servis işinde çalışan (yazan, planlayan, onaylayan, operasyonu izleyen): açılışı Ana Panel. */
const SERVIS_CALISANI_IZINLERI = ["servis.yaz", "servis.planla", "servis.kalite_onay", "operasyon.gor"];

/**
 * Servis çalışanı olmayan rollerin ana ekranı (ilk uyan, menüde görünürse).
 * Sıra önemli: finans yöneticisinde kiralama.gor da var, ana işi fatura devri.
 */
const ROL_ANA_EKRANLARI: [izin: string, yol: string][] = [
  ["teklif.yaz", "/teklifler"],
  ["tahsilat.gor", "/fatura-devri"],
  ["parca.gor", "/yedek-parca"],
  ["kiralama.gor", "/kiralamalar"],
  ["personel.gor", "/personel"],
];

/**
 * İşi dağıtan (tayin eden) servis rolü: Operasyon Merkezi'ni görür ve planlar
 * (şef, müdür; yetki verilen yedek kişi). 2026-11-18 kullanıcı kararı: bu
 * kişiler girişte doğrudan Operasyon Merkezi panosuna düşer.
 */
const DISPECER_IZINLERI = ["operasyon.gor", "servis.planla"];
const OPERASYON_YOLU = "/operasyon";

/**
 * Açılış sayfası (B-01). İşi dağıtan servis rolüne Operasyon Merkezi; diğer
 * servis çalışanına menüdeki ilk yaprak (Ana Panel);
 * diğer rollere kendi ana ekranı — satışçı boş servis panosuna, kiralama
 * deposu Zaman Takibi'ne, İK yetkisiz sayfaya düşmesin (UI/UX 2026-11-18).
 * Hiçbiri yoksa menüdeki ilk yaprak; menü boşsa Ana Panel.
 */
export function acilisYolu(gorunur: MenuOgesi[], yetkili?: Yetkili): string {
  const tumu = yapraklar(gorunur);
  if (
    yetkili &&
    DISPECER_IZINLERI.every((i) => yetkili(i)) &&
    tumu.some(({ yaprak }) => yolKismi(yaprak.yol) === OPERASYON_YOLU)
  ) {
    return OPERASYON_YOLU;
  }
  if (yetkili && !SERVIS_CALISANI_IZINLERI.some((i) => yetkili(i))) {
    for (const [izin, yol] of ROL_ANA_EKRANLARI) {
      if (yetkili(izin) && tumu.some(({ yaprak }) => yolKismi(yaprak.yol) === yol)) return yol;
    }
  }
  return tumu[0]?.yaprak.yol ?? ANA_PANEL_YOLU;
}

/**
 * Menüde yaprağı olmayan liste görünümleri (Ana Panel KPI bağlantıları): kırıntı
 * ve sekme başlığı genel "Tüm Servis İşleri" yerine KPI adını gösterir (B-11).
 */
export const KPI_ADLARI: Record<string, string> = {
  acik: "Açık İş Emirleri",
  atanmamis: "Tayin Edilmemiş İşler",
  beklemede: "Askıdaki İşler",
  bakim_acik: "Açık Bakım İşleri",
  bakim_geciken: "Geciken Bakım",
  kritik_acik: "Kritik Açık İşler",
  sla_riskli: "SLA Riski Olan İşler",
  bakim_bu_ay_planli: "Bu Ay Planlı Bakım",
  onay_bekleyen: "Onay Bekleyen İşler",
  plan_bekleyen: "Plan Bekleyen İşler",
  planlandi: "Planlanan İşler",
  sahada: "Sahadaki İşler",
  atolyede: "Atölyedeki İşler",
  bugun_acilan: "Bugün Açılan İşler",
  bugun_planli: "Bugün Planlı İşler",
  tamamlanan: "Tamamlanan İşler",
  poc_acik: "POC Açık Talepler",
};
