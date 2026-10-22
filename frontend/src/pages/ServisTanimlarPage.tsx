/**
 * Servis Tanımları — arıza nedeni ve bekleme nedeni katalogları (TS-024/023).
 *
 * - Arıza nedeni birim bazlıdır; düzenleme `servis.tanim`. Birim kapsamlı
 *   kullanıcı yalnız kendi birimlerinin listesini görür (sunucu süzer).
 * - Bekleme nedeni ortak katalogdur; düzenleme `operasyon.yonet`.
 *   "Sistem" nedenleri (ör. bakım uygunsuzluğu) ekrandan seçilemez, burada
 *   yalnız görünür ve sistem bayrağı değiştirilemez.
 * - Silme yoktur: geçmiş kayıtlar nedene bağlı olduğu için pasifleştirilir.
 * - İyimser kilit: düzenlemede `version` gönderilir; 409'da "kayıt değişti,
 *   yenileyin" mesajı verilir ve liste tazelenir.
 */
import { EditOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  message,
} from "antd";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const TS = "/api/teknik-servis";

interface ArizaNedeniSatiri {
  id: number;
  birim: string;
  ad: string;
  sira: number;
  is_active: boolean;
  version: number;
}

interface BeklemeNedeniSatiri {
  kod: string;
  ad: string;
  sla_durdurur: boolean;
  aciklama_zorunlu: boolean;
  sadece_sistem: boolean;
  sira: number;
  is_active: boolean;
  version: number;
}

interface FormVerileriBirim {
  birimler: { kod: string; ad: string }[];
}

function hataMesaji(e: unknown): string {
  if (e instanceof ApiError && e.cakisma) return `${e.message} — kayıt değişmiş olabilir, liste yenilendi.`;
  return e instanceof Error ? e.message : "Beklenmeyen hata";
}

function ArizaNedenleri() {
  const { yetkili } = useAuth();
  const duzenleyebilir = yetkili("servis.tanim");
  const qc = useQueryClient();
  const [birim, setBirim] = useState<string | undefined>();
  const [pencere, setPencere] = useState<{ acik: boolean; kayit?: ArizaNedeniSatiri }>({ acik: false });
  const [form] = Form.useForm();

  const birimler = useQuery({
    queryKey: ["servis-form-verileri"],
    queryFn: () => api.get<FormVerileriBirim>(`${TS}/isler/form-verileri`),
  });
  const liste = useQuery({
    queryKey: ["ariza-nedenleri", birim],
    queryFn: () => {
      const p = new URLSearchParams({ tumu: "true" });
      if (birim) p.set("birim", birim);
      return api.get<ArizaNedeniSatiri[]>(`${TS}/tanimlar/ariza-nedenleri?${p}`);
    },
  });
  const birimAdi = (kod: string) => birimler.data?.birimler.find((b) => b.kod === kod)?.ad ?? kod;

  const kaydet = useMutation({
    mutationFn: (g: Record<string, unknown>) => api.put<ArizaNedeniSatiri>(`${TS}/tanimlar/ariza-nedenleri`, g),
    onSuccess: () => {
      message.success("Arıza nedeni kaydedildi");
      setPencere({ acik: false });
      qc.invalidateQueries({ queryKey: ["ariza-nedenleri"] });
    },
    onError: (e) => {
      message.error(hataMesaji(e));
      if (e instanceof ApiError && e.cakisma) qc.invalidateQueries({ queryKey: ["ariza-nedenleri"] });
    },
  });

  const ac = (kayit?: ArizaNedeniSatiri) => {
    form.resetFields();
    form.setFieldsValue(kayit ?? { birim: birim ?? birimler.data?.birimler[0]?.kod, sira: 0, is_active: true });
    setPencere({ acik: true, kayit });
  };

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          allowClear
          placeholder="Tüm birimler"
          style={{ minWidth: 200 }}
          value={birim}
          onChange={setBirim}
          options={(birimler.data?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
        />
        {duzenleyebilir && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => ac()}>
            Yeni arıza nedeni
          </Button>
        )}
      </Space>
      <Table<ArizaNedeniSatiri>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data ?? []}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: true }}
        locale={{ emptyText: <Empty description="Kayıt yok" /> }}
        columns={[
          { title: "Birim", dataIndex: "birim", render: (b: string) => birimAdi(b) },
          { title: "Ad", dataIndex: "ad" },
          { title: "Sıra", dataIndex: "sira", width: 70 },
          {
            title: "Durum",
            dataIndex: "is_active",
            render: (a: boolean) => (a ? <Tag color="green">Aktif</Tag> : <Tag>Pasif</Tag>),
          },
          ...(duzenleyebilir
            ? [
                {
                  title: "",
                  key: "islem",
                  width: 60,
                  render: (_: unknown, r: ArizaNedeniSatiri) => (
                    <Button size="small" icon={<EditOutlined />} aria-label="Düzenle" onClick={() => ac(r)} />
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        title={pencere.kayit ? "Arıza nedenini düzenle" : "Yeni arıza nedeni"}
        open={pencere.acik}
        onCancel={() => setPencere({ acik: false })}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) =>
            kaydet.mutate({ ...v, id: pencere.kayit?.id, version: pencere.kayit?.version })
          }
        >
          <Form.Item name="birim" label="Birim" rules={[{ required: true, message: "Birim seçin" }]}>
            <Select
              disabled={!!pencere.kayit}
              options={(birimler.data?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
            />
          </Form.Item>
          <Form.Item name="ad" label="Ad" rules={[{ required: true, max: 80, message: "Ad 1-80 karakter" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="sira" label="Sıra">
            <InputNumber min={0} max={999} />
          </Form.Item>
          <Form.Item name="is_active" label="Aktif" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

function BeklemeNedenleri() {
  const { yetkili } = useAuth();
  const duzenleyebilir = yetkili("operasyon.yonet");
  const qc = useQueryClient();
  const [pencere, setPencere] = useState<{ acik: boolean; kayit?: BeklemeNedeniSatiri }>({ acik: false });
  const [form] = Form.useForm();

  const liste = useQuery({
    queryKey: ["bekleme-nedenleri"],
    queryFn: () => api.get<BeklemeNedeniSatiri[]>(`${TS}/tanimlar/bekleme-nedenleri?tumu=true`),
  });
  const kaydet = useMutation({
    mutationFn: (g: Record<string, unknown>) =>
      api.put<BeklemeNedeniSatiri>(`${TS}/tanimlar/bekleme-nedenleri`, g),
    onSuccess: () => {
      message.success("Bekleme nedeni kaydedildi");
      setPencere({ acik: false });
      qc.invalidateQueries({ queryKey: ["bekleme-nedenleri"] });
    },
    onError: (e) => {
      message.error(hataMesaji(e));
      if (e instanceof ApiError && e.cakisma) qc.invalidateQueries({ queryKey: ["bekleme-nedenleri"] });
    },
  });

  const ac = (kayit?: BeklemeNedeniSatiri) => {
    form.resetFields();
    form.setFieldsValue(
      kayit ?? { sira: 0, is_active: true, sla_durdurur: false, aciklama_zorunlu: false },
    );
    setPencere({ acik: true, kayit });
  };

  return (
    <>
      {duzenleyebilir && (
        <Button type="primary" icon={<PlusOutlined />} onClick={() => ac()} style={{ marginBottom: 12 }}>
          Yeni bekleme nedeni
        </Button>
      )}
      <Table<BeklemeNedeniSatiri>
        rowKey="kod"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data ?? []}
        pagination={false}
        scroll={{ x: true }}
        columns={[
          { title: "Kod", dataIndex: "kod", render: (k: string) => <span className="mono">{k}</span> },
          { title: "Ad", dataIndex: "ad" },
          {
            title: "Özellik",
            key: "ozellik",
            render: (_: unknown, r: BeklemeNedeniSatiri) => (
              <Space size={4} wrap>
                {r.sla_durdurur && <Tag color="blue">SLA durdurur</Tag>}
                {r.aciklama_zorunlu && <Tag>Açıklama zorunlu</Tag>}
                {r.sadece_sistem && <Tag color="purple">Sistem</Tag>}
              </Space>
            ),
          },
          { title: "Sıra", dataIndex: "sira", width: 70 },
          {
            title: "Durum",
            dataIndex: "is_active",
            render: (a: boolean) => (a ? <Tag color="green">Aktif</Tag> : <Tag>Pasif</Tag>),
          },
          ...(duzenleyebilir
            ? [
                {
                  title: "",
                  key: "islem",
                  width: 60,
                  render: (_: unknown, r: BeklemeNedeniSatiri) => (
                    <Button size="small" icon={<EditOutlined />} aria-label="Düzenle" onClick={() => ac(r)} />
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        title={pencere.kayit ? "Bekleme nedenini düzenle" : "Yeni bekleme nedeni"}
        open={pencere.acik}
        onCancel={() => setPencere({ acik: false })}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => kaydet.mutate({ ...v, version: pencere.kayit?.version })}
        >
          <Form.Item
            name="kod"
            label="Kod"
            extra="Büyük harf, rakam ve alt çizgi (ör. SAHA_KAPALI)"
            rules={[{ required: true, pattern: /^[A-Z][A-Z0-9_]{1,29}$/, message: "Geçerli bir kod girin" }]}
          >
            <Input disabled={!!pencere.kayit} />
          </Form.Item>
          <Form.Item name="ad" label="Ad" rules={[{ required: true, max: 80, message: "Ad 1-80 karakter" }]}>
            <Input />
          </Form.Item>
          <Form.Item name="sla_durdurur" label="SLA süresini durdurur" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="aciklama_zorunlu" label="Açıklama zorunlu" valuePropName="checked">
            <Switch disabled={pencere.kayit?.kod === "DIGER"} />
          </Form.Item>
          <Form.Item name="sira" label="Sıra">
            <InputNumber min={0} max={999} />
          </Form.Item>
          <Form.Item name="is_active" label="Aktif" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

export default function ServisTanimlarPage() {
  const { yetkili } = useAuth();
  const sekmeler = [
    { key: "ariza", label: "Arıza nedenleri", children: <ArizaNedenleri /> },
    { key: "bekleme", label: "Bekleme nedenleri", children: <BeklemeNedenleri /> },
  ];
  // Menü izni [servis.tanim, operasyon.yonet]; yetkili olunan sekme önce açılır.
  const varsayilan = yetkili("servis.tanim") || !yetkili("operasyon.yonet") ? "ariza" : "bekleme";
  return (
    <Card title="Servis Tanımları">
      <Tabs defaultActiveKey={varsayilan} items={sekmeler} />
    </Card>
  );
}
