import {
  AlertOutlined,
  CalendarOutlined,
  CarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CustomerServiceOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  HourglassOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  WarningOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import { Progress, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import type { CSSProperties, ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  type AktifIs,
  type AnaPanelKpi,
  type AnaPanelSuzgeci,
  type AnaPanelYaniti,
  type BekleyenAksiyon,
  type BirimOzeti,
  type EkipSatiri,
  type GrafikDilimi,
} from "../../api/anaPanel";
import { SLA_RENKLERI, sureMetni } from "../../api/servisOperasyon";
import { DURUM_RENKLERI, ONCELIK_RENKLERI } from "../../api/teknikServis";
import { TAYIN } from "../../fiori/etiketler";

/**
 * Ana Panel teknik servis parçaları (KARARLAR 2026-11-04 §4) — `AnaPanelPage`'ten
 * ayrıldı (KARARLAR 2026-11-09 S8: bileşen kaydı `kayit.tsx` bunları çizer).
 *
 * Bütün sayılar `GET /api/teknik-servis/ana-panel`'den gelir ve kullanıcının
 * kapsamıyla (birim, kendi işleri, etkin şirket) sunucuda süzülür. Kural
 * "sayı = liste": tıklanan her sayı `liste_yolu`'na gider; o listenin toplamı
 * kartta yazanla aynıdır. Ön yüz sayı/SLA HESAPLAMAZ, yalnız çizer.
 */

export const YENILEME_MS = 60_000;

export const RENK = {
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
export const renkli = (renk: string): Renkli => ({ "--renk": renk });

export const KPI_GORUNUM: Record<string, { ikon: ReactNode; renk: string; alt?: string; artisKotu?: boolean }> = {
  acik_is: { ikon: <FileTextOutlined />, renk: RENK.mavi, artisKotu: true },
  planli_bakim: { ikon: <CalendarOutlined />, renk: RENK.yesil },
  acil_ariza: { ikon: <WarningOutlined />, renk: RENK.kirmizi, artisKotu: true },
  poc_acik: { ikon: <CustomerServiceOutlined />, renk: RENK.mor, artisKotu: true },
  sla_riski: { ikon: <ClockCircleOutlined />, renk: RENK.turuncu, alt: "riskte + aşılmış", artisKotu: true },
  sahadaki_ekip: { ikon: <TeamOutlined />, renk: RENK.camgobegi, alt: "aktif / toplam" },
  askida: { ikon: <HourglassOutlined />, renk: RENK.gri, artisKotu: true },
  bekleyen_onay: { ikon: <CheckCircleOutlined />, renk: RENK.mor, alt: "kapanış / kalite onayı" },
};

export const BIRIM_GORUNUM: Record<string, { ikon: ReactNode; renk: string }> = {
  GUVENLIK: { ikon: <SafetyCertificateOutlined />, renk: RENK.mavi },
  HABERLESME: { ikon: <WifiOutlined />, renk: RENK.yesil },
  POC: { ikon: <CustomerServiceOutlined />, renk: RENK.mor },
  MOBILITE: { ikon: <CarOutlined />, renk: RENK.turuncu },
  ARAC_TAKIP: { ikon: <EnvironmentOutlined />, renk: RENK.camgobegi },
};
export const birimGorunum = (kod: string) => BIRIM_GORUNUM[kod] ?? { ikon: <AlertOutlined />, renk: RENK.gri };

export const DURUM_GRAFIK_RENGI: Record<string, string> = {
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

export const EKIP_RENGI: Record<string, string> = {
  SAHADA: RENK.yesil,
  UZAKTAN: RENK.mor,
  ATOLYEDE: RENK.turuncu,
  MUSAIT: RENK.gri,
  IZINLI: RENK.mavi,
};

export const PB_RENGI: Record<string, string> = {
  tamamlanan: RENK.yesil,
  devam_eden: RENK.mavi,
  planlanan: "#c6cdd5",
};

export const GUN_DK = 1440;

// --- Süzgeç (adres çubuğu) ---------------------------------------------------------------

export function sayi(p: URLSearchParams, k: string): number | undefined {
  const v = p.get(k);
  return v && /^\d+$/.test(v) ? Number(v) : undefined;
}

export function suzgecOku(p: URLSearchParams): AnaPanelSuzgeci {
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
export function listeSuzgeci(s: AnaPanelSuzgeci): string {
  const p = new URLSearchParams();
  if (s.birim) p.set("birim", s.birim);
  p.set("durum_grubu", s.durum_grubu ?? "ACIK");
  if (s.sef_id) p.set("sef_id", String(s.sef_id));
  if (s.personel_id) p.set("teknisyen_id", String(s.personel_id));
  if (s.lokasyon_id) p.set("adres_id", String(s.lokasyon_id));
  return `/servis-isleri?${p}`;
}

// --- Biçim yardımcıları ----------------------------------------------------------------------

export const tarihSaat = (t?: string | null) => (t ? dayjs(t).format("DD.MM.YYYY HH:mm") : "—");

/** Sunucunun verdiği dakikayı kısa metne çevirir (hesap değil, biçim). */
export function sureKisa(dk: number | null | undefined): string {
  if (dk == null) return "—";
  if (dk >= GUN_DK) return `${Math.floor(dk / GUN_DK)} gün`;
  if (dk >= 60) return `${Math.floor(dk / 60)} sa ${dk % 60 ? `${dk % 60} dk` : ""}`.trim();
  return `${dk} dk`;
}

export function slaMetni(sla: AktifIs["sla"]): string {
  if (!sla.ad) return "—";
  if (sla.kalan_dk == null) return sla.ad;
  if (sla.durum === "ASILDI") return `Gecikti ${sureMetni(sla.kalan_dk)}`;
  if (sla.durum === "DURDURULDU") return "Durduruldu";
  return sureMetni(sla.kalan_dk);
}

// --- Parçalar --------------------------------------------------------------------------------

export function Kart({ baslik, sag, children, style }: { baslik: ReactNode; sag?: ReactNode; children: ReactNode; style?: CSSProperties }) {
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

export function Bos({ children }: { children: ReactNode }) {
  return <div className="ap-bos">{children}</div>;
}

export function Degisim({ k, artisKotu }: { k: AnaPanelKpi; artisKotu?: boolean }) {
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

export function KpiKarti({ k }: { k: AnaPanelKpi }) {
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

export function BirimKarti({ b }: { b: BirimOzeti }) {
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

export function kisiler(liste: AktifIs["tayin_edilen_personel"]) {
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

export const AKTIF_SUTUNLAR: ColumnsType<AktifIs> = [
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

export function EkipListesi({ ekip }: { ekip: AnaPanelYaniti["ekip_durumu"] }) {
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

export function bekleme(a: BekleyenAksiyon) {
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

export const AKSIYON_SUTUNLAR: ColumnsType<BekleyenAksiyon> = [
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

export function Halka({
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

export function Lejant({ dilimler, renkler }: { dilimler: GrafikDilimi[]; renkler: Record<string, string> }) {
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

export function DurumGrafigi({ g }: { g: AnaPanelYaniti["grafikler"] }) {
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

export function BolumGrafigi({ g }: { g: AnaPanelYaniti["grafikler"] }) {
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

export function PbGrafigi({ g }: { g: AnaPanelYaniti["grafikler"] }) {
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

export function HaftalikPlan({ g }: { g: AnaPanelYaniti["grafikler"] }) {
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

export function AylikBakim({ g }: { g: AnaPanelYaniti["grafikler"] }) {
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
