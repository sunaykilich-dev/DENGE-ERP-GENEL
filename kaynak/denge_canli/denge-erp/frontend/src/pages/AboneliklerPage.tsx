import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api, type ApiError } from "../api/client";
import Statistic from "../components/Statistic";
import { useAuth } from "../auth/AuthContext";

interface Fiyat {
  id: number;
  unit_price: number;
  valid_from: string;
  valid_to: string | null;
  change_reason: string | null;
}

interface Olay {
  id: number;
  event_type: string;
  event_date: string;
  mrr_before: number;
  mrr_after: number;
  mrr_delta: number;
  reason: string | null;
}

interface Abonelik {
  id: number;
  subscription_no: string;
  customer_id: number;
  customer_title: string | null;
  title: string | null;
  vehicle_id: number | null;
  device_id: number | null;
  sim_id: number | null;
  product_id: number | null;
  order_id: number | null;
  status: string;
  billing_period: string;
  currency: string;
  vat_rate: number;
  start_date: string;
  end_date: string | null;
  commitment_end_date: string | null;
  renewal_type: string;
  renewal_months: number;
  notice_days: number;
  cancel_reason: string | null;
  notes: string | null;
  version: number;
  guncel_fiyat: number | null;
  aylik_tutar: number | null;
  taahhut_devam: boolean;
  sonraki_durumlar: string[];
  fiyat_gecmisi: Fiyat[];
  olaylar: Olay[];
}

interface TahakkukSatiri {
  subscription_no: string;
  customer_title: string;
  title: string | null;
  billing_period: string;
  birim_fiyat: number;
  aylik_tutar: number;
  aktif_gun: number;
  donem_gun: number;
  kist: boolean;
  tutar: number;
  kdv: number;
  toplam: number;
  currency: string;
}

interface Tahakkuk {
  donem: string;
  satir: number;
  toplam_matrah: number;
  toplam_kdv: number;
  toplam: number;
  satirlar: TahakkukSatiri[];
}

interface MrrHareket {
  donem: string;
  baslangic_mrr: number;
  bitis_mrr: number;
  hareket: Record<string, { adet: number; delta: number }>;
  churn_yuzde: number | null;
}

interface ZamSatiri {
  subscription_id: number;
  subscription_no: string;
  customer_title: string | null;
  billing_period: string;
  eski_fiyat: number;
  yeni_fiyat: number;
  fark: number;
  mrr_farki: number;
  status: string;
}

interface ZamHaric {
  subscription_id: number;
  subscription_no: string;
  customer_title: string | null;
  neden: string;
}

interface ZamOnizleme {
  etkilenen: ZamSatiri[];
  haric: ZamHaric[];
  etkilenen_sayisi: number;
  haric_sayisi: number;
  mrr_delta: number;
}

interface ZamPartisi {
  id: number;
  title: string;
  status: string;
  method: string;
  value: number;
  valid_from: string;
  round_to: number;
  affected_count: number;
  excluded_count: number;
  mrr_delta: number;
  applied_at: string | null;
  reverted_at: string | null;
  notified_at: string | null;
  notified_count: number;
  notes: string | null;
}

interface Yenilenecek {
  subscription_id: number;
  subscription_no: string;
  customer_title: string;
  end_date: string;
  kalan_gun: number;
  renewal_type: string;
  status: string;
}

interface Hesap {
  id: number;
  title: string;
}

interface Urun {
  id: number;
  code: string;
  name: string;
  list_price: number | null;
}

const tl = (v: number | null | undefined, para = "TRY") =>
  v == null
    ? "—"
    : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ${
        para === "TRY" ? "₺" : para
      }`;

/** Churn oranı; dönem başı MRR sıfırsa tanımsızdır. */
const yuzde = (v: number | null) =>
  v == null ? "—" : `%${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}`;

const DURUM_RENGI: Record<string, string> = {
  TASLAK: "default",
  AKTIF: "green",
  ASKIDA: "orange",
  IPTAL: "red",
  SONA_ERDI: "default",
};

const OLAY_RENGI: Record<string, string> = {
  YENI: "green",
  ARTIS: "blue",
  AZALIS: "gold",
  ASKI: "orange",
  GERI_DONUS: "cyan",
  IPTAL: "red",
  SONA_ERDI: "default",
};

const PERIYOTLAR = [
  { value: "AYLIK", label: "Aylık" },
  { value: "UC_AYLIK", label: "3 aylık" },
  { value: "ALTI_AYLIK", label: "6 aylık" },
  { value: "YILLIK", label: "Yıllık" },
];

export default function AboneliklerPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const [durum, setDurum] = useState<string | undefined>();
  const [secili, setSecili] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [zamAcik, setZamAcik] = useState(false);
  const [donem, setDonem] = useState(dayjs().format("YYYY-MM"));
  const [zamOnizleme, setZamOnizleme] = useState<ZamOnizleme | null>(null);
  const [yeniForm] = Form.useForm();
  const [zamForm] = Form.useForm();
  const [topluForm] = Form.useForm();

  const abonelikler = useQuery({
    queryKey: ["abonelikler", durum],
    queryFn: () => api.get<Abonelik[]>(`/api/abonelikler${durum ? `?durum=${durum}` : ""}`),
  });

  const detay = useQuery({
    queryKey: ["abonelik", secili],
    queryFn: () => api.get<Abonelik>(`/api/abonelikler/${secili}`),
    enabled: secili != null,
  });

  const yenilenecekler = useQuery({
    queryKey: ["abonelik-yenilenecek"],
    queryFn: () => api.get<Yenilenecek[]>("/api/abonelikler/yenilenecekler"),
  });

  const tahakkuk = useQuery({
    queryKey: ["abonelik-tahakkuk", donem],
    queryFn: () => api.get<Tahakkuk>(`/api/abonelikler/tahakkuk/${donem}`),
  });

  const mrr = useQuery({
    queryKey: ["abonelik-mrr", donem],
    queryFn: () => api.get<MrrHareket>(`/api/abonelikler/mrr/${donem}`),
  });

  const partiler = useQuery({
    queryKey: ["toplu-zam"],
    queryFn: () => api.get<ZamPartisi[]>("/api/toplu-zam"),
  });

  const musteriler = useQuery({
    queryKey: ["hesaplar-musteri"],
    queryFn: () => api.get<Hesap[]>("/api/hesaplar?rol=MUSTERI&limit=500"),
    enabled: yeniAcik,
  });

  const urunler = useQuery({
    queryKey: ["urunler-abonelik"],
    queryFn: () => api.get<Urun[]>("/api/urunler?limit=500"),
    enabled: yeniAcik,
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["abonelikler"] });
    void qc.invalidateQueries({ queryKey: ["abonelik"] });
    void qc.invalidateQueries({ queryKey: ["abonelik-yenilenecek"] });
    void qc.invalidateQueries({ queryKey: ["abonelik-tahakkuk"] });
    void qc.invalidateQueries({ queryKey: ["abonelik-mrr"] });
    void qc.invalidateQueries({ queryKey: ["toplu-zam"] });
  };

  const hata = (e: ApiError) => message.error(e.message);

  const olustur = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Abonelik>("/api/abonelikler", v),
    onSuccess: (a) => {
      message.success(`${a.subscription_no} açıldı — aktifleştirince MRR'a girer`);
      setYeniAcik(false);
      yeniForm.resetFields();
      setSecili(a.id);
      yenile();
    },
    onError: hata,
  });

  const durumDegistir = useMutation({
    mutationFn: ({
      id,
      ...v
    }: {
      id: number;
      durum: string;
      tarih?: string;
      neden?: string;
    }) => api.post(`/api/abonelikler/${id}/durum`, v),
    onSuccess: () => {
      message.success("Durum güncellendi, MRR olayı yazıldı");
      yenile();
    },
    onError: hata,
  });

  const zam = useMutation({
    mutationFn: ({
      id,
      ...v
    }: {
      id: number;
      unit_price: number;
      valid_from: string;
      neden?: string;
    }) => api.post(`/api/abonelikler/${id}/fiyat`, v),
    onSuccess: () => {
      message.success("Yeni ücret dönemi açıldı");
      setZamAcik(false);
      zamForm.resetFields();
      yenile();
    },
    onError: hata,
  });

  const yenileSozlesme = useMutation({
    mutationFn: ({ id, ay }: { id: number; ay?: number }) =>
      api.post(`/api/abonelikler/${id}/yenile`, { ay }),
    onSuccess: () => {
      message.success("Sözleşme uzatıldı");
      yenile();
    },
    onError: hata,
  });

  const topluOnizle = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      api.post<ZamOnizleme>("/api/toplu-zam/onizle", v),
    onSuccess: setZamOnizleme,
    onError: hata,
  });

  const topluKaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<ZamPartisi>("/api/toplu-zam", v),
    onSuccess: (p) => {
      message.success(`${p.title} taslak olarak kaydedildi — henüz ücret değişmedi`);
      yenile();
    },
    onError: hata,
  });

  const topluUygula = useMutation({
    mutationFn: (id: number) => api.post(`/api/toplu-zam/${id}/uygula`),
    onSuccess: () => {
      message.success("Zam uygulandı");
      setZamOnizleme(null);
      yenile();
    },
    onError: hata,
  });

  const topluGeriAl = useMutation({
    mutationFn: (id: number) => api.post(`/api/toplu-zam/${id}/geri-al`),
    onSuccess: () => {
      message.success("Parti geri alındı, ücretler eski haline döndü");
      yenile();
    },
    onError: hata,
  });

  const topluBildir = useMutation({
    mutationFn: (id: number) =>
      api.post<{ gonderilen: number; atlanan: unknown[] }>(`/api/toplu-zam/${id}/bildir`),
    onSuccess: (r) => {
      message.success(
        `${r.gonderilen} müşteriye bildirildi` +
          (r.atlanan.length ? `, ${r.atlanan.length} hesapta e-posta yok` : ""),
      );
      yenile();
    },
    onError: hata,
  });

  function topluVeri() {
    const v = topluForm.getFieldsValue();
    return {
      title: v.title,
      method: v.method ?? "YUZDE",
      value: v.value,
      valid_from: v.valid_from ? dayjs(v.valid_from).format("YYYY-MM-DD") : undefined,
      round_to: v.round_to ?? 1,
      criteria: {
        customer_ids: v.customer_ids ?? [],
        billing_periods: v.billing_periods ?? [],
      },
      notes: v.notes,
    };
  }

  function uygulaSor(p: ZamPartisi) {
    modal.confirm({
      title: `${p.title} uygulansın mı?`,
      content: (
        <Typography.Text type="secondary">
          {dayjs(p.valid_from).format("DD.MM.YYYY")} tarihinden geçerli olmak üzere yeni ücret
          dönemleri açılacak. Yürürlük tarihi geçmeden geri alınabilir.
        </Typography.Text>
      ),
      okText: "Uygula",
      cancelText: "Vazgeç",
      onOk: () => topluUygula.mutateAsync(p.id),
    });
  }

  const a = detay.data;

  function iptalSor(id: number) {
    let neden = "";
    modal.confirm({
      title: "Aboneliği iptal et",
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            İptal nedeni zorunludur — churn raporu buna dayanır. İptal geri alınamaz.
          </Typography.Text>
          <Input.TextArea
            rows={2}
            placeholder="İptal nedeni (araç satıldı, rakibe geçti, filo küçüldü…)"
            onChange={(e) => (neden = e.target.value)}
          />
        </Space>
      ),
      okText: "İptal et",
      cancelText: "Vazgeç",
      onOk: () => {
        if (neden.trim().length < 3) {
          message.error("İptal nedeni zorunludur");
          return Promise.reject();
        }
        return durumDegistir.mutateAsync({ id, durum: "IPTAL", neden });
      },
    });
  }

  const tahakkukKolonlari = [
    { title: "Abonelik", dataIndex: "subscription_no", width: 140, className: "mono" },
    { title: "Müşteri", dataIndex: "customer_title" },
    {
      title: "Periyot",
      dataIndex: "billing_period",
      width: 100,
      render: (x: string) => PERIYOTLAR.find((p) => p.value === x)?.label ?? x,
    },
    {
      title: "Aylık",
      dataIndex: "aylik_tutar",
      width: 120,
      className: "tutar",
      render: (x: number) => tl(x),
    },
    {
      title: "Gün",
      width: 90,
      className: "mono",
      render: (_: unknown, r: TahakkukSatiri) =>
        r.kist ? (
          <Tooltip title="Kıst hesap: aktif gün / dönem günü">
            <Tag color="gold">
              {r.aktif_gun}/{r.donem_gun}
            </Tag>
          </Tooltip>
        ) : (
          <Typography.Text type="secondary">tam ay</Typography.Text>
        ),
    },
    {
      title: "Matrah",
      dataIndex: "tutar",
      width: 120,
      className: "tutar",
      render: (x: number) => tl(x),
    },
    {
      title: "KDV",
      dataIndex: "kdv",
      width: 110,
      className: "tutar",
      render: (x: number) => tl(x),
    },
    {
      title: "Toplam",
      dataIndex: "toplam",
      width: 130,
      className: "tutar",
      render: (x: number) => <strong>{tl(x)}</strong>,
    },
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Tabs
        defaultActiveKey="liste"
        items={[
          {
            key: "liste",
            label: "Abonelikler",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Card
                  title="Abonelikler"
                  extra={
                    <Space>
                      <Select
                        allowClear
                        placeholder="Durum"
                        style={{ width: 160 }}
                        value={durum}
                        onChange={setDurum}
                        options={Object.keys(DURUM_RENGI).map((d) => ({
                          value: d,
                          label: d.replaceAll("_", " "),
                        }))}
                      />
                      {yetkili("abonelik.yaz") && (
                        <Button type="primary" onClick={() => setYeniAcik(true)}>
                          Yeni abonelik
                        </Button>
                      )}
                    </Space>
                  }
                >
                  <Table
                    rowKey="id"
                    size="small"
                    loading={abonelikler.isLoading}
                    dataSource={abonelikler.data ?? []}
                    pagination={{ pageSize: 20, showSizeChanger: false }}
                    onRow={(r) => ({
                      onClick: () => setSecili(r.id),
                      style: { cursor: "pointer" },
                    })}
                    columns={[
                      {
                        title: "Abonelik no",
                        dataIndex: "subscription_no",
                        width: 140,
                        className: "mono",
                      },
                      { title: "Müşteri", dataIndex: "customer_title" },
                      {
                        title: "Konu",
                        dataIndex: "title",
                        render: (x: string | null) => x ?? "—",
                      },
                      {
                        title: "Periyot",
                        dataIndex: "billing_period",
                        width: 100,
                        render: (x: string) =>
                          PERIYOTLAR.find((p) => p.value === x)?.label ?? x,
                      },
                      {
                        title: "Aylık",
                        dataIndex: "aylik_tutar",
                        width: 120,
                        className: "tutar",
                        render: (x: number | null, r: Abonelik) => tl(x, r.currency),
                      },
                      {
                        title: "Bitiş",
                        dataIndex: "end_date",
                        width: 110,
                        className: "mono",
                        render: (x: string | null) =>
                          x ? dayjs(x).format("DD.MM.YYYY") : "süresiz",
                      },
                      {
                        title: "Durum",
                        width: 150,
                        render: (_: unknown, r: Abonelik) => (
                          <Space size={4}>
                            <Tag color={DURUM_RENGI[r.status]}>
                              {r.status.replaceAll("_", " ")}
                            </Tag>
                            {r.taahhut_devam && (
                              <Tooltip title="Taahhüt sürerken ücret değiştirilemez">
                                <Tag color="purple">taahhüt</Tag>
                              </Tooltip>
                            )}
                          </Space>
                        ),
                      },
                    ]}
                  />
                </Card>

                <Card title="Yenileme yaklaşanlar">
                  <Table
                    rowKey="subscription_id"
                    size="small"
                    loading={yenilenecekler.isLoading}
                    dataSource={yenilenecekler.data ?? []}
                    pagination={false}
                    locale={{ emptyText: <Empty description="Yaklaşan yenileme yok" /> }}
                    onRow={(r) => ({
                      onClick: () => setSecili(r.subscription_id),
                      style: { cursor: "pointer" },
                    })}
                    columns={[
                      {
                        title: "Abonelik",
                        dataIndex: "subscription_no",
                        width: 140,
                        className: "mono",
                      },
                      { title: "Müşteri", dataIndex: "customer_title" },
                      {
                        title: "Bitiş",
                        dataIndex: "end_date",
                        width: 120,
                        className: "mono",
                        render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                      },
                      {
                        title: "Kalan",
                        dataIndex: "kalan_gun",
                        width: 100,
                        className: "mono",
                        render: (x: number) => (
                          <Tag color={x < 0 ? "red" : x <= 7 ? "orange" : "gold"}>
                            {x < 0 ? `${-x} gün geçti` : `${x} gün`}
                          </Tag>
                        ),
                      },
                      { title: "Yenileme", dataIndex: "renewal_type", width: 110 },
                    ]}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: "tahakkuk",
            label: "Aylık tahakkuk",
            children: (
              <Card
                title={`Tahakkuk · ${donem}`}
                extra={
                  <Space>
                    <DatePicker
                      picker="month"
                      value={dayjs(donem, "YYYY-MM")}
                      format="MMMM YYYY"
                      allowClear={false}
                      onChange={(d) => d && setDonem(d.format("YYYY-MM"))}
                    />
                    {yetkili("rapor.disaaktar") && (
                      <Button
                        onClick={() =>
                          window.open(`/api/abonelikler/tahakkuk/${donem}/xlsx`, "_blank")
                        }
                      >
                        Excel
                      </Button>
                    )}
                  </Space>
                }
              >
                <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                  <Space size={40} wrap>
                    <Statistic title="Satır" value={tahakkuk.data?.satir ?? 0} />
                    <Statistic
                      title="Matrah"
                      value={Number(tahakkuk.data?.toplam_matrah ?? 0)}
                      formatter={(v) => tl(Number(v))}
                    />
                    <Statistic
                      title="KDV"
                      value={Number(tahakkuk.data?.toplam_kdv ?? 0)}
                      formatter={(v) => tl(Number(v))}
                    />
                    <Statistic
                      title="Genel toplam"
                      value={Number(tahakkuk.data?.toplam ?? 0)}
                      formatter={(v) => tl(Number(v))}
                    />
                  </Space>
                  <Alert
                    type="info"
                    title="Tahakkuk hesaplanır, saklanmaz"
                    description="Ücret geçmişi ve durum olayları tarihli tutulduğu için aynı dönem her zaman aynı sonucu verir. Muhasebe kaydı Logo'da durur."
                  />
                  <Table
                    rowKey="subscription_no"
                    size="small"
                    loading={tahakkuk.isLoading}
                    dataSource={tahakkuk.data?.satirlar ?? []}
                    pagination={{ pageSize: 25, showSizeChanger: false }}
                    columns={tahakkukKolonlari}
                  />
                </Space>
              </Card>
            ),
          },
          {
            key: "mrr",
            label: "MRR ve churn",
            children: (
              <Card
                title={`MRR hareketi · ${donem}`}
                extra={
                  <DatePicker
                    picker="month"
                    value={dayjs(donem, "YYYY-MM")}
                    format="MMMM YYYY"
                    allowClear={false}
                    onChange={(d) => d && setDonem(d.format("YYYY-MM"))}
                  />
                }
              >
                <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                  <Space size={40} wrap>
                    <Statistic
                      title="Dönem başı MRR"
                      value={Number(mrr.data?.baslangic_mrr ?? 0)}
                      formatter={(v) => tl(Number(v))}
                    />
                    <Statistic
                      title="Dönem sonu MRR"
                      value={Number(mrr.data?.bitis_mrr ?? 0)}
                      formatter={(v) => tl(Number(v))}
                    />
                    <Statistic
                      title="Churn"
                      value={mrr.data?.churn_yuzde ?? 0}
                      formatter={() => yuzde(mrr.data?.churn_yuzde ?? null)}
                      valueStyle={
                        Number(mrr.data?.churn_yuzde ?? 0) > 0 ? { color: "#b42318" } : undefined
                      }
                    />
                  </Space>
                  <Table
                    rowKey="tip"
                    size="small"
                    loading={mrr.isLoading}
                    pagination={false}
                    locale={{ emptyText: <Empty description="Bu dönemde hareket yok" /> }}
                    dataSource={Object.entries(mrr.data?.hareket ?? {}).map(([tip, v]) => ({
                      tip,
                      ...v,
                    }))}
                    columns={[
                      {
                        title: "Olay",
                        dataIndex: "tip",
                        render: (x: string) => (
                          <Tag color={OLAY_RENGI[x]}>{x.replaceAll("_", " ")}</Tag>
                        ),
                      },
                      { title: "Adet", dataIndex: "adet", width: 100, className: "mono" },
                      {
                        title: "MRR etkisi",
                        dataIndex: "delta",
                        width: 150,
                        className: "tutar",
                        render: (x: number) => (
                          <strong style={{ color: Number(x) < 0 ? "#b42318" : undefined }}>
                            {Number(x) > 0 ? "+" : ""}
                            {tl(x)}
                          </strong>
                        ),
                      },
                    ]}
                  />
                </Space>
              </Card>
            ),
          },
          {
            key: "toplu-zam",
            label: "Toplu zam",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Card title="Yeni toplu fiyat güncelleme">
                  <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                    <Alert
                      type="info"
                      title="Önizle → onayla → bildir"
                      description="Önizleme hiçbir şey yazmaz. Taahhütlü sözleşmeler otomatik hariç tutulur; hariç kalan her sözleşmenin nedeni listelenir."
                    />
                    <Form
                      form={topluForm}
                      layout="inline"
                      initialValues={{ method: "YUZDE", round_to: 1 }}
                      onFinish={() => topluOnizle.mutate(topluVeri())}
                    >
                      <Form.Item
                        name="title"
                        label="Başlık"
                        rules={[{ required: true, min: 3, message: "En az 3 karakter" }]}
                      >
                        <Input placeholder="2027 yıllık zam" style={{ width: 220 }} />
                      </Form.Item>
                      <Form.Item name="method" label="Yöntem">
                        <Select
                          style={{ width: 130 }}
                          options={[
                            { value: "YUZDE", label: "Yüzde" },
                            { value: "TUTAR", label: "Tutar ekle" },
                            { value: "SABIT", label: "Sabit fiyat" },
                          ]}
                        />
                      </Form.Item>
                      <Form.Item
                        name="value"
                        label="Değer"
                        rules={[{ required: true, message: "Değer girin" }]}
                      >
                        <InputNumber style={{ width: 120 }} />
                      </Form.Item>
                      <Form.Item
                        name="valid_from"
                        label="Yürürlük"
                        rules={[{ required: true, message: "Tarih seçin" }]}
                      >
                        <DatePicker format="DD.MM.YYYY" />
                      </Form.Item>
                      <Form.Item name="round_to" label="Yuvarlama">
                        <Select
                          style={{ width: 130 }}
                          options={[
                            { value: 1, label: "Tam TL" },
                            { value: 0.01, label: "Kuruş" },
                            { value: 10, label: "10 TL" },
                          ]}
                        />
                      </Form.Item>
                      <Form.Item name="billing_periods" label="Periyot">
                        <Select
                          mode="multiple"
                          allowClear
                          placeholder="Hepsi"
                          style={{ minWidth: 200 }}
                          options={PERIYOTLAR}
                        />
                      </Form.Item>
                      <Form.Item>
                        <Space>
                          <Button
                            type="primary"
                            htmlType="submit"
                            loading={topluOnizle.isPending}
                          >
                            Önizle
                          </Button>
                          <Button
                            disabled={!zamOnizleme || zamOnizleme.etkilenen_sayisi === 0}
                            loading={topluKaydet.isPending}
                            onClick={() =>
                              topluForm
                                .validateFields()
                                .then(() => topluKaydet.mutate(topluVeri()))
                            }
                          >
                            Parti olarak kaydet
                          </Button>
                        </Space>
                      </Form.Item>
                    </Form>
                  </Space>
                </Card>

                {zamOnizleme && (
                  <Card
                    title={`Önizleme · ${zamOnizleme.etkilenen_sayisi} sözleşme etkileniyor`}
                    extra={
                      <Typography.Text>
                        MRR etkisi:{" "}
                        <strong
                          style={{
                            color: Number(zamOnizleme.mrr_delta) < 0 ? "#b42318" : "#1f6b4d",
                          }}
                        >
                          {Number(zamOnizleme.mrr_delta) > 0 ? "+" : ""}
                          {tl(zamOnizleme.mrr_delta)}
                        </strong>
                      </Typography.Text>
                    }
                  >
                    <Table
                      rowKey="subscription_id"
                      size="small"
                      dataSource={zamOnizleme.etkilenen}
                      pagination={{ pageSize: 15, showSizeChanger: false }}
                      locale={{ emptyText: <Empty description="Kriterlere uyan sözleşme yok" /> }}
                      columns={[
                        {
                          title: "Abonelik",
                          dataIndex: "subscription_no",
                          width: 140,
                          className: "mono",
                        },
                        { title: "Müşteri", dataIndex: "customer_title" },
                        {
                          title: "Eski",
                          dataIndex: "eski_fiyat",
                          width: 120,
                          className: "tutar",
                          render: (x: number) => tl(x),
                        },
                        {
                          title: "Yeni",
                          dataIndex: "yeni_fiyat",
                          width: 120,
                          className: "tutar",
                          render: (x: number) => <strong>{tl(x)}</strong>,
                        },
                        {
                          title: "Fark",
                          dataIndex: "fark",
                          width: 120,
                          className: "tutar",
                          render: (x: number) => (
                            <span style={{ color: Number(x) < 0 ? "#b42318" : "#1f6b4d" }}>
                              {Number(x) > 0 ? "+" : ""}
                              {tl(x)}
                            </span>
                          ),
                        },
                      ]}
                    />
                    {zamOnizleme.haric_sayisi > 0 && (
                      <>
                        <Typography.Title level={5} style={{ marginTop: 16 }}>
                          Hariç tutulanlar ({zamOnizleme.haric_sayisi})
                        </Typography.Title>
                        <Table
                          rowKey="subscription_id"
                          size="small"
                          dataSource={zamOnizleme.haric}
                          pagination={{ pageSize: 10, showSizeChanger: false }}
                          columns={[
                            {
                              title: "Abonelik",
                              dataIndex: "subscription_no",
                              width: 140,
                              className: "mono",
                            },
                            { title: "Müşteri", dataIndex: "customer_title" },
                            { title: "Neden", dataIndex: "neden" },
                          ]}
                        />
                      </>
                    )}
                  </Card>
                )}

                <Card title="Zam partileri">
                  <Table
                    rowKey="id"
                    size="small"
                    loading={partiler.isLoading}
                    dataSource={partiler.data ?? []}
                    pagination={false}
                    locale={{ emptyText: <Empty description="Henüz zam partisi yok" /> }}
                    columns={[
                      { title: "Başlık", dataIndex: "title" },
                      {
                        title: "Yöntem",
                        width: 150,
                        render: (_: unknown, p: ZamPartisi) =>
                          p.method === "YUZDE"
                            ? `%${Number(p.value).toLocaleString("tr-TR")}`
                            : p.method === "TUTAR"
                              ? `+${tl(p.value)}`
                              : tl(p.value),
                      },
                      {
                        title: "Yürürlük",
                        dataIndex: "valid_from",
                        width: 120,
                        className: "mono",
                        render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                      },
                      {
                        title: "Etkilenen",
                        width: 110,
                        className: "mono",
                        render: (_: unknown, p: ZamPartisi) =>
                          p.status === "TASLAK" ? "—" : `${p.affected_count} / ${p.excluded_count} hariç`,
                      },
                      {
                        title: "MRR",
                        dataIndex: "mrr_delta",
                        width: 130,
                        className: "tutar",
                        render: (x: number, p: ZamPartisi) =>
                          p.status === "TASLAK" ? "—" : tl(x),
                      },
                      {
                        title: "Durum",
                        dataIndex: "status",
                        width: 130,
                        render: (x: string) => (
                          <Tag
                            color={
                              x === "UYGULANDI" ? "green" : x === "GERI_ALINDI" ? "red" : "default"
                            }
                          >
                            {x.replaceAll("_", " ")}
                          </Tag>
                        ),
                      },
                      {
                        title: "Bildirim",
                        width: 110,
                        render: (_: unknown, p: ZamPartisi) =>
                          p.notified_at ? (
                            <Tag color="blue">{p.notified_count} kişi</Tag>
                          ) : (
                            <Typography.Text type="secondary">—</Typography.Text>
                          ),
                      },
                      {
                        title: "",
                        width: 240,
                        render: (_: unknown, p: ZamPartisi) =>
                          yetkili("abonelik.yaz") && (
                            <Space size={4}>
                              {p.status === "TASLAK" && (
                                <Button size="small" type="primary" onClick={() => uygulaSor(p)}>
                                  Uygula
                                </Button>
                              )}
                              {p.status === "UYGULANDI" && (
                                <>
                                  <Button
                                    size="small"
                                    onClick={() => topluBildir.mutate(p.id)}
                                    loading={topluBildir.isPending}
                                  >
                                    Bildir
                                  </Button>
                                  <Button
                                    size="small"
                                    danger
                                    onClick={() => topluGeriAl.mutate(p.id)}
                                  >
                                    Geri al
                                  </Button>
                                </>
                              )}
                            </Space>
                          ),
                      },
                    ]}
                  />
                </Card>
              </Space>
            ),
          },
        ]}
      />

      <Drawer
        title={a ? `${a.subscription_no} · ${a.customer_title ?? ""}` : "Abonelik"}
        open={secili != null}
        size={820}
        onClose={() => setSecili(null)}
        loading={detay.isLoading}
        extra={
          a &&
          yetkili("abonelik.yaz") && (
            <Space>
              {a.sonraki_durumlar.includes("AKTIF") && (
                <Button
                  type="primary"
                  onClick={() => durumDegistir.mutate({ id: a.id, durum: "AKTIF" })}
                >
                  {a.status === "TASLAK" ? "Aktifleştir" : "Geri aç"}
                </Button>
              )}
              {a.sonraki_durumlar.includes("ASKIDA") && (
                <Button onClick={() => durumDegistir.mutate({ id: a.id, durum: "ASKIDA" })}>
                  Askıya al
                </Button>
              )}
              {a.status === "AKTIF" && (
                <Button onClick={() => setZamAcik(true)}>Ücret değiştir</Button>
              )}
              {["AKTIF", "ASKIDA"].includes(a.status) && a.renewal_type !== "YOK" && (
                <Button onClick={() => yenileSozlesme.mutate({ id: a.id })}>Yenile</Button>
              )}
              {a.sonraki_durumlar.includes("IPTAL") && (
                <Button danger onClick={() => iptalSor(a.id)}>
                  İptal
                </Button>
              )}
            </Space>
          )
        }
      >
        {a && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Durum">
                <Tag color={DURUM_RENGI[a.status]}>{a.status.replaceAll("_", " ")}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Periyot">
                {PERIYOTLAR.find((p) => p.value === a.billing_period)?.label ??
                  a.billing_period}
              </Descriptions.Item>
              <Descriptions.Item label="Güncel ücret" className="tutar">
                {tl(a.guncel_fiyat, a.currency)}
              </Descriptions.Item>
              <Descriptions.Item label="Aylık karşılık (MRR)" className="tutar">
                <strong>{tl(a.aylik_tutar, a.currency)}</strong>
              </Descriptions.Item>
              <Descriptions.Item label="Başlangıç">
                {dayjs(a.start_date).format("DD.MM.YYYY")}
              </Descriptions.Item>
              <Descriptions.Item label="Bitiş">
                {a.end_date ? dayjs(a.end_date).format("DD.MM.YYYY") : "süresiz"}
              </Descriptions.Item>
              <Descriptions.Item label="Taahhüt bitişi">
                {a.commitment_end_date
                  ? dayjs(a.commitment_end_date).format("DD.MM.YYYY")
                  : "yok"}
              </Descriptions.Item>
              <Descriptions.Item label="Yenileme">
                {a.renewal_type} · {a.renewal_months} ay
              </Descriptions.Item>
              {a.cancel_reason && (
                <Descriptions.Item label="İptal nedeni" span={2}>
                  {a.cancel_reason}
                </Descriptions.Item>
              )}
            </Descriptions>

            {a.taahhut_devam && (
              <Alert
                type="warning"
                title="Taahhüt sürüyor"
                description={`${dayjs(a.commitment_end_date).format(
                  "DD.MM.YYYY",
                )} tarihine kadar ücret değiştirilemez; toplu zam da bu sözleşmeyi atlar.`}
              />
            )}

            <Card size="small" title="Ücret geçmişi">
              <Table
                rowKey="id"
                size="small"
                dataSource={a.fiyat_gecmisi}
                pagination={false}
                columns={[
                  {
                    title: "Tutar",
                    dataIndex: "unit_price",
                    width: 130,
                    className: "tutar",
                    render: (x: number) => tl(x, a.currency),
                  },
                  {
                    title: "Başlangıç",
                    dataIndex: "valid_from",
                    width: 120,
                    className: "mono",
                    render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                  },
                  {
                    title: "Bitiş",
                    dataIndex: "valid_to",
                    width: 120,
                    className: "mono",
                    render: (x: string | null) =>
                      x ? dayjs(x).format("DD.MM.YYYY") : <Tag color="green">yürürlükte</Tag>,
                  },
                  {
                    title: "Neden",
                    dataIndex: "change_reason",
                    render: (x: string | null) => x ?? "—",
                  },
                ]}
              />
            </Card>

            <Card size="small" title="MRR olayları">
              <Table
                rowKey="id"
                size="small"
                dataSource={a.olaylar}
                pagination={false}
                locale={{ emptyText: <Empty description="Henüz MRR olayı yok" /> }}
                columns={[
                  {
                    title: "Tarih",
                    dataIndex: "event_date",
                    width: 110,
                    className: "mono",
                    render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                  },
                  {
                    title: "Olay",
                    dataIndex: "event_type",
                    width: 120,
                    render: (x: string) => (
                      <Tag color={OLAY_RENGI[x]}>{x.replaceAll("_", " ")}</Tag>
                    ),
                  },
                  {
                    title: "Öncesi",
                    dataIndex: "mrr_before",
                    width: 110,
                    className: "tutar",
                    render: (x: number) => tl(x, a.currency),
                  },
                  {
                    title: "Sonrası",
                    dataIndex: "mrr_after",
                    width: 110,
                    className: "tutar",
                    render: (x: number) => tl(x, a.currency),
                  },
                  {
                    title: "Etki",
                    dataIndex: "mrr_delta",
                    width: 110,
                    className: "tutar",
                    render: (x: number) => (
                      <strong style={{ color: Number(x) < 0 ? "#b42318" : undefined }}>
                        {Number(x) > 0 ? "+" : ""}
                        {tl(x, a.currency)}
                      </strong>
                    ),
                  },
                  {
                    title: "Neden",
                    dataIndex: "reason",
                    render: (x: string | null) => x ?? "—",
                  },
                ]}
              />
            </Card>
          </Space>
        )}
      </Drawer>

      <Drawer
        title="Ücret değiştir"
        open={zamAcik}
        size={480}
        onClose={() => setZamAcik(false)}
        extra={
          <Button type="primary" onClick={() => zamForm.submit()} loading={zam.isPending}>
            Kaydet
          </Button>
        }
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Yeni ücret bir DÖNEM açar; eski ücret geçmişte kalır ve önceki ayların tahakkuku
            değişmez. Geçmişe dönük tarih kabul edilmez.
          </Typography.Text>
          <Form
            form={zamForm}
            layout="vertical"
            style={{ width: "100%" }}
            onFinish={(v) =>
              a &&
              zam.mutate({
                id: a.id,
                unit_price: v.unit_price,
                valid_from: dayjs(v.valid_from).format("YYYY-MM-DD"),
                neden: v.neden,
              })
            }
          >
            <Form.Item
              name="unit_price"
              label="Yeni ücret"
              rules={[{ required: true, message: "Ücret girin" }]}
            >
              <InputNumber min={0} style={{ width: "100%" }} addonAfter="₺" />
            </Form.Item>
            <Form.Item
              name="valid_from"
              label="Yürürlük tarihi"
              rules={[{ required: true, message: "Tarih seçin" }]}
            >
              <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="neden" label="Neden">
              <Input placeholder="Yıllık zam, sözleşme yenileme…" />
            </Form.Item>
          </Form>
        </Space>
      </Drawer>

      <Drawer
        title="Yeni abonelik"
        open={yeniAcik}
        size={640}
        onClose={() => setYeniAcik(false)}
        extra={
          <Button type="primary" onClick={() => yeniForm.submit()} loading={olustur.isPending}>
            Oluştur
          </Button>
        }
      >
        <Form
          form={yeniForm}
          layout="vertical"
          initialValues={{ billing_period: "AYLIK", renewal_type: "OTOMATIK", renewal_months: 12 }}
          onFinish={(v) =>
            olustur.mutate({
              ...v,
              start_date: dayjs(v.start_date).format("YYYY-MM-DD"),
              end_date: v.end_date ? dayjs(v.end_date).format("YYYY-MM-DD") : undefined,
              commitment_end_date: v.commitment_end_date
                ? dayjs(v.commitment_end_date).format("YYYY-MM-DD")
                : undefined,
            })
          }
        >
          <Form.Item
            name="customer_id"
            label="Müşteri"
            rules={[{ required: true, message: "Müşteri seçin" }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              loading={musteriler.isLoading}
              options={(musteriler.data ?? []).map((h) => ({ value: h.id, label: h.title }))}
            />
          </Form.Item>
          <Form.Item name="title" label="Konu">
            <Input placeholder="Platform aboneliği, kamera görüntü saklama…" />
          </Form.Item>
          <Form.Item name="product_id" label="Ürün">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={(urunler.data ?? []).map((u) => ({
                value: u.id,
                label: `${u.code} · ${u.name}`,
              }))}
            />
          </Form.Item>
          <Space>
            <Form.Item name="billing_period" label="Fatura periyodu">
              <Select style={{ width: 150 }} options={PERIYOTLAR} />
            </Form.Item>
            <Form.Item
              name="unit_price"
              label="Dönem ücreti"
              rules={[{ required: true, message: "Ücret girin" }]}
            >
              <InputNumber min={0} style={{ width: 160 }} addonAfter="₺" />
            </Form.Item>
          </Space>
          <Space>
            <Form.Item
              name="start_date"
              label="Başlangıç"
              rules={[{ required: true, message: "Tarih seçin" }]}
            >
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item name="end_date" label="Bitiş">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item name="commitment_end_date" label="Taahhüt bitişi">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
          </Space>
          <Space>
            <Form.Item name="renewal_type" label="Yenileme">
              <Select
                style={{ width: 150 }}
                options={[
                  { value: "OTOMATIK", label: "Otomatik" },
                  { value: "MANUEL", label: "Manuel" },
                  { value: "YOK", label: "Yenilenmez" },
                ]}
              />
            </Form.Item>
            <Form.Item name="renewal_months" label="Yenileme süresi (ay)">
              <InputNumber min={1} max={60} style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Drawer>
    </Space>
  );
}
