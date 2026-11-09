/**
 * Benim İşlerim — teknisyenin tek mobil ekranı (TS-077/078, E09-D01).
 *
 * Tek sayfa, iki sekme: "İşlerim" (GECIKEN/BUGÜN/YARIN/SONRA/PLANSIZ grupları,
 * aynı gün + tesis tek ziyaret kartı, her iş ayrı seçilir) ve "Bugünüm"
 * (yalnız kendi bölümlerim, kişi-saat, mola hariç, gün sonu süre eksik
 * listesi). Ayrı "Ziyaretlerim" sayfası yok.
 *
 * Dar ekran (375 px; yan menü 56 px + dolgu → ~279 px içerik): tablo yok,
 * her şey dikey; uzun metin kırılır; ana düğmeler ≥ 44 px. Bağlantı yoksa
 * sayaç düğmeleri kilitli (çevrimdışı yok).
 *
 * Kayıt yoksa süre "Süre kaydı eksik" yazılır — "0 dk" DEĞİL.
 */
import { CalendarOutlined, EditOutlined, RightOutlined, ToolOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, DatePicker, Empty, Grid, List, Space, Spin, Table, Tabs, Tag, Timeline, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import DurumCubugu from "../fiori/DurumCubugu";
import {
  ONCELIK_ETIKETLERI,
  SERVIS_DURUM_GRUPLARI,
  TAYIN,
  servisDurumEtiketi,
  type KategoriRengi,
} from "../fiori/etiketler";
import KategoriSeridi from "../fiori/KategoriSeridi";
import {
  AltNot,
  FioriBolum,
  FioriKart,
  TUMU_KATEGORISI,
  gunu,
  kategorilerOlustur,
} from "../fiori/ListeOgeleri";
import { ManuelKayitPenceresi } from "../components/SayacDugmeleri";
import SlaEtiketi from "../components/SlaEtiketi";
import Statistic from "../components/Statistic";
import {
  FAALIYET_ADLARI,
  KAYNAK_ADLARI,
  SURE_DURUMU_ADLARI,
  servisZaman,
  sureMetni,
  type MobilIs,
  type Ziyaret,
} from "../api/servisZaman";

/** Zaman grubu → kategori şeridi rengi (gecikmiş/plansız kırmızı, planlı yeşil). */
const GRUP_KATEGORI_RENGI: Record<string, KategoriRengi> = {
  GECIKEN: "kirmizi",
  BUGUN: "yesil",
  YARIN: "yesil",
  SONRA: "yesil",
  PLANSIZ: "kirmizi",
};

function IsSatiri({ is }: { is: MobilIs }) {
  const git = useNavigate();
  const kapali = ["TAMAMLANDI", "KAPATILDI", "IPTAL"].includes(is.durum);
  return (
    <FioriKart
      durum={servisDurumEtiketi(is.durum)}
      durumTon={is.durum === "IPTAL" ? "olumsuz" : kapali ? "kapali" : undefined}
      no={is.so_no}
      rozetler={
        <>
          {ONCELIK_ETIKETLERI[is.oncelik] && (
            <AltNot tur={is.oncelik === "KRITIK" ? "kritik" : "uyari"}>{ONCELIK_ETIKETLERI[is.oncelik]}</AltNot>
          )}
          {!is.bana_atanmis && <Tag color="purple">ekip</Tag>}
          <SlaEtiketi sla={is.sla} />
        </>
      }
      baslik={is.konu}
      altSatirlar={[
        (is.plan_baslangic ? dayjs(is.plan_baslangic).format("HH:mm") + " · " : "") +
          (is.sure_durumu === "EKSIK"
            ? "Süre kaydı eksik"
            : (sureMetni(is.kisi_saat_dk) ?? SURE_DURUMU_ADLARI[is.sure_durumu ?? ""] ?? "")),
      ]}
      sag={<RightOutlined />}
      onClick={() => git(`/benim-islerim/${is.id}`)}
    />
  );
}

function ZiyaretKarti({ z, isler }: { z: Ziyaret; isler: MobilIs[] }) {
  const baslik = [z.musteri, z.lokasyon].filter(Boolean).join(" · ") || "Lokasyon belirtilmemiş";
  return (
    <div className="fm-ziyaret">
      <div className="fm-ziyaret-ust">
        {baslik}
        <div className="fm-kart-alt">
          {[z.ilce, z.il].filter(Boolean).join(" / ")}
          {z.plan_tarihi ? ` · ${gunu(z.plan_tarihi)}` : ""}
          {isler.length > 1 ? ` · ${isler.length} iş` : ""}
        </div>
      </div>
      {isler.map((is) => (
        <IsSatiri key={is.id} is={is} />
      ))}
    </div>
  );
}

/** Tablo satırı: iş + bağlı olduğu ziyaret ve zaman grubu (geniş ekran görünümü). */
interface TabloSatiri {
  is: MobilIs;
  z: Ziyaret;
  grupKod: string;
  grupAd: string;
}

/**
 * Geniş ekranda (≥ 992 px) Servis İşleri listesiyle aynı tablo görünümü
 * (2026-11-09 kullanıcı isteği). Telefonda kart görünümü kalır (dar ekranda
 * tablo okunmaz). Satır → iş detayı (/benim-islerim/:id).
 */
function IslerTablosu({ satirlar }: { satirlar: TabloSatiri[] }) {
  const git = useNavigate();
  const ac = (id: number) => git(`/benim-islerim/${id}`);
  const sutunlar: ColumnsType<TabloSatiri> = [
    {
      title: "Durum",
      key: "durum",
      width: 150,
      align: "center",
      render: (_, { is }) => {
        const kapali = ["TAMAMLANDI", "KAPATILDI", "IPTAL"].includes(is.durum);
        return (
          <button
            type="button"
            className={`fl-durum${is.durum === "IPTAL" ? " olumsuz" : kapali ? " kapali" : ""}`}
            onClick={() => ac(is.id)}
          >
            {servisDurumEtiketi(is.durum)}
          </button>
        );
      },
    },
    {
      title: "İş No",
      key: "no",
      width: 170,
      align: "center",
      render: (_, { is }) => (
        <>
          <span className="fl-no-rozet" role="link" tabIndex={0} onClick={() => ac(is.id)}>
            {is.so_no}
          </span>
          {ONCELIK_ETIKETLERI[is.oncelik] && (
            <span className={`fl-alt-not ${is.oncelik === "KRITIK" ? "kritik" : "uyari"}`}>
              {ONCELIK_ETIKETLERI[is.oncelik]}
            </span>
          )}
        </>
      ),
    },
    {
      title: "Zaman",
      key: "grup",
      width: 110,
      align: "center",
      render: (_, r) => (
        <span className={`fl-kucuk${GRUP_KATEGORI_RENGI[r.grupKod] === "kirmizi" ? " fl-kirmizi" : ""}`}>
          {r.grupAd}
        </span>
      ),
    },
    {
      title: "Plan Tarihi",
      key: "tarih",
      width: 100,
      align: "center",
      render: (_, { is, z }) => {
        const t = is.plan_baslangic ?? z.plan_tarihi;
        return t ? gunu(t) : "—";
      },
    },
    {
      title: "Plan Saati",
      key: "saat",
      width: 80,
      align: "center",
      render: (_, { is }) => (is.plan_baslangic ? dayjs(is.plan_baslangic).format("HH:mm") : "—"),
    },
    {
      title: "Açıklama",
      key: "konu",
      width: 320,
      render: (_, { is }) => (
        <button type="button" className="fl-aciklama" title={is.konu} onClick={() => ac(is.id)}>
          {is.konu}
        </button>
      ),
    },
    {
      title: "Müşteri",
      key: "musteri",
      width: 200,
      render: (_, { z }) => (
        <span className="fl-kucuk" style={{ fontWeight: 600 }}>
          {z.musteri ?? "—"}
        </span>
      ),
    },
    {
      title: "Mahal",
      key: "mahal",
      width: 180,
      render: (_, { z }) => (
        <span className="fl-kucuk">
          {[z.lokasyon, [z.ilce, z.il].filter(Boolean).join(" / ")].filter(Boolean).join(" · ") || "—"}
        </span>
      ),
    },
    {
      title: "Süre",
      key: "sure",
      width: 120,
      align: "center",
      render: (_, { is }) => (
        <span className="fl-kucuk">
          {is.sure_durumu === "EKSIK"
            ? "Süre kaydı eksik"
            : (sureMetni(is.kisi_saat_dk) ?? SURE_DURUMU_ADLARI[is.sure_durumu ?? ""] ?? "—")}
        </span>
      ),
    },
    {
      title: "",
      key: "rozet",
      width: 120,
      align: "center",
      render: (_, { is }) => (
        <Space size={4} wrap>
          {!is.bana_atanmis && <Tag color="purple">ekip</Tag>}
          <SlaEtiketi sla={is.sla} />
        </Space>
      ),
    },
  ];
  return (
    <Table<TabloSatiri>
      className="fl-tablo"
      rowKey={(r) => r.is.id}
      size="small"
      columns={sutunlar}
      dataSource={satirlar}
      scroll={{ x: 1550 }}
      sticky={{ offsetHeader: 52 }}
      pagination={false}
      onRow={(r) => ({
        onClick: (e) => {
          const hedef = e.target as HTMLElement;
          if (hedef.closest("button, a, [role=link]")) return;
          ac(r.is.id);
        },
        style: { cursor: "pointer" },
      })}
    />
  );
}

function Islerim() {
  const genis = Grid.useBreakpoint().lg ?? false;
  const { yetkili } = useAuth();
  const [gorunum, setGorunum] = useState<"benim" | "tumu">("benim");
  const [kategori, setKategori] = useState<string>(TUMU_KATEGORISI.kod);
  const [durumGrubu, setDurumGrubu] = useState<string | undefined>();
  const liste = useQuery({
    queryKey: ["benim-islerim", gorunum],
    queryFn: () => servisZaman.benimIslerim(gorunum),
    refetchInterval: 60_000,
  });
  const gruplar = liste.data?.gruplar ?? [];
  const planlayabilir = yetkili("servis.planla");
  const durumlar = SERVIS_DURUM_GRUPLARI.find((g) => g.kod === durumGrubu)?.durumlar;
  const uyar = (is: MobilIs) => !durumlar || durumlar.includes(is.durum);

  // Süzgeç yalnız sunucunun döndürdüğü listeyi daraltır (sayım = görünen kart).
  const gorunen = gruplar
    .filter((g) => kategori === TUMU_KATEGORISI.kod || g.kod === kategori)
    .map((g) => ({
      ...g,
      ziyaretler: g.ziyaretler
        .map((z) => ({ z, isler: z.isler.filter(uyar) }))
        .filter((x) => x.isler.length > 0),
    }))
    .filter((g) => g.ziyaretler.length > 0);
  const sayi = gorunen.reduce((n, g) => n + g.ziyaretler.reduce((m, x) => m + x.isler.length, 0), 0);
  const kategoriler = kategorilerOlustur(
    gruplar.map((g) => ({ kod: g.kod, ad: g.baslik })),
    (k) => GRUP_KATEGORI_RENGI[k] ?? "yesil",
    (k) => (k === "GECIKEN" || k === "PLANSIZ" ? <ToolOutlined /> : <CalendarOutlined />),
  ).map((k) =>
    k.kod === TUMU_KATEGORISI.kod
      ? k
      : { ...k, sayi: gruplar.find((g) => g.kod === k.kod)?.ziyaretler.reduce((n, z) => n + z.isler.length, 0) },
  );

  return (
    <div className="fl-rapor">
      <KategoriSeridi kategoriler={kategoriler} secili={kategori} onSec={setKategori} />
      <div className="fl-ust">
        <span className="fl-kayit-sayisi">Kayıt Sayısı: {liste.isLoading ? "…" : sayi}</span>
      </div>
      <DurumCubugu
        gruplar={SERVIS_DURUM_GRUPLARI}
        secili={durumGrubu}
        onSec={setDurumGrubu}
        banaAit={gorunum === "benim"}
        onBanaAit={planlayabilir ? (v) => setGorunum(v ? "benim" : "tumu") : undefined}
        banaAitIpucu={
          gorunum === "benim" ? `${TAYIN.banaTayinEdilenler} · kapatınca birimimin tümü` : TAYIN.banaTayinEdilenler
        }
        onYenile={() => void liste.refetch()}
        yenileniyor={liste.isFetching}
      />
      <div style={{ padding: "0 8px 10px" }}>
        {liste.isError && <Alert type="error" showIcon title={(liste.error as Error).message} />}
        {liste.data?.kesildi && (
          <Alert type="warning" showIcon title="Liste uzun; yalnız ilk 500 iş gösteriliyor." />
        )}
        {liste.isLoading ? (
          <Spin />
        ) : sayi === 0 ? (
          <Empty description={gruplar.length && (durumGrubu || kategori !== TUMU_KATEGORISI.kod) ? "Seçili süzgeçte iş yok" : "Açık işiniz yok"} />
        ) : (
          genis ? (
          <IslerTablosu
            satirlar={gorunen.flatMap((g) =>
              g.ziyaretler.flatMap((x) => x.isler.map((is) => ({ is, z: x.z, grupKod: g.kod, grupAd: g.baslik }))),
            )}
          />
        ) : (
          <div className="fm-liste">
            {gorunen.map((g) => (
              <div key={g.kod} className="fm-liste">
                <div className={`fm-grup-baslik${GRUP_KATEGORI_RENGI[g.kod] === "kirmizi" ? " kirmizi" : ""}`}>
                  {g.baslik}
                  <span className="fm-grup-sayi">
                    · {g.ziyaretler.reduce((n, x) => n + x.isler.length, 0)} iş
                  </span>
                </div>
                {g.ziyaretler.map((x) => (
                  <ZiyaretKarti key={x.z.anahtar} z={x.z} isler={x.isler} />
                ))}
              </div>
            ))}
          </div>
        )
        )}
      </div>
    </div>
  );
}

function Bugunum() {
  const [gun, setGun] = useState<Dayjs>(dayjs());
  const [elle, setElle] = useState<{ id: number; so_no: string } | null>(null);
  const gunMetni = gun.format("YYYY-MM-DD");
  const ozet = useQuery({
    queryKey: ["bugunum", gunMetni],
    queryFn: () => servisZaman.bugunum(gunMetni),
  });
  const v = ozet.data;
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <DatePicker
        value={gun}
        format="DD.MM.YYYY"
        allowClear={false}
        onChange={(d) => d && setGun(d)}
        disabledDate={(d) => d.isAfter(dayjs(), "day") || d.isBefore(dayjs().subtract(31, "day"))}
        style={{ width: "100%", maxWidth: 220 }}
      />
      {ozet.isError && <Alert type="error" showIcon title={(ozet.error as Error).message} />}
      {v && (
        <>
          <FioriBolum baslik="Günün özeti">
            <Space wrap size={[24, 8]}>
              {v.kisi_saat_dk === null ? (
                <Statistic title="Kişi-saat" value="Kayıt yok" />
              ) : (
                <Statistic title="Kişi-saat" value={sureMetni(v.kisi_saat_dk) ?? ""} />
              )}
              {Object.entries(v.faaliyet_dk).map(([f, dk]) => (
                <Statistic
                  key={f}
                  title={FAALIYET_ADLARI[f as keyof typeof FAALIYET_ADLARI] ?? f}
                  value={sureMetni(dk) ?? ""}
                />
              ))}
              {v.mola_dk !== null && (
                <Statistic title="Mola (hariç)" value={sureMetni(v.mola_dk) ?? ""} />
              )}
            </Space>
          </FioriBolum>

          <FioriBolum baslik="Süre kaydı eksik işler">
            {v.sure_eksik_isler.length === 0 ? (
              <Typography.Text type="secondary">Eksik kayıt yok.</Typography.Text>
            ) : (
              <List
                size="small"
                dataSource={v.sure_eksik_isler}
                rowKey="id"
                renderItem={(i) => (
                  <List.Item
                    style={{ paddingInline: 0, flexWrap: "wrap", gap: 8 }}
                    actions={[
                      <Button
                        key="elle"
                        style={{ minHeight: 44 }}
                        icon={<EditOutlined />}
                        onClick={() => setElle({ id: i.id, so_no: i.so_no })}
                      >
                        Elle gir
                      </Button>,
                    ]}
                  >
                    <div style={{ minWidth: 0 }}>
                      <Link to={`/benim-islerim/${i.id}`} className="fl-no-rozet">
                        {i.so_no}
                      </Link>{" "}
                      <Tag color="red">Süre kaydı eksik</Tag>
                      <div className="fm-kart-baslik">{i.konu}</div>
                    </div>
                  </List.Item>
                )}
              />
            )}
          </FioriBolum>

          <FioriBolum baslik="Bölümler">
            {v.bolumler.length === 0 ? (
              <Typography.Text type="secondary">Bu gün kayıt yok.</Typography.Text>
            ) : (
              <Timeline
                items={v.bolumler.map((b) => ({
                  color: b.iptal_turu ? "gray" : b.faaliyet === "MOLA" ? "orange" : "blue",
                  content: (
                    <div style={{ opacity: b.iptal_turu ? 0.55 : 1 }}>
                      <Typography.Text strong>
                        {dayjs(b.started_at).format("HH:mm")}–
                        {b.ended_at ? dayjs(b.ended_at).format("HH:mm") : "…"}
                      </Typography.Text>{" "}
                      {FAALIYET_ADLARI[b.faaliyet]} · {b.so_no}
                      {b.sure_dk !== null && ` · ${sureMetni(b.sure_dk)}`}
                      {b.kaynak !== "CANLI" && (
                        <Tag style={{ marginInlineStart: 6 }}>{(KAYNAK_ADLARI[b.kaynak] ?? b.kaynak.replaceAll("_", " ")).toLocaleLowerCase("tr")}</Tag>
                      )}
                      {b.iptal_turu && <Tag>{b.iptal_turu === "GERI_ALINDI" ? "geri alındı" : "iptal"}</Tag>}
                    </div>
                  ),
                }))}
              />
            )}
          </FioriBolum>
        </>
      )}
      <ManuelKayitPenceresi
        acik={!!elle}
        isId={elle?.id ?? null}
        soNo={elle?.so_no}
        onKapat={() => setElle(null)}
      />
    </Space>
  );
}

export default function BenimIslerimPage() {
  const [params, setParams] = useSearchParams();
  const sekme = params.get("sekme") === "bugunum" ? "bugunum" : "islerim";
  // Geniş ekranda İşlerim tablo görünümü sayfayı tam kullanır; telefon/kart
  // görünümü ve Bugünüm okunabilir genişlikte (760 px) kalır.
  const genis = Grid.useBreakpoint().lg ?? false;
  return (
    <div className="fm-sayfa" style={{ maxWidth: genis && sekme === "islerim" ? undefined : 760 }}>
      <Tabs
        activeKey={sekme}
        onChange={(k) => setParams(k === "bugunum" ? { sekme: "bugunum" } : {})}
        items={[
          { key: "islerim", label: "İşlerim", children: <Islerim /> },
          { key: "bugunum", label: "Bugünüm", children: <Bugunum /> },
        ]}
      />
    </div>
  );
}
