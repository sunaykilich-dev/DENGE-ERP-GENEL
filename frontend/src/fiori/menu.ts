/**
 * Sol menü ağacı — Logo CRM kurgusu (KARARLAR 2026-11-04 §2).
 *
 * Ana bölüm başlıkları → alt bölümler (gruplar) → yapraklar. Her yaprak MEVCUT
 * bir ekranı açar; çoğu servis işleri listesini süzgeçle açar
 * (`/servis-isleri?birim=GUVENLIK&tur=KURULUM`). İzin tek kaynaktan gelir:
 * yaprak `uygulamalar.ts` kataloğundaki uygulamaya bağlanır ve onun `izin`
 * alanını kullanır (izin kodu burada yeniden yazılmaz).
 *
 * Şirket süzgeci: birime bağlı bölüm (`birimler`) yalnız etkin şirketin
 * birimlerinden biri varsa görünür (Güvenlik/Set Bariyer → ELEKTRONİK,
 * Haberleşme/POC → TELEKOM, Mobilite → MOBİLİTE). `birimler` yoksa ortak
 * bölümdür, her şirkette görünür. Bu yalnız görsel kısıtlamadır; sunucu
 * kapsamı etkin şirketin birimleriyle ayrıca süzer.
 *
 * Ekranı henüz olmayan dallar (Satış akışları, Frekans/Setra) bilerek YOK —
 * boş ekran göstermemek için (KARARLAR §2). "Satış ve Müşteri" bölümü
 * (rol testi B-02) yalnız MEVCUT ekranları açar: grup ortak müşteri kartları,
 * servis teklifleri, sonuçlanan arıza işleri, kurulum işleri ve kurulum
 * bekleyen ekipman. Mobilite modülünün kendi yaprakları yalnız MOBİLİTE'de. `scripts/menu-kontrol.mjs`
 * her yaprağın `main.tsx`'te gerçek bir rotaya gittiğini ve katalogdaki her
 * sayfanın menüde bulunduğunu derlemeden önce denetler.
 */
import {
  AlertOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  CalendarOutlined,
  ShopOutlined,
  CarOutlined,
  DatabaseOutlined,
  FieldTimeOutlined,
  FileProtectOutlined,
  InboxOutlined,
  SafetyOutlined,
  ScheduleOutlined,
  SettingOutlined,
  TeamOutlined,
  WifiOutlined,
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
}

export interface MenuGrubu {
  tur: "grup";
  anahtar: string;
  baslik: string;
  ikon?: IkonBileseni;
  /** Doluysa bölüm yalnız etkin şirketin bu birimlerinden biri varsa görünür. */
  birimler?: string[];
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
  ek: { ikon?: IkonBileseni; birimler?: string[] } = {},
): MenuGrubu {
  return { tur: "grup", anahtar, baslik, altlar, ...ek };
}

/** Birimin servis işleri, isteğe bağlı tür süzgeciyle. */
function servis(birim: string, tur: string | null, baslik: string): MenuYapragi {
  const yol = `/servis-isleri?birim=${birim}${tur ? `&tur=${tur}` : ""}`;
  return suzgecli(`servis:${birim}:${tur ?? "TUMU"}`, baslik, yol, "/servis-isleri");
}

const mobiliteSayfalari = SAYFALAR.filter((u) => u.grup === "mobilite").map((u) => sayfa(u.id));

/** Menü ağacı (sıra = ekrandaki sıra). */
export const MENU_AGACI: MenuOgesi[] = [
  // Anahtar eski favori/son açılan kayıtları bozulmasın diye "ana-panel".
  sayfa(ANA_PANEL_YOLU, undefined, "ana-panel"),
  { ...sayfa("/benim-islerim"), ikon: FieldTimeOutlined },

  // --- Birim bölümleri (şirkete göre) ---------------------------------------
  grup(
    "guvenlik",
    "Güvenlik",
    [
      grup("guvenlik:ts", "Teknik Servis", [
        servis("GUVENLIK", null, "Tüm işler"),
        servis("GUVENLIK", "KURULUM", "Kurulum"),
        servis("GUVENLIK", "ARIZA", "Arıza"),
        servis("GUVENLIK", "PLANSIZ_BAKIM", "Bakım"),
      ]),
      grup("guvenlik:atolye", "Atölye", [
        suzgecli("atolye:GUVENLIK", "Bakım", "/atolye?birim=GUVENLIK", "/atolye"),
      ]),
    ],
    { ikon: SafetyOutlined, birimler: ["GUVENLIK"] },
  ),
  grup(
    "haberlesme",
    "Haberleşme",
    [
      grup("haberlesme:ts", "Teknik Servis", [servis("HABERLESME", null, "Tüm işler")]),
      grup("haberlesme:lab", "Laboratuvar", [
        suzgecli("atolye:HABERLESME", "Arıza Onarım", "/atolye?birim=HABERLESME", "/atolye"),
        suzgecli("lab:yedek-parca", "Yedek Parça Stok", "/yedek-parca?sekme=stok", "/yedek-parca"),
      ]),
      grup("haberlesme:saha", "Saha", [
        servis("HABERLESME", "KESIF", "Keşif"),
        servis("HABERLESME", "ARIZA", "Arıza"),
        servis("HABERLESME", "PLANSIZ_BAKIM", "Bakım"),
      ]),
    ],
    { ikon: WifiOutlined, birimler: ["HABERLESME"] },
  ),
  grup(
    "poc",
    "POC",
    [
      // B-10: POC tek bölümde; Haberleşme altındaki yinelenen yaprak kaldırıldı.
      servis("POC", null, "Tüm işler"),
      servis("POC", "ARIZA", "Arıza"),
      servis("POC", "KURULUM", "Kurulum"),
    ],
    { ikon: ApartmentOutlined, birimler: ["POC"] },
  ),
  grup(
    "mobilite",
    "Mobilite",
    [
      grup("mobilite:ts", "Teknik Servis", [
        servis("MOBILITE", null, "Mobilite işleri"),
        servis("ARAC_TAKIP", null, "Araç Takip işleri"),
      ]),
      grup("mobilite:modul", "Mobilite Modülü", mobiliteSayfalari),
    ],
    { ikon: CarOutlined, birimler: ["MOBILITE", "ARAC_TAKIP"] },
  ),
  grup(
    "bariyer",
    "Set Bariyer",
    [
      servis("BARIYER", null, "Tüm işler"),
      servis("BARIYER", "KURULUM", "Kurulum"),
      servis("BARIYER", "TOPLAMA", "Toplama"),
      servis("BARIYER", "TASIMA", "Taşıma"),
    ],
    { ikon: AlertOutlined, birimler: ["BARIYER"] },
  ),

  // Satış / Satış Destek (B-02): ELEKTRONİK ve TELEKOM'da (birimli şirketler).
  // Müşteri kartları ve servis teklifleri grup ortaktır; servis görünümlerini
  // sunucu kullanıcının birim kapsamıyla süzer.
  grup(
    "satis",
    "Satış ve Müşteri",
    [
      sayfa("/hesaplar", "Müşteri Kartları", "satis:hesaplar"),
      sayfa("/teklifler", "Teklifler", "satis:teklifler"),
      suzgecli(
        "satis:ariza-sonuclanan",
        "Sonuçlanan Arıza İşleri",
        "/servis-isleri?tur=ARIZA&durum_grubu=COZULDU",
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
    { ikon: ShopOutlined, birimler: ["GUVENLIK", "BARIYER", "HABERLESME", "POC"] },
  ),

  // --- Ortak bölümler (her şirkette) ----------------------------------------
  grup("kiralama", "Kiralama", [sayfa("/kiralamalar"), sayfa("/kiralik-envanter")], { ikon: InboxOutlined }),
  grup(
    "planlama",
    "Planlama",
    [sayfa("/servis-planlama"), sayfa("/operasyon"), sayfa("/zaman-takibi")],
    { ikon: CalendarOutlined },
  ),
  grup(
    "planli-bakim",
    "Planlı Bakım",
    [
      sayfa("/bakim", "Bakım Bildirimleri"),
      suzgecli("bakim:sozlesmeler", "Sözleşmeler", "/bakim?sekme=sozlesmeler", "/bakim"),
      suzgecli("bakim:donemler", "Bakım Dönemleri", "/bakim?sekme=donemler", "/bakim"),
      sayfa("kpi:bakim_acik"),
      sayfa("kpi:bakim_geciken"),
    ],
    { ikon: ScheduleOutlined },
  ),
  grup(
    "takip",
    "Takip ve Onaylar",
    [
      sayfa("/servis-isleri", "Tüm Servis İşleri"),
      sayfa("/servis-paneli"),
      sayfa("kpi:atanmamis"),
      sayfa("kpi:kapanis_bekleyen"),
      suzgecli("kalite:bekleyen", "Kalite Onayı Bekleyen", "/servis-isleri?kalite=BEKLEYEN", "/servis-isleri"),
      sayfa("kpi:beklemede"),
      sayfa("/gorevler"),
    ],
    { ikon: FileProtectOutlined },
  ),
  grup(
    "depo",
    "Depo ve Yedek Parça",
    [sayfa("/yedek-parca"), sayfa("/servis-ekipman")],
    { ikon: DatabaseOutlined },
  ),
  grup(
    "raporlar",
    "Raporlar",
    [sayfa("/servis-raporlari"), sayfa("/servis-maliyet"), sayfa("/fatura-devri"), sayfa("/servis-ana-veri")],
    { ikon: BarChartOutlined },
  ),
  grup("ik", "İnsan Kaynakları", [sayfa("/personel"), sayfa("/egitim"), sayfa("/gelisim-kartim")], {
    ikon: TeamOutlined,
  }),
  grup(
    "sistem",
    "Sistem Yönetimi",
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
  if (y.uygulama === null) return true;
  const u = KATALOG.get(y.uygulama);
  return !!u && uygulamaYetkili(u, yetkili);
}

/** Görünür ağaç: yetkisiz yaprak, şirkete ait olmayan bölüm ve boş grup çıkar. */
export function gorunurMenu(agac: MenuOgesi[], s: MenuSuzgeci): MenuOgesi[] {
  const sonuc: MenuOgesi[] = [];
  for (const o of agac) {
    if (o.tur === "yaprak") {
      if (yaprakYetkili(o, s.yetkili)) sonuc.push(o);
      continue;
    }
    if (o.birimler && s.aktifBirimler && !o.birimler.some((b) => s.aktifBirimler!.has(b))) continue;
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
