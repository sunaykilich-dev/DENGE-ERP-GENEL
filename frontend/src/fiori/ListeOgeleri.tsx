/**
 * Fiori liste raporu hücre ve kart yardımcıları (rehber §3.4, fotoğraf 0–6, 9).
 *
 * `ListeRaporu`'nun sütunlarında ve mobil kart görünümünde tekrar eden
 * parçalar tek yerde: mavi BÜYÜK HARF durum bağlantısı, sarı no rozeti, mavi
 * tek satır açıklama, küçük ortalı hücre metni, kişi ikonlu personel düğmesi,
 * GG/AA/YYYY ve SS:DD:ss biçimleri; mobil için Fiori kart ve sayfa üst çubuğu.
 * Yalnız görünüm: veri, süzgeç ve yetki kararı çağırandadır.
 */
import { UserAddOutlined, UserOutlined } from "@ant-design/icons";
import { Button, Popover, Space, Typography } from "antd";
import dayjs from "dayjs";
import type { ReactNode } from "react";

import { TAYIN, type FioriDurumGrubu, type KategoriRengi } from "./etiketler";
import type { FioriKategori } from "./KategoriSeridi";
import "./fiori.css";
import "./fiori-ek.css";

export const gunu = (d?: string | null) => (d ? dayjs(d).format("DD/MM/YYYY") : "—");
export const saati = (d?: string | null) => (d ? dayjs(d).format("HH:mm:ss") : "—");

/** Türkçe büyük harf (SAP listesindeki gibi). */
export const buyuk = (s?: string | null) => (s ?? "").toLocaleUpperCase("tr");

/** Durum hücresi: mavi, kalın, BÜYÜK HARF, tıklanınca detay. */
export function DurumBaglantisi({
  metin,
  ipucu,
  ton,
  onClick,
  alt,
}: {
  metin: string;
  ipucu?: string;
  /** kapali = gri, olumsuz = kırmızı. */
  ton?: "kapali" | "olumsuz";
  onClick?: () => void;
  /** Altında küçük not (ör. GECİKTİ). */
  alt?: ReactNode;
}) {
  return (
    <>
      <button type="button" className={`fl-durum${ton ? ` ${ton}` : ""}`} title={ipucu} onClick={onClick}>
        {buyuk(metin)}
      </button>
      {alt}
    </>
  );
}

/** Küçük BÜYÜK HARF not (kritik kırmızı, uyarı turuncu). */
export function AltNot({ children, tur }: { children: ReactNode; tur?: "kritik" | "uyari" }) {
  return <span className={`fl-alt-not${tur ? ` ${tur}` : ""}`}>{children}</span>;
}

/** No hücresi: sarı rozet (ya da düz), tıklanınca detay. */
export function NoRozeti({
  no,
  onClick,
  duz,
  alt,
}: {
  no: string;
  onClick?: () => void;
  duz?: boolean;
  alt?: ReactNode;
}) {
  return (
    <>
      <span
        className={duz ? "fl-no-duz" : "fl-no-rozet"}
        role={onClick ? "link" : undefined}
        tabIndex={onClick ? 0 : undefined}
        onClick={onClick}
        onKeyDown={(e) => onClick && e.key === "Enter" && onClick()}
      >
        {no}
      </span>
      {alt && <span className="fl-kucuk-gri">{alt}</span>}
    </>
  );
}

/** Açıklama hücresi: mavi, kalın, BÜYÜK HARF, tek satır kesilir. */
export function Aciklama({ metin, onClick }: { metin?: string | null; onClick?: () => void }) {
  if (!metin) return <span className="fl-kucuk-gri">—</span>;
  return (
    <button type="button" className="fl-aciklama" title={metin} onClick={onClick}>
      {metin}
    </button>
  );
}

/** Küçük, ortalı, BÜYÜK HARF hücre metni (Mahal / Sistem sütunları). */
export function Kucuk({ children, kalin }: { children?: ReactNode; kalin?: boolean }) {
  return (
    <span className="fl-kucuk" style={kalin ? { fontWeight: 600 } : undefined}>
      {children ?? "—"}
    </span>
  );
}

/** Küçük gri ortalı metin (Bildiren Kişi/Tel). */
export function KucukGri({ children }: { children?: ReactNode }) {
  return <span className="fl-kucuk-gri">{children ?? "—"}</span>;
}

/**
 * Personel sütunu: kişi ikonlu kare düğme → tayin edilen ekip; yetki varsa
 * "Tayin Et / Tayini Değiştir" kısayolu.
 */
export function PersonelHucresi({
  sorumlu,
  kisiSayisi,
  kisiler,
  onTayin,
  etiket,
}: {
  sorumlu?: string | null;
  kisiSayisi?: number;
  /** Ekip adları (varsa listelenir). */
  kisiler?: (string | null | undefined)[];
  onTayin?: () => void;
  etiket?: string;
}) {
  const adlar = (kisiler ?? []).filter(Boolean) as string[];
  const bos = !sorumlu && !kisiSayisi && adlar.length === 0;
  return (
    <Popover
      trigger="click"
      title={TAYIN.tayinEdilenEkip}
      content={
        <Space orientation="vertical" size={4} style={{ maxWidth: 260 }}>
          {bos ? (
            <Typography.Text type="warning">{TAYIN.tayinEdilmemis}</Typography.Text>
          ) : (
            <>
              {sorumlu && <span>Sorumlu: {sorumlu}</span>}
              {adlar.length > 0 && <span>{adlar.join(", ")}</span>}
              {!!kisiSayisi && (
                <Typography.Text type="secondary">{kisiSayisi} kişi tayin edildi</Typography.Text>
              )}
            </>
          )}
          {onTayin && (
            <Button size="small" type="primary" icon={<UserAddOutlined />} onClick={onTayin}>
              {bos ? TAYIN.tayinEt : TAYIN.tayiniDegistir}
            </Button>
          )}
        </Space>
      }
    >
      <button
        type="button"
        className={`fl-personel${bos ? " bos" : ""}`}
        aria-label={etiket ?? TAYIN.tayinEdilenEkip}
      >
        <UserOutlined />
      </button>
    </Popover>
  );
}

/** "TÜMÜ" kategorisi (mavi). */
export const TUMU_KATEGORISI: FioriKategori = { kod: "_TUMU", ad: "TÜMÜ", renk: "mavi" };

/** Kod/ad listesinden kategori şeridi; kırmızı kodlar ayrıca verilir. */
export function kategorilerOlustur(
  ogeler: { kod: string; ad: string }[],
  renk: (kod: string) => KategoriRengi,
  ikon?: (kod: string) => ReactNode,
  tumu = true,
): FioriKategori[] {
  return [
    ...(tumu ? [TUMU_KATEGORISI] : []),
    ...ogeler.map((o) => ({ kod: o.kod, ad: buyuk(o.ad), ipucu: o.ad, renk: renk(o.kod), ikon: ikon?.(o.kod) })),
  ];
}

/** Tek kodlu durum grupları (sunucu tek `durum` alıyorsa): her durum bir düğme. */
export function tekliGruplar(adlar: Record<string, string>, kisa?: Record<string, string>): FioriDurumGrubu[] {
  return Object.entries(adlar).map(([kod, ad]) => ({ kod, ad: kisa?.[kod] ?? buyuk(ad), durumlar: [kod] }));
}

// --- Mobil Fiori kartı (BenimIslerim, dar ekran listeleri) ---------------------------

/**
 * Fiori nesne kartı: üstte mavi BÜYÜK HARF durum + sarı no rozeti, altında
 * mavi kalın açıklama, gri alt satırlar. Bütün kart dokunulabilir (≥ 44 px).
 */
export function FioriKart({
  durum,
  durumTon,
  no,
  rozetler,
  baslik,
  altSatirlar,
  sag,
  onClick,
}: {
  durum?: string;
  durumTon?: "kapali" | "olumsuz";
  no?: string;
  rozetler?: ReactNode;
  baslik?: ReactNode;
  altSatirlar?: ReactNode[];
  sag?: ReactNode;
  onClick?: () => void;
}) {
  return (
    <div
      className={`fm-kart${onClick ? " tiklanir" : ""}`}
      role={onClick ? "link" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={(e) => onClick && (e.key === "Enter" || e.key === " ") && onClick()}
    >
      <div className="fm-kart-govde">
        <div className="fm-kart-ust">
          {durum && <span className={`fm-kart-durum${durumTon ? ` ${durumTon}` : ""}`}>{buyuk(durum)}</span>}
          {no && <span className="fl-no-rozet">{no}</span>}
          {rozetler}
        </div>
        {baslik && <div className="fm-kart-baslik">{baslik}</div>}
        {altSatirlar
          ?.filter((s) => s !== null && s !== undefined && s !== false && s !== "")
          .map((s, i) => (
            <div key={i} className="fm-kart-alt">
              {s}
            </div>
          ))}
      </div>
      {sag && <div className="fm-kart-sag">{sag}</div>}
    </div>
  );
}

/** Fiori nesne sayfası başlığı (mobil kart / detay üstü): büyük başlık + durum. */
export function NesneBasligi({
  baslik,
  no,
  durum,
  durumTon,
  rozetler,
  alt,
}: {
  baslik?: ReactNode;
  no?: string;
  durum?: string;
  durumTon?: "kapali" | "olumsuz";
  rozetler?: ReactNode;
  alt?: ReactNode;
}) {
  return (
    <div className="fm-nesne-basligi">
      <div className="fm-kart-ust">
        {no && <span className="fl-no-rozet">{no}</span>}
        {durum && <span className={`fm-kart-durum${durumTon ? ` ${durumTon}` : ""}`}>{buyuk(durum)}</span>}
        {rozetler}
      </div>
      {baslik && <div className="fm-nesne-baslik">{baslik}</div>}
      {alt && <div className="fm-kart-alt">{alt}</div>}
    </div>
  );
}

/** Fiori bölüm kutusu (beyaz, ince kenar, başlık çizgisi). */
export function FioriBolum({
  baslik,
  sag,
  children,
  dolgusuz,
}: {
  baslik?: ReactNode;
  sag?: ReactNode;
  children: ReactNode;
  dolgusuz?: boolean;
}) {
  return (
    <section className="fm-bolum">
      {(baslik || sag) && (
        <div className="fm-bolum-ust">
          <span className="fm-bolum-baslik">{baslik}</span>
          {sag && <span className="fm-bolum-sag">{sag}</span>}
        </div>
      )}
      <div className={dolgusuz ? undefined : "fm-bolum-govde"}>{children}</div>
    </section>
  );
}
