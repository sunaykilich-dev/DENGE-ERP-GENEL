import {
  AuditOutlined,
  BarChartOutlined,
  CarOutlined,
  ContainerOutlined,
  CheckSquareOutlined,
  DollarOutlined,
  FileTextOutlined,
  HddOutlined,
  ImportOutlined,
  LogoutOutlined,
  PieChartOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  SolutionOutlined,
  SyncOutlined,
  TeamOutlined,
  ToolOutlined,
  UserOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import { Dropdown, Layout, Menu, Tag, Typography } from "antd";
import { useMemo } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import GlobalSearch from "./GlobalSearch";
import UyariZili from "./UyariZili";
import { marka } from "../theme";

const { Header, Sider, Content } = Layout;

/** Yan menü genişliği. Başlıktaki marka bloğu da bunu kullanır: arama kutusu
 *  tam olarak içeriğin başladığı yerden başlasın diye. */
const KENAR_GENISLIK = 228;
const BASLIK_PADDING = 20;

/**
 * Menü tanımı. Her kalem gerektirdiği izni taşır; kullanıcıda yoksa kalem
 * GÖRÜNMEZ. Bu yalnız görsel bir kısıtlamadır — sunucu her uçta kendi
 * kontrolünü ayrıca yapar (bkz. require_permission).
 */
const MENU: {
  key: string;
  label: string;
  icon: React.ReactNode;
  /** Tek izin ya da "bunlardan herhangi biri" listesi. */
  izin: string | string[];
}[] = [
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

export default function AppLayout() {
  const { kullanici, cikisYap, yetkili } = useAuth();
  const konum = useLocation();

  const kalemler = useMemo(
    () =>
      MENU.filter((m) =>
        Array.isArray(m.izin) ? m.izin.some((i) => yetkili(i)) : yetkili(m.izin),
      ).map((m) => ({
        key: m.key,
        icon: m.icon,
        label: <Link to={m.key}>{m.label}</Link>,
      })),
    [yetkili],
  );

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
                    {kullanici?.role.scope === "KENDI_MUSTERILERI" && (
                      <Tag style={{ marginInlineStart: 8 }}>yalnız kendi müşterileri</Tag>
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
            selectedKeys={[konum.pathname]}
            items={kalemler}
            style={{ height: "100%", borderInlineEnd: `1px solid ${marka.ruleSoft}` }}
          />
        </Sider>
        <Content style={{ padding: 20 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
