import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type ApiError } from "../api/client";
import { DEPO_KAYNAKLARI, DIS_HEDEFLER, irsaliyeApi } from "../api/irsaliye";
import IrsaliyeListesi from "../components/IrsaliyeListesi";
import { KameraDugmesi } from "../components/barkod/KameraOkuyucu";
import Statistic from "../components/Statistic";
import { useAuth } from "../auth/AuthContext";

interface StokSatiri {
  product_id: number;
  kod: string;
  ad: string;
  marka: string | null;
  model: string | null;
  tip: string;
  serili: boolean;
  elde: number;
  ayrilmis: number;
  yolda: number;
  sahada: number;
  serviste: number;
  konumlar: Record<string, number>;
}

interface Hareket {
  id: number;
  product_id: number;
  urun_kodu: string;
  urun_adi: string;
  qty: number;
  reason: string;
  document_no: string | null;
  notes: string | null;
  created_at: string;
}

interface Transfer {
  id: number;
  transfer_no: string;
  type: string;
  status: string;
  from_location_type: string;
  to_location_type: string;
  to_account_title: string | null;
  new_ownership: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  kalemler: { device_id: number; kimlik: string | null }[];
  document_no: string | null;
  irsaliye_id: number | null;
  irsaliye_no: string | null;
}

interface BayiStok {
  account_id: number | null;
  account_title: string | null;
  ownership: string;
  adet: number;
  en_eski: string;
}

interface Yaslanan {
  device_id: number;
  kimlik: string;
  account_title: string | null;
  ownership: string;
  bekleme_gunu: number;
}

interface Urun {
  id: number;
  code: string;
  name: string;
  identity_kind: string;
}

const KONUMLAR = [
  "MERKEZ_DEPO",
  "BOLGE_DEPO",
  "TEKNISYEN",
  "MONTAJ_NOKTASI",
  "BAYI",
  "MUSTERI",
  "YOLDA",
  "SERVIS",
  "HURDA",
];
const SAHIPLIK = ["DENGE", "BAYI_SATILDI", "MUSTERI_SATILDI", "MUSTERI_KIRALIK"];

const TIP_ADI: Record<string, string> = {
  CIHAZ_SERILI: "Cihaz",
  AKSESUAR: "Aksesuar",
  SIM_PAKETI: "SIM paketi",
  ABONELIK_PLANI: "Abonelik planı",
  HIZMET: "Hizmet",
};

const NEDEN_ADI: Record<string, string> = {
  GIRIS: "Giriş",
  CIKIS: "Çıkış",
  SAYIM: "Sayım",
  TRANSFER: "Transfer",
};

export default function StokPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();

  const [acik, setAcik] = useState(false);
  const [hareketAcik, setHareketAcik] = useState(false);
  const [tipFiltre, setTipFiltre] = useState<string>("HEPSI");
  const [arama, setArama] = useState("");
  const [form] = Form.useForm();
  const [hareketForm] = Form.useForm();

  const ozet = useQuery({
    queryKey: ["stok-ozet"],
    queryFn: () => api.get<StokSatiri[]>("/api/stok/ozet"),
  });
  const hareketler = useQuery({
    queryKey: ["stok-hareketler"],
    queryFn: () => api.get<Hareket[]>("/api/stok/hareketler"),
  });
  const urunler = useQuery({
    queryKey: ["urunler", "serisiz"],
    queryFn: () => api.get<Urun[]>("/api/urunler?limit=500"),
  });
  const transferler = useQuery({
    queryKey: ["transferler"],
    queryFn: () => api.get<Transfer[]>("/api/stok/transferler"),
  });
  // S4.3: depodan şirket dışına transfer irsaliye üretir; alıcı hesap zorunlu.
  const formKaynak = Form.useWatch("from_location_type", form) as string | undefined;
  const formHedef = Form.useWatch("to_location_type", form) as string | undefined;
  const irsaliyeli =
    DEPO_KAYNAKLARI.includes(formKaynak ?? "") && DIS_HEDEFLER.includes(formHedef ?? "");
  const hesaplar = useQuery({
    queryKey: ["hesaplar-transfer"],
    queryFn: () => api.get<{ id: number; title: string }[]>("/api/hesaplar?limit=500"),
    enabled: acik,
  });
  const bayiStok = useQuery({
    queryKey: ["bayi-stok"],
    queryFn: () => api.get<BayiStok[]>("/api/stok/bayi-stogu"),
  });
  const yaslanan = useQuery({
    queryKey: ["yaslanan"],
    queryFn: () => api.get<Yaslanan[]>("/api/stok/yaslanan"),
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["transferler"] });
    void qc.invalidateQueries({ queryKey: ["bayi-stok"] });
    void qc.invalidateQueries({ queryKey: ["stok-ozet"] });
  };

  const olustur = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Transfer>("/api/stok/transferler", v),
    onSuccess: (t) => {
      message.success(
        `${t.transfer_no} oluşturuldu · ${t.kalemler.length} cihaz` +
          (t.irsaliye_no ? ` · irsaliye ${t.irsaliye_no}` : ""),
      );
      void qc.invalidateQueries({ queryKey: ["irsaliyeler"] });
      setAcik(false);
      form.resetFields();
      yenile();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const teslim = useMutation({
    mutationFn: (id: number) => api.post(`/api/stok/transferler/${id}/teslim`, {}),
    onSuccess: () => {
      message.success("Teslim kaydedildi, cihazların konumu güncellendi");
      yenile();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const hareketYaz = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post("/api/stok/hareket", v),
    onSuccess: () => {
      message.success("Stok hareketi kaydedildi");
      setHareketAcik(false);
      hareketForm.resetFields();
      void qc.invalidateQueries({ queryKey: ["stok-ozet"] });
      void qc.invalidateQueries({ queryKey: ["stok-hareketler"] });
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const satirlar = useMemo(() => {
    let v = ozet.data ?? [];
    if (tipFiltre !== "HEPSI") v = v.filter((s) => s.tip === tipFiltre);
    const a = arama.trim().toLocaleLowerCase("tr");
    if (a)
      v = v.filter((s) =>
        [s.kod, s.ad, s.marka, s.model].some((x) => x?.toLocaleLowerCase("tr").includes(a)),
      );
    return v;
  }, [ozet.data, tipFiltre, arama]);

  const toplam = useMemo(
    () =>
      satirlar.reduce(
        (a, s) => ({
          elde: a.elde + s.elde,
          ayrilmis: a.ayrilmis + s.ayrilmis,
          yolda: a.yolda + s.yolda,
          sahada: a.sahada + s.sahada,
        }),
        { elde: 0, ayrilmis: 0, yolda: 0, sahada: 0 },
      ),
    [satirlar],
  );
  const enYuksek = Math.max(1, ...satirlar.map((s) => s.elde));
  const serisizUrunler = (urunler.data ?? []).filter((u) => u.identity_kind === "YOK");

  return (
    <Card
      title="Stok"
      extra={
        <Space>
          {yetkili("cihaz.yaz") && (
            <Button onClick={() => setHareketAcik(true)}>Stok hareketi</Button>
          )}
          {yetkili("cihaz.transfer") && (
            <Button type="primary" onClick={() => setAcik(true)}>
              Yeni transfer
            </Button>
          )}
        </Space>
      }
    >
      <Tabs
        defaultActiveKey="stok"
        items={[
          {
            key: "stok",
            label: "Stok",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Space wrap size={[16, 16]} style={{ width: "100%" }}>
                  <Card size="small" style={{ minWidth: 150 }}>
                    <Statistic
                      title="Elde"
                      value={toplam.elde}
                      valueStyle={{ color: "#1f6b4d" }}
                    />
                  </Card>
                  <Card size="small" style={{ minWidth: 150 }}>
                    <Tooltip title="Siparişe söz verilmiş cihazlar — yeni satışa sayılamaz">
                      <Statistic title="Rezerve" value={toplam.ayrilmis} />
                    </Tooltip>
                  </Card>
                  <Card size="small" style={{ minWidth: 150 }}>
                    <Tooltip title="Gümrükte ya da yolda — fiziksel olarak depoda değil">
                      <Statistic title="Yolda" value={toplam.yolda} />
                    </Tooltip>
                  </Card>
                  <Card size="small" style={{ minWidth: 150 }}>
                    <Statistic title="Sahada" value={toplam.sahada} />
                  </Card>
                </Space>

                <Space wrap>
                  <Input.Search
                    placeholder="Ürün, marka veya model"
                    allowClear
                    onSearch={setArama}
                    style={{ width: 280 }}
                  />
                  <Segmented
                    value={tipFiltre}
                    onChange={(v) => setTipFiltre(String(v))}
                    options={[
                      { label: "Hepsi", value: "HEPSI" },
                      { label: "Cihaz", value: "CIHAZ_SERILI" },
                      { label: "Aksesuar", value: "AKSESUAR" },
                    ]}
                  />
                </Space>

                <Table
                  rowKey="product_id"
                  size="small"
                  loading={ozet.isLoading}
                  dataSource={satirlar}
                  scroll={{ x: 980 }}
                  pagination={{ pageSize: 25, hideOnSinglePage: true }}
                  locale={{ emptyText: <Empty description="Ürün bulunamadı" /> }}
                  columns={[
                    {
                      title: "Ürün",
                      dataIndex: "ad",
                      width: 260,
                      ellipsis: true,
                      render: (x: string, s: StokSatiri) => (
                        <Link to={`/urunler/${s.product_id}`}>{x}</Link>
                      ),
                    },
                    {
                      title: "Marka / model",
                      width: 180,
                      ellipsis: true,
                      render: (_: unknown, s: StokSatiri) =>
                        s.marka ? (
                          <span>
                            {s.marka} · <span className="mono">{s.model}</span>
                          </span>
                        ) : (
                          <Tooltip title="Marka girilmemiş — ürün kartından ekleyin">
                            <Tag color="orange">markasız</Tag>
                          </Tooltip>
                        ),
                    },
                    {
                      title: "Tip",
                      dataIndex: "tip",
                      width: 110,
                      render: (x: string) => <Tag>{TIP_ADI[x] ?? x}</Tag>,
                    },
                    {
                      title: "Elde",
                      dataIndex: "elde",
                      width: 170,
                      sorter: (a: StokSatiri, b: StokSatiri) => a.elde - b.elde,
                      defaultSortOrder: "descend",
                      render: (x: number) => (
                        <Space orientation="vertical" size={2} style={{ width: "100%" }}>
                          <strong className="mono">{x.toLocaleString("tr-TR")}</strong>
                          <Progress
                            percent={Math.round((x / enYuksek) * 100)}
                            showInfo={false}
                            size="small"
                            strokeColor={x ? "#1f6b4d" : "#d3ccbe"}
                          />
                        </Space>
                      ),
                    },
                    {
                      title: "Rezerve",
                      dataIndex: "ayrilmis",
                      width: 90,
                      className: "mono",
                      render: (x: number) => x || "—",
                    },
                    {
                      title: "Yolda",
                      dataIndex: "yolda",
                      width: 90,
                      className: "mono",
                      render: (x: number) => x || "—",
                    },
                    {
                      title: "Sahada",
                      dataIndex: "sahada",
                      width: 90,
                      className: "mono",
                      render: (x: number) => x || "—",
                    },
                    {
                      title: "Serviste",
                      dataIndex: "serviste",
                      width: 90,
                      className: "mono",
                      render: (x: number) => x || "—",
                    },
                    {
                      title: "Nerede",
                      width: 240,
                      render: (_: unknown, s: StokSatiri) => {
                        const k = Object.entries(s.konumlar);
                        if (!k.length)
                          return <Typography.Text type="secondary">—</Typography.Text>;
                        return (
                          <Space size={4} wrap>
                            {k.map(([konum, adet]) => (
                              <Tag key={konum}>
                                {konum.replaceAll("_", " ").toLocaleLowerCase("tr")} {adet}
                              </Tag>
                            ))}
                          </Space>
                        );
                      },
                    },
                  ]}
                />

                <Alert
                  type="info"
                  title="Serili ve serisiz ürün aynı listede"
                  description="Cihazların adedi tek tek kayıtlardan sayılır (her IMEI'nin kendi kaydı var). Aksesuar ve kablo gibi seri numarasıyla takip edilmeyen ürünlerde adet, stok hareketlerinin toplamıdır — 'Stok hareketi' düğmesiyle giriş, çıkış ve sayım düzeltmesi girilir."
                />
              </Space>
            ),
          },
          {
            key: "bayi",
            label: "Bayi stoğu",
            children: (
              <Tabs
                size="small"
                items={[
                  {
                    key: "dagilim",
                    label: "Dağılım",
                    children: (
                      <Table
                        rowKey={(r) => `${r.account_id}-${r.ownership}`}
                        size="small"
                        loading={bayiStok.isLoading}
                        dataSource={bayiStok.data ?? []}
                        scroll={{ x: 620 }}
                        pagination={{ pageSize: 20, hideOnSinglePage: true }}
                        locale={{ emptyText: <Empty description="Bayide cihaz yok" /> }}
                        columns={[
                          {
                            title: "Bayi / Montaj noktası",
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
                            title: "Sahiplik",
                            dataIndex: "ownership",
                            width: 170,
                            render: (v: string) => <Tag>{v.replaceAll("_", " ")}</Tag>,
                          },
                          { title: "Adet", dataIndex: "adet", width: 80, className: "mono" },
                          {
                            title: "En eski giriş",
                            dataIndex: "en_eski",
                            width: 130,
                            className: "mono",
                            render: (v: string) => dayjs(v).format("DD.MM.YYYY"),
                          },
                        ]}
                      />
                    ),
                  },
                  {
                    key: "yaslanan",
                    label: `Yaşlanan${yaslanan.data?.length ? ` (${yaslanan.data.length})` : ""}`,
                    children: (
                      <>
                        <Alert
                          type="info"
                          showIcon
                          style={{ marginBottom: 16 }}
                          title="Bayide uzun süredir bekleyen cihazlar"
                          description="Eşik gün sayısı Parametreler ekranından değiştirilebilir. Konsinye kapsam dışı olduğu için bu liste satılmış ama hâlâ bayide duran stoğu izler — satış sonrası hareketsizlik de bir sinyaldir."
                        />
                        <Table
                          rowKey="device_id"
                          size="small"
                          loading={yaslanan.isLoading}
                          dataSource={yaslanan.data ?? []}
                          scroll={{ x: 620 }}
                          pagination={{ pageSize: 20, showSizeChanger: false }}
                          columns={[
                            {
                              title: "Cihaz",
                              dataIndex: "kimlik",
                              className: "mono",
                              width: 180,
                              render: (x: string) => <Link to={`/cihazlar/${x}`}>{x}</Link>,
                            },
                            { title: "Bayi", dataIndex: "account_title", ellipsis: true },
                            {
                              title: "Sahiplik",
                              dataIndex: "ownership",
                              width: 160,
                              render: (v: string) => <Tag>{v.replaceAll("_", " ")}</Tag>,
                            },
                            {
                              title: "Bekleme",
                              dataIndex: "bekleme_gunu",
                              width: 110,
                              render: (v: number) => (
                                <Tag color={v > 180 ? "red" : "orange"}>{v} gün</Tag>
                              ),
                            },
                          ]}
                        />
                      </>
                    ),
                  },
                ]}
              />
            ),
          },
          {
            key: "transferler",
            label: "Transfer",
            children: (
              <Tabs
                size="small"
                items={[
                  {
                    key: "belgeler",
                    label: "Transfer belgeleri",
                    children: (
                      <Table
                        rowKey="id"
                        size="small"
                        loading={transferler.isLoading}
                        dataSource={transferler.data ?? []}
                        scroll={{ x: 900 }}
                        pagination={{ pageSize: 15, showSizeChanger: false }}
                        locale={{ emptyText: <Empty description="Transfer kaydı yok" /> }}
                        columns={[
                          {
                            title: "No",
                            dataIndex: "transfer_no",
                            width: 150,
                            className: "mono",
                          },
                          { title: "Tip", dataIndex: "type", width: 130 },
                          {
                            title: "Yön",
                            ellipsis: true,
                            render: (_, t: Transfer) => (
                              <span>
                                {t.from_location_type.replaceAll("_", " ")} →{" "}
                                {t.to_account_title ?? t.to_location_type.replaceAll("_", " ")}
                              </span>
                            ),
                          },
                          {
                            title: "Sahiplik",
                            dataIndex: "new_ownership",
                            width: 150,
                            render: (v: string | null) =>
                              v ? <Tag>{v.replaceAll("_", " ")}</Tag> : "—",
                          },
                          {
                            title: "Cihaz",
                            width: 70,
                            className: "mono",
                            render: (_, t: Transfer) => t.kalemler.length,
                          },
                          {
                            title: "İrsaliye",
                            width: 190,
                            render: (_, t: Transfer) =>
                              t.irsaliye_id ? (
                                <Button
                                  size="small"
                                  type="link"
                                  href={irsaliyeApi.pdfYolu(t.irsaliye_id)}
                                  target="_blank"
                                  className="mono"
                                >
                                  {t.irsaliye_no} · PDF
                                </Button>
                              ) : (
                                <Typography.Text type="secondary" className="mono">
                                  {t.document_no ?? "—"}
                                </Typography.Text>
                              ),
                          },
                          {
                            title: "Durum",
                            width: 190,
                            render: (_, t: Transfer) => (
                              <Space size={4}>
                                <Tag color={t.status === "TESLIM_EDILDI" ? "green" : "gold"}>
                                  {t.status.replaceAll("_", " ")}
                                </Tag>
                                {t.status === "YOLDA" && yetkili("cihaz.transfer") && (
                                  <Button size="small" onClick={() => teslim.mutate(t.id)}>
                                    Teslim et
                                  </Button>
                                )}
                              </Space>
                            ),
                          },
                        ]}
                      />
                    ),
                  },
                  {
                    key: "irsaliyeler",
                    label: "İrsaliyeler",
                    children: <IrsaliyeListesi />,
                  },
                  {
                    key: "hareketler",
                    label: "Adet hareketleri",
                    children: (
                      <Table
                        rowKey="id"
                        size="small"
                        loading={hareketler.isLoading}
                        dataSource={hareketler.data ?? []}
                        scroll={{ x: 760 }}
                        pagination={{ pageSize: 20, hideOnSinglePage: true }}
                        locale={{
                          emptyText: (
                            <Empty description="Serisiz ürün hareketi yok — 'Stok hareketi' ile girilir" />
                          ),
                        }}
                        columns={[
                          {
                            title: "Tarih",
                            dataIndex: "created_at",
                            width: 150,
                            className: "mono",
                            render: (x: string) => dayjs(x).format("DD.MM.YYYY HH:mm"),
                          },
                          {
                            title: "Ürün",
                            dataIndex: "urun_adi",
                            ellipsis: true,
                            render: (x: string, h: Hareket) => (
                              <Link to={`/urunler/${h.product_id}`}>{x}</Link>
                            ),
                          },
                          {
                            title: "Neden",
                            dataIndex: "reason",
                            width: 110,
                            render: (x: string) => <Tag>{NEDEN_ADI[x] ?? x}</Tag>,
                          },
                          {
                            title: "Adet",
                            dataIndex: "qty",
                            width: 100,
                            className: "mono",
                            render: (x: number) => (
                              <strong style={{ color: x < 0 ? "#b42318" : "#1f6b4d" }}>
                                {x > 0 ? `+${x}` : x}
                              </strong>
                            ),
                          },
                          { title: "Belge", dataIndex: "document_no", width: 130 },
                          { title: "Not", dataIndex: "notes", ellipsis: true },
                        ]}
                      />
                    ),
                  },
                ]}
              />
            ),
          },
        ]}
      />

      <Modal
        title="Yeni transfer"
        open={acik}
        onCancel={() => setAcik(false)}
        onOk={() => form.submit()}
        confirmLoading={olustur.isPending}
        okText="Oluştur"
        cancelText="Vazgeç"
        width={620}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            type: "SATIS",
            from_location_type: "MERKEZ_DEPO",
            to_location_type: "BAYI",
          }}
          onFinish={(v) =>
            olustur.mutate({
              ...v,
              kimlikler: String(v.kimlikler ?? "")
                .split(/[\s,;]+/)
                .filter(Boolean),
            })
          }
        >
          <Form.Item name="type" label="Transfer tipi" rules={[{ required: true }]}>
            <Select
              options={["SATIS", "IADE", "IC_TRANSFER", "SERVIS_GONDERIM", "SERVIS_DONUS"].map(
                (t) => ({ value: t, label: t.replaceAll("_", " ") }),
              )}
            />
          </Form.Item>
          <Space style={{ display: "flex" }}>
            <Form.Item name="from_location_type" label="Kaynak" style={{ flex: 1 }}>
              <Select
                options={KONUMLAR.map((k) => ({ value: k, label: k.replaceAll("_", " ") }))}
              />
            </Form.Item>
            <Form.Item name="to_location_type" label="Hedef" style={{ flex: 1 }}>
              <Select
                options={KONUMLAR.map((k) => ({ value: k, label: k.replaceAll("_", " ") }))}
              />
            </Form.Item>
          </Space>
          {irsaliyeli && (
            <Form.Item
              name="to_account_id"
              label="Alıcı hesap"
              rules={[{ required: true, message: "İrsaliye için alıcı seçin" }]}
              extra="Depodan şirket dışına çıkışta numaralı irsaliye otomatik düzenlenir (e-İrsaliye değildir)."
            >
              <Select
                showSearch
                optionFilterProp="label"
                loading={hesaplar.isLoading}
                options={(hesaplar.data ?? []).map((h) => ({ value: h.id, label: h.title }))}
              />
            </Form.Item>
          )}
          <Form.Item
            name="new_ownership"
            label="Yeni sahiplik"
            extra="Boş bırakılırsa mevcut sahiplik korunur — konum değişikliği tek başına mülkiyeti değiştirmez."
          >
            <Select
              allowClear
              options={SAHIPLIK.map((s) => ({ value: s, label: s.replaceAll("_", " ") }))}
            />
          </Form.Item>
          <Form.Item name="document_no" label="Belge no">
            <Input className="mono" />
          </Form.Item>
          <Form.Item
            name="kimlikler"
            label="IMEI / seri no listesi"
            rules={[{ required: true }]}
            extra="El okuyucuyla ya da kamera düğmesiyle okutarak alt alta ekleyin veya Excel'den yapıştırın. Tanınmayan kimlik varsa transfer hiç oluşturulmaz."
          >
            <Input.TextArea
              rows={6}
              className="mono"
              placeholder="861100063834630&#10;861100063834631"
            />
          </Form.Item>
          <Space style={{ marginTop: -12, marginBottom: 12 }}>
            <KameraDugmesi
              onOkundu={(m) => {
                const eski = String(form.getFieldValue("kimlikler") ?? "").replace(/\s+$/, "");
                form.setFieldValue("kimlikler", eski ? `${eski}\n${m}` : m);
              }}
            />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Kamerayla okut (her okuma yeni satıra eklenir)
            </Typography.Text>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Transfer oluşunca cihazlar <strong>YOLDA</strong> sayılır; teslim kaydı girilince
            konumları tek işlemde güncellenir.
          </Typography.Text>
        </Form>
      </Modal>

      <Modal
        title="Stok hareketi"
        open={hareketAcik}
        onCancel={() => setHareketAcik(false)}
        onOk={() => hareketForm.submit()}
        confirmLoading={hareketYaz.isPending}
        okText="Kaydet"
        cancelText="Vazgeç"
        width={520}
      >
        <Alert
          type="info"
          style={{ marginBottom: 16 }}
          title="Yalnız seri numarasız ürünler"
          description="Cihazların adedi kendi kayıtlarından sayılır; ikinci bir sayaç tutmak iki rakamın birbirinden ayrışması demekti. Bu ekran aksesuar, kablo ve montaj malzemesi içindir."
        />
        <Form
          form={hareketForm}
          layout="vertical"
          initialValues={{ reason: "GIRIS", qty: 1 }}
          onFinish={(v) => hareketYaz.mutate(v)}
        >
          <Form.Item name="product_id" label="Ürün" rules={[{ required: true }]}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={
                serisizUrunler.length
                  ? "Seri numarasız ürün seçin"
                  : "Katalogda seri numarasız ürün yok"
              }
              options={serisizUrunler.map((u) => ({
                value: u.id,
                label: `${u.code} — ${u.name}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="reason" label="Neden" rules={[{ required: true }]}>
            <Select
              options={["GIRIS", "CIKIS", "SAYIM", "TRANSFER"].map((r) => ({
                value: r,
                label: NEDEN_ADI[r],
              }))}
            />
          </Form.Item>
          <Form.Item
            name="qty"
            label="Adet"
            rules={[{ required: true }]}
            extra="Çıkış için eksi değer girin (örn. -5)."
          >
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="document_no" label="Belge no">
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={2} maxLength={300} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
