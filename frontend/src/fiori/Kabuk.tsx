/**
 * Fiori kabuğu (Shell Bar) — rehber §1. Tüm oturumlu sayfaları sarar.
 *
 * Sol: geri ok (uygulama içindeyken), Denge kare logosu, uygulama başlığı ▾
 * (açılır menü: aynı gruptaki uygulamalar + Başlangıç sayfası + tüm gruplar).
 * Orta: yuvarlatılmış arama ("Arama yeri: "Uygulamalar""). Sağ: uyarı zili
 * ve kullanıcı baş harfleri dairesi (rol, bildirim tercihleri, parola
 * değiştir, çıkış). Sol kenar menüsü YOK; gezinme launchpad ve başlık menüsüyle.
 * 375 px'te arama ikona düşer ve dokununca başlığın altında tam genişlik açılır.
 */
import {
  AppstoreOutlined,
  BellOutlined,
  CloseOutlined,
  DownOutlined,
  HomeOutlined,
  KeyOutlined,
  LeftOutlined,
  LogoutOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { Dropdown, Modal, Tag } from "antd";
import type { MenuProps } from "antd";
import { useEffect, useMemo, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { kapsamEtiketi, useAuth } from "../auth/AuthContext";
import AktifSayacBandi from "../components/AktifSayacBandi";
import BildirimTercihleriPenceresi, { BILDIRIM_TERCIHLERI_ETKIN } from "../components/BildirimTercihleri";
import GlobalSearch from "../components/GlobalSearch";
import UyariZili from "../components/UyariZili";
import ParolaDegistirPage from "../pages/ParolaDegistirPage";
import { GRUPLAR, SAYFALAR, gorunurGruplar, uygulamaYetkili, yoldanUygulama } from "./uygulamalar";

const LAUNCHPAD_YOLLARI = new Set(["/", "/baslangic"]);
const BASLANGIC = "Başlangıç sayfası";

/** Ad ve soyadın baş harfleri, Türkçe büyük harfle (ör. "ışık öz" → "IÖ"). */
function basHarfler(ad: string | undefined): string {
  const parcalar = (ad ?? "").trim().split(/\s+/).filter(Boolean);
  if (parcalar.length === 0) return "?";
  const ilk = parcalar[0][0];
  const son = parcalar.length > 1 ? parcalar[parcalar.length - 1][0] : "";
  return `${ilk}${son}`.toLocaleUpperCase("tr");
}

export default function Kabuk() {
  const { kullanici, cikisYap, yetkili } = useAuth();
  const konum = useLocation();
  const navigate = useNavigate();
  const [bildirimAcik, setBildirimAcik] = useState(false);
  const [parolaAcik, setParolaAcik] = useState(false);
  const [aramaAcik, setAramaAcik] = useState(false);
  // TS-200: pencere bayrakla açılır; yalnız servis kullanıcısı.
  const bildirimTercihi = BILDIRIM_TERCIHLERI_ETKIN && yetkili("servis.gor");

  const launchpadda = LAUNCHPAD_YOLLARI.has(konum.pathname);
  const uygulama = launchpadda ? undefined : yoldanUygulama(konum.pathname);
  const baslik = launchpadda ? BASLANGIC : (uygulama?.baslik ?? "Denge ERP");

  useEffect(() => {
    document.title = `${baslik} – Denge ERP`;
  }, [baslik]);

  // Sayfa değişince mobil arama satırı kapansın.
  useEffect(() => setAramaAcik(false), [konum.pathname]);

  const baslikMenusu = useMemo<NonNullable<MenuProps["items"]>>(() => {
    const gruplar = gorunurGruplar(yetkili);
    const tumGruplar: NonNullable<MenuProps["items"]> = gruplar.map(({ grup, uygulamalar }) => ({
      key: `grup:${grup.kod}`,
      label: grup.baslik,
      children: uygulamalar
        .filter((u) => u.kpi?.tur !== "uyari")
        .map((u) => ({
        key: `${grup.kod}|${u.id}`,
        label: <Link to={u.yol}>{u.baslik}</Link>,
      })),
    }));
    const giris = {
      key: "baslangic",
      icon: <HomeOutlined />,
      label: <Link to="/">{BASLANGIC}</Link>,
    };
    if (!uygulama) return [giris, { type: "divider" as const }, ...tumGruplar];
    const grupAdi = GRUPLAR.find((g) => g.kod === uygulama.grup)?.baslik;
    const kardesler = SAYFALAR.filter(
      (u) => u.grup === uygulama.grup && uygulamaYetkili(u, yetkili),
    ).map((u) => ({
      key: `kardes|${u.id}`,
      label: <Link to={u.yol}>{u.baslik}</Link>,
    }));
    return [
      { key: "grup-baslik", type: "group" as const, label: grupAdi, children: kardesler },
      { type: "divider" as const },
      giris,
      {
        key: "tum",
        icon: <AppstoreOutlined />,
        label: "Tüm uygulamalar",
        children: tumGruplar,
      },
    ];
  }, [uygulama, yetkili]);

  const kapsam = kapsamEtiketi(kullanici?.role.scope);
  const kullaniciMenusu: NonNullable<MenuProps["items"]> = [
    {
      key: "kim",
      disabled: true,
      label: (
        <div style={{ lineHeight: 1.4, paddingBlock: 2 }}>
          <div style={{ fontWeight: 600, color: "#32363a" }}>{kullanici?.full_name}</div>
          <div style={{ fontSize: 12 }}>
            {kullanici?.role.name}
            {kapsam && <Tag style={{ marginInlineStart: 8 }}>{kapsam}</Tag>}
          </div>
        </div>
      ),
    },
    { type: "divider" },
    ...(bildirimTercihi
      ? [
          {
            key: "bildirim",
            icon: <BellOutlined />,
            label: "Bildirim tercihleri",
            onClick: () => setBildirimAcik(true),
          },
        ]
      : []),
    {
      key: "parola",
      icon: <KeyOutlined />,
      label: "Parola değiştir",
      onClick: () => setParolaAcik(true),
    },
    {
      key: "cikis",
      icon: <LogoutOutlined />,
      label: "Çıkış yap",
      onClick: () => void cikisYap(),
    },
  ];

  return (
    <div className="fiori-uygulama">
      <header className="fiori-kabuk">
        <div className="fiori-kabuk-sol">
          {!launchpadda && (
            <button
              type="button"
              className="fiori-kabuk-dugme"
              aria-label="Geri"
              title="Geri"
              onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/"))}
            >
              <LeftOutlined />
            </button>
          )}
          <Link to="/" className="fiori-kabuk-logo" title={BASLANGIC} aria-label={BASLANGIC}>
            <img src="/brand/favicon.png" alt="Denge" />
          </Link>
          <Dropdown menu={{ items: baslikMenusu }} trigger={["click"]} placement="bottomLeft">
            <button type="button" className="fiori-kabuk-baslik" aria-haspopup="menu">
              <span className="fiori-kabuk-baslik-metin">{baslik}</span>
              <DownOutlined style={{ fontSize: 11 }} />
            </button>
          </Dropdown>
        </div>

        <div className="fiori-kabuk-orta">
          <GlobalSearch />
        </div>

        <div className="fiori-kabuk-sag">
          <button
            type="button"
            className="fiori-kabuk-dugme fiori-kabuk-arama-ikon"
            aria-label={aramaAcik ? "Aramayı kapat" : "Ara"}
            onClick={() => setAramaAcik((a) => !a)}
          >
            {aramaAcik ? <CloseOutlined /> : <SearchOutlined />}
          </button>
          <span className="fiori-kabuk-dugme">
            <UyariZili />
          </span>
          <Dropdown menu={{ items: kullaniciMenusu }} trigger={["click"]} placement="bottomRight">
            <button
              type="button"
              className="fiori-kabuk-avatar"
              aria-label={`Kullanıcı menüsü: ${kullanici?.full_name ?? ""}`}
              title={kullanici?.full_name}
            >
              {basHarfler(kullanici?.full_name)}
            </button>
          </Dropdown>
        </div>
      </header>

      {aramaAcik && (
        <div className="fiori-kabuk-mobil-arama">
          <GlobalSearch otomatikOdak onSecildi={() => setAramaAcik(false)} />
        </div>
      )}

      <main className={launchpadda ? "fiori-icerik fiori-icerik-lp" : "fiori-icerik"}>
        {/* TS-077: açık sayaç her sayfada görünür; `zaman.yaz` yoksa ne çizer ne istek atar. */}
        <div className="fiori-sayac-bandi">
          <AktifSayacBandi />
        </div>
        <Outlet />
      </main>

      {bildirimTercihi && (
        <BildirimTercihleriPenceresi acik={bildirimAcik} kapat={() => setBildirimAcik(false)} />
      )}
      <Modal
        open={parolaAcik}
        onCancel={() => setParolaAcik(false)}
        footer={null}
        destroyOnHidden
        width={500}
        styles={{ body: { padding: 0 } }}
      >
        <ParolaDegistirPage zorunlu={false} />
      </Modal>
    </div>
  );
}
