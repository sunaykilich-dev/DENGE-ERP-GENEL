import {
  AlertOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BarChartOutlined,
  BuildOutlined,
  CalendarOutlined,
  CarOutlined,
  ContainerOutlined,
  CheckSquareOutlined,
  ClusterOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DollarOutlined,
  FileTextOutlined,
  FieldTimeOutlined,
  HddOutlined,
  IdcardOutlined,
  ImportOutlined,
  InboxOutlined,
  LogoutOutlined,
  PieChartOutlined,
  ProfileOutlined,
  ReadOutlined,
  SafetyCertificateOutlined,
  ScheduleOutlined,
  SettingOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  SolutionOutlined,
  SyncOutlined,
  TeamOutlined,
  ToolOutlined,
  UnorderedListOutlined,
  UserOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import { Dropdown, Layout, Menu, Tag, Typography } from "antd";
import type { MenuProps } from "antd";
import { useMemo } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import AktifSayacBandi from "./AktifSayacBandi";
import GlobalSearch from "./GlobalSearch";
import UyariZili from "./UyariZili";
import { marka } from "../theme";

const { Header, Sider, Content } = Layout;

/** Yan menü genişliği. Başlıktaki marka bloğu da bunu kullanır: arama kutusu
 *  tam olarak içeriğin başladığı yerden başlasın diye. */
const KENAR_GENISLIK = 228;
const BASLIK_PADDING = 20;

/** Menü grupları (teknik servis plan §1.10, KD-29). Canlı kalemler grupsuz. */
const GRUPLAR: Record<string, React.ReactNode> = {
  "Teknik Servis": <ToolOutlined />,
  "İnsan Kaynakları": <IdcardOutlined />,
};

export interface MenuKalemi {
  key: string;
  label: string;
  icon: React.ReactNode;
  /** Tek izin ya da "bunlardan herhangi biri" listesi. */
  izin: string | string[];
  /**
   * İsteğe bağlı grup: aynı gruptaki kalemler AntD alt menüsü olarak çizilir.
   * Grup başlığı ancak içinde en az bir yetkili kalem varsa görünür; böylece
   * teknik servis yetkisi olmayan mobilite kullanıcısı menüde hiçbir
   * değişiklik görmez.
   */
  grup?: keyof typeof GRUPLAR;
}

/**
 * Menü tanımı. Her kalem gerektirdiği izni taşır; kullanıcıda yoksa kalem
 * GÖRÜNMEZ. Bu yalnız görsel bir kısıtlamadır — sunucu her uçta kendi
 * kontrolünü ayrıca yapar (bkz. require_permission).
 *
 * Canlı kalemler AYNI sırada ve grupsuz kalır ("İş Emirleri" = mobilite,
 * "RMA / Servis" adları değişmez). Teknik servis kalemleri Dalga 0/1/2
 * ekranlarıdır; sonraki dalgaların kalemleri kendi rotalarıyla eklenir —
 * rotası olmayan kalem tıklanınca açılışa geri düşerdi.
 */
export const MENU: MenuKalemi[] = [
  { key: "/", label: "Panel", icon: <PieChartOutlined />, izin: "rapor.gor" },
  { key: "/hesaplar", label: "Hesaplar", icon: <TeamOutlined />, izin: "hesap.gor" },
  { key: "/urunler", label: "Ürün Kataloğu", icon: <ContainerOutlined />, izin: "urun.gor" },
  { key: "/cihazlar", label: "Cihazlar", icon: <HddOutlined />, izin: "cihaz.gor" },
  { key: "/stok", label: "Stok ve Transfer", icon: <ContainerOutlined />, izin: "cihaz.gor" },
  { key: "/hatlar", label: "Hatlar (SIM)", icon: <WifiOutlined />, izin: "hat.gor" },
  { key: "/araclar", label: "Araçlar", icon: <CarOutlined />, izin: "arac.gor" },
  { key: "/is-emirleri", label: "İş Emirleri", icon: <ToolOutlined />, izin: "isemri.gor" },
  { key: "/hakedis", label: "Hak Ediş", icon: <DollarOutlined />, izin: "hakedis.gor" },
  { key: "/teklifler", label: "Teklifler", icon: <FileTextOutlined />, izin: "teklif.gor" },
  { key: "/siparisler", label: "Siparişler", icon: <ShoppingCartOutlined />, izin: "siparis.gor" },
  { key: "/abonelikler", label: "Abonelikler", icon: <SyncOutlined />, izin: "abonelik.gor" },
  { key: "/rma", label: "RMA / Servis", icon: <SolutionOutlined />, izin: "rma.gor" },
  {
    key: "/satinalma",
    label: "Satın Alma",
    icon: <ShoppingOutlined />,
    izin: "satinalma.gor",
  },
  { key: "/tahsilat", label: "Tahsilat", icon: <DollarOutlined />, izin: "tahsilat.gor" },
  {
    key: "/ice-aktarma",
    label: "İçe Aktarma",
    icon: <ImportOutlined />,
    izin: ["hesap.yaz", "cihaz.yaz", "hat.yaz", "arac.yaz", "hakedis.yaz", "abonelik.yaz"],
  },
  { key: "/gorevler", label: "Görevler", icon: <CheckSquareOutlined />, izin: "gorev.gor" },
  { key: "/raporlar", label: "Raporlar", icon: <BarChartOutlined />, izin: "rapor.gor" },
  // --- Teknik Servis (plan §1.10) ------------------------------------------
  {
    key: "/servis-paneli",
    label: "Servis Paneli",
    icon: <DashboardOutlined />,
    izin: "servis.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/operasyon",
    label: "Operasyon Merkezi",
    icon: <AlertOutlined />,
    izin: "operasyon.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/servis-isleri",
    label: "Servis İşleri",
    icon: <UnorderedListOutlined />,
    izin: "servis.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/servis-planlama",
    label: "Planlama",
    icon: <CalendarOutlined />,
    izin: "servis.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/benim-islerim",
    label: "Benim İşlerim",
    icon: <FieldTimeOutlined />,
    izin: "zaman.yaz",
    grup: "Teknik Servis",
  },
  {
    key: "/servis-ekipman",
    label: "Ekipman Kütüğü",
    icon: <ClusterOutlined />,
    izin: "ekipman.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/bakim",
    label: "Planlı Bakım",
    icon: <ScheduleOutlined />,
    izin: "bakim.gor",
    grup: "Teknik Servis",
  },
  // --- Dalga 2 (D2-S) ---
  {
    key: "/atolye",
    label: "Atölye",
    icon: <BuildOutlined />,
    izin: "atolye.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/kiralamalar",
    label: "Kiralamalar",
    icon: <InboxOutlined />,
    izin: "kiralama.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/kiralik-envanter",
    label: "Kiralık Envanter",
    icon: <DatabaseOutlined />,
    izin: "kiralama.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/yedek-parca",
    label: "Yedek Parça",
    icon: <AppstoreOutlined />,
    izin: "parca.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/servis-maliyet",
    label: "Servis Maliyet",
    icon: <DollarOutlined />,
    izin: "maliyet.gor",
    grup: "Teknik Servis",
  },
  {
    key: "/servis-ana-veri",
    label: "Ana Veri Kalitesi",
    icon: <AuditOutlined />,
    izin: "hesap.birlestir",
    grup: "Teknik Servis",
  },
  {
    key: "/servis-tanimlar",
    label: "Servis Tanımları",
    icon: <ProfileOutlined />,
    izin: ["servis.tanim", "operasyon.yonet"],
    grup: "Teknik Servis",
  },
  // --- İnsan Kaynakları ----------------------------------------------------
  {
    key: "/personel",
    label: "Personel",
    icon: <TeamOutlined />,
    izin: "personel.gor",
    grup: "İnsan Kaynakları",
  },
  {
    key: "/egitim",
    label: "Eğitim ve Gelişim",
    icon: <ReadOutlined />,
    izin: "egitim.gor",
    grup: "İnsan Kaynakları",
  },
  {
    key: "/gelisim-kartim",
    label: "Gelişim Kartım",
    icon: <IdcardOutlined />,
    izin: "egitim.kendim",
    grup: "İnsan Kaynakları",
  },
  {
    key: "/kvkk",
    label: "KVKK",
    icon: <SafetyCertificateOutlined />,
    izin: "kvkk.yonet",
  },
  {
    key: "/kullanicilar",
    label: "Kullanıcılar",
    icon: <UserOutlined />,
    izin: "sistem.kullanici",
  },
  {
    key: "/ayarlar",
    label: "Parametreler",
    icon: <SettingOutlined />,
    izin: "sistem.ayar",
  },
  {
    key: "/denetim",
    label: "Denetim İzi",
    icon: <AuditOutlined />,
    izin: "sistem.denetim",
  },
];

type Yetkili = (...kodlar: string[]) => boolean;

function kalemYetkili(m: MenuKalemi, yetkili: Yetkili): boolean {
  return Array.isArray(m.izin) ? m.izin.some((i) => yetkili(i)) : yetkili(m.izin);
}

/**
 * Girişte açılacak sayfa (plan §1.10, KD-30). `/` canlı Panel'dir ve
 * `rapor.gor` ister; servis rolleri bu izni almaz (KD-06). Kural olmasa
 * teknisyen girişte 403 yağmuru gören boş bir panele düşerdi.
 *
 * Sıra: `rapor.gor` → `/` (değişmez) · `zaman.yaz` ∧ ¬`servis.planla` →
 * `/benim-islerim` · `servis.gor` → `/servis-paneli` · `egitim.kendim` →
 * `/gelisim-kartim` · değilse ilk yetkili menü kalemi. Hedef yalnız MENÜDE
 * tanımlı (rotası olan) bir yolsa seçilir; rotası henüz olmayan bir dalga
 * ekranına yönlendirip `*` → `/` döngüsüne düşülmez. Hiçbiri yoksa null.
 */
export function acilisYolu(yetkili: Yetkili): string | null {
  if (yetkili("rapor.gor")) return "/";
  const menude = (yol: string) =>
    MENU.some((m) => m.key === yol && kalemYetkili(m, yetkili));
  const kurallar: [boolean, string][] = [
    [yetkili("zaman.yaz") && !yetkili("servis.planla"), "/benim-islerim"],
    [yetkili("servis.gor"), "/servis-paneli"],
    [yetkili("egitim.kendim"), "/gelisim-kartim"],
  ];
  for (const [uygun, yol] of kurallar) {
    if (uygun && menude(yol)) return yol;
  }
  return MENU.find((m) => m.key !== "/" && kalemYetkili(m, yetkili))?.key ?? null;
}

/** `/servis-isleri/12` gibi alt yollarda da menü kalemi seçili görünsün. */
function seciliAnahtar(yol: string): string {
  const aday = MENU.filter(
    (m) => m.key !== "/" && (yol === m.key || yol.startsWith(`${m.key}/`)),
  ).sort((a, b) => b.key.length - a.key.length)[0];
  return aday?.key ?? yol;
}

const KAPSAM_ETIKETI: Record<string, string> = {
  KENDI_MUSTERILERI: "yalnız kendi müşterileri",
  KENDI_BIRIMI: "servis işlerinde kendi birimi",
  KENDI_ISLERI: "servis işlerinde kendi işleri",
};

export default function AppLayout() {
  const { kullanici, cikisYap, yetkili } = useAuth();
  const konum = useLocation();

  const kalemler = useMemo(() => {
    const sonuc: NonNullable<MenuProps["items"]> = [];
    const cizilenGruplar = new Set<string>();
    for (const m of MENU) {
      if (!m.grup) {
        if (kalemYetkili(m, yetkili)) {
          sonuc.push({ key: m.key, icon: m.icon, label: <Link to={m.key}>{m.label}</Link> });
        }
        continue;
      }
      if (cizilenGruplar.has(m.grup)) continue;
      cizilenGruplar.add(m.grup);
      const alt = MENU.filter((k) => k.grup === m.grup && kalemYetkili(k, yetkili)).map((k) => ({
        key: k.key,
        icon: k.icon,
        label: <Link to={k.key}>{k.label}</Link>,
      }));
      // Yetkili kalemi olmayan grup başlığı hiç çizilmez.
      if (alt.length) {
        sonuc.push({ key: `grup:${m.grup}`, icon: GRUPLAR[m.grup], label: m.grup, children: alt });
      }
    }
    return sonuc;
  }, [yetkili]);

  const secili = seciliAnahtar(konum.pathname);
  const acikGrup = MENU.find((m) => m.key === secili)?.grup;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          paddingInline: BASLIK_PADDING,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", minWidth: 0, flex: 1 }}>
          {/* Marka bloğu yan menüyle aynı genişlikte; aramanın sol kenarı
              içeriğin sol kenarıyla hizalanıyor. Dar ekranda bu genişlik
              SABİT KALMAMALI: 375 px'te başlık taşıyor, arama kutusu ve
              kullanıcı menüsü ekranın dışında kalıyordu — telefonda ÇIKIŞ
              YAPILAMIYORDU (sayfa yatay da kaymıyor). */}
          <div
            className="baslik-marka"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexShrink: 0,
            }}
          >
            {/* Mono sürüm `currentColor` kullanıyor ve <img> içinde siyaha
                düşüyordu; lacivert zeminde okunmuyordu. */}
            <img
              src="/brand/denge-mobilite-beyaz.svg"
              alt="Denge Mobilite"
              style={{ height: 24 }}
            />
            <Typography.Text style={{ color: "#fff", letterSpacing: "-0.02em", fontWeight: 600 }}>
              ERP
            </Typography.Text>
          </div>
          <GlobalSearch />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 18, flexShrink: 0 }}>
        <UyariZili />
        <Dropdown
          menu={{
            items: [
              {
                key: "rol",
                disabled: true,
                label: (
                  <span>
                    {kullanici?.role.name}
                    {kullanici && KAPSAM_ETIKETI[kullanici.role.scope] && (
                      <Tag style={{ marginInlineStart: 8 }}>
                        {KAPSAM_ETIKETI[kullanici.role.scope]}
                      </Tag>
                    )}
                  </span>
                ),
              },
              { type: "divider" },
              {
                key: "cikis",
                icon: <LogoutOutlined />,
                label: "Çıkış yap",
                onClick: () => void cikisYap(),
              },
            ],
          }}
        >
          <span
            style={{
              color: "#fff",
              cursor: "pointer",
              flexShrink: 0,
              marginInlineStart: 12,
              whiteSpace: "nowrap",
            }}
          >
            {/* Ad dar ekranda gizlenir, ikon kalır: menüye erişim kaybolmasın. */}
            <UserOutlined /> <span className="baslik-kullanici">{kullanici?.full_name}</span>
          </span>
        </Dropdown>
        </div>
      </Header>
      <Layout>
        <Sider width={KENAR_GENISLIK} breakpoint="lg" collapsedWidth={56}>
          <Menu
            mode="inline"
            selectedKeys={[secili]}
            defaultOpenKeys={acikGrup ? [`grup:${acikGrup}`] : []}
            items={kalemler}
            style={{ height: "100%", borderInlineEnd: `1px solid ${marka.ruleSoft}` }}
          />
        </Sider>
        <Content style={{ padding: 20 }}>
          {/* TS-077: açık sayaç her sayfada görünür; `zaman.yaz` yoksa ne çizer ne istek atar. */}
          <AktifSayacBandi />
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
