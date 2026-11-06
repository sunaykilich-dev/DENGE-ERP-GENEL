import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
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
import { useNavigate } from "react-router-dom";

import { api, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import TeklifFormu from "./TeklifFormu";

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
}

interface Versiyon {
  id: number;
  version_no: number;
  currency: string;
  fx_rate: number | null;
  fx_date: string | null;
  fx_source: string | null;
  valid_until: string | null;
  subtotal: number;
  discount_total: number;
  vat_total: number;
  grand_total: number;
  max_discount_pct: number;
  discount_approved_at: string | null;
  sent_at: string | null;
  viewed_at: string | null;
  accepted_at: string | null;
  rejected_at: string | null;
  reject_reason: string | null;
  decision_channel: string | null;
  is_locked: boolean;
  public_url: string | null;
  kalemler: Kalem[];
}

interface Teklif {
  id: number;
  quote_no: string;
  customer_id: number;
  customer_title: string | null;
  owner_id: number | null;
  status: string;
  title: string | null;
  lost_reason: string | null;
  version: number;
  onay_gerekiyor: boolean;
  guncel: Versiyon | null;
  versiyon_sayisi: number;
}

interface Hesap {
  id: number;
  title: string;
  email: string | null;
}

interface Urun {
  id: number;
  code: string;
  name: string;
  list_price: number | null;
}

interface KalemFormu {
  item_type?: string;
  product_id?: number;
  description?: string;
  qty?: number;
  unit_price?: number;
  discount_pct?: number;
}

const tl = (v: number | null | undefined, para = "TRY") =>
  v == null
    ? "—"
    : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ${
        para === "TRY" ? "₺" : para
      }`;

const DURUM_RENGI: Record<string, string> = {
  TASLAK: "default",
  ONAY_BEKLIYOR: "gold",
  GONDERILDI: "blue",
  GORUNTULENDI: "cyan",
  REVIZE_EDILDI: "purple",
  KABUL: "green",
  RED: "red",
  SURESI_DOLDU: "default",
  SIPARISE_DONUSTU: "green",
};

/** Kalem satırlarını hem yeni teklif hem revizyon formunda aynı biçimde toplar. */
function KalemAlanlari({ urunler }: { urunler: Urun[] }) {
  const form = Form.useFormInstance();
  return (
    <Form.List name="kalemler">
      {(alanlar, { add, remove }) => (
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          {alanlar.map(({ key, name, ...rest }) => {
            const tip: string = form.getFieldValue(["kalemler", name, "item_type"]) ?? "URUN";
            return (
              <Space key={key} align="start" wrap>
                <Form.Item {...rest} name={[name, "item_type"]} noStyle initialValue="URUN">
                  <Select
                    style={{ width: 120 }}
                    options={[
                      { value: "URUN", label: "Ürün" },
                      { value: "HIZMET", label: "Hizmet" },
                      { value: "ABONELIK", label: "Abonelik" },
                      { value: "SIM_PAKETI", label: "SIM paketi" },
                      { value: "SERBEST", label: "Serbest" },
                    ]}
                    onChange={() => form.setFields([])}
                  />
                </Form.Item>
                {tip === "URUN" ? (
                  <Form.Item
                    {...rest}
                    name={[name, "product_id"]}
                    noStyle
                    rules={[{ required: true, message: "Ürün seçin" }]}
                  >
                    <Select
                      showSearch
                      placeholder="Ürün"
                      style={{ width: 280 }}
                      optionFilterProp="label"
                      options={urunler.map((u) => ({
                        value: u.id,
                        label: `${u.code} · ${u.name}`,
                      }))}
                    />
                  </Form.Item>
                ) : (
                  <>
                    <Form.Item
                      {...rest}
                      name={[name, "description"]}
                      noStyle
                      rules={[{ required: true, message: "Açıklama girin" }]}
                    >
                      <Input placeholder="Açıklama" style={{ width: 280 }} />
                    </Form.Item>
                    <Form.Item
                      {...rest}
                      name={[name, "unit_price"]}
                      noStyle
                      rules={[{ required: true, message: "Fiyat girin" }]}
                    >
                      <InputNumber placeholder="Birim fiyat" style={{ width: 130 }} min={0} />
                    </Form.Item>
                  </>
                )}
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
            );
          })}
          <Button onClick={() => add({ item_type: "URUN", qty: 1, discount_pct: 0 })}>
            Kalem ekle
          </Button>
        </Space>
      )}
    </Form.List>
  );
}

export default function TekliflerPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const navigate = useNavigate();
  const [durum, setDurum] = useState<string | undefined>();
  const [sekme, setSekme] = useState("liste");
  const [secili, setSecili] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [revizeAcik, setRevizeAcik] = useState(false);
  const [yeniForm] = Form.useForm();
  const [revizeForm] = Form.useForm();

  const teklifler = useQuery({
    queryKey: ["teklifler", durum],
    queryFn: () => api.get<Teklif[]>(`/api/teklifler${durum ? `?durum=${durum}` : ""}`),
  });

  const detay = useQuery({
    queryKey: ["teklif", secili],
    queryFn: () => api.get<Teklif>(`/api/teklifler/${secili}`),
    enabled: secili != null,
  });

  const musteriler = useQuery({
    queryKey: ["hesaplar-musteri"],
    queryFn: () => api.get<Hesap[]>("/api/hesaplar?rol=MUSTERI&limit=500"),
    enabled: yeniAcik,
  });

  const urunler = useQuery({
    queryKey: ["urunler-teklif"],
    queryFn: () => api.get<Urun[]>("/api/urunler?limit=500"),
    enabled: yeniAcik || revizeAcik,
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["teklifler"] });
    void qc.invalidateQueries({ queryKey: ["teklif"] });
  };

  const hata = (e: ApiError) => message.error(e.message);

  const olustur = useMutation({
    mutationFn: (v: Record<string, unknown>) => api.post<Teklif>("/api/teklifler", v),
    onSuccess: (t) => {
      message.success(`${t.quote_no} oluşturuldu`);
      setYeniAcik(false);
      yeniForm.resetFields();
      setSecili(t.id);
      yenile();
    },
    onError: hata,
  });

  const revize = useMutation({
    mutationFn: ({ id, ...v }: { id: number } & Record<string, unknown>) =>
      api.post<Teklif>(`/api/teklifler/${id}/revize`, v),
    onSuccess: () => {
      message.success("Yeni versiyon açıldı, önceki kilitlendi");
      setRevizeAcik(false);
      revizeForm.resetFields();
      yenile();
    },
    onError: hata,
  });

  const iskontoOnayla = useMutation({
    mutationFn: (id: number) => api.post(`/api/teklifler/${id}/iskonto-onayla`),
    onSuccess: () => {
      message.success("İskonto onaylandı");
      yenile();
    },
    onError: hata,
  });

  const gonder = useMutation({
    mutationFn: ({ id, ...v }: { id: number; alici?: string | null }) =>
      api.post(`/api/teklifler/${id}/gonder`, v),
    onSuccess: () => {
      message.success("Teklif PDF ekiyle gönderildi");
      yenile();
    },
    onError: hata,
  });

  const karar = useMutation({
    mutationFn: ({ id, ...v }: { id: number; kabul: boolean; red_nedeni?: string }) =>
      api.post(`/api/teklifler/${id}/karar`, v),
    onSuccess: () => {
      message.success("Karar kaydedildi");
      yenile();
    },
    onError: hata,
  });

  const siparise = useMutation({
    mutationFn: (id: number) =>
      api.post<{ order_no: string }>(`/api/siparisler/tekliften/${id}`),
    onSuccess: (o) => {
      message.success(`${o.order_no} siparişi açıldı`);
      yenile();
      navigate("/siparisler");
    },
    onError: hata,
  });

  const t = detay.data;
  const v = t?.guncel ?? null;

  function gonderSor(teklif: Teklif) {
    let alici = "";
    modal.confirm({
      title: `Teklifi gönder · ${teklif.quote_no}`,
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Gönderim versiyonu KİLİTLER. Değişiklik için yeni versiyon açmanız gerekir.
          </Typography.Text>
          <Input
            placeholder="Alıcı e-posta (boş bırakılırsa müşteri kartındaki adres)"
            onChange={(e) => (alici = e.target.value)}
          />
        </Space>
      ),
      okText: "Gönder",
      cancelText: "Vazgeç",
      onOk: () => gonder.mutateAsync({ id: teklif.id, alici: alici || null }),
    });
  }

  function redSor(id: number) {
    let neden = "";
    modal.confirm({
      title: "Teklif reddedildi",
      content: (
        <Input.TextArea
          placeholder="Red nedeni (fiyat, rakip, ihtiyaç kalmadı…)"
          rows={3}
          onChange={(e) => (neden = e.target.value)}
        />
      ),
      okText: "Reddedildi olarak kaydet",
      cancelText: "Vazgeç",
      onOk: () => {
        if (neden.trim().length < 3) {
          message.error("Red nedeni zorunludur");
          return Promise.reject();
        }
        return karar.mutateAsync({ id, kabul: false, red_nedeni: neden });
      },
    });
  }

  function revizeAc() {
    if (!v) return;
    revizeForm.setFieldsValue({
      valid_until: v.valid_until ? dayjs(v.valid_until) : undefined,
      kalemler: v.kalemler.map((k) => ({
        item_type: k.item_type,
        product_id: k.product_id ?? undefined,
        description: k.item_type === "URUN" ? undefined : k.description,
        qty: Number(k.qty),
        unit_price: Number(k.unit_price),
        discount_pct: Number(k.discount_pct),
      })),
    });
    setRevizeAcik(true);
  }

  const kalemKolonlari = [
    {
      title: "Tip",
      dataIndex: "item_type",
      width: 100,
      render: (x: string) => x.replaceAll("_", " ").toLowerCase(),
    },
    { title: "Açıklama", dataIndex: "description" },
    { title: "Adet", dataIndex: "qty", width: 70, className: "mono" },
    {
      title: "Birim",
      dataIndex: "unit_price",
      width: 120,
      className: "tutar",
      render: (x: number) => tl(x, v?.currency),
    },
    {
      title: "İsk.",
      dataIndex: "discount_pct",
      width: 70,
      className: "mono",
      render: (x: number) => (Number(x) ? `%${x}` : "—"),
    },
    {
      title: "KDV",
      dataIndex: "vat_rate",
      width: 70,
      className: "mono",
      render: (x: number) => `%${(Number(x) * 100).toFixed(0)}`,
    },
    {
      title: "Tutar",
      dataIndex: "line_total",
      width: 130,
      className: "tutar",
      render: (x: number) => <strong>{tl(x, v?.currency)}</strong>,
    },
  ];

  const listeEkrani = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card
        title="Teklifler"
        extra={
          <Space>
            <Select
              allowClear
              placeholder="Durum"
              style={{ width: 180 }}
              value={durum}
              onChange={setDurum}
              options={Object.keys(DURUM_RENGI).map((d) => ({
                value: d,
                label: d.replaceAll("_", " "),
              }))}
            />
            {yetkili("teklif.yaz") && (
              <Button type="primary" onClick={() => setYeniAcik(true)}>
                Yeni teklif
              </Button>
            )}
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={teklifler.isLoading}
          dataSource={teklifler.data ?? []}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          onRow={(r) => ({ onClick: () => setSecili(r.id), style: { cursor: "pointer" } })}
          columns={[
            { title: "Teklif no", dataIndex: "quote_no", width: 140, className: "mono" },
            { title: "Müşteri", dataIndex: "customer_title" },
            { title: "Konu", dataIndex: "title", render: (x: string | null) => x ?? "—" },
            {
              title: "Ver.",
              dataIndex: "versiyon_sayisi",
              width: 60,
              className: "mono",
            },
            {
              title: "Geçerlilik",
              width: 110,
              className: "mono",
              render: (_: unknown, r: Teklif) =>
                r.guncel?.valid_until ? dayjs(r.guncel.valid_until).format("DD.MM.YYYY") : "—",
            },
            {
              title: "Tutar",
              width: 140,
              className: "tutar",
              render: (_: unknown, r: Teklif) =>
                r.guncel ? <strong>{tl(r.guncel.grand_total, r.guncel.currency)}</strong> : "—",
            },
            {
              title: "Durum",
              width: 180,
              render: (_: unknown, r: Teklif) => (
                <Space size={4}>
                  <Tag color={DURUM_RENGI[r.status]}>{r.status.replaceAll("_", " ")}</Tag>
                  {r.onay_gerekiyor && (
                    <Tooltip title="İskonto eşiği aşıldı; satış müdürü onayı olmadan gönderilemez">
                      <Tag color="orange">onay</Tag>
                    </Tooltip>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Drawer
        title={t ? `${t.quote_no} · ${t.customer_title ?? ""}` : "Teklif"}
        open={secili != null}
        size={820}
        onClose={() => setSecili(null)}
        loading={detay.isLoading}
        extra={
          t && (
            <Space>
              <Button href={`/api/teklifler/${t.id}/pdf`} target="_blank">
                PDF
              </Button>
              {yetkili("teklif.yaz") && v && !v.accepted_at && (
                <Button onClick={() => gonderSor(t)} loading={gonder.isPending}>
                  E-posta ile gönder
                </Button>
              )}
              {yetkili("siparis.yaz") && t.status === "KABUL" && (
                <Button
                  type="primary"
                  loading={siparise.isPending}
                  onClick={() => siparise.mutate(t.id)}
                >
                  Siparişe dönüştür
                </Button>
              )}
            </Space>
          )
        }
      >
        {t && v && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            {t.onay_gerekiyor && (
              <Alert
                type="warning"
                showIcon
                title={`%${v.max_discount_pct} iskonto onay eşiğini aşıyor`}
                description="Satış müdürü onaylamadan teklif gönderilemez."
                action={
                  yetkili("teklif.iskonto_onayla") ? (
                    <Button
                      size="small"
                      type="primary"
                      loading={iskontoOnayla.isPending}
                      onClick={() => iskontoOnayla.mutate(t.id)}
                    >
                      Onayla
                    </Button>
                  ) : undefined
                }
              />
            )}
            {v.is_locked && (
              <Alert
                type="info"
                showIcon
                title={`Versiyon ${v.version_no} kilitli`}
                description="Gönderilmiş veya karara bağlanmış versiyon değiştirilemez; değişiklik yeni versiyon açar."
              />
            )}

            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Versiyon">
                <span className="mono">
                  v{v.version_no} / {t.versiyon_sayisi}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Para birimi">
                {v.currency}
                {v.fx_rate ? ` · ${v.fx_rate} (${v.fx_source ?? ""})` : ""}
              </Descriptions.Item>
              <Descriptions.Item label="Ara toplam">
                {tl(v.subtotal, v.currency)}
              </Descriptions.Item>
              <Descriptions.Item label="İskonto">
                {tl(v.discount_total, v.currency)}
              </Descriptions.Item>
              <Descriptions.Item label="KDV">{tl(v.vat_total, v.currency)}</Descriptions.Item>
              <Descriptions.Item label="Genel toplam">
                <strong>{tl(v.grand_total, v.currency)}</strong>
              </Descriptions.Item>
              <Descriptions.Item label="Geçerlilik">
                {v.valid_until ? dayjs(v.valid_until).format("DD.MM.YYYY") : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Gönderim">
                {v.sent_at ? dayjs(v.sent_at).format("DD.MM.YYYY HH:mm") : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Görüntülenme">
                {v.viewed_at ? dayjs(v.viewed_at).format("DD.MM.YYYY HH:mm") : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Karar">
                {v.accepted_at
                  ? `Kabul · ${dayjs(v.accepted_at).format("DD.MM.YYYY")}`
                  : v.rejected_at
                    ? `Red · ${dayjs(v.rejected_at).format("DD.MM.YYYY")}`
                    : "—"}
                {v.decision_channel ? ` (${v.decision_channel.toLowerCase()})` : ""}
              </Descriptions.Item>
              {v.reject_reason && (
                <Descriptions.Item label="Red nedeni" span={2}>
                  {v.reject_reason}
                </Descriptions.Item>
              )}
            </Descriptions>

            {v.public_url && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Müşteri linki:{" "}
                <Typography.Text className="mono" copyable>
                  {v.public_url}
                </Typography.Text>
              </Typography.Text>
            )}

            {yetkili("teklif.yaz") && (
              <Space wrap>
                <Button onClick={revizeAc} disabled={["KABUL", "SIPARISE_DONUSTU"].includes(t.status)}>
                  Revize et
                </Button>
                {v.sent_at && !v.accepted_at && !v.rejected_at && (
                  <>
                    <Button
                      type="primary"
                      loading={karar.isPending}
                      onClick={() => karar.mutate({ id: t.id, kabul: true })}
                    >
                      Kabul edildi
                    </Button>
                    <Button danger onClick={() => redSor(t.id)}>
                      Reddedildi
                    </Button>
                  </>
                )}
              </Space>
            )}

            <Table
              rowKey="id"
              size="small"
              dataSource={v.kalemler}
              pagination={false}
              columns={kalemKolonlari}
            />
          </Space>
        )}
      </Drawer>

      <Modal
        title="Yeni teklif"
        open={yeniAcik}
        onCancel={() => setYeniAcik(false)}
        onOk={() => yeniForm.submit()}
        confirmLoading={olustur.isPending}
        okText="Oluştur"
        cancelText="Vazgeç"
        width={900}
      >
        <Form
          form={yeniForm}
          layout="vertical"
          onFinish={(d) =>
            olustur.mutate({
              customer_id: d.customer_id,
              title: d.title || null,
              currency: d.currency ?? "TRY",
              valid_until: d.valid_until ? dayjs(d.valid_until).format("YYYY-MM-DD") : null,
              kalemler: (d.kalemler ?? []).map((k: KalemFormu) => ({
                item_type: k.item_type ?? "URUN",
                product_id: k.item_type === "URUN" ? k.product_id : null,
                description: k.description ?? null,
                qty: k.qty ?? 1,
                unit_price: k.item_type === "URUN" ? null : k.unit_price,
                discount_pct: k.discount_pct ?? 0,
              })),
            })
          }
        >
          <Space wrap align="start">
            <Form.Item
              name="customer_id"
              label="Müşteri"
              rules={[{ required: true, message: "Müşteri seçin" }]}
            >
              <Select
                showSearch
                style={{ width: 320 }}
                loading={musteriler.isLoading}
                optionFilterProp="label"
                options={(musteriler.data ?? []).map((h) => ({ value: h.id, label: h.title }))}
              />
            </Form.Item>
            <Form.Item name="title" label="Konu">
              <Input style={{ width: 260 }} placeholder="30 araç filo takip" />
            </Form.Item>
            <Form.Item name="currency" label="Para birimi" initialValue="TRY">
              <Select
                style={{ width: 110 }}
                options={["TRY", "USD", "EUR"].map((p) => ({ value: p, label: p }))}
              />
            </Form.Item>
            <Form.Item name="valid_until" label="Geçerlilik">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
          </Space>
          <Form.Item label="Kalemler">
            <KalemAlanlari urunler={urunler.data ?? []} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t ? `Revize · ${t.quote_no}` : "Revize"}
        open={revizeAcik}
        onCancel={() => setRevizeAcik(false)}
        onOk={() => revizeForm.submit()}
        confirmLoading={revize.isPending}
        okText="Yeni versiyon aç"
        cancelText="Vazgeç"
        width={900}
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          title="Önceki versiyon kilitlenir ve görüntülenebilir kalır"
          description="Kalem fiyatları kaynak versiyondan taşınır — ürün kartındaki güncel fiyat değil, müşteriye gösterilen fiyat esastır."
        />
        <Form
          form={revizeForm}
          layout="vertical"
          onFinish={(d) =>
            t &&
            revize.mutate({
              id: t.id,
              valid_until: d.valid_until ? dayjs(d.valid_until).format("YYYY-MM-DD") : null,
              notes: d.notes || null,
              kalemler: (d.kalemler ?? []).map((k: KalemFormu) => ({
                item_type: k.item_type ?? "URUN",
                product_id: k.item_type === "URUN" ? k.product_id : null,
                description: k.description ?? null,
                qty: k.qty ?? 1,
                unit_price: k.item_type === "URUN" ? null : k.unit_price,
                discount_pct: k.discount_pct ?? 0,
              })),
            })
          }
        >
          <Space wrap align="start">
            <Form.Item name="valid_until" label="Geçerlilik">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item name="notes" label="Not">
              <Input style={{ width: 420 }} placeholder="Revizyon gerekçesi" />
            </Form.Item>
          </Space>
          <Form.Item label="Kalemler">
            <KalemAlanlari urunler={urunler.data ?? []} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );

  return (
    <Tabs
      activeKey={sekme}
      onChange={setSekme}
      items={[
        { key: "liste", label: "Teklifler", children: listeEkrani },
        ...(yetkili("teklif.yaz")
          ? [
              {
                key: "yeni",
                label: "Yeni teklif",
                children: <TeklifFormu onKaydedildi={() => setSekme("liste")} />,
              },
            ]
          : []),
      ]}
    />
  );
}
