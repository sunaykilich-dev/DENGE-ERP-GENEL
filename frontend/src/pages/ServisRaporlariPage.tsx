import { FileExcelOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  filtreOku,
  filtreSorgusu,
  servisRaporlariApi,
  type BasitKpi,
  type KirilimSatiri,
  type KpiIsSatiri,
  type PersonelSatiri,
  type RaporFiltresiDegeri,
  type RaporKpi,
  type RaporOlcumu,
  type TrendSatiri,
} from "../api/servisRaporlari";
import { useAuth } from "../auth/AuthContext";
import KpiKutusu from "../components/KpiKutusu";
import RaporFiltresi from "../components/RaporFiltresi";
import Statistic from "../components/Statistic";

/**
 * Servis Raporları (TS-181…187, TS-201) — eski 8 sayfalı Excel'in ekranı.
 *
 * Kurallar:
 * - Her sayı SUNUCUDAN gelir; istemci KPI, oran, kişi-saat hesaplamaz.
 * - KPI kutusu tıklanınca aynı filtreyle `/kpi-liste?kpi=` açılır; listenin
 *   toplamı kutudaki sayıya eşittir (sunucuda aynı sorgu). Süzgeç Servis
 *   İşleri ekranına taşınabiliyorsa oraya bağlantı da verilir.
 * - Filtre, sekme ve açık liste URL'dedir (paylaşılabilir bağlantı).
 * - Excel `servis_rapor.disaaktar`; kişi sekmesi `servis_rapor.personel`
 *   (sunucu da 403 verir; düğme/sekme yalnız gizlenir).
 * - Ölçülemeyen değer "—"dir, 0 değil (süre kaydı yoksa "eksik").
 */

const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");
const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");
const sayi = (n: number | null | undefined, ek = "") =>
  n === null || n === undefined ? "—" : `${n.toLocaleString("tr-TR")}${ek}`;
const OLCU_EKI: Record<string, string> = { yuzde: " %", saat: " sa", kisi_saat: " kişi-sa" };

function varsayilanla(f: RaporFiltresiDegeri): RaporFiltresiDegeri {
  if (f.baslangic && f.bitis) return f;
  const bugun = dayjs();
  return {
    ...f,
    baslangic: f.baslangic ?? bugun.startOf("month").format("YYYY-MM-DD"),
    bitis: f.bitis ?? bugun.format("YYYY-MM-DD"),
  };
}

function FarkMetni({ k }: { k: { fark: number | null; fark_yuzde: number | null; onceki: number | null } }) {
  if (k.onceki === null || k.fark === null) return <Typography.Text type="secondary">Önceki: —</Typography.Text>;
  const isaret = k.fark > 0 ? "+" : "";
  return (
    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
      Önceki {sayi(k.onceki)} · {isaret}
      {sayi(k.fark)}
      {k.fark_yuzde !== null ? ` (${isaret}${sayi(k.fark_yuzde)} %)` : ""}
    </Typography.Text>
  );
}

interface SekmeProps {
  filtre: RaporFiltresiDegeri;
  listeYolu: (kod: string) => string;
}

function KpiIzgarasi({ kpiler, listeYolu }: { kpiler: (RaporKpi | BasitKpi)[]; listeYolu: (kod: string) => string }) {
  return (
    <Row gutter={[12, 12]}>
      {kpiler.map((k) => (
        <Col key={k.kod} xs={12} sm={8} md={6} xl={4}>
          <KpiKutusu
            kod={k.kod}
            baslik={k.baslik}
            tanim={k.tanim}
            deger={k.deger}
            yol={listeYolu(k.kod)}
            vurgu={"vurgu" in k ? k.vurgu : "normal"}
          />
          {"fark" in k && <FarkMetni k={k} />}
        </Col>
      ))}
    </Row>
  );
}

function OlcuKarti({ o }: { o: RaporOlcumu }) {
  return (
    <Card size="small" style={{ height: "100%" }}>
      <Statistic
        title={
          <Tooltip title={o.tanim}>
            <span>{o.baslik}</span>
          </Tooltip>
        }
        value={o.deger === null ? "—" : o.deger}
        suffix={o.deger === null ? undefined : OLCU_EKI[o.olcu_birimi]}
        precision={o.deger === null ? undefined : 1}
      />
      <FarkMetni k={o} />
      {o.deger === null && o.eksik ? (
        <div>
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            {o.eksik} çözülmüş işte süre kaydı eksik
          </Typography.Text>
        </div>
      ) : null}
    </Card>
  );
}

function OzetSekmesi({ filtre, listeYolu }: SekmeProps) {
  const ozet = useQuery({
    queryKey: ["servis-rapor", "ozet", filtreSorgusu(filtre).toString()],
    queryFn: () => servisRaporlariApi.ozet(filtre),
  });
  if (ozet.isLoading) return <Spin />;
  if (ozet.error) return <Alert type="error" showIcon message={(ozet.error as Error).message} />;
  const v = ozet.data;
  if (!v) return <Empty />;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        Dönem {tarih(v.donem.baslangic)} – {tarih(v.donem.bitis)} · önceki {tarih(v.onceki_donem.baslangic)} –{" "}
        {tarih(v.onceki_donem.bitis)} · {v.kapsam} · oluşturma {zaman(v.generated_at)}
      </Typography.Text>
      {v.eksik_veri_is > 0 && (
        <Alert
          type="warning"
          showIcon
          message={
            <span>
              Bu seçimde {v.eksik_veri_is} çözülmüş işte süre kaydı eksik.{" "}
              <Link to={listeYolu("rapor_sure_eksik")}>Listeyi aç</Link>
            </span>
          }
        />
      )}
      {v.gecmis_degisebilir && (
        <Alert type="info" showIcon message="Olay geçmişi olmayan göç işleri var; geçmiş dönem değerleri değişebilir." />
      )}
      {v.bolumler.map((b) => {
        const kpiler = v.kpiler.filter((k) => k.bolum === b.kod);
        if (!kpiler.length) return null;
        return (
          <div key={b.kod}>
            <Typography.Title level={5}>{b.ad}</Typography.Title>
            <KpiIzgarasi kpiler={kpiler} listeYolu={listeYolu} />
          </div>
        );
      })}
      <div>
        <Typography.Title level={5}>Ölçüler</Typography.Title>
        <Row gutter={[12, 12]}>
          {v.olcumler.map((o) => (
            <Col key={o.kod} xs={12} sm={8} md={6} xl={4}>
              <OlcuKarti o={o} />
            </Col>
          ))}
        </Row>
      </div>
      <Card size="small" title="Toplam (tarih esasına göre)">
        <Space wrap>
          <Tag>Toplam {v.toplamlar.toplam}</Tag>
          <Tag color="blue">Açık {v.toplamlar.acik}</Tag>
          <Tag color="green">Çözüldü {v.toplamlar.cozuldu}</Tag>
          <Tag>İptal {v.toplamlar.iptal}</Tag>
        </Space>
        <Table
          size="small"
          style={{ marginTop: 12 }}
          pagination={false}
          rowKey="kategori"
          dataSource={v.kategoriler}
          scroll={{ x: 420 }}
          columns={[
            { title: "Kategori", dataIndex: "ad" },
            { title: "Gelen", dataIndex: "gelen", align: "right" },
            { title: "Çözülen", dataIndex: "cozulen", align: "right" },
            { title: "Dönem sonu açık", dataIndex: "donem_sonu_acik", align: "right" },
          ]}
        />
      </Card>
    </Space>
  );
}

const KIRILIM_SUTUNLARI: ColumnsType<KirilimSatiri> = [
  { title: "Değer", dataIndex: "ad", fixed: "left" },
  { title: "Toplam", dataIndex: "toplam", align: "right" },
  { title: "Açık", dataIndex: "acik", align: "right" },
  { title: "Çözülen", dataIndex: "cozuldu", align: "right" },
  { title: "İptal", dataIndex: "iptal", align: "right" },
  { title: "Beklemede", dataIndex: "beklemede", align: "right" },
  { title: "Kritik", dataIndex: "kritik", align: "right" },
  { title: "Süre eksik", dataIndex: "sure_eksik", align: "right" },
  { title: "Kişi-saat", dataIndex: "kisi_saat", align: "right", render: (v: number | null) => sayi(v) },
];

function KirilimSekmesi({ filtre }: SekmeProps) {
  const [boyut, setBoyut] = useState("birim");
  const tanimlar = useQuery({ queryKey: ["servis-rapor", "tanimlar"], queryFn: servisRaporlariApi.tanimlar, staleTime: 300_000 });
  const veri = useQuery({
    queryKey: ["servis-rapor", "kirilim", boyut, filtreSorgusu(filtre).toString()],
    queryFn: () => servisRaporlariApi.kirilim(filtre, boyut),
  });
  const ekSutunlar: ColumnsType<KirilimSatiri> =
    boyut === "lokasyon"
      ? [
          { title: "Müşteri", dataIndex: "musteri" },
          { title: "Şehir", dataIndex: "sehir" },
        ]
      : [];
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Select
        style={{ width: 220 }}
        value={boyut}
        onChange={setBoyut}
        options={(tanimlar.data?.boyutlar ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
        aria-label="Kırılım boyutu"
      />
      {veri.error && <Alert type="error" showIcon message={(veri.error as Error).message} />}
      <Table
        size="small"
        loading={veri.isLoading}
        rowKey={(r) => `${r.anahtar}|${r.ikinci_ad ?? ""}`}
        dataSource={veri.data?.satirlar ?? []}
        columns={[...KIRILIM_SUTUNLARI.slice(0, 1), ...ekSutunlar, ...KIRILIM_SUTUNLARI.slice(1)]}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: 900 }}
        footer={() =>
          veri.data ? (
            <Typography.Text type="secondary">
              Detay toplamı {veri.data.toplam}
              {veri.data.toplam_esit === null
                ? " · bir iş birden çok teknisyende sayılabilir"
                : veri.data.toplam_esit
                  ? " · satır toplamı eşit"
                  : " · satır toplamı EŞİT DEĞİL"}
            </Typography.Text>
          ) : null
        }
      />
    </Space>
  );
}

const FAALIYETLER: [keyof PersonelSatiri, string][] = [
  ["SAHA", "Saha"],
  ["YOL", "Yol"],
  ["BEKLEME", "Bekleme"],
  ["UZAKTAN", "Uzaktan"],
  ["ATOLYE", "Atölye"],
  ["TEST", "Test"],
  ["DIGER", "Diğer"],
];

function KisiSaatSekmesi({ filtre }: SekmeProps) {
  const veri = useQuery({
    queryKey: ["servis-rapor", "kisi-saat", filtreSorgusu(filtre).toString()],
    queryFn: () => servisRaporlariApi.kisiSaat(filtre),
  });
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="Kişi-saat bordro değildir; mola dahil değildir. Süre kaydı olmayan atanmış teknisyen &quot;eksik&quot; satırıyla gösterilir."
      />
      {veri.error && <Alert type="error" showIcon message={(veri.error as Error).message} />}
      <Table
        size="small"
        loading={veri.isLoading}
        rowKey={(r) => `${r.user_id ?? r.personel}`}
        dataSource={veri.data?.satirlar ?? []}
        pagination={false}
        scroll={{ x: 1000 }}
        columns={[
          { title: "Personel", dataIndex: "personel", fixed: "left" },
          { title: "Kişi-saat", dataIndex: "kisi_saat", align: "right", render: (v) => sayi(v) },
          { title: "Farklı iş", dataIndex: "farkli_is", align: "right", render: (v) => sayi(v) },
          { title: "Kayıt", dataIndex: "kayit", align: "right" },
          ...FAALIYETLER.map(([k, ad]) => ({
            title: ad,
            dataIndex: k,
            align: "right" as const,
            render: (v: number | null) => sayi(v),
          })),
          { title: "Not", dataIndex: "not", render: (v: string | null) => (v ? <Tag color="orange">{v}</Tag> : null) },
        ]}
        summary={() =>
          veri.data ? (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0}>Toplam</Table.Summary.Cell>
              <Table.Summary.Cell index={1} align="right">
                {sayi(veri.data.toplam.toplam_saat)}
              </Table.Summary.Cell>
              <Table.Summary.Cell index={2} align="right">
                {veri.data.toplam.farkli_is}
              </Table.Summary.Cell>
            </Table.Summary.Row>
          ) : null
        }
      />
    </Space>
  );
}

function SlaSekmesi({ filtre, listeYolu }: SekmeProps) {
  const veri = useQuery({
    queryKey: ["servis-rapor", "sla", filtreSorgusu(filtre).toString()],
    queryFn: () => servisRaporlariApi.sla(filtre),
  });
  const v = veri.data;
  if (veri.isLoading) return <Spin />;
  if (veri.error) return <Alert type="error" showIcon message={(veri.error as Error).message} />;
  if (!v) return <Empty />;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        Yalnız günlük servis işleri. Ölçülemedi ve damgasız işler uyum paydasında yoktur.
      </Typography.Text>
      <KpiIzgarasi kpiler={v.kpiler} listeYolu={listeYolu} />
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="SLA uyumu" value={v.uyum_yuzde ?? "—"} suffix={v.uyum_yuzde === null ? undefined : "%"} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="Geciken açık (şu an)" value={v.geciken_acik ?? "—"} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="Ortalama çözüm (saat)" value={v.cozum_suresi.ortalama_saat ?? "—"} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small">
            <Statistic title="Medyan çözüm (saat)" value={v.cozum_suresi.medyan_saat ?? "—"} />
          </Card>
        </Col>
      </Row>
      <Table
        size="small"
        title={() => "Önceliğe göre"}
        rowKey="oncelik"
        pagination={false}
        dataSource={v.oncelik_kirilimi}
        scroll={{ x: 560 }}
        columns={[
          { title: "Öncelik", dataIndex: "ad" },
          { title: "Zamanında", dataIndex: "zamaninda", align: "right" },
          { title: "Aşıldı", dataIndex: "asildi", align: "right" },
          { title: "Ölçülemedi", dataIndex: "olculemedi", align: "right" },
          { title: "Uyum %", dataIndex: "uyum_yuzde", align: "right", render: (x) => sayi(x) },
        ]}
      />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={12}>
          <Table
            size="small"
            title={() => "Gecikme nedenleri (aşılan işler)"}
            rowKey={(r) => r.kod ?? "-"}
            pagination={false}
            dataSource={v.gecikme_nedenleri}
            columns={[
              { title: "Neden", dataIndex: "ad" },
              { title: "Adet", dataIndex: "adet", align: "right" },
            ]}
          />
        </Col>
        <Col xs={24} md={12}>
          <Table
            size="small"
            title={() => "İş beklemeleri (dönemde başlayan)"}
            rowKey="kod"
            pagination={false}
            dataSource={v.bekleme_nedenleri}
            columns={[
              {
                title: "Neden",
                dataIndex: "ad",
                render: (ad, r) => (
                  <span>
                    {ad} {r.sla_durdurur && <Tag color="blue">SLA durdurur</Tag>}
                  </span>
                ),
              },
              { title: "Adet", dataIndex: "adet", align: "right" },
              { title: "Saat", dataIndex: "toplam_saat", align: "right", render: (x) => sayi(x) },
            ]}
          />
        </Col>
      </Row>
    </Space>
  );
}

function TekrarSekmesi({ filtre, listeYolu }: SekmeProps) {
  const veri = useQuery({
    queryKey: ["servis-rapor", "tekrar", filtreSorgusu(filtre).toString()],
    queryFn: () => servisRaporlariApi.tekrarAriza(filtre),
  });
  const v = veri.data;
  if (veri.isLoading) return <Spin />;
  if (veri.error) return <Alert type="error" showIcon message={(veri.error as Error).message} />;
  if (!v) return <Empty />;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        Pencere {v.gun} gün. Onaylı oran yalnız kök nedeni &quot;aynı arıza&quot; teyitli işlerden; aday
        (onaysız) ayrı satırdır. Yeniden açılan iş tekrar arıza sayılmaz.
      </Typography.Text>
      <KpiIzgarasi kpiler={v.kpiler} listeYolu={listeYolu} />
      <Space wrap>
        <Tag color="red">Onaylı oran {sayi(v.onayli_oran, " %")}</Tag>
        <Tag>Aday oranı (onaysız) {sayi(v.aday_oran, " %")}</Tag>
      </Space>
      <Table
        size="small"
        rowKey={(r) => `${r.id}-${r.etiket}`}
        dataSource={v.satirlar}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: 700 }}
        columns={[
          { title: "İş", dataIndex: "so_no", render: (no, r) => <Link to={`/servis-isleri/${r.id}`}>{no}</Link> },
          { title: "Birim", dataIndex: "birim" },
          { title: "Kategori", dataIndex: "kategori" },
          { title: "Çözüm", dataIndex: "cozum", render: zaman },
          { title: "Durum", dataIndex: "etiket", render: (e: string) => <Tag>{e}</Tag> },
          { title: "Sonraki iş", dataIndex: "sonraki_isler", render: (x: string[]) => x.join(", ") },
        ]}
      />
    </Space>
  );
}

function YenidenSekmesi({ filtre, listeYolu }: SekmeProps) {
  const veri = useQuery({
    queryKey: ["servis-rapor", "yeniden", filtreSorgusu(filtre).toString()],
    queryFn: () => servisRaporlariApi.yenidenAcilan(filtre),
  });
  const v = veri.data;
  if (veri.isLoading) return <Spin />;
  if (veri.error) return <Alert type="error" showIcon message={(veri.error as Error).message} />;
  if (!v) return <Empty />;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Space wrap>
        <Link to={listeYolu("rapor_yeniden_acilan")}>
          <Tag color="orange">Yeniden açılan iş {v.yeniden_acilan}</Tag>
        </Link>
        <Link to={listeYolu("rapor_ilk_cozulen")}>
          <Tag>İlk kez çözülen {v.ilk_cozulen}</Tag>
        </Link>
        <Tag>Oran {sayi(v.oran, " %")}</Tag>
        <Link to={listeYolu("rapor_yeniden_acilan_pb")}>
          <Tag>PB (ayrı) {v.yeniden_acilan_pb}</Tag>
        </Link>
      </Space>
      <Table
        size="small"
        rowKey={(r) => `${r.id}-${r.yeniden_acilis}`}
        dataSource={v.olaylar}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: 760 }}
        footer={() =>
          v.olay_sayisi > v.olaylar.length ? `İlk ${v.olaylar.length} / ${v.olay_sayisi} olay (tamamı Excel'de)` : null
        }
        columns={[
          { title: "İş", dataIndex: "so_no", render: (no, r) => <Link to={`/servis-isleri/${r.id}`}>{no}</Link> },
          { title: "Kategori", dataIndex: "kategori", render: (k, r) => (r.pb ? <Tag>PB</Tag> : k) },
          { title: "İlk çözüm", dataIndex: "ilk_cozum", render: zaman },
          { title: "Yeniden açılış", dataIndex: "yeniden_acilis", render: zaman },
          { title: "Gün", dataIndex: "gun_farki", align: "right", render: (x) => sayi(x) },
          { title: "Gerekçe", dataIndex: "gerekce" },
        ]}
      />
    </Space>
  );
}

function TrendSekmesi({ filtre }: SekmeProps) {
  const veri = useQuery({
    queryKey: ["servis-rapor", "trend", filtreSorgusu(filtre).toString()],
    queryFn: () => servisRaporlariApi.trend(filtre),
  });
  const satirlar = veri.data?.satirlar ?? [];
  const enCok = Math.max(1, ...satirlar.map((s) => Math.max(s.gelen, s.cozulen)));
  const cubuk = (n: number, renk: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: `${(60 * n) / enCok}px`, height: 8, background: renk, borderRadius: 2 }} />
      {n}
    </div>
  );
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {veri.data?.gecmis_degisebilir && (
        <Alert type="info" showIcon message="Geçmiş değerler değişebilir (olay geçmişi olmayan göç işleri)." />
      )}
      <Table<TrendSatiri>
        size="small"
        loading={veri.isLoading}
        rowKey="ay"
        dataSource={satirlar}
        pagination={false}
        scroll={{ x: 640 }}
        columns={[
          { title: "Ay", dataIndex: "ay_adi" },
          { title: "Gelen", dataIndex: "gelen", render: (n: number) => cubuk(n, "#4a6fa5") },
          { title: "Çözülen", dataIndex: "cozulen", render: (n: number) => cubuk(n, "#3f8f5c") },
          { title: "İptal", dataIndex: "iptal", align: "right" },
          { title: "Dönem sonu açık", dataIndex: "donem_sonu_acik", align: "right" },
          { title: "Kişi-saat", dataIndex: "kisi_saat", align: "right", render: (x: number | null) => sayi(x) },
        ]}
      />
    </Space>
  );
}

function KpiListesi({
  filtre,
  kod,
  kapat,
}: {
  filtre: RaporFiltresiDegeri;
  kod: string;
  kapat: () => void;
}) {
  const [sayfa, setSayfa] = useState(1);
  const qc = useQueryClient();
  const sorgu = filtreSorgusu(filtre).toString();
  const boy = 50;
  const veri = useQuery({
    queryKey: ["servis-rapor", "kpi-liste", kod, sorgu, sayfa],
    queryFn: () => servisRaporlariApi.kpiListe(filtre, kod, boy, (sayfa - 1) * boy),
  });
  // Servis İşleri bağlantısı ve başlık önbellekteki özet/SLA/tekrar yanıtından.
  const bilinen = useMemo(() => {
    for (const anahtar of ["ozet", "sla", "tekrar"]) {
      const v = qc.getQueryData<{ kpiler: (RaporKpi | BasitKpi)[] }>(["servis-rapor", anahtar, sorgu]);
      const k = v?.kpiler.find((x) => x.kod === kod);
      if (k) return k;
    }
    return undefined;
  }, [qc, sorgu, kod]);
  const sutunlar: ColumnsType<KpiIsSatiri> = [
    { title: "İş", dataIndex: "so_no", fixed: "left", render: (no, r) => <Link to={r.yol}>{no}</Link> },
    { title: "Birim", dataIndex: "birim_adi" },
    { title: "Kategori", dataIndex: "kategori_adi" },
    { title: "Durum", dataIndex: "durum_adi" },
    { title: "Öncelik", dataIndex: "oncelik" },
    { title: "Müşteri", dataIndex: "musteri" },
    { title: "Lokasyon", dataIndex: "lokasyon" },
    { title: "Şehir", dataIndex: "sehir" },
    { title: "Konu", dataIndex: "konu" },
    { title: "Açılış", dataIndex: "acilis", render: zaman },
    { title: "Tamamlanma", dataIndex: "tamamlanma", render: zaman },
  ];
  return (
    <Drawer
      open
      onClose={kapat}
      width="min(1100px, 100vw)"
      title={
        <Space wrap>
          <span>{bilinen?.baslik ?? kod}</span>
          <Tag>{veri.data ? veri.data.toplam : "…"} iş</Tag>
          {bilinen?.isler_yolu && <Link to={bilinen.isler_yolu}>Servis İşleri'nde aç (toplu işlem)</Link>}
        </Space>
      }
    >
      {bilinen?.tanim && <Typography.Paragraph type="secondary">{bilinen.tanim}</Typography.Paragraph>}
      {veri.error && <Alert type="error" showIcon message={(veri.error as Error).message} />}
      <Table
        size="small"
        rowKey="id"
        loading={veri.isLoading}
        dataSource={veri.data?.kayitlar ?? []}
        columns={sutunlar}
        scroll={{ x: 1100 }}
        pagination={{
          current: sayfa,
          pageSize: boy,
          total: veri.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
        }}
      />
    </Drawer>
  );
}

export default function ServisRaporlariPage() {
  const { yetkili } = useAuth();
  const [arama, setArama] = useSearchParams();
  const filtre = useMemo(() => varsayilanla(filtreOku(arama)), [arama]);
  const sekme = arama.get("sekme") ?? "ozet";
  const liste = arama.get("liste");

  if (!yetkili("servis.gor", "servis_rapor.gor")) {
    return <Alert type="warning" showIcon message="Servis raporlarını görme yetkiniz yok (servis_rapor.gor)." />;
  }

  const yaz = (f: RaporFiltresiDegeri, ek: Record<string, string> = {}) =>
    setArama(filtreSorgusu(f, ek), { replace: false });
  const listeYolu = (kod: string) => `/servis-raporlari?${filtreSorgusu(filtre, { sekme, liste: kod }).toString()}`;
  const ortak: SekmeProps = { filtre, listeYolu };
  const kisisel = yetkili("servis_rapor.personel");

  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Servis Raporları
          </Typography.Title>
          {yetkili("servis.gor", "servis_rapor.disaaktar") && (
            <Button
              icon={<FileExcelOutlined />}
              onClick={() => window.open(servisRaporlariApi.kitapAdresi(filtre), "_blank")}
            >
              Excel (servis kitabı)
            </Button>
          )}
        </Space>
        <RaporFiltresi deger={filtre} degisti={(f) => yaz(f, { sekme })} tekrarGun={sekme === "tekrar"} />
        <Tabs
          activeKey={sekme}
          onChange={(k) => yaz(filtre, { sekme: k })}
          destroyOnHidden
          items={[
            { key: "ozet", label: "Özet", children: <OzetSekmesi {...ortak} /> },
            { key: "kirilim", label: "Kırılımlar", children: <KirilimSekmesi {...ortak} /> },
            ...(kisisel ? [{ key: "kisi", label: "Kişi-Saat", children: <KisiSaatSekmesi {...ortak} /> }] : []),
            { key: "sla", label: "SLA ve Bekleme", children: <SlaSekmesi {...ortak} /> },
            { key: "tekrar", label: "Tekrar Arıza", children: <TekrarSekmesi {...ortak} /> },
            { key: "yeniden", label: "Yeniden Açılan", children: <YenidenSekmesi {...ortak} /> },
            { key: "trend", label: "12 Ay Trend", children: <TrendSekmesi {...ortak} /> },
          ]}
        />
      </Space>
      {liste && (
        <KpiListesi
          filtre={filtre}
          kod={liste}
          kapat={() => {
            const p = new URLSearchParams(arama);
            p.delete("liste");
            setArama(p);
          }}
        />
      )}
    </Card>
  );
}
