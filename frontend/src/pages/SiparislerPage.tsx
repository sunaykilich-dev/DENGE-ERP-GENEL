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
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { api, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import SatisIsleri from "./SatisIsleri";

interface Kalem {
  id: number;
  item_type: string;
  product_id: number | null;
  description: string;
  qty: number;
  unit_price: number;
  discount_pct: number;
  vat_rate: number;
  line_total: number;
  qty_shipped: number;
  rezerve_adet: number;
  kimlik_gerekir: boolean;
}

interface Rezervasyon {
  id: number;
  order_line_id: number;
  device_id: number;
  kimlik: string | null;
  reserved_at: string;
  shipped_at: string | null;
  transfer_id: number | null;
}

interface Siparis {
  id: number;
  order_no: string;
  customer_id: number;
  customer_title: string | null;
  quote_id: number | null;
  owner_id: number | null;
  status: string;
  order_date: string;
  requested_date: string | null;
  currency: string;
  subtotal: number;
  discount_total: number;
  vat_total: number;
  grand_total: number;
  notes: string | null;
  version: number;
  sonraki_durumlar: string[];
  kalemler: Kalem[];
  rezervasyonlar: Rezervasyon[];
}

interface UygunCihaz {
  id: number;
  imei: string | null;
  serial_no: string | null;
  product_id: number | null;
  status: string;
}

interface BekleyenSatir {
  order_id: number;
  order_no: string;
  status: string;
  order_date: string;
  requested_date: string | null;
  toplam_adet: number;
  sevk_adet: number;
  kalan_adet: number;
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

const DURUM_RENGI: Record<string, string> = {
  TASLAK: "default",
  ONAYLANDI: "blue",
  REZERVE: "gold",
  KISMI_SEVK: "orange",
  SEVK_EDILDI: "cyan",
  TAMAMLANDI: "green",
  IPTAL: "red",
};

export default function SiparislerPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const [durum, setDurum] = useState<string | undefined>();
  const [secili, setSecili] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [rezerveKalem, setRezerveKalem] = useState<Kalem | null>(null);
  const [secilenCihazlar, setSecilenCihazlar] = useState<number[]>([]);
  const [cihazAra, setCihazAra] = useState("");
  const [yeniForm] = Form.useForm();

  const siparisler = useQuery({
    queryKey: ["siparisler", durum],
    queryFn: () => api.get<Siparis[]>(`/api/siparisler${durum ? `?durum=${durum}` : ""}`),
  });

  const bekleyen = useQuery({
    queryKey: ["siparis-bekleyen"],
    queryFn: () => api.get<BekleyenSatir[]>("/api/siparisler/bekleyen-sevkiyat"),
  });

  const detay = useQuery({
    queryKey: ["siparis", secili],
    queryFn: () => api.get<Siparis>(`/api/siparisler/${secili}`),
    enabled: secili != null,
  });

  const uygun = useQuery({
    queryKey: ["uygun-cihazlar", secili, rezerveKalem?.id, cihazAra],
    queryFn: () =>
      api.get<UygunCihaz[]>(
        `/api/siparisler/${secili}/uygun-cihazlar?kalem_id=${rezerveKalem?.id}` +
          (cihazAra ? `&ara=${encodeURIComponent(cihazAra)}` : ""),
      ),
    enabled: secili != null && rezerveKalem != null,
  });

  const musteriler = useQuery({
    queryKey: ["hesaplar-musteri"],
    queryFn: () => api.get<Hesap[]>("/api/hesaplar?rol=MUSTERI&limit=500"),
    enabled: yeniAcik,
  });

  const urunler = useQuery({
    queryKey: ["urunler-siparis"],
    queryFn: () => api.get<Urun[]>("/api/urunler?limit=500"),
    enabled: yeniAcik,
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["siparisler"] });
    void qc.invalidateQueries({ queryKey: ["siparis"] });
    void qc.invalidateQueries({ queryKey: ["siparis-bekleyen"] });
    void qc.invalidateQueries({ queryKey: ["uygun-cihazlar"] });
  };

  const hata = (e: ApiError) => message.error(e.message);

  const olustur = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Siparis>("/api/siparisler", v),
    onSuccess: (s) => {
      message.success(`${s.order_no} oluşturuldu`);
      setYeniAcik(false);
      yeniForm.resetFields();
      setSecili(s.id);
      yenile();
    },
    onError: hata,
  });

  const onayla = useMutation({
    mutationFn: (id: number) => api.post(`/api/siparisler/${id}/onayla`),
    onSuccess: () => {
      message.success("Sipariş onaylandı; artık IMEI ayrılabilir");
      yenile();
    },
    onError: hata,
  });

  const rezerve = useMutation({
    mutationFn: ({ id, ...v }: { id: number; kalem_id: number; device_ids: number[] }) =>
      api.post(`/api/siparisler/${id}/rezerve`, v),
    onSuccess: () => {
      message.success("Cihazlar rezerve edildi");
      setRezerveKalem(null);
      setSecilenCihazlar([]);
      setCihazAra("");
      yenile();
    },
    onError: hata,
  });

  const birak = useMutation({
    mutationFn: ({ id, neden }: { id: number; neden?: string }) =>
      api.post(`/api/siparisler/rezervasyon/${id}/birak`, { neden }),
    onSuccess: () => {
      message.success("Rezervasyon serbest bırakıldı, cihaz stoğa döndü");
      yenile();
    },
    onError: hata,
  });

  const sevk = useMutation({
    mutationFn: ({ id, ...v }: { id: number; belge_no?: string }) =>
      api.post<{ transfer_no: string; adet: number }>(`/api/siparisler/${id}/sevk`, v),
    onSuccess: (r) => {
      message.success(`${r.transfer_no} ile ${r.adet} cihaz sevk edildi`);
      yenile();
    },
    onError: hata,
  });

  const teslim = useMutation({
    mutationFn: ({ transferId, received_by }: { transferId: number; received_by?: string }) =>
      api.post(`/api/siparisler/sevkiyat/${transferId}/teslim`, { received_by }),
    onSuccess: () => {
      message.success("Teslim kaydedildi; cihazlar müşteriye geçti");
      yenile();
    },
    onError: hata,
  });

  const iptal = useMutation({
    mutationFn: ({ id, neden }: { id: number; neden: string }) =>
      api.post(`/api/siparisler/${id}/iptal`, { neden }),
    onSuccess: () => {
      message.success("Sipariş iptal edildi, rezervasyonlar bırakıldı");
      yenile();
    },
    onError: hata,
  });

  const s = detay.data;

  function iptalSor(id: number) {
    let neden = "";
    modal.confirm({
      title: "Siparişi iptal et",
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Açık rezervasyonlar serbest bırakılır. Sevk edilmiş cihazlar geri gelmez — iade
            ayrı bir transfer belgesidir.
          </Typography.Text>
          <Input.TextArea
            rows={2}
            placeholder="İptal nedeni"
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
        return iptal.mutateAsync({ id, neden });
      },
    });
  }

  function sevkSor(siparis: Siparis) {
    const acik = siparis.rezervasyonlar.filter((r) => r.shipped_at == null);
    if (acik.length === 0) {
      message.warning("Sevk edilecek açık rezervasyon yok");
      return;
    }
    let belge = "";
    modal.confirm({
      title: `Sevk et · ${acik.length} cihaz`,
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Stok transfer belgesi YOLDA olarak açılır. Konum ve sahiplik, teslim
            işaretlendiğinde güncellenir.
          </Typography.Text>
          <Input
            placeholder="İrsaliye / belge no (isteğe bağlı)"
            onChange={(e) => (belge = e.target.value)}
          />
        </Space>
      ),
      okText: "Sevk et",
      cancelText: "Vazgeç",
      onOk: () => sevk.mutateAsync({ id: siparis.id, belge_no: belge || undefined }),
    });
  }

  const sevkBekleyenTransferler = s
    ? [
        ...new Set(
          s.rezervasyonlar
            .filter((r) => r.shipped_at != null && r.transfer_id != null)
            .map((r) => r.transfer_id as number),
        ),
      ]
    : [];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card
        title="Siparişler"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="Durum"
              style={{ width: 170 }}
              value={durum}
              onChange={setDurum}
              options={Object.keys(DURUM_RENGI).map((d) => ({
                value: d,
                label: d.replaceAll("_", " "),
              }))}
            />
            {yetkili("siparis.yaz") && (
              <Button type="primary" onClick={() => setYeniAcik(true)}>
                Yeni sipariş
              </Button>
            )}
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={siparisler.isLoading}
          dataSource={siparisler.data ?? []}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          onRow={(r) => ({ onClick: () => setSecili(r.id), style: { cursor: "pointer" } })}
          columns={[
            { title: "Sipariş no", dataIndex: "order_no", width: 140, className: "mono" },
            { title: "Müşteri", dataIndex: "customer_title" },
            {
              title: "Tarih",
              dataIndex: "order_date",
              width: 110,
              className: "mono",
              render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
            },
            {
              title: "İstenen",
              dataIndex: "requested_date",
              width: 110,
              className: "mono",
              render: (x: string | null) => (x ? dayjs(x).format("DD.MM.YYYY") : "—"),
            },
            {
              title: "Tutar",
              width: 140,
              className: "tutar",
              render: (_: unknown, r: Siparis) => (
                <strong>{tl(r.grand_total, r.currency)}</strong>
              ),
            },
            {
              title: "Kaynak",
              width: 90,
              render: (_: unknown, r: Siparis) =>
                r.quote_id ? <Tag color="purple">teklif</Tag> : <Tag>doğrudan</Tag>,
            },
            {
              title: "Durum",
              width: 130,
              render: (_: unknown, r: Siparis) => (
                <Tag color={DURUM_RENGI[r.status]}>{r.status.replaceAll("_", " ")}</Tag>
              ),
            },
          ]}
        />
      </Card>

      <Card title="Depo iş listesi — bekleyen sevkiyat">
        <Table
          rowKey="order_id"
          size="small"
          loading={bekleyen.isLoading}
          dataSource={bekleyen.data ?? []}
          pagination={false}
          locale={{ emptyText: <Empty description="Bekleyen sevkiyat yok" /> }}
          onRow={(r) => ({
            onClick: () => setSecili(r.order_id),
            style: { cursor: "pointer" },
          })}
          columns={[
            { title: "Sipariş no", dataIndex: "order_no", width: 140, className: "mono" },
            {
              title: "İstenen tarih",
              dataIndex: "requested_date",
              width: 120,
              className: "mono",
              render: (x: string | null) => (x ? dayjs(x).format("DD.MM.YYYY") : "—"),
            },
            {
              title: "Durum",
              dataIndex: "status",
              width: 130,
              render: (x: string) => <Tag color={DURUM_RENGI[x]}>{x.replaceAll("_", " ")}</Tag>,
            },
            {
              title: "İlerleme",
              render: (_: unknown, r: BekleyenSatir) => (
                <Space>
                  <Progress
                    percent={
                      Number(r.toplam_adet) > 0
                        ? Math.round((Number(r.sevk_adet) / Number(r.toplam_adet)) * 100)
                        : 0
                    }
                    size="small"
                    style={{ width: 160 }}
                  />
                  <Typography.Text className="mono">
                    {Number(r.sevk_adet)}/{Number(r.toplam_adet)}
                  </Typography.Text>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Drawer
        title={s ? `${s.order_no} · ${s.customer_title ?? ""}` : "Sipariş"}
        open={secili != null}
        size={860}
        onClose={() => {
          setSecili(null);
          setRezerveKalem(null);
        }}
        loading={detay.isLoading}
        extra={
          s &&
          yetkili("siparis.yaz") && (
            <Space>
              {s.status === "TASLAK" && (
                <Button type="primary" onClick={() => onayla.mutate(s.id)}>
                  Onayla
                </Button>
              )}
              {["REZERVE", "KISMI_SEVK"].includes(s.status) && (
                <Button type="primary" onClick={() => sevkSor(s)}>
                  Sevk et
                </Button>
              )}
              {!["IPTAL", "TAMAMLANDI"].includes(s.status) && (
                <Button danger onClick={() => iptalSor(s.id)}>
                  İptal
                </Button>
              )}
            </Space>
          )
        }
      >
        {s && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="Durum">
                <Tag color={DURUM_RENGI[s.status]}>{s.status.replaceAll("_", " ")}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Sipariş tarihi">
                {dayjs(s.order_date).format("DD.MM.YYYY")}
              </Descriptions.Item>
              <Descriptions.Item label="Ara toplam" className="tutar">
                {tl(s.subtotal, s.currency)}
              </Descriptions.Item>
              <Descriptions.Item label="İskonto" className="tutar">
                {tl(s.discount_total, s.currency)}
              </Descriptions.Item>
              <Descriptions.Item label="KDV" className="tutar">
                {tl(s.vat_total, s.currency)}
              </Descriptions.Item>
              <Descriptions.Item label="Genel toplam" className="tutar">
                <strong>{tl(s.grand_total, s.currency)}</strong>
              </Descriptions.Item>
            </Descriptions>

            {s.status === "TASLAK" && (
              <Alert
                type="info"
                title="Taslak sipariş"
                description="Kalemler yalnız taslakken değiştirilebilir. Onayladıktan sonra IMEI ayırabilirsiniz."
              />
            )}

            <Card size="small" title="Kalemler">
              <Table
                rowKey="id"
                size="small"
                dataSource={s.kalemler}
                pagination={false}
                columns={[
                  { title: "Açıklama", dataIndex: "description" },
                  { title: "Adet", dataIndex: "qty", width: 70, className: "mono" },
                  {
                    title: "Birim",
                    dataIndex: "unit_price",
                    width: 120,
                    className: "tutar",
                    render: (x: number) => tl(x, s.currency),
                  },
                  {
                    title: "Tutar",
                    dataIndex: "line_total",
                    width: 130,
                    className: "tutar",
                    render: (x: number) => <strong>{tl(x, s.currency)}</strong>,
                  },
                  {
                    title: "Rezerve / Sevk",
                    width: 130,
                    className: "mono",
                    render: (_: unknown, k: Kalem) =>
                      k.kimlik_gerekir ? (
                        `${k.rezerve_adet} / ${Number(k.qty_shipped)}`
                      ) : (
                        <Tooltip title="Bu ürün kimlik taşımıyor; IMEI ayrılmaz">
                          <Typography.Text type="secondary">—</Typography.Text>
                        </Tooltip>
                      ),
                  },
                  {
                    title: "",
                    width: 110,
                    render: (_: unknown, k: Kalem) =>
                      yetkili("siparis.yaz") &&
                      k.kimlik_gerekir &&
                      !["TASLAK", "IPTAL", "TAMAMLANDI"].includes(s.status) &&
                      k.rezerve_adet + Number(k.qty_shipped) < Number(k.qty) ? (
                        <Button
                          size="small"
                          onClick={() => {
                            setRezerveKalem(k);
                            setSecilenCihazlar([]);
                          }}
                        >
                          IMEI ayır
                        </Button>
                      ) : null,
                  },
                ]}
              />
            </Card>

            <Card size="small" title="Rezerve ve sevk edilen cihazlar">
              <Table
                rowKey="id"
                size="small"
                dataSource={s.rezervasyonlar}
                pagination={false}
                locale={{ emptyText: <Empty description="Henüz cihaz ayrılmadı" /> }}
                columns={[
                  { title: "Kimlik", dataIndex: "kimlik", className: "mono" },
                  {
                    title: "Ayrıldı",
                    dataIndex: "reserved_at",
                    width: 130,
                    className: "mono",
                    render: (x: string) => dayjs(x).format("DD.MM.YYYY HH:mm"),
                  },
                  {
                    title: "Durum",
                    width: 120,
                    render: (_: unknown, r: Rezervasyon) =>
                      r.shipped_at ? (
                        <Tag color="cyan">sevk edildi</Tag>
                      ) : (
                        <Tag color="gold">rezerve</Tag>
                      ),
                  },
                  {
                    title: "",
                    width: 90,
                    render: (_: unknown, r: Rezervasyon) =>
                      !r.shipped_at && yetkili("siparis.yaz") ? (
                        <Button
                          size="small"
                          danger
                          type="text"
                          onClick={() => birak.mutate({ id: r.id })}
                        >
                          Bırak
                        </Button>
                      ) : null,
                  },
                ]}
              />
            </Card>

            {/* KARARLAR 2026-11-09 S4.1/S4.2: bağlı kurulum/teslimat işleri ve aşamaları. */}
            <Card size="small" title="Kurulum ve teslimat işleri">
              <SatisIsleri
                kaynak="siparis"
                id={s.id}
                teklifId={s.quote_id}
                isAcilabilir={["ONAYLANDI", "REZERVE", "KISMI_SEVK", "SEVK_EDILDI", "TAMAMLANDI"].includes(
                  s.status,
                )}
              />
            </Card>

            {sevkBekleyenTransferler.length > 0 && yetkili("siparis.yaz") && (
              <Card size="small" title="Teslim onayı">
                <Space orientation="vertical" style={{ width: "100%" }}>
                  <Typography.Text type="secondary">
                    Teslim işaretlenince cihazların konumu MÜŞTERİ, sahipliği MÜŞTERİ_SATILDI
                    olur.
                  </Typography.Text>
                  {sevkBekleyenTransferler.map((tid) => (
                    <Button key={tid} onClick={() => teslim.mutate({ transferId: tid })}>
                      Sevkiyat #{tid} teslim alındı
                    </Button>
                  ))}
                </Space>
              </Card>
            )}
          </Space>
        )}
      </Drawer>

      <Drawer
        title={rezerveKalem ? `IMEI ayır · ${rezerveKalem.description}` : "IMEI ayır"}
        open={rezerveKalem != null}
        size={520}
        onClose={() => {
          setRezerveKalem(null);
          setSecilenCihazlar([]);
          setCihazAra("");
        }}
        extra={
          <Button
            type="primary"
            disabled={secilenCihazlar.length === 0}
            onClick={() =>
              secili != null &&
              rezerveKalem &&
              rezerve.mutate({
                id: secili,
                kalem_id: rezerveKalem.id,
                device_ids: secilenCihazlar,
              })
            }
          >
            {secilenCihazlar.length} cihazı ayır
          </Button>
        }
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Listede yalnız ayrılabilir cihazlar var: başka siparişte rezerve olan veya stokta
            olmayan cihaz görünmez.
          </Typography.Text>
          <Input.Search
            placeholder="IMEI / seri no ara"
            allowClear
            onSearch={setCihazAra}
            onChange={(e) => !e.target.value && setCihazAra("")}
          />
          <Table
            rowKey="id"
            size="small"
            loading={uygun.isLoading}
            dataSource={uygun.data ?? []}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            locale={{ emptyText: <Empty description="Ayrılabilir cihaz yok" /> }}
            rowSelection={{
              selectedRowKeys: secilenCihazlar,
              onChange: (keys) => setSecilenCihazlar(keys as number[]),
            }}
            columns={[
              {
                title: "Kimlik",
                className: "mono",
                render: (_: unknown, c: UygunCihaz) => c.imei ?? c.serial_no ?? `#${c.id}`,
              },
              { title: "Durum", dataIndex: "status", width: 140 },
            ]}
          />
        </Space>
      </Drawer>

      <Drawer
        title="Yeni sipariş"
        open={yeniAcik}
        size={720}
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
          onFinish={(v) =>
            olustur.mutate({
              ...v,
              order_date: v.order_date ? dayjs(v.order_date).format("YYYY-MM-DD") : undefined,
              requested_date: v.requested_date
                ? dayjs(v.requested_date).format("YYYY-MM-DD")
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
          <Space>
            <Form.Item name="order_date" label="Sipariş tarihi">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item name="requested_date" label="İstenen teslim">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
          </Space>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={2} />
          </Form.Item>

          <Typography.Title level={5}>Kalemler</Typography.Title>
          <Form.List name="kalemler">
            {(alanlar, { add, remove }) => (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                {alanlar.map(({ key, name, ...rest }) => (
                  <Space key={key} align="start" wrap>
                    <Form.Item
                      {...rest}
                      name={[name, "product_id"]}
                      noStyle
                      rules={[{ required: true, message: "Ürün seçin" }]}
                    >
                      <Select
                        showSearch
                        placeholder="Ürün"
                        style={{ width: 300 }}
                        optionFilterProp="label"
                        options={(urunler.data ?? []).map((u) => ({
                          value: u.id,
                          label: `${u.code} · ${u.name}`,
                        }))}
                      />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, "qty"]} noStyle initialValue={1}>
                      <InputNumber placeholder="Adet" style={{ width: 80 }} min={0.01} />
                    </Form.Item>
                    <Form.Item {...rest} name={[name, "discount_pct"]} noStyle initialValue={0}>
                      <InputNumber placeholder="% isk." style={{ width: 90 }} min={0} max={100} />
                    </Form.Item>
                    <Button danger type="text" onClick={() => remove(name)}>
                      Sil
                    </Button>
                  </Space>
                ))}
                <Button onClick={() => add({ qty: 1, discount_pct: 0 })}>Kalem ekle</Button>
              </Space>
            )}
          </Form.List>
        </Form>
      </Drawer>
    </Space>
  );
}
