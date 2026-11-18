/**
 * Sol menü — Logo CRM kurgusu (KARARLAR 2026-11-04 §2, §5).
 *
 * - Ana bölüm başlıkları akordeon: başlığa tıklayınca alt bölümler aşağı
 *   açılır; alt bölüm (grup) başlıkları ve yaprakları girintilidir.
 * - Seçili yaprak vurgulu; etkin bölüm adres değişince kendiliğinden açılır.
 * - Daraltılmış hâlde yalnız ikonlar; ikona tıklamak menüyü açar ve o bölümü
 *   genişletir (ipucunda bölüm adı).
 * - Tepede "Favoriler" (yaprağın yanındaki yıldız). "Son açılanlar" bloğu
 *   2026-11-18'de kaldırıldı: hep bulunulan sayfanın kopyasını gösteriyordu.
 * - Klavye: ↑/↓ öğeler arası, → bölümü aç, ← kapat/üst bölüme dön,
 *   Home/End, Enter/Boşluk etkinleştir. Dokunma hedefleri ≥ 40 px.
 * Açık bölümler ve favoriler kullanıcı başına yerelde tutulur.
 */
import {
  DownOutlined,
  RightOutlined,
  StarFilled,
  StarOutlined,
} from "@ant-design/icons";
import { Tooltip } from "antd";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useRef } from "react";
import { Link } from "react-router-dom";

import type { MenuGrubu, MenuOgesi, MenuYapragi } from "./menu";
import { useTayinSayilari } from "./tayinRozeti";

export interface YanMenuProps {
  agac: MenuOgesi[];
  aktifAnahtar?: string;
  acikBolumler: ReadonlySet<string>;
  bolumDegistir: (anahtar: string, acik?: boolean) => void;
  daraltilmis: boolean;
  /** Daraltılmış menüde bölüm ikonuna tıklanınca: menüyü aç + bölümü genişlet. */
  genislet: (bolum: string) => void;
  favoriler: MenuYapragi[];
  favoriMi: (anahtar: string) => boolean;
  favoriDegistir: (anahtar: string) => void;
  /** Yaprağa tıklanınca (mobil çekmeceyi kapatmak için). */
  secildi?: () => void;
}

const ODAK = "[data-menu-odak]";

/** Operasyon Merkezi yaprağında tayin bekleyen iş rozeti (süresi geçen varsa kırmızı). */
function TayinRozeti() {
  const s = useTayinSayilari().data;
  if (!s?.bekleyen) return null;
  return (
    <span
      className={`dk-menu-rozet${s.geciken ? " kirmizi" : ""}`}
      title={`${s.bekleyen} iş tayin bekliyor${s.geciken ? `, ${s.geciken} işin süresi geçti` : ""}`}
    >
      {s.bekleyen}
    </span>
  );
}

function Yaprak({
  y,
  derinlik,
  aktif,
  favori,
  favoriDegistir,
  secildi,
  bolum,
}: {
  y: MenuYapragi;
  derinlik: number;
  aktif: boolean;
  favori: boolean;
  favoriDegistir: (anahtar: string) => void;
  secildi?: () => void;
  bolum?: string;
}) {
  const Ikon = y.ikon;
  return (
    <li className={`dk-menu-yaprak derinlik-${derinlik}${aktif ? " aktif" : ""}`}>
      <Link
        to={y.yol}
        className="dk-menu-baglanti"
        data-menu-odak=""
        data-bolum={bolum}
        aria-current={aktif ? "page" : undefined}
        onClick={secildi}
      >
        {derinlik === 0 && Ikon && <Ikon className="dk-menu-ikon" />}
        <span className="dk-menu-metin">{y.baslik}</span>
        {y.yol === "/operasyon" && <TayinRozeti />}
      </Link>
      <button
        type="button"
        className={`dk-menu-yildiz${favori ? " dolu" : ""}`}
        aria-label={favori ? `${y.baslik}: favorilerden çıkar` : `${y.baslik}: favorilere ekle`}
        aria-pressed={favori}
        title={favori ? "Favorilerden çıkar" : "Favorilere ekle"}
        tabIndex={-1}
        onClick={() => favoriDegistir(y.anahtar)}
      >
        {favori ? <StarFilled /> : <StarOutlined />}
      </button>
    </li>
  );
}

export default function YanMenu({
  agac,
  aktifAnahtar,
  acikBolumler,
  bolumDegistir,
  daraltilmis,
  genislet,
  favoriler,
  favoriMi,
  favoriDegistir,
  secildi,
}: YanMenuProps) {
  const kok = useRef<HTMLElement>(null);

  /** Yaprak ya da grubun içinde etkin yaprak var mı. */
  const icerir = (o: MenuOgesi): boolean =>
    o.tur === "yaprak" ? o.anahtar === aktifAnahtar : o.altlar.some(icerir);

  const tusla = (e: ReactKeyboardEvent<HTMLElement>) => {
    const ogeler = Array.from(kok.current?.querySelectorAll<HTMLElement>(ODAK) ?? []);
    const i = ogeler.indexOf(document.activeElement as HTMLElement);
    if (i < 0) return;
    const odakla = (n: number) => ogeler[Math.max(0, Math.min(ogeler.length - 1, n))]?.focus();
    const simdiki = ogeler[i];
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        odakla(i + 1);
        break;
      case "ArrowUp":
        e.preventDefault();
        odakla(i - 1);
        break;
      case "Home":
        e.preventDefault();
        odakla(0);
        break;
      case "End":
        e.preventDefault();
        odakla(ogeler.length - 1);
        break;
      case "ArrowRight": {
        const b = simdiki.dataset.bolumBasligi;
        if (b && !acikBolumler.has(b)) {
          e.preventDefault();
          bolumDegistir(b, true);
        }
        break;
      }
      case "ArrowLeft": {
        e.preventDefault();
        const b = simdiki.dataset.bolumBasligi;
        if (b && acikBolumler.has(b)) {
          bolumDegistir(b, false);
          break;
        }
        // Yapraktaysa bölüm başlığına dön.
        const ust = simdiki.dataset.bolum;
        if (ust) kok.current?.querySelector<HTMLElement>(`[data-bolum-basligi="${ust}"]`)?.focus();
        break;
      }
      case "*": {
        // Klavyeyle favori: yaprağın yıldız düğmesi sekme sırasında değil.
        const yildiz = simdiki.parentElement?.querySelector<HTMLButtonElement>(".dk-menu-yildiz");
        if (yildiz) {
          e.preventDefault();
          yildiz.click();
        }
        break;
      }
      default:
    }
  };

  const altlariCiz = (altlar: MenuOgesi[], derinlik: number, bolum: string) =>
    altlar.map((o) =>
      o.tur === "yaprak" ? (
        <Yaprak
          key={o.anahtar}
          y={o}
          derinlik={derinlik}
          aktif={o.anahtar === aktifAnahtar}
          favori={favoriMi(o.anahtar)}
          favoriDegistir={favoriDegistir}
          secildi={secildi}
          bolum={bolum}
        />
      ) : (
        <li key={o.anahtar} className={`dk-menu-altgrup derinlik-${derinlik}`}>
          <div className="dk-menu-altgrup-baslik" id={`dk-ag-${o.anahtar}`}>
            {o.baslik}
          </div>
          <ul className="dk-menu-liste" aria-labelledby={`dk-ag-${o.anahtar}`}>
            {altlariCiz(o.altlar, derinlik + 1, bolum)}
          </ul>
        </li>
      ),
    );

  const bolumCiz = (g: MenuGrubu) => {
    const acik = acikBolumler.has(g.anahtar);
    const Ikon = g.ikon;
    const etkin = icerir(g);
    const baslik = (
      <button
        type="button"
        className={`dk-menu-bolum-baslik${etkin ? " etkin" : ""}`}
        data-menu-odak=""
        data-bolum-basligi={g.anahtar}
        aria-expanded={daraltilmis ? undefined : acik}
        aria-controls={`dk-bolum-${g.anahtar}`}
        aria-label={daraltilmis ? g.baslik : undefined}
        onClick={() => (daraltilmis ? genislet(g.anahtar) : bolumDegistir(g.anahtar))}
      >
        {Ikon && <Ikon className="dk-menu-ikon" />}
        <span className="dk-menu-metin">{g.baslik}</span>
        <span className="dk-menu-ok" aria-hidden>
          {acik ? <DownOutlined /> : <RightOutlined />}
        </span>
      </button>
    );
    return (
      <li key={g.anahtar} className={`dk-menu-bolum${acik ? " acik" : ""}`}>
        {daraltilmis ? (
          <Tooltip title={g.baslik} placement="right">
            {baslik}
          </Tooltip>
        ) : (
          baslik
        )}
        {acik && !daraltilmis && (
          <ul className="dk-menu-liste" id={`dk-bolum-${g.anahtar}`}>
            {altlariCiz(g.altlar, 1, g.anahtar)}
          </ul>
        )}
      </li>
    );
  };

  const hizliListe = (anahtar: string, baslik: string, ikon: React.ReactNode, liste: MenuYapragi[]) => {
    if (daraltilmis || !liste.length) return null;
    return (
      <div className="dk-menu-hizli" key={anahtar}>
        <div className="dk-menu-hizli-baslik">
          {ikon}
          <span>{baslik}</span>
        </div>
        <ul className="dk-menu-liste">
          {liste.map((y) => (
            <Yaprak
              key={`${anahtar}:${y.anahtar}`}
              y={y}
              derinlik={1}
              aktif={y.anahtar === aktifAnahtar}
              favori={favoriMi(y.anahtar)}
              favoriDegistir={favoriDegistir}
              secildi={secildi}
            />
          ))}
        </ul>
      </div>
    );
  };

  return (
    <nav
      ref={kok}
      className={`dk-menu${daraltilmis ? " daraltilmis" : ""}`}
      aria-label="Ana menü"
      onKeyDown={tusla}
    >
      {hizliListe("favori", "Favoriler", <StarFilled className="dk-menu-hizli-ikon" />, favoriler)}
      <ul className="dk-menu-liste dk-menu-kok">
        {agac.map((o) =>
          o.tur === "yaprak" ? (
            daraltilmis ? (
              <li key={o.anahtar} className={`dk-menu-yaprak derinlik-0${o.anahtar === aktifAnahtar ? " aktif" : ""}`}>
                <Tooltip title={o.baslik} placement="right">
                  <Link
                    to={o.yol}
                    className="dk-menu-baglanti"
                    data-menu-odak=""
                    aria-label={o.baslik}
                    aria-current={o.anahtar === aktifAnahtar ? "page" : undefined}
                    onClick={secildi}
                  >
                    {o.ikon && <o.ikon className="dk-menu-ikon" />}
                  </Link>
                </Tooltip>
              </li>
            ) : (
              <Yaprak
                key={o.anahtar}
                y={o}
                derinlik={0}
                aktif={o.anahtar === aktifAnahtar}
                favori={favoriMi(o.anahtar)}
                favoriDegistir={favoriDegistir}
                secildi={secildi}
              />
            )
          ) : (
            bolumCiz(o)
          ),
        )}
      </ul>
    </nav>
  );
}
