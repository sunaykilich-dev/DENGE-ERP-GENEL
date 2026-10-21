import { DownloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  Progress,
  Row,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import Statistic from "../components/Statistic";
import { useAuth } from "../auth/AuthContext";

const tl = (v: number | string | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

const yuzde = (v: number | string | null | undefined) =>
  v == null ? "—" : `%${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}`;

/** Tutar alanları sunucudan Decimal olarak gelir; JSON'da string'tir. */
interface MontajNoktasi {
  partner_id: number;
  unvan: string;
  dokum_sayisi: number;
  is_sayisi: number;
  brut: string;
  net: string;
  is_basina_maliyet: string | null;
}

interface MusteriGeliri {
  account_id: number;
  unvan: string;
  abonelik_geliri: string;
  siparis_geliri: string;
  toplam_gelir: string;
  cihaz_sayisi: number;
}

interface HareketsizStok {
  device_id: number;
  kimlik: string | null;
  urun_kodu: string;
  status: string;
  bekleme_gun: number | null;
  landed_cost_try: string | null;
}

interface BayiStok {
  account_id: number | null;
  account_title: string | null;
  ownership: string;
  adet: number;
  en_eski: string;
}

interface TeklifDonusumu {
  gun: number;
  toplam_teklif: number;
  durumlar: Record<string, number>;
  kazanilan: number;
  kaybedilen: number;
  donusum_yuzde: number | null;
  kayip_nedenleri: { neden: string; adet: number }[];
}

interface MrrHareketi {
  donem: string;
  baslangic_mrr: string;
  bitis_mrr: string;
  arr: string;
  hareket: Record<string, string>;
  churn_yuzde: string | null;
}

interface OmurBoyu {
  device_id: number;
  kimlik: string | null;
  status: string;
  cihaz_maliyeti: string | null;
  montaj_maliyeti: string | null;
  tek_seferlik_maliyet: string | null;
  aylik_gelir: string;
  aylik_maliyet: string | null;
  aylik_marj: string | null;
  basabas_ay: number | null;
}

/** MRR hareket tiplerinin okunabilir karşılığı ve işareti. */
const HAREKET_ADI: Record<string, string> = {
  YENI: "Yeni satış",
  ARTIS: "Yukarı satış",
  AZALIS: "Aşağı satış",
  IPTAL: "İptal",
  ASKI: "Askıya alma",
  GERI_DONUS: "Geri dönüş",
};

export default function RaporlarPage() {
  const { yetkili } = useAuth();
  const aktarabilir = yetkili("rapor.disaaktar");

  const [donem, setDonem] = useState(dayjs().format("YYYY-MM"));
  const [montajDonem, setMontajDonem] = useState("");
  const [bekleme, setBekleme] = useState(180);
  const [donusumGun, setDonusumGun] = useState(365);
  const [cihazKimlik, setCihazKimlik] = useState("");

  const montaj = useQuery({
    queryKey: ["rapor-montaj", montajDonem],
    queryFn: () =>
      api.get<MontajNoktasi[]>(
        `/api/raporlar/montaj-noktasi${montajDonem ? `?donem=${montajDonem}` : ""}`,
      ),
  });

  const musteri = useQuery({
    queryKey: ["rapor-musteri"],
    queryFn: () => api.get<MusteriGeliri[]>("/api/raporlar/musteri-geliri?limit=200"),
  });

  const hareketsiz = useQuery({
    queryKey: ["rapor-hareketsiz", bekleme],
    queryFn: () => api.get<HareketsizStok[]>(`/api/raporlar/hareketsiz-stok?gun=${bekleme}`),
  });

  const bayi = useQuery({
    queryKey: ["rapor-bayi-stok"],
    queryFn: () => api.get<BayiStok[]>("/api/raporlar/bayi-stogu"),
  });

  const donusum = useQuery({
    queryKey: ["rapor-donusum", donusumGun],
    queryFn: () => api.get<TeklifDonusumu>(`/api/raporlar/teklif-donusumu?gun=${donusumGun}`),
  });

  const mrr = useQuery({
    queryKey: ["rapor-mrr", donem],
    queryFn: () => api.get<MrrHareketi>(`/api/raporlar/mrr/${donem}`),
    enabled: /^\d{4}-\d{2}$/.test(donem),
  });

  // Cihaz ömür boyu raporu id ister; kullanıcı IMEI yazar. Arama cihaz
  // ucundan çözülür — kimseye "önce id'yi bul" dedirtmemek için.
  const cihazArama = useQuery({
    queryKey: ["rapor-cihaz-ara", cihazKimlik],
    queryFn: () =>
      api.get<{ id: number; imei: string | null; serial_no: string | null }>(
        `/api/cihazlar/${encodeURIComponent(cihazKimlik)}`,
      ),
    enabled: cihazKimlik.length >= 4,
    retry: false,
  });

  // Kimlikten id'ye çözüm başarılı olur olmaz rapor çekilir; kullanıcıya
  // ikinci bir "hesapla" düğmesi tıklatmanın bir karşılığı yoktu.
  const cihazId = cihazArama.data?.id ?? null;

  const omur = useQuery({
    queryKey: ["rapor-omur", cihazId],
    queryFn: () => api.get<OmurBoyu>(`/api/raporlar/cihaz-omur-boyu/${cihazId}`),
    enabled: cihazId != null,
  });

  const indir = (yol: string) => window.open(yol, "_blank");

  const ExcelBtn = ({ yol }: { yol: string }) =>
    aktarabilir ? (
      <Button icon={<DownloadOutlined />} onClick={() => indir(yol)}>
        Excel
      </Button>
    ) : null;

  return (
    <Tabs
      defaultActiveKey="montaj"
      items={[
        {
          key: "montaj",
          label: "Montaj noktası",
          children: (
            <Card
              title="Montaj noktası performansı"
              extra={
                <Space>
                  <Input
                    placeholder="Dönem (2026-03)"
                    value={montajDonem}
                    onChange={(e) => setMontajDonem(e.target.value.trim())}
                    allowClear
                    style={{ width: 160 }}
                  />
                  <ExcelBtn
                    yol={`/api/raporlar/montaj-noktasi.xlsx${
                      montajDonem ? `?donem=${montajDonem}` : ""
                    }`}
                  />
                </Space>
              }
            >
              <Table
                rowKey="partner_id"
                size="small"
                loading={montaj.isLoading}
                dataSource={montaj.data ?? []}
                scroll={{ x: 760 }}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                columns={[
                  {
                    title: "Montaj noktası",
                    dataIndex: "unvan",
                    width: 260,
                    ellipsis: true,
                    render: (x: string, r: MontajNoktasi) => (
                      <Link to={`/hesaplar/${r.partner_id}`}>{x}</Link>
                    ),
                  },
                  { title: "Döküm", dataIndex: "dokum_sayisi", width: 90 },
                  { title: "İş", dataIndex: "is_sayisi", width: 90 },
                  {
                    title: "Brüt",
                    dataIndex: "brut",
                    width: 140,
                    className: "tutar",
                    sorter: (a: MontajNoktasi, b: MontajNoktasi) => Number(a.brut) - Number(b.brut),
                    render: tl,
                  },
                  {
                    title: "Net ödenen",
                    dataIndex: "net",
                    width: 140,
                    className: "tutar",
                    render: tl,
                  },
                  {
                    title: "İş başına",
                    dataIndex: "is_basina_maliyet",
                    width: 130,
                    className: "tutar",
                    render: tl,
                  },
                ]}
              />
            </Card>
          ),
        },
        {
          key: "musteri",
          label: "Müşteri geliri",
          children: (
            <Card
              title="Müşteri başına gelir"
              extra={<ExcelBtn yol="/api/raporlar/musteri-geliri.xlsx" />}
            >
              <Table
                rowKey="account_id"
                size="small"
                loading={musteri.isLoading}
                dataSource={musteri.data ?? []}
                scroll={{ x: 760 }}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                columns={[
                  {
                    title: "Müşteri",
                    dataIndex: "unvan",
                    width: 280,
                    ellipsis: true,
                    render: (x: string, r: MusteriGeliri) => (
                      <Link to={`/hesaplar/${r.account_id}`}>{x}</Link>
                    ),
                  },
                  {
                    title: "Abonelik (aylık)",
                    dataIndex: "abonelik_geliri",
                    width: 150,
                    className: "tutar",
                    render: tl,
                  },
                  {
                    title: "Sipariş",
                    dataIndex: "siparis_geliri",
                    width: 150,
                    className: "tutar",
                    render: tl,
                  },
                  {
                    title: "Toplam",
                    dataIndex: "toplam_gelir",
                    width: 150,
                    className: "tutar",
                    sorter: (a: MusteriGeliri, b: MusteriGeliri) =>
                      Number(a.toplam_gelir) - Number(b.toplam_gelir),
                    render: (x: number) => <strong>{tl(x)}</strong>,
                  },
                  { title: "Cihaz", dataIndex: "cihaz_sayisi", width: 90 },
                ]}
              />
            </Card>
          ),
        },
        {
          key: "hareketsiz",
          label: "Hareketsiz stok",
          children: (
            <Space orientation="vertical" size={16} style={{ width: "100%" }}>
              <Alert
                type="info"
                title="Bekleme süresi son konum değişikliğinden sayılır"
                description="Cihaz el değiştirmediği sürece bekliyor sayılır; depo içi raf değişimi hareket değildir."
              />
              <Card
                title="Hareketsiz stok"
                extra={
                  <Space>
                    <InputNumber
                      value={bekleme}
                      onChange={(v) => setBekleme(Number(v) || 180)}
                      min={1}
                      max={3650}
                      addonAfter="gün"
                      style={{ width: 140 }}
                    />
                    <ExcelBtn yol={`/api/raporlar/hareketsiz-stok.xlsx?gun=${bekleme}`} />
                  </Space>
                }
              >
                <Table
                  rowKey="device_id"
                  size="small"
                  loading={hareketsiz.isLoading}
                  dataSource={hareketsiz.data ?? []}
                  scroll={{ x: 720 }}
                  pagination={{ pageSize: 20, hideOnSinglePage: true }}
                  columns={[
                    {
                      title: "Kimlik",
                      dataIndex: "kimlik",
                      width: 180,
                      className: "mono",
                      render: (x: string | null) =>
                        x ? <Link to={`/cihazlar/${x}`}>{x}</Link> : "—",
                    },
                    { title: "Ürün", dataIndex: "urun_kodu", width: 150, ellipsis: true },
                    {
                      title: "Durum",
                      dataIndex: "status",
                      width: 150,
                      render: (x: string) => <Tag>{x.replaceAll("_", " ")}</Tag>,
                    },
                    {
                      title: "Bekleme",
                      dataIndex: "bekleme_gun",
                      width: 120,
                      sorter: (a: HareketsizStok, b: HareketsizStok) =>
                        (a.bekleme_gun ?? 0) - (b.bekleme_gun ?? 0),
                      render: (x: number | null) =>
                        x == null ? (
                          <Typography.Text type="secondary">hareket kaydı yok</Typography.Text>
                        ) : (
                          <Tag color={x > 365 ? "red" : x > 180 ? "orange" : "default"}>
                            {x} gün
                          </Tag>
                        ),
                    },
                    {
                      title: "Maliyet",
                      dataIndex: "landed_cost_try",
                      width: 130,
                      className: "tutar",
                      render: tl,
                    },
                  ]}
                />
              </Card>
            </Space>
          ),
        },
        {
          key: "bayi",
          label: "Bayi stoğu",
          children: (
            <Card title="Bayi ve montaj noktasındaki cihazlar">
              <Table
                rowKey={(r: BayiStok) => `${r.account_id}-${r.ownership}`}
                size="small"
                loading={bayi.isLoading}
                dataSource={bayi.data ?? []}
                scroll={{ x: 620 }}
                pagination={{ pageSize: 20, hideOnSinglePage: true }}
                columns={[
                  {
                    title: "Hesap",
                    dataIndex: "account_title",
                    width: 280,
                    ellipsis: true,
                    render: (x: string | null, r: BayiStok) =>
                      r.account_id ? (
                        <Link to={`/hesaplar/${r.account_id}`}>{x ?? r.account_id}</Link>
                      ) : (
                        "—"
                      ),
                  },
                  {
                    title: "Mülkiyet",
                    dataIndex: "ownership",
                    width: 150,
                    render: (x: string) => <Tag>{x.replaceAll("_", " ")}</Tag>,
                  },
                  {
                    title: "Adet",
                    dataIndex: "adet",
                    width: 90,
                    sorter: (a: BayiStok, b: BayiStok) => a.adet - b.adet,
                  },
                  {
                    title: "En eski giriş",
                    dataIndex: "en_eski",
                    width: 140,
                    className: "mono",
                    render: (x: string) => (x ? dayjs(x).format("DD.MM.YYYY") : "—"),
                  },
                ]}
              />
            </Card>
          ),
        },
        {
          key: "donusum",
          label: "Teklif dönüşümü",
          children: (
            <Space orientation="vertical" size={16} style={{ width: "100%" }}>
              <Card
                title="Teklif dönüşümü"
                extra={
                  <InputNumber
                    value={donusumGun}
                    onChange={(v) => setDonusumGun(Number(v) || 365)}
                    min={7}
                    max={3650}
                    addonAfter="gün"
                    style={{ width: 150 }}
                  />
                }
                loading={donusum.isLoading}
              >
                <Row gutter={[16, 16]}>
                  <Col xs={12} md={6}>
                    <Statistic title="Toplam teklif" value={donusum.data?.toplam_teklif ?? 0} />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="Kazanılan"
                      value={donusum.data?.kazanilan ?? 0}
                      valueStyle={{ color: "#1f6b4d" }}
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="Kaybedilen"
                      value={donusum.data?.kaybedilen ?? 0}
                      valueStyle={{ color: "#b42318" }}
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="Dönüşüm"
                      value={donusum.data?.donusum_yuzde ?? 0}
                      formatter={() => yuzde(donusum.data?.donusum_yuzde)}
                      valueStyle={{ color: "#11417f" }}
                    />
                  </Col>
                </Row>
                <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
                  Oran yalnız karara bağlanmış tekliflerden hesaplanır; cevap bekleyen teklif
                  paydaya girmez.
                </Typography.Paragraph>
              </Card>

              <Row gutter={[16, 16]}>
                <Col xs={24} lg={12}>
                  <Card title="Durum dağılımı" loading={donusum.isLoading}>
                    {Object.entries(donusum.data?.durumlar ?? {}).length === 0 ? (
                      <Empty description="Bu aralıkta teklif yok" />
                    ) : (
                      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                        {Object.entries(donusum.data?.durumlar ?? {}).map(([durum, adet]) => (
                          <div key={durum}>
                            <Space style={{ width: "100%", justifyContent: "space-between" }}>
                              <Typography.Text>{durum.replaceAll("_", " ")}</Typography.Text>
                              <Typography.Text className="mono">
                                {adet.toLocaleString("tr-TR")}
                              </Typography.Text>
                            </Space>
                            <Progress
                              percent={Math.round(
                                (adet / (donusum.data?.toplam_teklif || 1)) * 100,
                              )}
                              showInfo={false}
                              size="small"
                            />
                          </div>
                        ))}
                      </Space>
                    )}
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card title="Kayıp nedenleri" loading={donusum.isLoading}>
                    <Table
                      rowKey="neden"
                      size="small"
                      pagination={false}
                      dataSource={donusum.data?.kayip_nedenleri ?? []}
                      locale={{ emptyText: <Empty description="Kayıp nedeni girilmemiş" /> }}
                      columns={[
                        { title: "Neden", dataIndex: "neden", ellipsis: true },
                        { title: "Adet", dataIndex: "adet", width: 80 },
                      ]}
                    />
                  </Card>
                </Col>
              </Row>
            </Space>
          ),
        },
        {
          key: "mrr",
          label: "MRR / churn",
          children: (
            <Card
              title="Aylık yinelenen gelir"
              extra={
                <Input
                  value={donem}
                  onChange={(e) => setDonem(e.target.value.trim())}
                  placeholder="2026-09"
                  style={{ width: 140 }}
                />
              }
              loading={mrr.isLoading}
            >
              <Row gutter={[16, 16]}>
                <Col xs={12} md={6}>
                  <Statistic
                    title="Dönem başı MRR"
                    value={mrr.data?.baslangic_mrr ?? 0}
                    formatter={(v) => tl(Number(v))}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="Dönem sonu MRR"
                    value={mrr.data?.bitis_mrr ?? 0}
                    formatter={(v) => tl(Number(v))}
                    valueStyle={{ color: "#11417f" }}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="ARR"
                    value={mrr.data?.arr ?? 0}
                    formatter={(v) => tl(Number(v))}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="Churn"
                    value={mrr.data?.churn_yuzde ?? 0}
                    formatter={() => yuzde(mrr.data?.churn_yuzde)}
                    valueStyle={
                      Number(mrr.data?.churn_yuzde ?? 0) > 0 ? { color: "#b42318" } : undefined
                    }
                  />
                </Col>
              </Row>

              <Table
                style={{ marginTop: 16 }}
                rowKey="tip"
                size="small"
                pagination={false}
                dataSource={Object.entries(mrr.data?.hareket ?? {}).map(([tip, tutar]) => ({
                  tip,
                  tutar,
                }))}
                locale={{ emptyText: <Empty description="Bu dönemde MRR hareketi yok" /> }}
                columns={[
                  {
                    title: "Hareket",
                    dataIndex: "tip",
                    render: (x: string) => HAREKET_ADI[x] ?? x.replaceAll("_", " "),
                  },
                  {
                    title: "Tutar",
                    dataIndex: "tutar",
                    width: 160,
                    className: "tutar",
                    render: (x: string) => (
                      <span style={{ color: Number(x) < 0 ? "#b42318" : "#1f6b4d" }}>{tl(x)}</span>
                    ),
                  },
                ]}
              />
            </Card>
          ),
        },
        {
          key: "omur",
          label: "Cihaz ömür boyu",
          children: (
            <Space orientation="vertical" size={16} style={{ width: "100%" }}>
              <Card title="Cihaz ömür boyu gelir ve marj">
                <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                  <Input.Search
                    placeholder="IMEI veya seri no"
                    allowClear
                    enterButton="Getir"
                    loading={cihazArama.isFetching || omur.isFetching}
                    style={{ maxWidth: 360 }}
                    onSearch={(v) => setCihazKimlik(v.trim())}
                  />
                  {cihazArama.isError && cihazKimlik && (
                    <Alert
                      type="warning"
                      title={
                        (cihazArama.error as ApiError)?.status === 404
                          ? "Bu kimlikte cihaz bulunamadı"
                          : ((cihazArama.error as Error)?.message ?? "Cihaz getirilemedi")
                      }
                    />
                  )}
                </Space>
              </Card>

              {omur.data && (
                <Card
                  title={
                    <Space>
                      <span className="mono">{omur.data.kimlik}</span>
                      <Tag>{omur.data.status.replaceAll("_", " ")}</Tag>
                    </Space>
                  }
                  loading={omur.isLoading}
                >
                  <Row gutter={[16, 16]}>
                    <Col xs={12} md={6}>
                      <Statistic
                        title="Cihaz maliyeti"
                        value={omur.data.cihaz_maliyeti ?? 0}
                        formatter={() => tl(omur.data!.cihaz_maliyeti)}
                      />
                    </Col>
                    <Col xs={12} md={6}>
                      <Statistic
                        title="Montaj maliyeti"
                        value={omur.data.montaj_maliyeti ?? 0}
                        formatter={() => tl(omur.data!.montaj_maliyeti)}
                      />
                    </Col>
                    <Col xs={12} md={6}>
                      <Statistic
                        title="Aylık gelir"
                        value={omur.data.aylik_gelir}
                        formatter={(v) => tl(Number(v))}
                        valueStyle={{ color: "#1f6b4d" }}
                      />
                    </Col>
                    <Col xs={12} md={6}>
                      <Statistic
                        title="Aylık marj"
                        value={omur.data.aylik_marj ?? 0}
                        formatter={() => tl(omur.data!.aylik_marj)}
                        valueStyle={
                          Number(omur.data.aylik_marj ?? 0) < 0 ? { color: "#b42318" } : undefined
                        }
                      />
                    </Col>
                  </Row>
                  <Typography.Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
                    {omur.data.aylik_marj == null ? (
                      <Typography.Text type="secondary">
                        Maliyet görme yetkiniz olmadığı için başabaş süresi hesaplanmadı.
                      </Typography.Text>
                    ) : omur.data.basabas_ay == null ? (
                      <Typography.Text type="danger">
                        Aylık marj sıfır veya eksi — bu cihaz tek seferlik maliyetini hiç
                        çıkarmıyor.
                      </Typography.Text>
                    ) : (
                      <>
                        Tek seferlik maliyet <strong>{tl(omur.data.tek_seferlik_maliyet)}</strong>,{" "}
                        <strong>{omur.data.basabas_ay} ayda</strong> başabaşa geliyor.
                      </>
                    )}
                  </Typography.Paragraph>
                </Card>
              )}
            </Space>
          ),
        },
      ]}
    />
  );
}
