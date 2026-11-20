/**
 * Uygulama kataloğu — Fiori launchpad kutucukları ve kabuk gezinmesi (rehber §1–2).
 *
 * Eski sol menüdeki (`MENU`) HER sayfa burada bir kutucuktur; hiçbiri
 * kaybolmaz. Yol ve izin kodları eski menüyle birebir aynıdır (izin kodları
 * DEĞİŞMEZ). Kutucuk yalnız kullanıcı yetkiliyse görünür — bu yalnız görsel
 * bir kısıtlamadır, sunucu her uçta kendi kontrolünü ayrıca yapar.
 *
 * KPI'lı kutucuklar sayıyı MEVCUT uçlardan alır, ekran sayı hesaplamaz:
 *  - `panel`: Servis Paneli KPI kutusu (`/api/teknik-servis/panel`), "sayı = liste".
 *  - `benim`: bana tayin edilen açık işler (`/benim-islerim`).
 *  - `uyari`: uyarı zili özeti (`/api/raporlar/uyarilar`).
 */
import {
  AlertOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BarChartOutlined,
  BellOutlined,
  BuildOutlined,
  CalendarOutlined,
  CarOutlined,
  CheckSquareOutlined,
  ClockCircleOutlined,
  ClusterOutlined,
  ContainerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DollarOutlined,
  FieldTimeOutlined,
  FileDoneOutlined,
  FileProtectOutlined,
  FileTextOutlined,
  FundOutlined,
  HddOutlined,
  IdcardOutlined,
  ImportOutlined,
  InboxOutlined,
  PieChartOutlined,
  ProfileOutlined,
  ReadOutlined,
  SafetyCertificateOutlined,
  ScheduleOutlined,
  SendOutlined,
  SettingOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  SolutionOutlined,
  SyncOutlined,
  TeamOutlined,
  ToolOutlined,
  UnorderedListOutlined,
  UserOutlined,
  UserSwitchOutlined,
  WalletOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import type { ComponentType, CSSProperties } from "react";

export type Yetkili = (...kodlar: string[]) => boolean;

export type IkonBileseni = ComponentType<{ style?: CSSProperties; className?: string }>;

/** Kutucuktaki büyük sayının kaynağı (yalnız mevcut uçlar). */
export type KpiKaynagi =
  /** Servis Paneli KPI kutusu; `kod` sunucudaki `KPI_TANIMLARI` kodudur. */
  | { tur: "panel"; kod: string }
  /** Bana tayin edilen açık işlerin sayısı. */
  | { tur: "benim" }
  /** Bekleyen uyarı sayısı. */
  | { tur: "uyari" };

export interface Uygulama {
  /** Benzersiz anahtar (çoğunlukla yol). */
  id: string;
  /** Kutucuk başlığı (kalın). */
  baslik: string;
  /** Kutucukta başlığın altındaki küçük gri metin. */
  altBaslik?: string;
  ikon: IkonBileseni;
  /** Açılacak yol. KPI'lı kutucukta sunucunun verdiği liste yolu önceliklidir. */
  yol: string;
  /** Tek izin ya da "bunlardan herhangi biri" listesi (eski MENU ile aynı). */
  izin: string | string[];
  /** Launchpad grubu (sekme). */
  grup: GrupKodu;
  kpi?: KpiKaynagi;
  /** KPI'nin altına yazılan birim ("iş", "uyarı"). */
  kpiBirimi?: string;
  /**
   * Eski menüde olmayan, aynı ekranın süzülmüş görünümünü açan ek kutucuk
   * (ör. "Tayin Edilmemiş İşler"). Kabuk başlığında ve açılış kuralında
   * sayfa olarak kullanılmaz.
   */
  ek?: boolean;
  /**
   * Sunucuda yalnız DENGE MOBİLİTE etkinken açılan ekran (`MOBILITE_KAPISI`,
   * KARARLAR 2026-11-04 §1). Başka şirketteyken rota kapısı "bu sayfa bu
   * şirkette kullanılamaz" der; boş tablo/"Veri Yok" çizilmez (sızıntı S4).
   * Hesaplar, Ürün Kataloğu ve Teklifler grup ortaktır, kapısı yoktur.
   */
  yalnizMobilite?: boolean;
}

export type GrupKodu =
  | "servis"
  | "takip"
  | "bakim"
  | "operasyon"
  | "depo"
  | "raporlar"
  | "ik"
  | "mobilite"
  | "sistem";

export interface Grup {
  kod: GrupKodu;
  baslik: string;
}

/** Launchpad sekme (anchor) çubuğunun sırası. */
export const GRUPLAR: Grup[] = [
  { kod: "servis", baslik: "Teknik Servis Uygulamaları" },
  { kod: "takip", baslik: "Takip ve Onay İşlemleri" },
  { kod: "bakim", baslik: "Bakım" },
  { kod: "operasyon", baslik: "Operasyon" },
  { kod: "depo", baslik: "Depo ve Kiralama" },
  { kod: "raporlar", baslik: "Raporlar ve Maliyet" },
  { kod: "ik", baslik: "İnsan Kaynakları" },
  { kod: "mobilite", baslik: "Mobilite" },
  { kod: "sistem", baslik: "Sistem Yönetimi" },
];

export const UYGULAMALAR: Uygulama[] = [
  // --- Teknik Servis Uygulamaları ------------------------------------------
  {
    // KARARLAR 2026-11-04 §4: ana sayfa. KARARLAR 2026-11-09 S8: panel
    // bileşenlerden oluşur ve her bileşen kendi izniyle süzülür (sunucu
    // `services/ana_panel_duzeni.BILESENLER`); servis ya da teklif bileşeni
    // görebilen açar. Hiçbirini göremeyen rolün açılışı menüdeki ilk yetkili
    // sayfadır (rol testi B-01). Yeni izinli bileşen grubu eklenince buraya da.
    id: "/ana-panel",
    baslik: "Ana Panel",
    altBaslik: "Operasyon özeti",
    ikon: DashboardOutlined,
    yol: "/ana-panel",
    // Teknisyende Ana Panel yok (takip.gor yok); satış rolleri teklif.gor ile açar.
    izin: ["takip.gor", "teklif.gor"],
    grup: "servis",
  },
  {
    id: "/servis-isleri",
    baslik: "Servis İşleri",
    altBaslik: "Arıza ve servis bildirimleri",
    ikon: ToolOutlined,
    yol: "/servis-isleri",
    izin: "servis.gor",
    grup: "servis",
    kpi: { tur: "panel", kod: "acik" },
    kpiBirimi: "açık iş",
  },
  {
    // KARARLAR 2026-11-20 §5–6: satış/kiralama talebi müdüre, müdürden birime.
    id: "/yonlendirmeler",
    baslik: "Yönlendirmeler",
    altBaslik: "Satış ve kiralama talepleri",
    ikon: SendOutlined,
    yol: "/yonlendirmeler",
    izin: ["servis.yonlendir", "servis.planla"],
    grup: "servis",
  },
  {
    // 2026-11-10: onaya gelen işler ayrı modül; birim (Güvenlik/Haberleşme/
    // Mobilite) sekmeli. Liste Ana Panel "Bekleyen Onaylar" süzgecidir.
    id: "/is-emri-onayi",
    baslik: "İş Emri Onayı",
    altBaslik: "Onaya gelen işler, birim birim",
    ikon: FileProtectOutlined,
    yol: "/is-emri-onayi",
    izin: ["servis.kalite_onay", "servis.son_onay"],
    grup: "servis",
  },
  {
    id: "/benim-islerim",
    baslik: "Benim İşlerim",
    altBaslik: "Bana tayin edilenler",
    ikon: FieldTimeOutlined,
    yol: "/benim-islerim",
    izin: "zaman.yaz",
    grup: "servis",
    kpi: { tur: "benim" },
    kpiBirimi: "iş",
  },
  {
    id: "/servis-paneli",
    baslik: "Servis Paneli",
    altBaslik: "Kritik açık işler",
    ikon: DashboardOutlined,
    yol: "/servis-paneli",
    izin: "takip.gor",
    grup: "servis",
    kpi: { tur: "panel", kod: "kritik_acik" },
    kpiBirimi: "kritik",
  },
  {
    id: "/servis-planlama",
    baslik: "Planlama",
    altBaslik: "Plan bekleyen işler",
    ikon: CalendarOutlined,
    yol: "/servis-planlama",
    izin: "takip.gor",
    grup: "servis",
    kpi: { tur: "panel", kod: "plan_bekleyen" },
    kpiBirimi: "iş",
  },
  {
    id: "/servis-ekipman",
    baslik: "Ekipman Kütüğü",
    ikon: ClusterOutlined,
    yol: "/servis-ekipman",
    izin: "ekipman.gor",
    grup: "servis",
  },
  {
    id: "/servis-tanimlar",
    baslik: "Servis Tanımları",
    ikon: ProfileOutlined,
    yol: "/servis-tanimlar",
    izin: ["servis.tanim", "operasyon.yonet"],
    grup: "servis",
  },
  // --- Takip ve Onay İşlemleri ---------------------------------------------
  {
    id: "kpi:atanmamis",
    baslik: "Tayin Edilmemiş İşler",
    altBaslik: "Teknisyen tayini bekleyen",
    ikon: UserSwitchOutlined,
    yol: "/servis-isleri?kpi=atanmamis",
    izin: "takip.gor",
    grup: "takip",
    kpi: { tur: "panel", kod: "atanmamis" },
    kpiBirimi: "iş",
    ek: true,
  },
  {
    id: "kpi:kapanis_bekleyen",
    baslik: "Kapanış Onayı",
    altBaslik: "Şef kapanışı bekleyen",
    ikon: FileProtectOutlined,
    yol: "/servis-isleri?kpi=kapanis_bekleyen",
    izin: "takip.gor",
    grup: "takip",
    kpi: { tur: "panel", kod: "kapanis_bekleyen" },
    kpiBirimi: "iş",
    ek: true,
  },
  {
    id: "kpi:beklemede",
    baslik: "Askıdaki İşler",
    altBaslik: "Beklemeye alınmış",
    ikon: ClockCircleOutlined,
    yol: "/servis-isleri?kpi=beklemede",
    izin: "takip.gor",
    grup: "takip",
    kpi: { tur: "panel", kod: "beklemede" },
    kpiBirimi: "iş",
    ek: true,
  },
  {
    id: "uyarilar",
    baslik: "Uyarılar",
    altBaslik: "Bekleyen uyarılar",
    ikon: BellOutlined,
    yol: "#uyarilar",
    // Uyarı ucu her oturuma açık; sayılar sunucuda izne göre süzülür.
    izin: [],
    grup: "takip",
    kpi: { tur: "uyari" },
    kpiBirimi: "uyarı",
    ek: true,
  },
  {
    id: "/gorevler",
    baslik: "Görevler",
    altBaslik: "İş listesi",
    ikon: CheckSquareOutlined,
    yol: "/gorevler",
    izin: "gorev.gor",
    grup: "takip",
  },
  // --- Bakım ---------------------------------------------------------------
  {
    id: "/bakim",
    baslik: "Planlı Bakım",
    altBaslik: "Sözleşme ve dönemler",
    ikon: ScheduleOutlined,
    yol: "/bakim",
    izin: "bakim.gor",
    grup: "bakim",
  },
  {
    id: "kpi:bakim_acik",
    baslik: "Açık Bakım İşleri",
    altBaslik: "Planlı bakım (PB)",
    ikon: ScheduleOutlined,
    yol: "/servis-isleri?kpi=bakim_acik",
    izin: "takip.gor",
    grup: "bakim",
    kpi: { tur: "panel", kod: "bakim_acik" },
    kpiBirimi: "iş",
    ek: true,
  },
  {
    id: "kpi:bakim_geciken",
    baslik: "Geciken Bakım",
    altBaslik: "Hedef tarihi geçmiş",
    ikon: AlertOutlined,
    yol: "/servis-isleri?kpi=bakim_geciken",
    izin: "takip.gor",
    grup: "bakim",
    kpi: { tur: "panel", kod: "bakim_geciken" },
    kpiBirimi: "iş",
    ek: true,
  },
  {
    id: "/atolye",
    baslik: "Atölye",
    altBaslik: "Atölye kabul ve onarım",
    ikon: BuildOutlined,
    yol: "/atolye",
    izin: "atolye.gor",
    grup: "bakim",
  },
  // --- Operasyon -----------------------------------------------------------
  {
    id: "/operasyon",
    baslik: "Operasyon Merkezi",
    altBaslik: "Tayin ve SLA takibi",
    ikon: AlertOutlined,
    yol: "/operasyon",
    izin: "operasyon.gor",
    grup: "operasyon",
  },
  {
    id: "/zaman-takibi",
    baslik: "Zaman Takibi",
    ikon: ClockCircleOutlined,
    yol: "/zaman-takibi",
    izin: "servis_rapor.gor",
    grup: "operasyon",
  },
  // --- Depo ve Kiralama ----------------------------------------------------
  {
    id: "/kiralamalar",
    baslik: "Kiralamalar",
    ikon: InboxOutlined,
    yol: "/kiralamalar",
    izin: "kiralama.gor",
    grup: "depo",
  },
  {
    id: "/kiralik-envanter",
    baslik: "Kiralık Envanter",
    ikon: DatabaseOutlined,
    yol: "/kiralik-envanter",
    izin: "kiralama.gor",
    grup: "depo",
  },
  {
    id: "/yedek-parca",
    baslik: "Yedek Parça",
    ikon: AppstoreOutlined,
    yol: "/yedek-parca",
    izin: "parca.gor",
    grup: "depo",
  },
  // --- Raporlar ve Maliyet -------------------------------------------------
  {
    id: "/servis-raporlari",
    baslik: "Servis Raporları",
    ikon: FundOutlined,
    yol: "/servis-raporlari",
    izin: "servis_rapor.gor",
    grup: "raporlar",
  },
  {
    id: "/servis-maliyet",
    baslik: "Servis Maliyet",
    ikon: WalletOutlined,
    yol: "/servis-maliyet",
    izin: "maliyet.gor",
    grup: "raporlar",
  },
  {
    id: "/fatura-devri",
    baslik: "Fatura Devri",
    ikon: FileDoneOutlined,
    yol: "/fatura-devri",
    izin: "tahsilat.gor",
    grup: "raporlar",
  },
  // KARARLAR 2026-11-09 S2.2 / S4.2: satışçının kendi teklif sonuçları ve
  // kabul edilen satışlarının servis işi aşamaları (menüde Satış ve Müşteri).
  {
    id: "/tekliflerim",
    baslik: "Tekliflerim",
    altBaslik: "Sonuç ve kazanma oranı",
    ikon: ProfileOutlined,
    yol: "/tekliflerim",
    izin: "teklif.gor",
    grup: "raporlar",
  },
  {
    id: "/satislarim",
    baslik: "Satışlarımın Durumu",
    altBaslik: "Kurulum ve teslimat aşamaları",
    ikon: CheckSquareOutlined,
    yol: "/satislarim",
    izin: "teklif.gor",
    grup: "raporlar",
  },
  {
    id: "/servis-ana-veri",
    baslik: "Ana Veri Kalitesi",
    ikon: AuditOutlined,
    yol: "/servis-ana-veri",
    // Dalga 3 (TS-188): Veri Kalitesi sayfası `servis_rapor.gor` ile de açılır.
    izin: ["hesap.birlestir", "servis_rapor.gor"],
    grup: "raporlar",
  },
  // --- İnsan Kaynakları ----------------------------------------------------
  {
    id: "/personel",
    baslik: "Personel",
    ikon: TeamOutlined,
    yol: "/personel",
    izin: "personel.gor",
    grup: "ik",
  },
  {
    id: "/egitim",
    baslik: "Eğitim ve Gelişim",
    ikon: ReadOutlined,
    yol: "/egitim",
    izin: "egitim.gor",
    grup: "ik",
  },
  {
    id: "/gelisim-kartim",
    baslik: "Gelişim Kartım",
    ikon: IdcardOutlined,
    yol: "/gelisim-kartim",
    izin: "egitim.kendim",
    grup: "ik",
  },
  {
    id: "/ik-belgeler",
    baslik: "Bordro ve Belgeler",
    altBaslik: "Gönder, imzayı takip et",
    ikon: SolutionOutlined,
    yol: "/ik-belgeler",
    izin: ["bordro.yonet", "ik_belge.yonet"],
    grup: "ik",
  },
  {
    // Herkese açık: kişi kendi bordrosunu/belgesini görür (izin değil kimlik, §11).
    // KARARLAR 2026-11-20 §7: herkes kendi iznini girer; onaycı "Onayımda" sekmesinde.
    id: "/izin-talepleri",
    baslik: "İzin Talepleri",
    altBaslik: "İzin iste, onayla",
    ikon: CalendarOutlined,
    yol: "/izin-talepleri",
    izin: [],
    grup: "ik",
  },
  {
    id: "/belgelerim",
    baslik: "Belgelerim",
    altBaslik: "Bordro ve imzalanacak belgeler",
    ikon: FileDoneOutlined,
    yol: "/belgelerim",
    izin: [],
    grup: "ik",
  },  // --- Mobilite (canlı ekranlar; adlar değişmez) ---------------------------
  { id: "/panel", baslik: "Panel", altBaslik: "Mobilite özeti", ikon: PieChartOutlined, yol: "/panel", izin: "rapor.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/hesaplar", baslik: "Hesaplar", ikon: TeamOutlined, yol: "/hesaplar", izin: "hesap.gor", grup: "mobilite" },
  { id: "/urunler", baslik: "Ürün Kataloğu", ikon: ContainerOutlined, yol: "/urunler", izin: "urun.gor", grup: "mobilite" },
  { id: "/cihazlar", baslik: "Cihazlar", ikon: HddOutlined, yol: "/cihazlar", izin: "cihaz.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/stok", baslik: "Stok ve Transfer", ikon: ContainerOutlined, yol: "/stok", izin: "cihaz.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/hatlar", baslik: "Hatlar (SIM)", ikon: WifiOutlined, yol: "/hatlar", izin: "hat.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/araclar", baslik: "Araçlar", ikon: CarOutlined, yol: "/araclar", izin: "arac.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/is-emirleri", baslik: "İş Emirleri", ikon: UnorderedListOutlined, yol: "/is-emirleri", izin: "isemri.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/hakedis", baslik: "Hak Ediş", ikon: DollarOutlined, yol: "/hakedis", izin: "hakedis.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/teklifler", baslik: "Teklifler", ikon: FileTextOutlined, yol: "/teklifler", izin: "teklif.gor", grup: "mobilite" },
  { id: "/siparisler", baslik: "Siparişler", ikon: ShoppingCartOutlined, yol: "/siparisler", izin: "siparis.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/abonelikler", baslik: "Abonelikler", ikon: SyncOutlined, yol: "/abonelikler", izin: "abonelik.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/rma", baslik: "RMA / Servis", ikon: SolutionOutlined, yol: "/rma", izin: "rma.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/satinalma", baslik: "Satın Alma", ikon: ShoppingOutlined, yol: "/satinalma", izin: "satinalma.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/tahsilat", baslik: "Tahsilat", ikon: DollarOutlined, yol: "/tahsilat", izin: "tahsilat.gor", grup: "mobilite", yalnizMobilite: true },
  { id: "/raporlar", baslik: "Raporlar", ikon: BarChartOutlined, yol: "/raporlar", izin: "rapor.gor", grup: "mobilite", yalnizMobilite: true },
  // --- Sistem Yönetimi -----------------------------------------------------
  {
    id: "/ice-aktarma",
    baslik: "İçe Aktarma",
    ikon: ImportOutlined,
    yol: "/ice-aktarma",
    izin: ["hesap.yaz", "cihaz.yaz", "hat.yaz", "arac.yaz", "hakedis.yaz", "abonelik.yaz"],
    grup: "sistem",
  },
  { id: "/kvkk", baslik: "KVKK", ikon: SafetyCertificateOutlined, yol: "/kvkk", izin: "kvkk.yonet", grup: "sistem" },
  { id: "/kullanicilar", baslik: "Kullanıcılar", ikon: UserOutlined, yol: "/kullanicilar", izin: "sistem.kullanici", grup: "sistem" },
  { id: "/ayarlar", baslik: "Parametreler", ikon: SettingOutlined, yol: "/ayarlar", izin: "sistem.ayar", grup: "sistem" },
  { id: "/denetim", baslik: "Denetim İzi", ikon: AuditOutlined, yol: "/denetim", izin: "sistem.denetim", grup: "sistem" },
];

/** Uygulamanın izni: dizi = "herhangi biri"; boş dizi = herkese açık. */
export function uygulamaYetkili(u: Pick<Uygulama, "izin">, yetkili: Yetkili): boolean {
  if (Array.isArray(u.izin)) return u.izin.length === 0 || u.izin.some((i) => yetkili(i));
  return yetkili(u.izin);
}

/** Sayfa kutucukları (ek süzgeç kutucukları hariç) — eski `MENU`'nün karşılığı. */
export const SAYFALAR: Uygulama[] = UYGULAMALAR.filter((u) => !u.ek);

/** `/servis-isleri/12` gibi alt yollarda da doğru uygulama bulunsun. */
export function yoldanUygulama(yol: string): Uygulama | undefined {
  return SAYFALAR.filter((u) => yol === u.yol || yol.startsWith(`${u.yol}/`)).sort(
    (a, b) => b.yol.length - a.yol.length,
  )[0];
}

/**
 * Girişte öne çıkacak sayfa (plan §1.10, KD-30) — eski açılış kuralı aynen.
 * Açılış artık launchpad; bu yol yalnız hangi SEKMEYE kaydırılacağını
 * belirler (bkz. `acilisGrubu`).
 *
 * Sıra: `rapor.gor` → `/panel` · `zaman.yaz` ∧ ¬`servis.planla` →
 * `/benim-islerim` · `takip.gor` → `/servis-paneli` · `egitim.kendim` →
 * `/gelisim-kartim` · değilse ilk yetkili sayfa. Hiçbiri yoksa null.
 */
export function acilisYolu(yetkili: Yetkili): string | null {
  if (yetkili("rapor.gor")) return "/panel";
  const yetkiliSayfa = (yol: string) =>
    SAYFALAR.some((u) => u.yol === yol && uygulamaYetkili(u, yetkili));
  const kurallar: [boolean, string][] = [
    [yetkili("zaman.yaz") && !yetkili("servis.planla"), "/benim-islerim"],
    [yetkili("takip.gor"), "/servis-paneli"],
    [yetkili("egitim.kendim"), "/gelisim-kartim"],
  ];
  for (const [uygun, yol] of kurallar) {
    if (uygun && yetkiliSayfa(yol)) return yol;
  }
  return SAYFALAR.find((u) => uygulamaYetkili(u, yetkili))?.yol ?? null;
}

/** Rol bazlı açılış kuralının launchpad karşılığı: kaydırılacak grup. */
export function acilisGrubu(yetkili: Yetkili): GrupKodu | null {
  const yol = acilisYolu(yetkili);
  if (!yol) return null;
  return SAYFALAR.find((u) => u.yol === yol)?.grup ?? null;
}

/** Kullanıcının görebildiği gruplar ve kutucukları (boş grup çizilmez). */
export function gorunurGruplar(yetkili: Yetkili): { grup: Grup; uygulamalar: Uygulama[] }[] {
  return GRUPLAR.map((grup) => ({
    grup,
    uygulamalar: UYGULAMALAR.filter((u) => u.grup === grup.kod && uygulamaYetkili(u, yetkili)),
  })).filter((g) => g.uygulamalar.length > 0);
}
