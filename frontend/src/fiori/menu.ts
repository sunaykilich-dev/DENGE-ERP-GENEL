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
  AppstoreOutlined,
  BarChartOutlined,
  CalendarOutlined,
  ShopOutlined,
  CarOutlined,
  DatabaseOutlined,
  FieldTimeOutlined,
  InboxOutlined,
  SafetyOutlined,
  SettingOutlined,
  TeamOutlined,
} from "@ant-design/icons";

import {
  SAYFALAR,
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

const mobiliteSayfalari = SAYFALAR.filter((u) => u.grup === "mobilite").map((u) => sayfa(u.id));

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

  grup(
    "servis",
    "Servis İşleri",
    [
      sayfa("/servis-isleri", "Tüm Servis İşleri"),
      tur("ARIZA", "Arıza"),
      tur("KURULUM", "Kurulum"),
      tur("PLANSIZ_BAKIM", "Bakım"),
      tur("KESIF", "Keşif", ["HABERLESME"]),
      tur("TOPLAMA", "Toplama", ["BARIYER"]),
      tur("TASIMA", "Taşıma", ["BARIYER"]),
      sayfa("/atolye", "Atölye / Laboratuvar"),
      sayfa("/servis-paneli"),
      sayfa("kpi:atanmamis"),
      sayfa("kpi:kapanis_bekleyen"),
      sayfa("kpi:beklemede"),
      {
        ...suzgecli("kalite:bekleyen", "Kalite Onayı Bekleyen", "/servis-isleri?kalite=BEKLEYEN", "/servis-isleri"),
        izin: ["servis.kalite_onay"],
      },
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
      sayfa("/bakim", "Planlı Bakım Bildirimleri"),
      suzgecli("bakim:sozlesmeler", "Bakım Sözleşmeleri", "/bakim?sekme=sozlesmeler", "/bakim"),
      suzgecli("bakim:donemler", "Bakım Dönemleri", "/bakim?sekme=donemler", "/bakim"),
      sayfa("kpi:bakim_acik"),
      sayfa("kpi:bakim_geciken"),
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
      sayfa("/hesaplar", "Müşteri Kartları", "satis:hesaplar"),
      sayfa("/teklifler", "Teklifler", "satis:teklifler"),
      suzgecli(
        "satis:teklif-hazirlanacak",
        "Teklif Hazırlanacak İşler",
        "/servis-isleri?sonuc=TEKLIF_SUNULACAK",
        "/servis-isleri",
      ),
      suzgecli("satis:kurulum", "Kurulum İşleri", "/servis-isleri?tur=KURULUM", "/servis-isleri"),
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
    { ikon: ShopOutlined, birimler: ["GUVENLIK", "BARIYER", "HABERLESME", "POC"], izin: ["hesap.gor", "teklif.gor"] },
  ),
  grup("depo", "Depo", [sayfa("/yedek-parca"), sayfa("/servis-ekipman")], { ikon: DatabaseOutlined }),
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
    [sayfa("/personel"), sayfa("/egitim"), sayfa("/ik-belgeler"), sayfa("/gelisim-kartim"), sayfa("/belgelerim")],
    { ikon: TeamOutlined },
  ),
  // Mobilite modülü (DENGE MOBİLİTE etkinken). Modülün kendisine dokunulmadı.
  grup("mobilite", "Mobilite", mobiliteSayfalari, { ikon: CarOutlined, birimler: ["MOBILITE", "ARAC_TAKIP"] }),
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
      {
        tur: "yaprak",
        anahtar: "uygulamalar",
        baslik: "Uygulamalar (kutucuklar)",
        yol: "/uygulamalar",
        // Launchpad yalnız kullanıcının yetkili olduğu kutucukları çizer; kendisi herkese açık.
        uygulama: null,
        ikon: AppstoreOutlined,
      },
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
    if (altlar.length) sonuc.push({ ...o, altlar });
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

/**
 * Açılış sayfası (B-01): görünür menüdeki ilk yaprak — Ana Panel izni olana
 * Ana Panel, olmayana (satış, finans uzmanı, mobilite depo…) izni ve şirketi
 * tutan ilk anlamlı ekran. Kutucuk ekranı (`/uygulamalar`) son çaredir.
 */
export function acilisYolu(gorunur: MenuOgesi[]): string {
  const ilk = yapraklar(gorunur).find(({ yaprak }) => yaprak.yol !== "/uygulamalar");
  return ilk?.yaprak.yol ?? "/uygulamalar";
}

/**
 * Menüde yaprağı olmayan liste görünümleri (Ana Panel KPI bağlantıları): kırıntı
 * ve sekme başlığı genel "Tüm Servis İşleri" yerine KPI adını gösterir (B-11).
 */
export const KPI_ADLARI: Record<string, string> = {
  acik: "Açık İş Emirleri",
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
