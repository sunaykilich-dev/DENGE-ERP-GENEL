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
import { useAuth } from "../auth/AuthContext";

interface Rma {
  id: number;
  rma_no: string;
  device_id: number;
  device_kimlik: string | null;
  customer_id: number | null;
  customer_title: string | null;
  vehicle_id: number | null;
  vehicle_plate: string | null;
  status: string;
  received_at: string;
  fault_description: string;
  warranty_status: string;
  warranty_end_date: string | null;
  resolution: string | null;
  resolution_note: string | null;
  replacement_device_id: number | null;
  replacement_kimlik: string | null;
  cost: number | null;
  supplier_id: number | null;
  supplier_rma_no: string | null;
  sent_to_supplier_at: string | null;
  returned_from_supplier_at: string | null;
  closed_at: string | null;
  notes: string | null;
  version: number;
  sonraki_durumlar: string[];
}

interface ArizaSatiri {
  product_id: number;
  urun_kodu: string;
  urun_adi: string;
  cihaz_sayisi: number;
  rma_sayisi: number;
  ariza_orani: number;
}

interface Hesap {
  id: number;
  title: string;
}

const tl = (v: number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

const DURUM_RENGI: Record<string, string> = {
  ACIK: "gold",
  INCELEMEDE: "blue",
  TAMIRDE: "purple",
  TEDARIKCIDE: "cyan",
  COZULDU: "green",
  KAPANDI: "default",
  IPTAL: "red",
};

const GARANTI_RENGI: Record<string, string> = {
  GARANTI_ICI: "green",
  GARANTI_DISI: "red",
  BELIRSIZ: "default",
};

const COZUMLER = [
  { value: "TAMIR", label: "Tamir edildi" },
  { value: "DEGISIM", label: "Cihaz değişimi" },
  { value: "IADE", label: "İade" },
  { value: "ONARILMADI", label: "Onarılamadı" },
  { value: "HURDAYA_AYRILDI", label: "Hurdaya ayrıldı" },
];

export default function RmaPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const [durum, setDurum] = useState<string | undefined>();
  const [secili, setSecili] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [cozumAcik, setCozumAcik] = useState(false);
  const [yeniForm] = Form.useForm();
  const [cozumForm] = Form.useForm();

  const kayitlar = useQuery({
    queryKey: ["rma", durum],
    queryFn: () => api.get<Rma[]>(`/api/rma${durum ? `?durum=${durum}` : ""}`),
  });

  const detay = useQuery({
    queryKey: ["rma-detay", secili],
    queryFn: () => api.get<Rma>(`/api/rma/${secili}`),
    enabled: secili != null,
  });

  const arizaOrani = useQuery({
    queryKey: ["rma-ariza-orani"],
    queryFn: () => api.get<ArizaSatiri[]>("/api/rma/ariza-orani"),
  });

  const tedarikciler = useQuery({
    queryKey: ["hesaplar-tedarikci"],
    queryFn: () => api.get<Hesap[]>("/api/hesaplar?rol=TEDARIKCI&limit=200"),
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["rma"] });
    void qc.invalidateQueries({ queryKey: ["rma-detay"] });
    void qc.invalidateQueries({ queryKey: ["rma-ariza-orani"] });
  };

  const hata = (e: ApiError) => message.error(e.message);

  const ac = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Rma>("/api/rma", v),
    onSuccess: (k) => {
      message.success(
        `${k.rma_no} açıldı · garanti: ${k.warranty_status.replaceAll("_", " ").toLowerCase()}`,
      );
      setYeniAcik(false);
      yeniForm.resetFields();
      setSecili(k.id);
      yenile();
    },
    onError: hata,
  });

  const durumDegistir = useMutation({
    mutationFn: ({ id, durum }: { id: number; durum: string }) =>
      api.post(`/api/rma/${id}/durum`, { durum }),
    onSuccess: () => {
      message.success("Durum güncellendi");
      yenile();
    },
    onError: hata,
  });

  const coz = useMutation({
    mutationFn: ({ id, ...v }: { id: number } & Record<string, unknown>) =>
      api.post(`/api/rma/${id}/coz`, v),
    onSuccess: () => {
      message.success("Çözüm kaydedildi");
      setCozumAcik(false);
      cozumForm.resetFields();
      yenile();
    },
    onError: hata,
  });

  const tedarikciKaydet = useMutation({
    mutationFn: ({ id, ...v }: { id: number } & Record<string, unknown>) =>
      api.patch(`/api/rma/${id}/tedarikci`, v),
    onSuccess: () => {
      message.success("Tedarikçi bilgisi kaydedildi");
      yenile();
    },
    onError: hata,
  });

  const k = detay.data;

  function tedarikciSor(kayit: Rma) {
    let rmaNo = kayit.supplier_rma_no ?? "";
    let tedarikciId = kayit.supplier_id ?? undefined;
    modal.confirm({
      title: "Üreticiye garanti iadesi",
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Select
            placeholder="Tedarikçi"
            style={{ width: "100%" }}
            defaultValue={tedarikciId}
            options={(tedarikciler.data ?? []).map((t) => ({
              value: t.id,
              label: t.title,
            }))}
            onChange={(v) => (tedarikciId = v)}
          />
          <Input
            placeholder="Tedarikçi RMA no"
            defaultValue={rmaNo}
            onChange={(e) => (rmaNo = e.target.value)}
          />
        </Space>
      ),
      okText: "Kaydet",
      cancelText: "Vazgeç",
      onOk: () =>
        tedarikciKaydet.mutateAsync({
          id: kayit.id,
          supplier_id: tedarikciId ?? null,
          supplier_rma_no: rmaNo || null,
          sent_to_supplier_at: dayjs().format("YYYY-MM-DD"),
          version: kayit.version,
        }),
    });
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Tabs
        defaultActiveKey="kayitlar"
        items={[
          {
            key: "kayitlar",
            label: "Servis kayıtları",
            children: (
              <Card
                title="RMA / Teknik servis"
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
                        label: d.replaceAll("_", " ").toLowerCase(),
                      }))}
                    />
                    {yetkili("rma.yaz") && (
                      <Button type="primary" onClick={() => setYeniAcik(true)}>
                        Servise al
                      </Button>
                    )}
                  </Space>
                }
              >
                <Table
                  rowKey="id"
                  size="small"
                  loading={kayitlar.isLoading}
                  dataSource={kayitlar.data ?? []}
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                  scroll={{ x: 1060 }}
                  onRow={(r) => ({
                    onClick: () => setSecili(r.id),
                    style: { cursor: "pointer" },
                  })}
                  columns={[
                    {
                      title: "RMA no",
                      dataIndex: "rma_no",
                      width: 140,
                      className: "mono",
                    },
                    {
                      title: "Cihaz",
                      dataIndex: "device_kimlik",
                      width: 160,
                      className: "mono",
                    },
                    {
                      title: "Müşteri",
                      dataIndex: "customer_title",
                      width: 200,
                      ellipsis: true,
                      render: (x: string | null) => x ?? "—",
                    },
                    {
                      title: "Arıza",
                      dataIndex: "fault_description",
                      width: 240,
                      ellipsis: true,
                    },
                    {
                      title: "Geliş",
                      dataIndex: "received_at",
                      width: 110,
                      className: "mono",
                      render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                    },
                    {
                      title: "Garanti",
                      dataIndex: "warranty_status",
                      width: 120,
                      render: (x: string) => (
                        <Tag color={GARANTI_RENGI[x]}>{x.replaceAll("_", " ").toLowerCase()}</Tag>
                      ),
                    },
                    {
                      title: "Durum",
                      dataIndex: "status",
                      width: 120,
                      render: (x: string) => (
                        <Tag color={DURUM_RENGI[x]}>{x.replaceAll("_", " ").toLowerCase()}</Tag>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "ariza",
            label: "Arıza oranı",
            children: (
              <Card title="Model bazında arıza oranı (son 1 yıl)">
                <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                  <Alert
                    type="info"
                    title="Payda o modeldeki toplam cihaz"
                    description="Yalnız arıza sayısını listelemek çok satan modeli haksız yere kötü gösterirdi."
                  />
                  <Table
                    rowKey="product_id"
                    size="small"
                    loading={arizaOrani.isLoading}
                    dataSource={arizaOrani.data ?? []}
                    pagination={false}
                    locale={{ emptyText: <Empty description="Veri yok" /> }}
                    columns={[
                      {
                        title: "Ürün",
                        dataIndex: "urun_kodu",
                        width: 180,
                        className: "mono",
                      },
                      { title: "Ad", dataIndex: "urun_adi", ellipsis: true },
                      {
                        title: "Cihaz",
                        dataIndex: "cihaz_sayisi",
                        width: 100,
                        className: "mono",
                      },
                      {
                        title: "RMA",
                        dataIndex: "rma_sayisi",
                        width: 90,
                        className: "mono",
                      },
                      {
                        title: "Arıza oranı",
                        dataIndex: "ariza_orani",
                        width: 130,
                        className: "tutar",
                        render: (x: number) => (
                          <strong style={{ color: x >= 10 ? "#b42318" : undefined }}>
                            %
                            {Number(x).toLocaleString("tr-TR", {
                              minimumFractionDigits: 2,
                            })}
                          </strong>
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
        title={k ? `${k.rma_no} · ${k.device_kimlik ?? ""}` : "Servis kaydı"}
        open={secili != null}
        size={780}
        onClose={() => setSecili(null)}
        loading={detay.isLoading}
        extra={
          k &&
          yetkili("rma.yaz") && (
            <Space>
              {k.sonraki_durumlar
                .filter((d) => d !== "COZULDU" && d !== "IPTAL")
                .map((d) => (
                  <Button
                    key={d}
                    type={d === "KAPANDI" ? "primary" : "default"}
                    onClick={() => durumDegistir.mutate({ id: k.id, durum: d })}
                  >
                    {d.replaceAll("_", " ").toLowerCase()}
                  </Button>
                ))}
              {!k.resolution && !["KAPANDI", "IPTAL"].includes(k.status) && (
                <Button type="primary" onClick={() => setCozumAcik(true)}>
                  Çözüm gir
                </Button>
              )}
            </Space>
          )
        }
      >
        {k && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            {k.warranty_status === "BELIRSIZ" && (
              <Alert
                type="warning"
                title="Garanti durumu belirsiz"
                description="Cihazın ilk aktivasyon tarihi bilinmiyor; garanti başlangıcı hesaplanamadı. Ücret kararını elle verin."
              />
            )}

            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Durum">
                <Tag color={DURUM_RENGI[k.status]}>{k.status.replaceAll("_", " ")}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Garanti">
                <Space size={4}>
                  <Tag color={GARANTI_RENGI[k.warranty_status]}>
                    {k.warranty_status.replaceAll("_", " ").toLowerCase()}
                  </Tag>
                  {k.warranty_end_date && (
                    <Typography.Text type="secondary">
                      {dayjs(k.warranty_end_date).format("DD.MM.YYYY")}
                    </Typography.Text>
                  )}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Müşteri">{k.customer_title ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Araç">{k.vehicle_plate ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Geliş tarihi">
                {dayjs(k.received_at).format("DD.MM.YYYY")}
              </Descriptions.Item>
              <Descriptions.Item label="Kapanış">
                {k.closed_at ? dayjs(k.closed_at).format("DD.MM.YYYY HH:mm") : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Arıza" span={2}>
                {k.fault_description}
              </Descriptions.Item>
              {k.resolution && (
                <>
                  <Descriptions.Item label="Çözüm">
                    {COZUMLER.find((c) => c.value === k.resolution)?.label ?? k.resolution}
                  </Descriptions.Item>
                  <Descriptions.Item label="Müşteri bedeli" className="tutar">
                    {tl(k.cost)}
                  </Descriptions.Item>
                  {k.replacement_kimlik && (
                    <Descriptions.Item label="Yerine geçen cihaz" span={2}>
                      <Tooltip title="Araç, hat ve müşteri bağı bu cihaza taşındı">
                        <span className="mono">{k.replacement_kimlik}</span>
                      </Tooltip>
                    </Descriptions.Item>
                  )}
                  {k.resolution_note && (
                    <Descriptions.Item label="Çözüm notu" span={2}>
                      {k.resolution_note}
                    </Descriptions.Item>
                  )}
                </>
              )}
            </Descriptions>

            <Card
              size="small"
              title="Üreticiye garanti iadesi"
              extra={
                yetkili("rma.yaz") && (
                  <Button size="small" onClick={() => tedarikciSor(k)}>
                    Düzenle
                  </Button>
                )
              }
            >
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="Tedarikçi RMA no">
                  {k.supplier_rma_no ?? "—"}
                </Descriptions.Item>
                <Descriptions.Item label="Gönderim">
                  {k.sent_to_supplier_at ? dayjs(k.sent_to_supplier_at).format("DD.MM.YYYY") : "—"}
                </Descriptions.Item>
                <Descriptions.Item label="Dönüş">
                  {k.returned_from_supplier_at
                    ? dayjs(k.returned_from_supplier_at).format("DD.MM.YYYY")
                    : "—"}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Space>
        )}
      </Drawer>

      <Drawer
        title="Servise al"
        open={yeniAcik}
        size={520}
        onClose={() => setYeniAcik(false)}
        extra={
          <Button type="primary" onClick={() => yeniForm.submit()} loading={ac.isPending}>
            Kaydet
          </Button>
        }
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Garanti durumu cihazın ilk aktivasyonundan otomatik hesaplanır ve kayda DONDURULUR;
            sonradan garanti tarihi düzeltilse bile bu kaydın kararı değişmez.
          </Typography.Text>
          <Form
            form={yeniForm}
            layout="vertical"
            style={{ width: "100%" }}
            onFinish={(v) =>
              ac.mutate({
                ...v,
                received_at: v.received_at ? dayjs(v.received_at).format("YYYY-MM-DD") : undefined,
              })
            }
          >
            <Form.Item
              name="kimlik"
              label="IMEI / Seri no"
              rules={[{ required: true, message: "Cihaz kimliği girin" }]}
            >
              <Input placeholder="860000000000001" />
            </Form.Item>
            <Form.Item
              name="fault_description"
              label="Arıza tanımı"
              rules={[{ required: true, min: 3, message: "Arızayı yazın" }]}
            >
              <Input.TextArea rows={3} />
            </Form.Item>
            <Form.Item name="received_at" label="Geliş tarihi">
              <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="notes" label="Not">
              <Input.TextArea rows={2} />
            </Form.Item>
          </Form>
        </Space>
      </Drawer>

      <Drawer
        title="Çözüm gir"
        open={cozumAcik}
        size={480}
        onClose={() => setCozumAcik(false)}
        extra={
          <Button type="primary" onClick={() => cozumForm.submit()} loading={coz.isPending}>
            Kaydet
          </Button>
        }
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          {k?.warranty_status === "GARANTI_ICI" && (
            <Alert
              type="info"
              title="Garanti içi"
              description="Bu kayda müşteri bedeli yazılamaz."
            />
          )}
          <Form
            form={cozumForm}
            layout="vertical"
            style={{ width: "100%" }}
            onFinish={(v) => k && coz.mutate({ id: k.id, ...v })}
          >
            <Form.Item
              name="resolution"
              label="Çözüm"
              rules={[{ required: true, message: "Çözüm seçin" }]}
            >
              <Select options={COZUMLER} />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(o, n) => o.resolution !== n.resolution}>
              {({ getFieldValue }) =>
                getFieldValue("resolution") === "DEGISIM" ? (
                  <Form.Item
                    name="replacement_kimlik"
                    label="Yerine geçecek cihazın IMEI / seri no'su"
                    rules={[{ required: true, message: "Yeni cihazı girin" }]}
                    extra="Araç, hat ve müşteri bağı bu cihaza taşınır; eski cihaz hurdaya ayrılır."
                  >
                    <Input placeholder="860000000000002" />
                  </Form.Item>
                ) : null
              }
            </Form.Item>
            {k?.warranty_status !== "GARANTI_ICI" && (
              <Form.Item name="cost" label="Müşteri bedeli">
                <InputNumber min={0} style={{ width: "100%" }} addonAfter="₺" />
              </Form.Item>
            )}
            <Form.Item name="resolution_note" label="Çözüm notu">
              <Input.TextArea rows={3} />
            </Form.Item>
          </Form>
        </Space>
      </Drawer>
    </Space>
  );
}
