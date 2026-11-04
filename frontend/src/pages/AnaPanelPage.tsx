import {
  AlertOutlined,
  CalendarOutlined,
  CarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CustomerServiceOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  FilterOutlined,
  HourglassOutlined,
  ReloadOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  WarningOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, DatePicker, Progress, Select, Skeleton, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import type { CSSProperties, ReactNode } from "react";
import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  anaPanelApi,
  anaPanelParametreleri,
  type AktifIs,
  type AnaPanelKpi,
  type AnaPanelSuzgeci,
  type AnaPanelYaniti,
  type BekleyenAksiyon,
  type BirimOzeti,
  type EkipSatiri,
  type GrafikDilimi,
} from "../api/anaPanel";
import { SLA_RENKLERI, sureMetni } from "../api/servisOperasyon";
import { DURUM_RENKLERI, ONCELIK_RENKLERI } from "../api/teknikServis";
import { TAYIN } from "../fiori/etiketler";
import "./anaPanel.css";

/**
 * Ana Panel — master dashboard (KARARLAR 2026-11-04 §4; Launchpad'in yerine).
 *
 * Bütün sayılar `GET /api/teknik-servis/ana-panel`'den gelir ve kullanıcının
 * kapsamıyla (birim, kendi işleri, etkin şirket) sunucuda süzülür. Kural
 * "sayı = liste": tıklanan her sayı `liste_yolu`'na gider; o listenin toplamı
 * kartta yazanla aynıdır. Ön yüz sayı/SLA HESAPLAMAZ, yalnız çizer.
 *
 * Süzgeçler adres çubuğunda tutulur (paylaşılabilir; geri tuşu çalışır); sorgu
 * anahtarı `["ana-panel", süzgeçler]`. Sekme görünürken 60 sn'de bir yenilenir
 * (TanStack Query arka planda yenilemez).
 */

const YENILEME_MS = 60_000;

const RENK = {
  mavi: "#0a6ed1",
  yesil: "#107e3e",
  kirmizi: "#bb0000",
  turuncu: "#e9730c",
  mor: "#6c32a9",
  camgobegi: "#0f828f",
  gri: "#556b82",
  sari: "#c87b00",
} as const;

type Renkli = CSSProperties & { "--renk"?: string };
const renkli = (renk: string): Renkli => ({ "--renk": renk });

const KPI_GORUNUM: Record<string, { ikon: ReactNode; renk: string; alt?: string; artisKotu?: boolean }> = {
  acik_is: { ikon: <FileTextOutlined />, renk: RENK.mavi, artisKotu: true },
  planli_bakim: { ikon: <CalendarOutlined />, renk: RENK.yesil },
  acil_ariza: { ikon: <WarningOutlined />, renk: RENK.kirmizi, artisKotu: true },
  poc_acik: { ikon: <CustomerServiceOutlined />, renk: RENK.mor, artisKotu: true },
  sla_riski: { ikon: <ClockCircleOutlined />, renk: RENK.turuncu, alt: "riskte + aşılmış", artisKotu: true },
  sahadaki_ekip: { ikon: <TeamOutlined />, renk: RENK.camgobegi, alt: "aktif / toplam" },
  askida: { ikon: <HourglassOutlined />, renk: RENK.gri, artisKotu: true },
  bekleyen_onay: { ikon: <CheckCircleOutlined />, renk: RENK.mor, alt: "kapanış / kalite onayı" },
};

const BIRIM_GORUNUM: Record<string, { ikon: ReactNode; renk: string }> = {
  GUVENLIK: { ikon: <SafetyCertificateOutlined />, renk: RENK.mavi },
  HABERLESME: { ikon: <WifiOutlined />, renk: RENK.yesil },
  POC: { ikon: <CustomerServiceOutlined />, renk: RENK.mor },
  MOBILITE: { ikon: <CarOutlined />, renk: RENK.turuncu },
  ARAC_TAKIP: { ikon: <EnvironmentOutlined />, renk: RENK.camgobegi },
};
const birimGorunum = (kod: string) => BIRIM_GORUNUM[kod] ?? { ikon: <AlertOutlined />, renk: RENK.gri };

const DURUM_GRAFIK_RENGI: Record<string, string> = {
  MUSTERI_TALEBI: "#89919a",
  PLANLAMADA: "#c87b00",
  PLANLANDI: RENK.mavi,
  YOLA_CIKILDI: "#5ab4d6",
  SAHADA: RENK.camgobegi,
  ISLEMDE: "#3f51b5",
  ATOLYEDE: RENK.mor,
  BEKLEMEDE: RENK.turuncu,
  TEKRAR_ACILDI: "#c2185b",
  TAMAMLANDI: RENK.yesil,
};

const EKIP_RENGI: Record<string, string> = {
  SAHADA: RENK.yesil,
  UZAKTAN: RENK.mor,
  ATOLYEDE: RENK.turuncu,
  MUSAIT: RENK.gri,
  IZINLI: RENK.mavi,
};

const PB_RENGI: Record<string, string> = {
  tamamlanan: RENK.yesil,
  devam_eden: RENK.mavi,
  planlanan: "#c6cdd5",
};

const GUN_DK = 1440;

// --- Süzgeç (adres çubuğu) ---------------------------------------------------------------

function sayi(p: URLSearchParams, k: string): number | undefined {
  const v = p.get(k);
  return v && /^\d+$/.test(v) ? Number(v) : undefined;
}

function suzgecOku(p: URLSearchParams): AnaPanelSuzgeci {
  return {
    birim: p.get("birim") ?? undefined,
    durum_grubu: p.get("durum_grubu") ?? undefined,
    sef_id: sayi(p, "sef_id"),
    personel_id: sayi(p, "personel_id"),
    lokasyon_id: sayi(p, "lokasyon_id"),
    bas: p.get("bas") ?? undefined,
    bit: p.get("bit") ?? undefined,
  };
}

/** Süzgeci iş listesinin parametre adlarına çevirir ("Daha fazla filtre"). */
function listeSuzgeci(s: AnaPanelSuzgeci): string {
  const p = new URLSearchParams();
  if (s.birim) p.set("birim", s.birim);
  p.set("durum_grubu", s.durum_grubu ?? "ACIK");
  if (s.sef_id) p.set("sef_id", String(s.sef_id));
  if (s.personel_id) p.set("teknisyen_id", String(s.personel_id));
  if (s.lokasyon_id) p.set("adres_id", String(s.lokasyon_id));
  return `/servis-isleri?${p}`;
}

// --- Biçim yardımcıları ----------------------------------------------------------------------

const tarihSaat = (t?: string | null) => (t ? dayjs(t).format("DD.MM.YYYY HH:mm") : "—");

/** Sunucunun verdiği dakikayı kısa metne çevirir (hesap değil, biçim). */
function sureKisa(dk: number | null | undefined): string {
  if (dk == null) return "—";
  if (dk >= GUN_DK) return `${Math.floor(dk / GUN_DK)} gün`;
  if (dk >= 60) return `${Math.floor(dk / 60)} sa ${dk % 60 ? `${dk % 60} dk` : ""}`.trim();
  return `${dk} dk`;
}

function slaMetni(sla: AktifIs["sla"]): string {
  if (!sla.ad) return "—";
  if (sla.kalan_dk == null) return sla.ad;
  if (sla.durum === "ASILDI") return `Gecikti ${sureMetni(sla.kalan_dk)}`;
  if (sla.durum === "DURDURULDU") return "Durduruldu";
  return sureMetni(sla.kalan_dk);
}

// --- Parçalar --------------------------------------------------------------------------------

function Kart({ baslik, sag, children, style }: { baslik: ReactNode; sag?: ReactNode; children: ReactNode; style?: CSSProperties }) {
  return (
    <section className="ap-kart" style={style}>
      <div className="ap-kart-baslik">
        <span>{baslik}</span>
        {sag}
      </div>
      {children}
    </section>
  );
}

function Bos({ children }: { children: ReactNode }) {
  return <div className="ap-bos">{children}</div>;
}

function Degisim({ k, artisKotu }: { k: AnaPanelKpi; artisKotu?: boolean }) {
  if (k.degisim_yuzde == null) return null;
  const yuzde = k.degisim_yuzde;
  const ok = yuzde > 0 ? "↑" : yuzde < 0 ? "↓" : "→";
  let sinif = "notr";
  if (yuzde !== 0) sinif = (yuzde > 0) === Boolean(artisKotu) ? "kotu" : "iyi";
  return (
    <span className={sinif}>
      {ok} %{Math.abs(yuzde).toLocaleString("tr-TR", { maximumFractionDigits: 1 })}
    </span>
  );
}

function KpiKarti({ k }: { k: AnaPanelKpi }) {
  const git = useNavigate();
  const g = KPI_GORUNUM[k.kod] ?? { ikon: <FileTextOutlined />, renk: RENK.mavi };
  const icerik = (
    <>
      <span className="ap-kpi-ikon" aria-hidden>
        {g.ikon}
      </span>
      <span className="ap-kpi-govde">
        <span className="ap-kpi-ad">{k.ad}</span>
        <span className="ap-kpi-deger">
          {k.deger.toLocaleString("tr-TR")}
          {k.toplam != null && <span className="ap-kpi-toplam"> / {k.toplam.toLocaleString("tr-TR")}</span>}
        </span>
        <span className="ap-kpi-alt">
          <Degisim k={k} artisKotu={g.artisKotu} />
          {k.degisim_yuzde != null && " "}
          {k.karsilastirma
            ? `(${k.karsilastirma}${k.onceki_deger != null ? `: ${k.onceki_deger}` : ""})`
            : g.alt ?? ""}
        </span>
      </span>
    </>
  );
  const ipucu = k.tanim ?? undefined;
  if (!k.liste_yolu) {
    return (
      <Tooltip title={ipucu}>
        <div className="ap-kpi" style={renkli(g.renk)} data-kpi={k.kod}>
          {icerik}
        </div>
      </Tooltip>
    );
  }
  const yol = k.liste_yolu;
  return (
    <Tooltip title={ipucu}>
      <button
        type="button"
        className="ap-kpi"
        style={renkli(g.renk)}
        data-kpi={k.kod}
        aria-label={`${k.ad}: ${k.deger}${k.toplam != null ? ` / ${k.toplam}` : ""} — listeyi aç`}
        onClick={() => git(yol)}
      >
        {icerik}
      </button>
    </Tooltip>
  );
}

function BirimKarti({ b }: { b: BirimOzeti }) {
  const g = birimGorunum(b.birim);
  const sayilar: [keyof BirimOzeti["yollar"], string][] = [
    ["acik", "Açık İş"],
    ["sahada", "Sahada"],
    ["atolyede", "Atölyede"],
    ["tamamlanan", "Tamamlanan"],
  ];
  return (
    <div className="ap-birim" style={renkli(g.renk)}>
      <Link to={b.yollar.acik} className="ap-birim-ust">
        {g.ikon}
        <span className="ad">{b.ad}</span>
        <RightOutlined style={{ fontSize: 11 }} />
      </Link>
      <div className="ap-birim-sayilar">
        {sayilar.map(([k, ad]) => (
          <Link key={k} to={b.yollar[k]} className="ap-birim-sayi">
            <small>{ad}</small>
            <b>{b[k] as number}</b>
          </Link>
        ))}
      </div>
      <Progress
        percent={b.tamamlanma_yuzde ?? 0}
        size="small"
        strokeColor={g.renk}
        format={() => (b.tamamlanma_yuzde == null ? "—" : `%${b.tamamlanma_yuzde}`)}
        aria-label={`${b.ad} tamamlanma oranı`}
      />
      <div className="ap-birim-alt">
        <Link to={b.yollar.donem_is_emri}>Dönemde {b.donem_is_emri} iş emri</Link>
      </div>
    </div>
  );
}

function kisiler(liste: AktifIs["tayin_edilen_personel"]) {
  if (!liste.length) return <span className="ap-hucre-ince">—</span>;
  const [ilk, ...diger] = liste;
  return (
    <Tooltip title={liste.map((k) => k.ad).join(", ")}>
      <span>
        {ilk.ad}
        {diger.length > 0 && <span className="ap-hucre-ince"> +{diger.length}</span>}
      </span>
    </Tooltip>
  );
}

const AKTIF_SUTUNLAR: ColumnsType<AktifIs> = [
  { title: "Kayıt No", dataIndex: "no", key: "no", width: 120, render: (_, r) => <Link to={r.yol}>{r.no}</Link> },
  {
    title: "Tür",
    key: "tur",
    width: 90,
    render: (_, r) => (
      <span>
        {r.oncelik !== "NORMAL" && (
          <Tooltip title={`Öncelik: ${r.oncelik}`}>
            <Tag color={ONCELIK_RENKLERI[r.oncelik]} style={{ marginInlineEnd: 4 }}>
              !
            </Tag>
          </Tooltip>
        )}
        {r.tur_adi}
      </span>
    ),
  },
  { title: "Bölüm", dataIndex: "birim_adi", key: "birim", width: 110, ellipsis: true },
  {
    title: "Ekipman / Alt Sistem",
    key: "ekipman",
    width: 140,
    ellipsis: true,
    render: (_, r) => r.ekipman ?? r.alt_sistem ?? <span className="ap-hucre-ince">—</span>,
  },
  { title: "Müşteri", dataIndex: "musteri", key: "musteri", width: 140, ellipsis: true, render: (v) => v ?? "—" },
  { title: "Lokasyon", dataIndex: "lokasyon", key: "lokasyon", width: 120, ellipsis: true, render: (v) => v ?? "—" },
  {
    title: `${TAYIN.tayin} Edilen Şef`,
    key: "sef",
    width: 110,
    ellipsis: true,
    render: (_, r) => kisiler(r.tayin_edilen_sef),
  },
  {
    title: `${TAYIN.tayin} Edilen Personel`,
    key: "personel",
    width: 120,
    ellipsis: true,
    render: (_, r) => kisiler(r.tayin_edilen_personel),
  },
  { title: "Araç", dataIndex: "arac", key: "arac", width: 90, render: (v) => v ?? <span className="ap-hucre-ince">—</span> },
  {
    title: "Durum",
    key: "durum",
    width: 110,
    render: (_, r) => <Tag color={DURUM_RENKLERI[r.durum] ?? "default"}>{r.durum_adi}</Tag>,
  },
  {
    title: "Son Güncelleme",
    dataIndex: "son_guncelleme",
    key: "guncelleme",
    width: 120,
    render: (v: string) => <span className="ap-hucre-ince">{tarihSaat(v)}</span>,
  },
  {
    title: "SLA",
    key: "sla",
    width: 110,
    render: (_, r) =>
      r.sla.olculur && r.sla.durum ? (
        <Tooltip title={`SLA: ${r.sla.ad}`}>
          <Tag color={SLA_RENKLERI[r.sla.durum] ?? "default"}>{slaMetni(r.sla)}</Tag>
        </Tooltip>
      ) : (
        <span className="ap-hucre-ince">{r.sla.ad ?? "—"}</span>
      ),
  },
];

function EkipListesi({ ekip }: { ekip: AnaPanelYaniti["ekip_durumu"] }) {
  if (!ekip.gorunur) {
    return <Bos>Ekibin canlı durumu Operasyon Merkezi yetkisiyle görünür.</Bos>;
  }
  if (!ekip.satirlar.length) {
    return <Bos>Kapsamınızda saha personeli yok. Personel kartında saha rolü ve birim tanımlanmalı.</Bos>;
  }
  return (
    <div>
      {ekip.satirlar.slice(0, 8).map((e: EkipSatiri) => (
        <div key={e.user_id} className="ap-ekip-satir" style={renkli(EKIP_RENGI[e.durum] ?? RENK.gri)}>
          <span className="ap-nokta" aria-hidden />
          <span className="ap-ekip-ad">
            <b>{e.ad}</b>
            <small>{e.birimler.join(", ") || "—"}</small>
          </span>
          <span className="ap-durum-rozet" style={renkli(EKIP_RENGI[e.durum] ?? RENK.gri)}>
            {e.durum_adi}
          </span>
          <span className="ap-ekip-is">
            {e.is_ ? (
              e.is_.id ? (
                <Link to={`/servis-isleri/${e.is_.id}`}>{e.is_.lokasyon ?? e.is_.no}</Link>
              ) : (
                e.is_.no
              )
            ) : (
              (e.aciklama ?? "—")
            )}
          </span>
          <span className="ap-ekip-sure">{e.sure_dk != null ? sureKisa(e.sure_dk) : ""}</span>
        </div>
      ))}
      {ekip.satirlar.length > 8 && (
        <div className="ap-hucre-ince" style={{ paddingTop: 4 }}>
          +{ekip.satirlar.length - 8} kişi daha
        </div>
      )}
    </div>
  );
}

function bekleme(a: BekleyenAksiyon) {
  const dk = a.bekleme_dk;
  const sinif = dk == null ? "" : dk >= GUN_DK ? "kirmizi" : dk >= 240 ? "turuncu" : "";
  return (
    <Tooltip title={a.bekleme_baslangic ? `Başlangıç: ${tarihSaat(a.bekleme_baslangic)}` : undefined}>
      <span className={`ap-bekleme ${sinif}`}>
        <ClockCircleOutlined /> {sureKisa(dk)}
      </span>
    </Tooltip>
  );
}

const AKSIYON_SUTUNLAR: ColumnsType<BekleyenAksiyon> = [
  {
    title: "Kayıt No / Açıklama",
    key: "no",
    ellipsis: true,
    render: (_, r) => (
      <Tooltip title={`${r.kaynak_birim} · ${r.aciklama ?? ""}`}>
        <Link to={r.yol}>{r.kayit_no}</Link>
        <div className="ap-hucre-ince" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
          {r.aciklama}
        </div>
      </Tooltip>
    ),
  },
  { title: "Hedef Birim", dataIndex: "hedef_birim", key: "hedef", width: 92, ellipsis: true },
  { title: "Bekleme", key: "bekleme", width: 80, render: (_, r) => bekleme(r) },
];

// --- Grafikler (yeni bağımlılık yok: SVG + CSS) -------------------------------------------------

function Halka({
  dilimler,
  boyut = 120,
  kalinlik = 18,
  orta,
}: {
  dilimler: { deger: number; renk: string; ad: string }[];
  boyut?: number;
  kalinlik?: number;
  orta: ReactNode;
}) {
  const r = (boyut - kalinlik) / 2;
  const cevre = 2 * Math.PI * r;
  const toplam = dilimler.reduce((t, d) => t + d.deger, 0);
  let birikim = 0;
  return (
    <div className="ap-halka" style={{ width: boyut, height: boyut }}>
      <svg width={boyut} height={boyut} viewBox={`0 0 ${boyut} ${boyut}`} role="img" aria-label="Dağılım grafiği">
        <circle cx={boyut / 2} cy={boyut / 2} r={r} fill="none" stroke="#eef2f6" strokeWidth={kalinlik} />
        {toplam > 0 &&
          dilimler
            .filter((d) => d.deger > 0)
            .map((d) => {
              const uzunluk = (d.deger / toplam) * cevre;
              const parca = (
                <circle
                  key={d.ad}
                  cx={boyut / 2}
                  cy={boyut / 2}
                  r={r}
                  fill="none"
                  stroke={d.renk}
                  strokeWidth={kalinlik}
                  strokeDasharray={`${uzunluk} ${cevre - uzunluk}`}
                  strokeDashoffset={-birikim}
                  transform={`rotate(-90 ${boyut / 2} ${boyut / 2})`}
                >
                  <title>{`${d.ad}: ${d.deger}`}</title>
                </circle>
              );
              birikim += uzunluk;
              return parca;
            })}
      </svg>
      <div className="ap-halka-orta">{orta}</div>
    </div>
  );
}

function Lejant({ dilimler, renkler }: { dilimler: GrafikDilimi[]; renkler: Record<string, string> }) {
  return (
    <div className="ap-lejant">
      {dilimler.map((d) => {
        const icerik = (
          <>
            <i style={renkli(renkler[d.kod] ?? RENK.gri)} />
            <em>{d.ad}</em>
            <b>{d.deger}</b>
          </>
        );
        return d.liste_yolu ? (
          <Link key={d.kod} to={d.liste_yolu}>
            {icerik}
          </Link>
        ) : (
          <span key={d.kod} className="satir">
            {icerik}
          </span>
        );
      })}
    </div>
  );
}

function DurumGrafigi({ g }: { g: AnaPanelYaniti["grafikler"] }) {
  const dilimler = g.durum_dagilimi.filter((d) => d.deger > 0);
  return (
    <Kart baslik="Duruma Göre İşler">
      {dilimler.length === 0 ? (
        <Bos>Bu süzgeçle açık ya da kapanış bekleyen iş yok.</Bos>
      ) : (
        <div className="ap-halka-sarici">
          <Halka
            dilimler={dilimler.map((d) => ({ deger: d.deger, ad: d.ad, renk: DURUM_GRAFIK_RENGI[d.kod] ?? RENK.gri }))}
            orta={
              <>
                <b>{g.acik_toplam}</b>
                <small>Açık İş Emri</small>
              </>
            }
          />
          <Lejant dilimler={dilimler} renkler={DURUM_GRAFIK_RENGI} />
        </div>
      )}
    </Kart>
  );
}

function BolumGrafigi({ g }: { g: AnaPanelYaniti["grafikler"] }) {
  const enCok = Math.max(1, ...g.bolum_is_yuku.map((b) => b.deger));
  return (
    <Kart baslik="Bölüme Göre İş Yükü">
      {g.bolum_is_yuku.length === 0 ? (
        <Bos>Görebileceğiniz bölüm yok.</Bos>
      ) : (
        <div className="ap-cubuklar" role="list">
          {g.bolum_is_yuku.map((b) => (
            <Link
              key={b.birim}
              to={b.liste_yolu}
              className="ap-cubuk"
              role="listitem"
              aria-label={`${b.ad}: ${b.deger} açık iş`}
              style={renkli(birimGorunum(b.birim).renk)}
            >
              <b>{b.deger}</b>
              <i style={{ height: `${(b.deger / enCok) * 100}%` }} />
              <small title={b.ad}>{b.ad}</small>
            </Link>
          ))}
        </div>
      )}
    </Kart>
  );
}

function PbGrafigi({ g }: { g: AnaPanelYaniti["grafikler"] }) {
  const pb = g.planli_bakim;
  return (
    <Kart baslik="Planlı Bakım Tamamlanma" sag={<Link to={pb.liste_yolu}>Listeyi Aç</Link>}>
      {pb.toplam === 0 ? (
        <Bos>Bu ay planlanmış bakım yok.</Bos>
      ) : (
        <div className="ap-halka-sarici">
          <Halka
            boyut={100}
            kalinlik={14}
            dilimler={pb.parcalar.map((p) => ({ deger: p.deger, ad: p.ad, renk: PB_RENGI[p.kod] ?? RENK.gri }))}
            orta={
              <>
                <b>%{pb.yuzde ?? 0}</b>
                <small>
                  {pb.tamamlanan} / {pb.toplam}
                </small>
              </>
            }
          />
          <Lejant dilimler={pb.parcalar} renkler={PB_RENGI} />
        </div>
      )}
    </Kart>
  );
}

function HaftalikPlan({ g }: { g: AnaPanelYaniti["grafikler"] }) {
  const enCok = Math.max(1, ...g.haftalik_plan.map((h) => h.adet));
  const toplam = g.haftalik_plan.reduce((t, h) => t + h.adet, 0);
  return (
    <Kart baslik="Haftalık Plan" sag={<Link to="/servis-planlama">Planlamaya Git</Link>}>
      {toplam === 0 && <Bos>Bu hafta planlanmış iş yok.</Bos>}
      <div className="ap-hafta">
        {g.haftalik_plan.map((h) => (
          <Link key={h.tarih} to={h.liste_yolu} className={`ap-hafta-satir${h.bugun ? " bugun" : ""}`}>
            <span>
              {dayjs(h.tarih).format("DD MMM")} {h.gun_adi}
            </span>
            <b>{h.adet} iş</b>
            <span className="ap-hafta-cubuk">
              <i style={{ width: `${(h.adet / enCok) * 100}%` }} />
            </span>
          </Link>
        ))}
      </div>
    </Kart>
  );
}

function AylikBakim({ g }: { g: AnaPanelYaniti["grafikler"] }) {
  const ay = g.aylik_bakim;
  return (
    <Kart baslik="Aylık Plan / Bakım Takvimi" sag={<Link to="/bakim">Tümünü Gör</Link>}>
      <div className="ap-ay-sayilar">
        <span>
          <b>{ay.planlanan}</b>Planlanan
        </span>
        <span>
          <b style={{ color: RENK.yesil }}>{ay.tamamlanan}</b>Tamamlanan
        </span>
        <span>
          <b style={{ color: ay.kalan ? RENK.kirmizi : undefined }}>{ay.kalan}</b>Kalan
        </span>
      </div>
      <Progress percent={ay.yuzde ?? 0} size="small" strokeColor={RENK.yesil} format={() => (ay.yuzde == null ? "—" : `%${ay.yuzde}`)} />
      <div className="ap-hucre-ince" style={{ marginTop: 4 }}>
        Yaklaşan Bakımlar
      </div>
      {ay.yaklasan.length === 0 ? (
        <Bos>Yaklaşan planlı bakım yok.</Bos>
      ) : (
        <div className="ap-yaklasan">
          {ay.yaklasan.map((y) => (
            <Link key={`${y.id}-${y.tarih}`} to={y.yol}>
              <b>{dayjs(y.tarih).format("DD.MM")}</b>
              <span>
                {y.musteri ?? y.no}
                {y.aciklama ? ` – ${y.aciklama}` : ""}
              </span>
            </Link>
          ))}
        </div>
      )}
    </Kart>
  );
}

// --- Sayfa -------------------------------------------------------------------------------------

export default function AnaPanelPage() {
  const yonlendir = useNavigate();
  const [arama, setArama] = useSearchParams();
  const suzgec = useMemo(() => suzgecOku(arama), [arama]);
  const panel = useQuery({
    queryKey: ["ana-panel", suzgec],
    queryFn: () => anaPanelApi.getir(suzgec),
    refetchInterval: YENILEME_MS,
    refetchIntervalInBackground: false,
    placeholderData: (onceki) => onceki,
  });
  const veri = panel.data;
  const sec = veri?.secenekler;

  const degistir = (yeni: Partial<AnaPanelSuzgeci>) => {
    const p = anaPanelParametreleri({ ...suzgec, ...yeni });
    setArama(p, { replace: true });
  };

  const aralik: [Dayjs, Dayjs] | null = veri ? [dayjs(veri.donem.bas), dayjs(veri.donem.bit)] : null;
  const secim = (deger: string | number | undefined, secenekler: { value: string | number; label: string }[]) => ({
    value: deger,
    options: secenekler,
    allowClear: true,
    placeholder: "Tümü",
    size: "small" as const,
    showSearch: { optionFilterProp: "label" as const },
    popupMatchSelectWidth: false,
  });

  return (
    <div className="ap">
      <div className="ap-ust">
        <div>
          <h1 className="ap-baslik">Ana Panel</h1>
          <div className="ap-alt-baslik">Tüm operasyonların anlık özeti ve ekiplerin güncel durumu</div>
        </div>
      </div>

      <div className="ap-suzgec" role="search" aria-label="Ana panel süzgeçleri">
        <div className="ap-suzgec-alan">
          <span>Bölüm</span>
          <Select
            aria-label="Bölüm"
            {...secim(suzgec.birim, (sec?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad })))}
            onChange={(v) => degistir({ birim: v as string | undefined })}
          />
        </div>
        <div className="ap-suzgec-alan">
          <span>Durum</span>
          <Select
            aria-label="Durum"
            {...secim(suzgec.durum_grubu, (sec?.durum_gruplari ?? []).map((d) => ({ value: d.kod, label: d.ad })))}
            onChange={(v) => degistir({ durum_grubu: v as string | undefined })}
          />
        </div>
        <div className="ap-suzgec-alan">
          <span>Şef</span>
          <Select
            aria-label="Şef"
            {...secim(suzgec.sef_id, (sec?.sefler ?? []).map((k) => ({ value: k.id, label: k.ad ?? `#${k.id}` })))}
            onChange={(v) => degistir({ sef_id: v as number | undefined })}
          />
        </div>
        <div className="ap-suzgec-alan">
          <span>Personel</span>
          <Select
            aria-label="Personel"
            {...secim(suzgec.personel_id, (sec?.personel ?? []).map((k) => ({ value: k.id, label: k.ad ?? `#${k.id}` })))}
            onChange={(v) => degistir({ personel_id: v as number | undefined })}
          />
        </div>
        <div className="ap-suzgec-alan">
          <span>Lokasyon</span>
          <Select
            aria-label="Lokasyon"
            {...secim(suzgec.lokasyon_id, (sec?.lokasyonlar ?? []).map((l) => ({ value: l.id, label: l.ad ?? `#${l.id}` })))}
            notFoundContent="Açık işi olan lokasyon yok"
            onChange={(v) => degistir({ lokasyon_id: v as number | undefined })}
          />
        </div>
        <div className="ap-suzgec-alan">
          <span>Dönem</span>
          <DatePicker.RangePicker
            size="small"
            format="DD.MM.YYYY"
            value={aralik}
            allowClear
            style={{ width: 210 }}
            onChange={(d) =>
              degistir({
                bas: d?.[0] ? d[0].format("YYYY-MM-DD") : undefined,
                bit: d?.[1] ? d[1].format("YYYY-MM-DD") : undefined,
              })
            }
          />
        </div>
        <Tooltip title="İş listesinde bütün süzgeçler (tür, öncelik, müşteri, arama) kullanılabilir">
          <Button size="small" type="text" icon={<FilterOutlined />} onClick={() => yonlendir(listeSuzgeci(suzgec))}>
            Daha Fazla Filtre
          </Button>
        </Tooltip>
        <span className="ap-suzgec-sag">
          {veri && (
            <span className="ap-son-guncelleme" aria-live="polite">
              Son güncelleme: {dayjs(veri.guncelleme_zamani).format("DD.MM.YYYY HH:mm")}
            </span>
          )}
          <Button
            size="small"
            type="primary"
            icon={<ReloadOutlined />}
            loading={panel.isFetching}
            onClick={() => panel.refetch()}
          >
            Yenile
          </Button>
        </span>
      </div>

      {panel.isError && (
        <Alert
          type="error"
          showIcon
          title="Ana panel yüklenemedi"
          description={(panel.error as Error)?.message}
          action={
            <Button size="small" onClick={() => panel.refetch()}>
              Tekrar dene
            </Button>
          }
        />
      )}

      {!veri ? (
        panel.isError ? null : <Skeleton active paragraph={{ rows: 10 }} />
      ) : (
        <>
          <div className="ap-kpiler">
            {veri.kpiler.map((k) => (
              <KpiKarti key={k.kod} k={k} />
            ))}
          </div>

          <div className="ap-orta">
            <div className="ap-sol">
              <Kart baslik="Canlı Operasyon Özeti">
                {veri.birim_ozeti.length === 0 ? (
                  <Bos>Görebileceğiniz bir birim yok. Birim üyeliğiniz için yöneticinize başvurun.</Bos>
                ) : (
                  <div className="ap-birimler">
                    {veri.birim_ozeti.map((b) => (
                      <BirimKarti key={b.birim} b={b} />
                    ))}
                  </div>
                )}
              </Kart>
              <Kart
                baslik="Aktif İşler / Kim Ne Yapıyor"
                sag={<Link to={veri.aktif_isler.liste_yolu}>Tüm İşleri Gör</Link>}
              >
                <Table<AktifIs>
                  className="ap-tablo"
                  rowKey="id"
                  size="small"
                  columns={AKTIF_SUTUNLAR}
                  dataSource={veri.aktif_isler.satirlar}
                  pagination={false}
                  scroll={{ x: 1340 }}
                  locale={{ emptyText: "Bu süzgeçle açık iş yok. Süzgeçleri genişletmeyi deneyin." }}
                />
              </Kart>
            </div>
            <div className="ap-sag">
              <Kart
                baslik="Canlı Ekip Durumu"
                sag={veri.ekip_durumu.liste_yolu ? <Link to={veri.ekip_durumu.liste_yolu}>Tüm Ekipleri Gör</Link> : null}
              >
                {veri.ekip_durumu.gorunur && veri.ekip_durumu.satirlar.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
                    {veri.ekip_durumu.ozet
                      .filter((o) => o.adet > 0)
                      .map((o) => (
                        <span key={o.durum} className="ap-durum-rozet" style={renkli(EKIP_RENGI[o.durum] ?? RENK.gri)}>
                          {o.ad} {o.adet}
                        </span>
                      ))}
                  </div>
                )}
                <EkipListesi ekip={veri.ekip_durumu} />
              </Kart>
              <Kart
                baslik="Birimler Arası Bekleyen Aksiyonlar"
                sag={veri.bekleyen_aksiyonlar.toplam > 0 ? <span className="ap-hucre-ince">Toplam {veri.bekleyen_aksiyonlar.toplam}</span> : null}
              >
                {veri.bekleyen_aksiyonlar.ozet.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
                    {veri.bekleyen_aksiyonlar.ozet.map((o) => (
                      <Tag key={o.hedef_birim} style={{ marginInlineEnd: 0 }}>
                        {o.hedef_birim}: {o.adet}
                      </Tag>
                    ))}
                  </div>
                )}
                <Table<BekleyenAksiyon>
                  className="ap-tablo"
                  rowKey={(r) => `${r.kayit_id}-${r.hedef_birim}`}
                  size="small"
                  columns={AKSIYON_SUTUNLAR}
                  dataSource={veri.bekleyen_aksiyonlar.satirlar}
                  pagination={false}
                  locale={{ emptyText: "Birimler arasında bekleyen iş yok." }}
                />
              </Kart>
            </div>
          </div>

          <div className="ap-grafikler">
            <DurumGrafigi g={veri.grafikler} />
            <BolumGrafigi g={veri.grafikler} />
            <PbGrafigi g={veri.grafikler} />
            <HaftalikPlan g={veri.grafikler} />
            <AylikBakim g={veri.grafikler} />
          </div>
        </>
      )}
    </div>
  );
}
