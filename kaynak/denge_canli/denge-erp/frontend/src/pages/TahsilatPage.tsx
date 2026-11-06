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
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

interface Tahsilat {
  id: number;
  account_id: number;
  account_title: string | null;
  direction: string;
  amount: number;
  paid_at: string;
  method: string | null;
  reference: string | null;
  subscription_id: number | null;
  order_id: number | null;
  settlement_id: number | null;
  period: string | null;
  notes: string | null;
}

interface Bakiye {
  account_id: number;
  title: string;
  abonelik_tahakkuk: number;
  siparis_tahakkuk: number;
  tahsil_edilen: number;
  musteri_bakiye: number;
  hakedis_tahakkuk: number;
  hakedis_odenen: number;
  ortak_bakiye: number;
  son_tahsilat: string | null;
}

interface Geciken extends Bakiye {
  gecen_gun: number | null;
  esik_gun: number;
  aktif_abonelik: number;
  askiya_alma_onerilen: { id: number; no: string; otomatik: boolean }[];
}

interface Hesap {
  id: number;
  title: string;
}

const tl = (v: number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

const YONTEMLER = [
  "HAVALE",
  "EFT",
  "NAKIT",
  "CEK",
  "SENET",
  "KREDI_KARTI",
  "MAHSUP",
].map((v) => ({ value: v, label: v.replaceAll("_", " ").toLowerCase() }));

export default function TahsilatPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const [yon, setYon] = useState<string | undefined>();
  const [hesapId, setHesapId] = useState<number | undefined>();
  const [yeniAcik, setYeniAcik] = useState(false);
  const [yeniForm] = Form.useForm();

  const tahsilatlar = useQuery({
    queryKey: ["tahsilat", yon, hesapId],
    queryFn: () => {
      const q = new URLSearchParams();
      if (yon) q.set("yon", yon);
      if (hesapId) q.set("hesap_id", String(hesapId));
      return api.get<Tahsilat[]>(`/api/tahsilat?${q}`);
    },
  });

  const gecikenler = useQuery({
    queryKey: ["tahsilat-gecikenler"],
    queryFn: () => api.get<Geciken[]>("/api/tahsilat/gecikenler"),
  });

  const bakiye = useQuery({
    queryKey: ["tahsilat-bakiye", hesapId],
    queryFn: () => api.get<Bakiye>(`/api/tahsilat/bakiye/${hesapId}`),
    enabled: hesapId != null,
  });

  const hesaplar = useQuery({
    queryKey: ["hesaplar-tumu"],
    queryFn: () => api.get<Hesap[]>("/api/hesaplar?limit=500"),
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["tahsilat"] });
    void qc.invalidateQueries({ queryKey: ["tahsilat-gecikenler"] });
    void qc.invalidateQueries({ queryKey: ["tahsilat-bakiye"] });
  };

  const hata = (e: ApiError) => message.error(e.message);

  const olustur = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Tahsilat>("/api/tahsilat", v),
    onSuccess: () => {
      message.success("Tahsilat kaydedildi");
      setYeniAcik(false);
      yeniForm.resetFields();
      yenile();
    },
    onError: hata,
  });

  const sil = useMutation({
    mutationFn: (id: number) => api.delete(`/api/tahsilat/${id}`),
    onSuccess: () => {
      message.success("Tahsilat kaydı silindi, denetim izine yazıldı");
      yenile();
    },
    onError: hata,
  });

  function silSor(kayit: Tahsilat) {
    modal.confirm({
      title: "Tahsilat kaydını sil",
      content: `${kayit.account_title ?? ""} · ${tl(kayit.amount)} · ${dayjs(
        kayit.paid_at,
      ).format("DD.MM.YYYY")}`,
      okText: "Sil",
      okButtonProps: { danger: true },
      cancelText: "Vazgeç",
      onOk: () => sil.mutateAsync(kayit.id),
    });
  }

  const tahsilatKolonlari = [
    {
      title: "Tarih",
      dataIndex: "paid_at",
      width: 110,
      className: "mono",
      render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
    },
    { title: "Hesap", dataIndex: "account_title" },
    {
      title: "Yön",
      dataIndex: "direction",
      width: 90,
      render: (x: string) => (
        <Tag color={x === "GELEN" ? "green" : "blue"}>
          {x === "GELEN" ? "tahsilat" : "ödeme"}
        </Tag>
      ),
    },
    {
      title: "Tutar",
      dataIndex: "amount",
      width: 140,
      className: "tutar",
      render: (x: number) => <strong>{tl(x)}</strong>,
    },
    {
      title: "Yöntem",
      dataIndex: "method",
      width: 120,
      render: (x: string | null) => (x ? x.replaceAll("_", " ").toLowerCase() : "—"),
    },
    {
      title: "Dekont",
      dataIndex: "reference",
      width: 140,
      className: "mono",
      render: (x: string | null) => x ?? "—",
    },
    {
      title: "Dönem",
      dataIndex: "period",
      width: 90,
      className: "mono",
      render: (x: string | null) => x ?? "—",
    },
    ...(yetkili("tahsilat.yaz")
      ? [
          {
            title: "",
            width: 70,
            render: (_: unknown, r: Tahsilat) => (
              <Button size="small" type="text" danger onClick={() => silSor(r)}>
                Sil
              </Button>
            ),
          },
        ]
      : []),
  ];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Tabs
        defaultActiveKey="kayitlar"
        items={[
          {
            key: "kayitlar",
            label: "Tahsilat kayıtları",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Card
                  title="Tahsilat ve ödemeler"
                  extra={
                    <Space>
                      <Select
                        allowClear
                        showSearch
                        placeholder="Hesap"
                        style={{ width: 240 }}
                        optionFilterProp="label"
                        value={hesapId}
                        onChange={setHesapId}
                        loading={hesaplar.isLoading}
                        options={(hesaplar.data ?? []).map((h) => ({
                          value: h.id,
                          label: h.title,
                        }))}
                      />
                      <Select
                        allowClear
                        placeholder="Yön"
                        style={{ width: 130 }}
                        value={yon}
                        onChange={setYon}
                        options={[
                          { value: "GELEN", label: "Tahsilat" },
                          { value: "GIDEN", label: "Ödeme" },
                        ]}
                      />
                      {yetkili("tahsilat.yaz") && (
                        <Button type="primary" onClick={() => setYeniAcik(true)}>
                          Kayıt ekle
                        </Button>
                      )}
                    </Space>
                  }
                >
                  {bakiye.data && (
                    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                      <Descriptions
                        size="small"
                        bordered
                        column={{ xs: 1, sm: 2, xl: 3 }}
                        title={`${bakiye.data.title} — ERP bakiyesi`}
                      >
                        <Descriptions.Item label="Abonelik tahakkuku" className="tutar">
                          {tl(bakiye.data.abonelik_tahakkuk)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Sipariş tahakkuku" className="tutar">
                          {tl(bakiye.data.siparis_tahakkuk)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Tahsil edilen" className="tutar">
                          {tl(bakiye.data.tahsil_edilen)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Müşteri bakiyesi" className="tutar">
                          <strong
                            style={{
                              color:
                                Number(bakiye.data.musteri_bakiye) > 0 ? "#b42318" : "#1f6b4d",
                            }}
                          >
                            {tl(bakiye.data.musteri_bakiye)}
                          </strong>
                        </Descriptions.Item>
                        <Descriptions.Item label="Hak ediş borcu" className="tutar">
                          {tl(bakiye.data.ortak_bakiye)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Son tahsilat">
                          {bakiye.data.son_tahsilat
                            ? dayjs(bakiye.data.son_tahsilat).format("DD.MM.YYYY")
                            : "—"}
                        </Descriptions.Item>
                      </Descriptions>
                      <Alert
                        type="info"
                        title="Resmî cari hesap Logo'da"
                        description="Buradaki bakiye ERP'nin bildiği tahakkuk eksi kaydedilen tahsilattır; tahsilat takibi için tutulur, muhasebe kaydının yerini almaz."
                      />
                    </Space>
                  )}
                  <Table
                    rowKey="id"
                    size="small"
                    style={{ marginTop: 16 }}
                    loading={tahsilatlar.isLoading}
                    dataSource={tahsilatlar.data ?? []}
                    pagination={{ pageSize: 20, showSizeChanger: false }}
                    columns={tahsilatKolonlari}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: "gecikenler",
            label: `Gecikenler${
              gecikenler.data?.length ? ` (${gecikenler.data.length})` : ""
            }`,
            children: (
              <Card title="Ödeme geciken müşteriler">
                <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                  <Alert
                    type="warning"
                    title="Askıya alma otomatik yapılmaz"
                    description="Ödeme banka ekstresine ERP'den önce düşer; çalışan bir müşterinin takibini yanlışlıkla kesmek, gecikmiş tahsilattan pahalıya gelir. Karar ekibindir."
                  />
                  <Table
                    rowKey="account_id"
                    size="small"
                    loading={gecikenler.isLoading}
                    dataSource={gecikenler.data ?? []}
                    pagination={false}
                    locale={{ emptyText: <Empty description="Geciken ödeme yok" /> }}
                    onRow={(r) => ({
                      onClick: () => setHesapId(r.account_id),
                      style: { cursor: "pointer" },
                    })}
                    columns={[
                      { title: "Müşteri", dataIndex: "title" },
                      {
                        title: "Bakiye",
                        dataIndex: "musteri_bakiye",
                        width: 150,
                        className: "tutar",
                        render: (x: number) => (
                          <strong style={{ color: "#b42318" }}>{tl(x)}</strong>
                        ),
                      },
                      {
                        title: "Son tahsilat",
                        width: 130,
                        className: "mono",
                        render: (_: unknown, r: Geciken) =>
                          r.son_tahsilat ? dayjs(r.son_tahsilat).format("DD.MM.YYYY") : "—",
                      },
                      {
                        title: "Geciken",
                        width: 130,
                        render: (_: unknown, r: Geciken) => (
                          <Tag color="red">
                            {r.gecen_gun == null ? "hiç ödeme yok" : `${r.gecen_gun} gün`}
                          </Tag>
                        ),
                      },
                      {
                        title: "Aktif abonelik",
                        dataIndex: "aktif_abonelik",
                        width: 120,
                        className: "mono",
                      },
                      {
                        title: "Askıya alma önerisi",
                        render: (_: unknown, r: Geciken) =>
                          r.askiya_alma_onerilen.length === 0 ? (
                            "—"
                          ) : (
                            <Space size={4} wrap>
                              {r.askiya_alma_onerilen.map((a) => (
                                <Tag key={a.id} color={a.otomatik ? "orange" : "default"}>
                                  {a.no}
                                  {a.otomatik ? " · sözleşmede otomatik" : ""}
                                </Tag>
                              ))}
                            </Space>
                          ),
                      },
                    ]}
                  />
                </Space>
              </Card>
            ),
          },
        ]}
      />

      <Drawer
        title="Tahsilat / ödeme kaydı"
        open={yeniAcik}
        size={520}
        onClose={() => setYeniAcik(false)}
        extra={
          <Button type="primary" onClick={() => yeniForm.submit()} loading={olustur.isPending}>
            Kaydet
          </Button>
        }
      >
        <Form
          form={yeniForm}
          layout="vertical"
          initialValues={{ direction: "GELEN", method: "HAVALE" }}
          onFinish={(v) =>
            olustur.mutate({
              ...v,
              paid_at: dayjs(v.paid_at).format("YYYY-MM-DD"),
              period: v.period ? dayjs(v.period).format("YYYY-MM") : undefined,
            })
          }
        >
          <Form.Item
            name="account_id"
            label="Hesap"
            rules={[{ required: true, message: "Hesap seçin" }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              loading={hesaplar.isLoading}
              options={(hesaplar.data ?? []).map((h) => ({ value: h.id, label: h.title }))}
            />
          </Form.Item>
          <Space>
            <Form.Item name="direction" label="Yön">
              <Select
                style={{ width: 170 }}
                options={[
                  { value: "GELEN", label: "Tahsilat (müşteriden)" },
                  { value: "GIDEN", label: "Ödeme (montaj noktasına)" },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="amount"
              label="Tutar"
              rules={[{ required: true, message: "Tutar girin" }]}
            >
              <InputNumber min={0.01} style={{ width: 160 }} addonAfter="₺" />
            </Form.Item>
          </Space>
          <Space>
            <Form.Item
              name="paid_at"
              label="Tarih"
              rules={[{ required: true, message: "Tarih seçin" }]}
            >
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item name="method" label="Yöntem">
              <Select style={{ width: 170 }} options={YONTEMLER} />
            </Form.Item>
            <Form.Item name="period" label="Dönem">
              <DatePicker picker="month" format="MMMM YYYY" />
            </Form.Item>
          </Space>
          <Form.Item name="reference" label="Dekont / referans no">
            <Input />
          </Form.Item>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Typography.Text type="secondary">
            Dönem ve abonelik bağı isteğe bağlıdır; boş bırakılan tahsilat hesaba mahsuben
            işlenir ve bakiyeye yine girer.
          </Typography.Text>
        </Form>
      </Drawer>
    </Space>
  );
}
