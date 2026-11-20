import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, type ApiError } from "../api/client";
import EkYukleyici from "../components/EkYukleyici";
import { useAuth } from "../auth/AuthContext";

interface Urun {
  id: number;
  code: string;
  supplier_code: string | null;
  name: string;
  type: string;
  brand: string | null;
  model: string | null;
  family: string | null;
  identity_kind: string;
  requires_parent: boolean;
  channel_count: number | null;
  supported_network_tech: string[] | null;
  warranty_months: number;
  is_112_approved: boolean;
  is_school_service_ready: boolean;
  vat_rate: number | null;
  list_price: number | null;
  currency: string;
  notes: string | null;
  is_active: boolean;
  version: number;
  cover_attachment_id: number | null;
  stok_adedi: number | null;
}

interface MarkaGrubu {
  marka: string;
  modeller: string[];
}

const KIMLIK_ETIKETI: Record<string, { renk: string; ad: string; aciklama: string }> = {
  IMEI: {
    renk: "blue",
    ad: "IMEI",
    aciklama: "Cihaz kaydında IMEI zorunludur; IMEI'siz kayıt sistem tarafından reddedilir.",
  },
  SERI_NO: {
    renk: "orange",
    ad: "Seri no",
    aciklama:
      "Bu üründe IMEI fiziksel olarak yok (analog kamera — modemi ve SIM'i yok). Kimlik seri numarasıdır.",
  },
  YOK: {
    renk: "default",
    ad: "Adet",
    aciklama: "Tekil kimlikle takip edilmez; stok adedi hareketlerden hesaplanır.",
  },
};

const TIP_ADI: Record<string, string> = {
  CIHAZ_SERILI: "Cihaz",
  AKSESUAR: "Aksesuar",
  SIM_PAKETI: "SIM paketi",
  ABONELIK_PLANI: "Abonelik planı",
  HIZMET: "Hizmet",
};

const MARKASIZ = "-";

export default function UrunlerPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const { id } = useParams();
  const navigate = useNavigate();

  const [arama, setArama] = useState("");
  const [marka, setMarka] = useState<string | undefined>();
  const [model, setModel] = useState<string | undefined>();
  const [tip, setTip] = useState<string | undefined>();
  const [duzenlenen, setDuzenlenen] = useState<Urun | null>(null);
  const [formAcik, setFormAcik] = useState(false);
  const [form] = Form.useForm();

  const markalar = useQuery({
    queryKey: ["urun-markalar"],
    queryFn: () => api.get<MarkaGrubu[]>("/api/urunler/markalar"),
  });

  const urunler = useQuery({
    queryKey: ["urunler", arama, marka, model, tip],
    queryFn: () => {
      const p = new URLSearchParams();
      if (arama) p.set("q", arama);
      if (marka) p.set("marka", marka);
      if (model) p.set("model", model);
      if (tip) p.set("tip", tip);
      p.set("limit", "500");
      return api.get<Urun[]>(`/api/urunler?${p}`);
    },
  });

  const secili = useQuery({
    queryKey: ["urun", id],
    queryFn: () => api.get<Urun>(`/api/urunler/${id}`),
    enabled: !!id,
  });

  const kaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      duzenlenen
        ? api.patch<Urun>(`/api/urunler/${duzenlenen.id}`, { ...v, version: duzenlenen.version })
        : api.post<Urun>("/api/urunler", v),
    onSuccess: () => {
      message.success(duzenlenen ? "Ürün güncellendi" : "Ürün eklendi");
      setFormAcik(false);
      setDuzenlenen(null);
      form.resetFields();
      void qc.invalidateQueries({ queryKey: ["urunler"] });
      void qc.invalidateQueries({ queryKey: ["urun-markalar"] });
      void qc.invalidateQueries({ queryKey: ["urun", id] });
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  function duzenle(u: Urun | null) {
    setDuzenlenen(u);
    form.setFieldsValue(
      u ?? { type: "CIHAZ_SERILI", identity_kind: "IMEI", warranty_months: 24, currency: "TRY" },
    );
    setFormAcik(true);
  }

  const seciliMarka = (markalar.data ?? []).find((m) => (m.marka || MARKASIZ) === marka);
  const seriNoluVar = (urunler.data ?? []).some((u) => u.identity_kind === "SERI_NO");
  const u = secili.data;

  return (
    <Card
      title="Ürün Kataloğu"
      extra={
        yetkili("urun.yaz") && (
          <Button type="primary" onClick={() => duzenle(null)}>
            Yeni ürün
          </Button>
        )
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="Ad, kod, marka veya model"
          allowClear
          onSearch={setArama}
          style={{ width: 260 }}
        />
        <Select
          placeholder="Marka"
          allowClear
          value={marka}
          style={{ width: 180 }}
          loading={markalar.isLoading}
          onChange={(v) => {
            setMarka(v);
            setModel(undefined);
          }}
          options={(markalar.data ?? []).map((m) => ({
            value: m.marka || MARKASIZ,
            label: m.marka || "(markası girilmemiş)",
          }))}
        />
        <Select
          placeholder="Model"
          allowClear
          value={model}
          style={{ width: 200 }}
          disabled={!marka}
          onChange={setModel}
          options={(seciliMarka?.modeller ?? []).map((m) => ({ value: m, label: m }))}
        />
        <Select
          placeholder="Tip"
          allowClear
          value={tip}
          style={{ width: 160 }}
          onChange={setTip}
          options={Object.entries(TIP_ADI).map(([v, l]) => ({ value: v, label: l }))}
        />
      </Space>

      {seriNoluVar && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title="Kimlik tipi neden ürüne bağlı?"
          description={
            <>
              Takip cihazları ve araç kameraları IMEI taşır. Ek kameralar (Dahua HMW3200LP ve HAC
              serisi) analog cihazlardır — modemleri ve SIM'leri yoktur, ana cihazın kanalına
              kabloyla bağlanırlar; IMEI'leri fiziksel olarak yoktur. Bu yüzden IMEI zorunluluğu
              ürün kartında tanımlanır: <strong>IMEI</strong> tipindeki bir üründe IMEI'siz cihaz
              kaydı açılamaz.
            </>
          }
        />
      )}

      <Table
        rowKey="id"
        size="small"
        loading={urunler.isLoading}
        dataSource={urunler.data ?? []}
        pagination={{ pageSize: 25, hideOnSinglePage: true }}
        scroll={{ x: 1040 }}
        onRow={(r) => ({
          onClick: () => navigate(`/urunler/${r.id}`),
          style: { cursor: "pointer" },
        })}
        locale={{ emptyText: <Empty description="Ürün bulunamadı" /> }}
        columns={[
          {
            title: "",
            width: 56,
            render: (_, p: Urun) =>
              p.cover_attachment_id ? (
                <img
                  src={`/api/ekler/dosya/${p.cover_attachment_id}`}
                  alt=""
                  style={{ width: 40, height: 30, objectFit: "cover", borderRadius: 3 }}
                />
              ) : null,
          },
          { title: "Kod", dataIndex: "code", className: "mono", width: 150, ellipsis: true },
          { title: "Ad", dataIndex: "name", ellipsis: true },
          {
            title: "Marka",
            dataIndex: "brand",
            width: 120,
            render: (x: string | null) =>
              x ?? (
                <Tooltip title="Marka girilmemiş — ürün kartından ekleyin">
                  <Tag color="orange">—</Tag>
                </Tooltip>
              ),
          },
          { title: "Model", dataIndex: "model", width: 150, className: "mono", ellipsis: true },
          {
            title: "Tip",
            dataIndex: "type",
            width: 110,
            render: (x: string) => <Tag>{TIP_ADI[x] ?? x}</Tag>,
          },
          {
            title: "Kimlik",
            width: 140,
            render: (_, p: Urun) => {
              const kk = KIMLIK_ETIKETI[p.identity_kind] ?? KIMLIK_ETIKETI.YOK;
              return (
                <Tooltip title={kk.aciklama}>
                  <Space size={4}>
                    <Tag color={kk.renk}>{kk.ad}</Tag>
                    {p.requires_parent && <Tag>ana cihaza bağlı</Tag>}
                  </Space>
                </Tooltip>
              );
            },
          },
          {
            title: "Liste fiyatı",
            width: 130,
            className: "tutar",
            render: (_, p: Urun) =>
              p.list_price == null ? (
                <Typography.Text type="secondary">—</Typography.Text>
              ) : (
                `${Number(p.list_price).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ${p.currency}`
              ),
          },
        ]}
      />

      {/* --- Ürün kartı --- */}
      <Drawer
        title={u?.name ?? "Ürün"}
        open={!!id}
        size={720}
        onClose={() => navigate("/urunler")}
        loading={secili.isLoading}
        extra={yetkili("urun.yaz") && u && <Button onClick={() => duzenle(u)}>Düzenle</Button>}
      >
        {secili.isError && <Empty description="Ürün bulunamadı" />}
        {u && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Kod">
                <span className="mono">{u.code}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Tedarikçi kodu">
                <span className="mono">{u.supplier_code ?? "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Marka">{u.brand ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Model">
                <span className="mono">{u.model ?? "—"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Tip">{TIP_ADI[u.type] ?? u.type}</Descriptions.Item>
              <Descriptions.Item label="Kimlik">
                {(KIMLIK_ETIKETI[u.identity_kind] ?? KIMLIK_ETIKETI.YOK).ad}
              </Descriptions.Item>
              <Descriptions.Item label="Stokta">
                <strong className="mono">
                  {u.stok_adedi == null ? "—" : u.stok_adedi.toLocaleString("tr-TR")}
                </strong>
              </Descriptions.Item>
              <Descriptions.Item label="Garanti">{u.warranty_months} ay</Descriptions.Item>
              <Descriptions.Item label="Şebeke">
                <Space size={2} wrap>
                  {(u.supported_network_tech ?? []).map((t) => (
                    <Tag key={t} style={{ marginInlineEnd: 0 }}>
                      {t}
                    </Tag>
                  ))}
                  {!u.supported_network_tech?.length && "—"}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Kanal">{u.channel_count ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Liste fiyatı" span={2}>
                {u.list_price == null
                  ? "—"
                  : `${Number(u.list_price).toLocaleString("tr-TR", {
                      minimumFractionDigits: 2,
                    })} ${u.currency}`}
              </Descriptions.Item>
              {(u.is_112_approved || u.is_school_service_ready) && (
                <Descriptions.Item label="Onaylar" span={2}>
                  <Space size={4} wrap>
                    {u.is_112_approved && <Tag color="green">112 onaylı</Tag>}
                    {u.is_school_service_ready && <Tag color="green">okul servisi</Tag>}
                  </Space>
                </Descriptions.Item>
              )}
              {u.notes && (
                <Descriptions.Item label="Not" span={2}>
                  {u.notes}
                </Descriptions.Item>
              )}
            </Descriptions>

            <EkYukleyici
              entity="products"
              entityId={u.id}
              kind="URUN_GORSELI"
              baslik="Ürün görselleri"
              aciklama="Teklif hazırlarken ve sahada model doğrularken kullanılır. JPEG, PNG veya WebP."
              accept="image/*"
              yazabilir={yetkili("urun.yaz")}
            />
            <EkYukleyici
              entity="products"
              entityId={u.id}
              kind="BROSUR"
              baslik="Broşürler"
              aciklama="Müşteriye gönderilen tanıtım dosyaları."
              accept=".pdf,image/*"
              yazabilir={yetkili("urun.yaz")}
            />
            <EkYukleyici
              entity="products"
              entityId={u.id}
              kind="TEKNIK_DOKUMAN"
              baslik="Teknik dokümanlar"
              aciklama="Kurulum kılavuzu, kablo şeması, CE/TSE uygunluk belgesi. Belgeler MODEL bazındadır — aynı belge o modeldeki bütün cihazları kapsar."
              accept=".pdf,.docx,.xlsx,image/*"
              yazabilir={yetkili("urun.yaz")}
            />
          </Space>
        )}
      </Drawer>

      {/* --- Ürün düzenleme --- */}
      <Drawer
        title={duzenlenen ? duzenlenen.name : "Yeni ürün"}
        open={formAcik}
        size={520}
        onClose={() => setFormAcik(false)}
        extra={
          <Button type="primary" onClick={() => form.submit()} loading={kaydet.isPending}>
            Kaydet
          </Button>
        }
      >
        <Form form={form} layout="vertical" onFinish={(v) => kaydet.mutate(v)}>
          <Form.Item name="code" label="Kod" rules={[{ required: true }]}>
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="name" label="Ad" rules={[{ required: true, min: 2 }]}>
            <Input />
          </Form.Item>
          <Space style={{ display: "flex" }}>
            <Form.Item name="brand" label="Marka" style={{ flex: 1 }} extra="Üretici firma">
              <Input />
            </Form.Item>
            <Form.Item name="model" label="Model" style={{ flex: 1 }}>
              <Input className="mono" />
            </Form.Item>
          </Space>
          <Form.Item name="family" label="Ürün ailesi" extra="Örn. L300, GS900 — raporlarda gruplama için">
            <Input />
          </Form.Item>
          <Form.Item name="type" label="Tip" rules={[{ required: true }]}>
            <Select options={Object.entries(TIP_ADI).map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
          <Form.Item
            name="identity_kind"
            label="Kimlik tipi"
            rules={[{ required: true }]}
            extra="IMEI seçilirse bu üründe IMEI'siz cihaz kaydı açılamaz. Adet seçilirse cihaz kaydı tutulmaz, stok hareketle izlenir."
          >
            <Select
              options={[
                { value: "IMEI", label: "IMEI" },
                { value: "SERI_NO", label: "Seri no" },
                { value: "YOK", label: "Adet (tekil kimlik yok)" },
              ]}
            />
          </Form.Item>
          <Form.Item name="requires_parent" valuePropName="checked">
            <Checkbox>Ana cihaza bağlanır (ek kamera)</Checkbox>
          </Form.Item>
          <Space style={{ display: "flex" }}>
            <Form.Item name="channel_count" label="Kanal sayısı" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="warranty_months" label="Garanti (ay)" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
          </Space>
          <Form.Item name="supported_network_tech" label="Şebeke">
            <Select
              mode="multiple"
              allowClear
              options={["2G", "3G", "4G", "LTE_M", "NB_IOT"].map((t) => ({ value: t, label: t }))}
            />
          </Form.Item>
          <Space style={{ display: "flex" }}>
            <Form.Item name="list_price" label="Liste fiyatı" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="currency" label="Para birimi" style={{ width: 110 }}>
              <Select options={["TRY", "USD", "EUR"].map((c) => ({ value: c, label: c }))} />
            </Form.Item>
          </Space>
          <Form.Item
            name="vat_rate"
            label="KDV oranı"
            extra="Kesir olarak: %20 için 0.20 yazın."
          >
            <InputNumber min={0} max={1} step={0.01} style={{ width: "100%" }} />
          </Form.Item>
          <Space style={{ display: "flex" }} wrap>
            <Form.Item name="is_112_approved" valuePropName="checked" noStyle>
              <Checkbox>112 onaylı</Checkbox>
            </Form.Item>
            <Form.Item name="is_school_service_ready" valuePropName="checked" noStyle>
              <Checkbox>Okul servisine uygun</Checkbox>
            </Form.Item>
          </Space>
          <Form.Item name="notes" label="Not" style={{ marginTop: 18 }}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Drawer>
    </Card>
  );
}
