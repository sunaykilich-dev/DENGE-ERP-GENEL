/**
 * Uygulama kabuğu — Logo CRM kurgusu (KARARLAR 2026-11-04 §1, §2, §5).
 *
 * Üst çubuk (koyu lacivert): menü daralt/aç, Denge logosu, ŞİRKET SEÇİCİ
 * (renkli işaretle), genel arama (Ctrl+K), "+ Hızlı oluştur", uyarı zili,
 * kullanıcı menüsü. Sol: akordeon ana menü (`YanMenu`), mobilde çekmece.
 * İçerik: ekmek kırıntısı (Şirket › Bölüm › Alt bölüm › Sayfa), açık sayaç
 * bandı, sayfa. Fiori liste ekranlarının iç düzeni değişmez; yalnız çerçeve.
 *
 * Eski Fiori kabuğu (başlık ▾ menüsü + launchpad açılışı) kaldırıldı: ana
 * sayfa Ana Panel'dir, launchpad "Sistem › Uygulamalar (kutucuklar)" altında.
 */
import {
  BellOutlined,
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
  FileProtectOutlined,
  InboxOutlined,
  KeyOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ScheduleOutlined,
  SearchOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { Drawer, Dropdown, Modal, Skeleton, Spin, Tag } from "antd";
import type { MenuProps } from "antd";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { kapsamEtiketi, useAuth } from "../auth/AuthContext";
import { sirketRengi, useSirket } from "../auth/SirketContext";
import AktifSayacBandi from "../components/AktifSayacBandi";
import BildirimTercihleriPenceresi, { BILDIRIM_TERCIHLERI_ETKIN } from "../components/BildirimTercihleri";
import GlobalSearch, { type AranabilirMenuOgesi } from "../components/GlobalSearch";
import RotaKapisi from "../components/RotaKapisi";
import UyariZili from "../components/UyariZili";
import ParolaDegistirPage from "../pages/ParolaDegistirPage";
import { KPI_ADLARI, MENU_AGACI, aktifYaprak, gorunurMenu, yapraklar, type MenuYapragi } from "./menu";
import YanMenu from "./YanMenu";
import { yerelOku, yerelYaz } from "./yerelDepo";
import "./kabuk.css";

const LAUNCHPAD_YOLU = "/uygulamalar";
const ARAMA_KIMLIGI = "dk-genel-arama";
const SON_ACILAN_SAYISI = 5;

/** Ad ve soyadın baş harfleri, Türkçe büyük harfle (ör. "ışık öz" → "IÖ"). */
function basHarfler(ad: string | undefined): string {
  const parcalar = (ad ?? "").trim().split(/\s+/).filter(Boolean);
  if (parcalar.length === 0) return "?";
  const ilk = parcalar[0][0];
  const son = parcalar.length > 1 ? parcalar[parcalar.length - 1][0] : "";
  return `${ilk}${son}`.toLocaleUpperCase("tr");
}

const MOBIL_SORGU = "(max-width: 767px)";

/** Dar ekran (mobil çekmece) — matchMedia, sunucusuz ortamda masaüstü. */
function useMobil(): boolean {
  return useSyncExternalStore(
    (dinle) => {
      const m = window.matchMedia?.(MOBIL_SORGU);
      m?.addEventListener("change", dinle);
      return () => m?.removeEventListener("change", dinle);
    },
    () => window.matchMedia?.(MOBIL_SORGU).matches ?? false,
    () => false,
  );
}

/** Menü durumu: açık bölümler, daraltma, favoriler, son açılanlar (kullanıcı başına). */
function useMenuDurumu(kullaniciId: number | undefined) {
  const [daraltilmis, setDaraltilmis] = useState(() => yerelOku(kullaniciId, "menu.daraltilmis", false));
  const [acik, setAcik] = useState<Set<string>>(
    () => new Set(yerelOku<string[]>(kullaniciId, "menu.acik", [])),
  );
  const [favoriler, setFavoriler] = useState<string[]>(() => yerelOku(kullaniciId, "menu.favoriler", []));
  const [son, setSon] = useState<string[]>(() => yerelOku(kullaniciId, "menu.son", []));

  useEffect(() => yerelYaz(kullaniciId, "menu.daraltilmis", daraltilmis), [kullaniciId, daraltilmis]);
  useEffect(() => yerelYaz(kullaniciId, "menu.acik", [...acik]), [kullaniciId, acik]);
  useEffect(() => yerelYaz(kullaniciId, "menu.favoriler", favoriler), [kullaniciId, favoriler]);
  useEffect(() => yerelYaz(kullaniciId, "menu.son", son), [kullaniciId, son]);

  const bolumDegistir = useCallback((anahtar: string, istenen?: boolean) => {
    setAcik((eski) => {
      const acilsin = istenen ?? !eski.has(anahtar);
      if (acilsin === eski.has(anahtar)) return eski;
      const yeni = new Set(eski);
      if (acilsin) yeni.add(anahtar);
      else yeni.delete(anahtar);
      return yeni;
    });
  }, []);

  const favoriDegistir = useCallback((anahtar: string) => {
    setFavoriler((f) => (f.includes(anahtar) ? f.filter((x) => x !== anahtar) : [...f, anahtar]));
  }, []);

  const sonaEkle = useCallback((anahtar: string) => {
    setSon((s) => (s[0] === anahtar ? s : [anahtar, ...s.filter((x) => x !== anahtar)].slice(0, SON_ACILAN_SAYISI)));
  }, []);

  return { daraltilmis, setDaraltilmis, acik, bolumDegistir, favoriler, favoriDegistir, son, sonaEkle };
}

/** "DENGE MOBİLİTE" → "MOBİLİTE" (dar ekran etiketi). */
function kisaAd(ad: string): string {
  return ad.replace(/^DENGE\s+/i, "") || ad;
}

/** Şirket bilgisi gelene kadar menü yerine iskelet (B-05: başka şirketin bölümü görünmesin). */
function MenuIskeleti() {
  return (
    <div className="dk-menu" aria-busy="true" aria-label="Menü yükleniyor" style={{ padding: 16 }}>
      <Skeleton active title={false} paragraph={{ rows: 8, width: ["80%", "65%", "75%", "60%", "70%", "55%", "72%", "62%"] }} />
    </div>
  );
}

/** Üst çubukta şirket seçici; tek şirkette sabit etiket, uç yoksa hiç çizilmez. */
function SirketSecici({ mobil }: { mobil: boolean }) {
  const { destekleniyor, sirketler, aktif, degistir, degisiyor } = useSirket();
  if (!destekleniyor) return null;
  const isaret = <span className="dk-sirket-isaret" style={{ background: sirketRengi(aktif?.kod) }} aria-hidden />;
  // B-15: mobilde kod ("MOBILITE") değil, Türkçe kısa ad ("MOBİLİTE").
  const ad = aktif ? (mobil ? kisaAd(aktif.ad) : aktif.ad) : "Şirket seçin";
  if (sirketler.length <= 1) {
    return (
      <span className="dk-sirket sabit" title={aktif?.ad}>
        {isaret}
        <span className="dk-sirket-ad">{ad}</span>
      </span>
    );
  }
  const items: MenuProps["items"] = [
    { key: "baslik", type: "group", label: "Çalışılacak şirket" },
    ...sirketler.map((s) => ({
      key: s.kod,
      label: (
        <span className="dk-sirket-secenek">
          <span className="dk-sirket-isaret" style={{ background: sirketRengi(s.kod) }} aria-hidden />
          {s.ad}
          {s.kod === aktif?.kod && <CheckOutlined style={{ marginInlineStart: 8, color: "#0a6ed1" }} />}
        </span>
      ),
    })),
  ];
  return (
    <Dropdown
      menu={{ items, onClick: ({ key }) => degistir(String(key)), selectable: false }}
      trigger={["click"]}
      placement="bottomLeft"
      disabled={degisiyor}
    >
      <button
        type="button"
        className="dk-sirket"
        aria-haspopup="menu"
        aria-label={`Etkin şirket: ${aktif?.ad ?? "seçilmedi"}. Değiştirmek için açın.`}
        title="Şirket değiştir"
        style={{ borderColor: sirketRengi(aktif?.kod) }}
      >
        {isaret}
        <span className="dk-sirket-ad">{ad}</span>
        <DownOutlined style={{ fontSize: 10 }} />
      </button>
    </Dropdown>
  );
}

/** "+ Hızlı oluştur": mevcut oluşturma pencerelerini açar (yetkiye göre). */
function HizliOlustur({ mobil }: { mobil: boolean }) {
  const { yetkili } = useAuth();
  const konum = useLocation();
  const navigate = useNavigate();

  // Servis listesindeyken mevcut süzgeç korunur; yeni iş birim/türü oradan alır.
  const servisYolu = (ek: Record<string, string>) => {
    const p = new URLSearchParams(konum.pathname === "/servis-isleri" ? konum.search : "");
    for (const [k, v] of Object.entries(ek)) p.set(k, v);
    p.set("yeni", "1");
    return `/servis-isleri?${p.toString()}`;
  };

  const secenekler = [
    yetkili("servis.yaz") && {
      key: "servis",
      icon: <ToolOutlined />,
      label: "Yeni servis işi",
      yol: () => servisYolu({}),
    },
    yetkili("servis.yaz") && {
      key: "bakim-isi",
      icon: <FileProtectOutlined />,
      label: "Yeni bakım işi",
      yol: () => servisYolu({ tur: "PLANSIZ_BAKIM" }),
    },
    yetkili("bakim.yaz") && {
      key: "sozlesme",
      icon: <ScheduleOutlined />,
      label: "Yeni bakım sözleşmesi",
      yol: () => "/bakim?sekme=sozlesmeler&yeni=1",
    },
    yetkili("kiralama.yaz") && {
      key: "kiralama",
      icon: <InboxOutlined />,
      label: "Yeni kiralama",
      yol: () => "/kiralamalar?yeni=1",
    },
  ].filter(Boolean) as { key: string; icon: React.ReactNode; label: string; yol: () => string }[];

  if (!secenekler.length) return null;
  return (
    <Dropdown
      trigger={["click"]}
      placement="bottomRight"
      menu={{
        items: secenekler.map(({ key, icon, label }) => ({ key, icon, label })),
        onClick: ({ key }) => {
          const s = secenekler.find((x) => x.key === key);
          if (s) navigate(s.yol());
        },
      }}
    >
      <button type="button" className="dk-hizli" aria-haspopup="menu" aria-label="Hızlı oluştur">
        <PlusOutlined />
        {!mobil && <span>Hızlı oluştur</span>}
      </button>
    </Dropdown>
  );
}

export default function Kabuk() {
  const { kullanici, cikisYap, yetkili } = useAuth();
  const { aktif: aktifSirket, menuBirimleri, yukleniyor: sirketYukleniyor } = useSirket();
  const konum = useLocation();
  const mobil = useMobil();
  const [bildirimAcik, setBildirimAcik] = useState(false);
  const [parolaAcik, setParolaAcik] = useState(false);
  const [aramaAcik, setAramaAcik] = useState(false);
  const [cekmeceAcik, setCekmeceAcik] = useState(false);
  // TS-200: pencere bayrakla açılır; yalnız servis kullanıcısı.
  const bildirimTercihi = BILDIRIM_TERCIHLERI_ETKIN && yetkili("servis.gor");

  const menu = useMenuDurumu(kullanici?.id);
  const { sonaEkle, bolumDegistir, setDaraltilmis } = menu;

  const gorunur = useMemo(
    () => gorunurMenu(MENU_AGACI, { yetkili, aktifBirimler: menuBirimleri }),
    [yetkili, menuBirimleri],
  );
  const aktif = useMemo(
    () => aktifYaprak(gorunur, konum.pathname, konum.search),
    [gorunur, konum.pathname, konum.search],
  );
  const gorunurYapraklar = useMemo(() => yapraklar(gorunur), [gorunur]);
  const yaprakBul = useCallback(
    (anahtar: string): MenuYapragi | undefined => gorunurYapraklar.find((x) => x.yaprak.anahtar === anahtar)?.yaprak,
    [gorunurYapraklar],
  );
  const favoriListesi = menu.favoriler.map(yaprakBul).filter((y): y is MenuYapragi => !!y);
  const sonListesi = menu.son.map(yaprakBul).filter((y): y is MenuYapragi => !!y);
  const aranabilir = useMemo<AranabilirMenuOgesi[]>(
    () =>
      gorunurYapraklar.map(({ yaprak, atalar }) => ({
        baslik: yaprak.baslik,
        yol: yaprak.yol,
        ust: atalar.map((a) => a.baslik).join(" › "),
      })),
    [gorunurYapraklar],
  );

  const aktifAnahtar = aktif?.yaprak.anahtar;
  const aktifBolum = aktif?.atalar[0]?.anahtar;
  // B-11: Ana Panel KPI bağlantısı (`?kpi=acik`) menüde yaprak değilse kırıntıya KPI adı eklenir.
  const kpi = new URLSearchParams(konum.search).get("kpi");
  const kpiAdi = kpi && !aktif?.yaprak.yol.includes(`kpi=${kpi}`) ? KPI_ADLARI[kpi] : undefined;
  const sayfaBasligi = kpiAdi ?? aktif?.yaprak.baslik ?? "Denge ERP";

  // Etkin sayfa: başlık, son açılanlar ve bölümünün açık olması.
  useEffect(() => {
    document.title = `${sayfaBasligi} – Denge ERP`;
  }, [sayfaBasligi]);
  useEffect(() => {
    if (aktifAnahtar) sonaEkle(aktifAnahtar);
  }, [aktifAnahtar, sonaEkle]);
  useEffect(() => {
    if (aktifBolum) bolumDegistir(aktifBolum, true);
  }, [aktifBolum, bolumDegistir]);

  // Sayfa değişince mobil arama satırı ve menü çekmecesi kapansın.
  useEffect(() => {
    setAramaAcik(false);
    setCekmeceAcik(false);
  }, [konum.pathname, konum.search]);

  // Ctrl+K / ⌘K: genel arama.
  useEffect(() => {
    const dinle = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLocaleLowerCase("tr") === "k") {
        e.preventDefault();
        if (mobil) setAramaAcik(true);
        else document.getElementById(ARAMA_KIMLIGI)?.focus();
      }
    };
    window.addEventListener("keydown", dinle);
    return () => window.removeEventListener("keydown", dinle);
  }, [mobil]);

  const genislet = useCallback(
    (bolum: string) => {
      setDaraltilmis(false);
      bolumDegistir(bolum, true);
    },
    [setDaraltilmis, bolumDegistir],
  );

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
          {aktifSirket && <div style={{ fontSize: 12, color: "#6a6d70" }}>{aktifSirket.ad}</div>}
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

  const yanMenu = sirketYukleniyor ? (
    <MenuIskeleti />
  ) : (
    <YanMenu
      agac={gorunur}
      aktifAnahtar={aktifAnahtar}
      acikBolumler={menu.acik}
      bolumDegistir={bolumDegistir}
      daraltilmis={!mobil && menu.daraltilmis}
      genislet={genislet}
      favoriler={favoriListesi}
      sonAcilanlar={sonListesi}
      favoriMi={(a) => menu.favoriler.includes(a)}
      favoriDegistir={menu.favoriDegistir}
      secildi={mobil ? () => setCekmeceAcik(false) : undefined}
    />
  );

  const launchpadda = konum.pathname === LAUNCHPAD_YOLU;

  return (
    <div className="dk-uygulama">
      <header className="dk-ust" style={{ ["--dk-sirket" as string]: sirketRengi(aktifSirket?.kod) }}>
        <button
          type="button"
          className="dk-ust-dugme"
          aria-label={mobil ? "Menüyü aç" : menu.daraltilmis ? "Menüyü genişlet" : "Menüyü daralt"}
          title={mobil ? "Menü" : menu.daraltilmis ? "Menüyü genişlet" : "Menüyü daralt"}
          onClick={() => (mobil ? setCekmeceAcik(true) : setDaraltilmis((d) => !d))}
        >
          {mobil ? <MenuOutlined /> : menu.daraltilmis ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
        <Link to="/" className="dk-logo" title="Açılış sayfası" aria-label="Açılış sayfası">
          <img src="/brand/favicon.png" alt="" />
          {!mobil && <span className="dk-logo-metin">Denge ERP</span>}
        </Link>
        <SirketSecici mobil={mobil} />

        <div className="dk-ust-bosluk" />

        {!mobil && (
          <div className="dk-ust-arama">
            <GlobalSearch kimlik={ARAMA_KIMLIGI} menuOgeleri={aranabilir} />
          </div>
        )}
        {mobil && (
          <button
            type="button"
            className="dk-ust-dugme"
            aria-label={aramaAcik ? "Aramayı kapat" : "Ara"}
            onClick={() => setAramaAcik((a) => !a)}
          >
            {aramaAcik ? <CloseOutlined /> : <SearchOutlined />}
          </button>
        )}
        <HizliOlustur mobil={mobil} />
        <span className="dk-ust-dugme dk-zil">
          <UyariZili renk="#e6edf5" />
        </span>
        <Dropdown menu={{ items: kullaniciMenusu }} trigger={["click"]} placement="bottomRight">
          <button
            type="button"
            className="dk-kullanici"
            aria-label={`Kullanıcı menüsü: ${kullanici?.full_name ?? ""}`}
            title={kullanici?.full_name}
          >
            <span className="dk-avatar">{basHarfler(kullanici?.full_name)}</span>
            {!mobil && <span className="dk-kullanici-ad">{kullanici?.full_name}</span>}
            {!mobil && <DownOutlined style={{ fontSize: 10 }} />}
          </button>
        </Dropdown>
      </header>

      {mobil && aramaAcik && (
        <div className="dk-mobil-arama">
          <GlobalSearch otomatikOdak menuOgeleri={aranabilir} onSecildi={() => setAramaAcik(false)} />
        </div>
      )}

      <div className="dk-govde">
        {!mobil && <aside className={`dk-yan${menu.daraltilmis ? " daraltilmis" : ""}`}>{yanMenu}</aside>}
        {mobil && (
          <Drawer
            open={cekmeceAcik}
            onClose={() => setCekmeceAcik(false)}
            placement="left"
            size={300}
            title={null}
            closable={false}
            className="dk-cekmece"
            styles={{ body: { padding: 0 } }}
          >
            {yanMenu}
          </Drawer>
        )}

        <main className={launchpadda ? "fiori-icerik fiori-icerik-lp dk-icerik" : "fiori-icerik dk-icerik"}>
          <nav className={`dk-kirinti${launchpadda ? " lp" : ""}`} aria-label="Bulunduğunuz yer">
            <ol>
              {aktifSirket && (
                <li>
                  <span className="dk-sirket-isaret" style={{ background: sirketRengi(aktifSirket.kod) }} aria-hidden />
                  {aktifSirket.ad}
                </li>
              )}
              {!sirketYukleniyor && aktif?.atalar.map((a) => <li key={a.anahtar}>{a.baslik}</li>)}
              {kpiAdi && aktif && <li>{aktif.yaprak.baslik}</li>}
              <li aria-current="page">{sirketYukleniyor ? "Yükleniyor…" : sayfaBasligi}</li>
            </ol>
          </nav>
          {/* TS-077: açık sayaç her sayfada görünür; `zaman.yaz` yoksa ne çizer ne istek atar. */}
          <div className="fiori-sayac-bandi">
            <AktifSayacBandi />
          </div>
          {sirketYukleniyor ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12, padding: 48 }}>
              <Spin />
              <span style={{ color: "#6a6d70" }}>Şirket bilgisi yükleniyor…</span>
            </div>
          ) : (
            <RotaKapisi>
              <Outlet />
            </RotaKapisi>
          )}
        </main>
      </div>

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
