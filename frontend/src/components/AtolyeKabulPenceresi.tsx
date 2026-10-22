/**
 * Atölye cihaz kabulü — tek cihaz ya da toplu kabul (TS-090/096/097/100).
 *
 * Sunucu servis işini (ATOLYE) ve atölye kaydını tek transaction'da açar;
 * durum ve kabul zamanı istemciden GÖNDERİLMEZ. Seri girilince
 * `/seri-gecmisi` sorulur: önceki kayıtlar, açık kayıt ve "tekrar geliş"
 * (onarım garantisi olabilir) uyarısı gösterilir — garanti durumu yine
 * sunucuda hesaplanıp dondurulur.
 *
 * 409 `COKLU_EKIPMAN`: aynı seriyle birden çok aktif ekipman var → aday
 * listesinden biri seçilip `ekipman_id` ile yeniden gönderilir.
 * 409 `ACIK_KAYIT`: cihazın açık atölye kaydı var (kapsam içindeyse numarası).
 *
 * Toplu kabulde her cihaz ayrı kayıt + ayrı servis işi olur, ortak kabul
 * grubu numarası ve tek fiş üretilir; bir cihaz hatalıysa hiçbiri açılmaz.
 */
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Col,
  DatePicker,
  Divider,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { useEffect, useState } from "react";

import {
  AtolyeHatasi,
  atolyeApi,
  DURUM_RENKLERI,
  MARKA_ADLARI,
  type AksesuarGirdisi,
  type AtolyeDetay,
  type EkipmanGirdisi,
  type FormVerileri,
  type KabulOrtak,
  type SeriGecmisi,
} from "../api/atolye";
import { TIP_ETIKETLERI } from "../api/servisEkipman";
import MusteriLokasyonSecici, {
  type MusteriLokasyonSecimi,
  type SahaOnerisi,
} from "./MusteriLokasyonSecici";

interface CihazSatiri {
  tip: string;
  marka?: string;
  marka_diger?: string;
  model?: string;
  seri?: string;
  customer_complaint?: string;
  warranty_start?: Dayjs | null;
  warranty_end?: Dayjs | null;
}

interface FormDegeri {
  musteri?: MusteriLokasyonSecimi;
  contact_id?: number | null;
  service_type: string;
  receive_type: string;
  oncelik: string;
  customer_complaint: string;
  physical_condition?: string;
  estimated_finish_date?: Dayjs | null;
  logo_form_no?: string;
  logo_main_service_no?: string;
  integration_company?: string;
  project_name?: string;
  notes?: string;
  cihaz: CihazSatiri;
  cihazlar: CihazSatiri[];
  aksesuarlar: AksesuarGirdisi[];
}

const ONCELIKLER = [
  { value: "DUSUK", label: "Düşük" },
  { value: "NORMAL", label: "Normal" },
  { value: "YUKSEK", label: "Yüksek" },
  { value: "KRITIK", label: "Kritik" },
];

const gun = (d?: Dayjs | null) => (d ? d.format("YYYY-MM-DD") : null);
const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");

function ekipmanGovdesi(c: CihazSatiri): EkipmanGirdisi {
  return {
    tip: c.tip,
    marka: c.marka ?? null,
    marka_diger: c.marka === "DIGER" ? (c.marka_diger ?? null) : null,
    model: c.model || null,
    seri: c.seri || null,
    warranty_start: gun(c.warranty_start),
    warranty_end: gun(c.warranty_end),
  };
}

/** Seri geçmişi özeti (kabul ekranının "bu cihaz daha önce geldi mi" kutusu). */
function SeriGecmisiKutusu({ gecmis }: { gecmis: SeriGecmisi }) {
  if (!gecmis.kayitlar.length) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Bu seriyle önceki atölye kaydı yok.
      </Typography.Text>
    );
  }
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={4}>
      {gecmis.acik_kayit && (
        <Alert
          type="error"
          showIcon
          title={`Bu cihazın açık atölye kaydı var: ${gecmis.acik_kayit.atolye_no}`}
        />
      )}
      {gecmis.tekrar_gelis && (
        <Alert
          type="warning"
          showIcon
          title={`Son ${gecmis.pencere_gun ?? ""} gün içinde onarılarak teslim edilmiş — onarım garantisi olabilir`}
        />
      )}
      <Table
        size="small"
        rowKey="so_id"
        pagination={false}
        dataSource={gecmis.kayitlar.slice(0, 5)}
        columns={[
          { title: "Atölye no", dataIndex: "atolye_no" },
          { title: "Kabul", dataIndex: "received_at", render: tarih },
          {
            title: "Durum",
            dataIndex: "status",
            render: (s: string) => <Tag color={DURUM_RENKLERI[s]}>{s}</Tag>,
          },
          { title: "Arıza", dataIndex: "ariza_nedeni", render: (v) => v ?? "—" },
          { title: "Teslim", dataIndex: "delivered_at", render: tarih },
        ]}
      />
    </Space>
  );
}

function CihazAlanlari({
  ad,
  kok,
  sozluk,
  kompakt,
}: {
  /** Form.Item adı (Form.List içinde göreli). */
  ad: (string | number)[];
  /** İzleme için mutlak yol (Form.List içinde liste adıyla). */
  kok?: (string | number)[];
  sozluk?: FormVerileri;
  kompakt?: boolean;
}) {
  const marka = Form.useWatch([...(kok ?? ad), "marka"]);
  const tipler = sozluk?.ekipman_tipleri ?? ["TELSIZ", "ROLE_TEKRARLAYICI", "TELSIZ_DIGER"];
  const markalar = sozluk?.markalar ?? Object.keys(MARKA_ADLARI);
  return (
    <Row gutter={8}>
      <Col xs={12} md={kompakt ? 4 : 6}>
        <Form.Item name={[...ad, "tip"]} label={kompakt ? undefined : "Tip"} rules={[{ required: true }]}>
          <Select
            placeholder="Tip"
            options={tipler.map((t) => ({ value: t, label: TIP_ETIKETLERI[t] ?? t }))}
          />
        </Form.Item>
      </Col>
      <Col xs={12} md={kompakt ? 4 : 6}>
        <Form.Item
          name={[...ad, "marka"]}
          label={kompakt ? undefined : "Marka"}
          rules={[{ required: true, message: "Marka zorunlu" }]}
        >
          <Select
            placeholder="Marka"
            options={markalar.map((m) => ({ value: m, label: MARKA_ADLARI[m] ?? m }))}
          />
        </Form.Item>
      </Col>
      {marka === "DIGER" && (
        <Col xs={12} md={4}>
          <Form.Item
            name={[...ad, "marka_diger"]}
            label={kompakt ? undefined : "Marka adı"}
            rules={[{ required: true, whitespace: true, message: "Marka adı zorunlu" }]}
          >
            <Input maxLength={60} placeholder="Marka adı" />
          </Form.Item>
        </Col>
      )}
      <Col xs={12} md={kompakt ? 4 : 6}>
        <Form.Item name={[...ad, "model"]} label={kompakt ? undefined : "Model"}>
          <Input maxLength={80} placeholder="Model" />
        </Form.Item>
      </Col>
      <Col xs={12} md={kompakt ? 4 : 6}>
        <Form.Item
          name={[...ad, "seri"]}
          label={kompakt ? undefined : "Seri no"}
          rules={[{ required: true, whitespace: true, message: "Seri numarası zorunlu" }]}
        >
          <Input maxLength={200} placeholder="Seri no" className="mono" />
        </Form.Item>
      </Col>
    </Row>
  );
}

function AksesuarListesi({ sozluk }: { sozluk?: FormVerileri }) {
  const turler = sozluk?.aksesuar_turleri ?? [];
  return (
    <Form.List name="aksesuarlar">
      {(alanlar, { add, remove }) => (
        <Space orientation="vertical" style={{ width: "100%" }} size={0}>
          {alanlar.map(({ key, name }) => (
            <AksesuarSatiri key={key} name={name} turler={turler} sil={() => remove(name)} />
          ))}
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => add({ kind: "BATARYA", qty: 1 })}
          >
            Aksesuar ekle
          </Button>
        </Space>
      )}
    </Form.List>
  );
}

function AksesuarSatiri({
  name,
  turler,
  sil,
}: {
  name: number;
  turler: { kod: string; ad: string }[];
  sil: () => void;
}) {
  const tur = Form.useWatch(["aksesuarlar", name, "kind"]);
  return (
    <Row gutter={8} align="top">
      <Col xs={10} md={7}>
        <Form.Item name={[name, "kind"]} rules={[{ required: true }]}>
          <Select options={turler.map((t) => ({ value: t.kod, label: t.ad }))} />
        </Form.Item>
      </Col>
      <Col xs={5} md={3}>
        <Form.Item name={[name, "qty"]} rules={[{ required: true }]}>
          <InputNumber min={1} max={99} style={{ width: "100%" }} />
        </Form.Item>
      </Col>
      <Col xs={7} md={12}>
        <Form.Item
          name={[name, "description"]}
          rules={[
            {
              required: tur === "DIGER",
              whitespace: true,
              message: "'Diğer' aksesuarda açıklama zorunlu",
            },
          ]}
        >
          <Input maxLength={120} placeholder={tur === "DIGER" ? "Açıklama (zorunlu)" : "Açıklama"} />
        </Form.Item>
      </Col>
      <Col xs={2} md={2}>
        <Button type="text" danger icon={<DeleteOutlined />} onClick={sil} aria-label="Sil" />
      </Col>
    </Row>
  );
}

export default function AtolyeKabulPenceresi({
  acik,
  kapat,
  bitti,
}: {
  acik: boolean;
  kapat: () => void;
  /** Tek kabulde yeni kaydın detayı; toplu kabulde grup numarası ve servis işi kimlikleri. */
  bitti: (sonuc: { detay?: AtolyeDetay; grup?: number; soIdler: number[] }) => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormDegeri>();
  const [mod, setMod] = useState<"TEK" | "TOPLU">("TEK");
  const [irtibatlar, setIrtibatlar] = useState<SahaOnerisi["irtibatlar"]>([]);
  const [adaylar, setAdaylar] = useState<
    { id: number; marka: string | null; model: string | null; seri: string | null; account_id: number | null }[]
  >([]);
  const [hata, setHata] = useState<string | null>(null);

  const sozluk = useQuery({
    queryKey: ["atolye-form-verileri"],
    queryFn: () => atolyeApi.formVerileri(),
    enabled: acik,
    staleTime: 5 * 60_000,
  });

  const tekCihaz = Form.useWatch("cihaz", form);
  const [sorgulananSeri, setSorgulananSeri] = useState<{ tip: string; marka: string; seri: string } | null>(
    null,
  );
  useEffect(() => {
    if (mod !== "TEK") return;
    const seri = tekCihaz?.seri?.trim();
    const marka = tekCihaz?.marka === "DIGER" ? tekCihaz?.marka_diger?.trim() : tekCihaz?.marka;
    if (!seri || !marka || !tekCihaz?.tip) {
      setSorgulananSeri(null);
      return;
    }
    const t = setTimeout(() => setSorgulananSeri({ tip: tekCihaz.tip, marka, seri }), 400);
    return () => clearTimeout(t);
  }, [mod, tekCihaz?.tip, tekCihaz?.marka, tekCihaz?.marka_diger, tekCihaz?.seri]);

  const gecmis = useQuery({
    queryKey: ["atolye-seri-gecmisi", sorgulananSeri],
    queryFn: () => atolyeApi.seriGecmisi(sorgulananSeri!),
    enabled: acik && !!sorgulananSeri,
  });

  useEffect(() => {
    if (acik) {
      form.resetFields();
      setMod("TEK");
      setAdaylar([]);
      setHata(null);
      setIrtibatlar([]);
    }
  }, [acik, form]);

  const gonder = useMutation({
    mutationFn: async (args: { v: FormDegeri; ekipmanId?: number }) => {
      const { v, ekipmanId } = args;
      const ortak: KabulOrtak = {
        customer_id: v.musteri!.musteriId!,
        address_id: v.musteri?.lokasyonId ?? null,
        contact_id: v.contact_id ?? null,
        service_type: v.service_type,
        receive_type: v.receive_type,
        oncelik: v.oncelik,
        customer_complaint: v.customer_complaint,
        physical_condition: v.physical_condition || null,
        estimated_finish_date: gun(v.estimated_finish_date),
        logo_form_no: v.logo_form_no || null,
        logo_main_service_no: v.logo_main_service_no || null,
        integration_company: v.integration_company || null,
        project_name: v.project_name || null,
        notes: v.notes || null,
      };
      const aksesuarlar = (v.aksesuarlar ?? []).map((a) => ({
        kind: a.kind,
        qty: a.qty,
        description: a.description || null,
      }));
      if (mod === "TEK") {
        const ekipman = ekipmanId
          ? { ekipman_id: ekipmanId, tip: v.cihaz.tip }
          : ekipmanGovdesi(v.cihaz);
        const detay = await atolyeApi.kabul({ ...ortak, ekipman, aksesuarlar });
        return { detay, soIdler: [detay.so_id] };
      }
      const r = await atolyeApi.topluKabul({
        ...ortak,
        cihazlar: (v.cihazlar ?? []).map((c) => ({
          ...ekipmanGovdesi(c),
          aksesuarlar,
          customer_complaint: c.customer_complaint || null,
        })),
      });
      return { grup: r.kabul_grubu, soIdler: r.kayitlar.map((k) => k.so_id) };
    },
    onSuccess: (r) => {
      message.success(
        r.detay ? `Kabul edildi: ${r.detay.atolye_no}` : `${r.soIdler.length} cihaz kabul edildi (grup ${r.grup})`,
      );
      bitti(r);
    },
    onError: (e: Error) => {
      if (e instanceof AtolyeHatasi && e.detay?.kod === "COKLU_EKIPMAN") {
        setAdaylar((e.detay.adaylar as typeof adaylar) ?? []);
        setHata(e.message);
        return;
      }
      setHata(e.message);
      message.error(e.message);
    },
  });

  const kaydet = (v: FormDegeri, ekipmanId?: number) => {
    setHata(null);
    if (!v.musteri?.musteriId) {
      message.error("Müşteri seçin");
      return;
    }
    if (mod === "TOPLU" && !(v.cihazlar ?? []).length) {
      message.error("En az bir cihaz girin");
      return;
    }
    gonder.mutate({ v, ekipmanId });
  };

  const s = sozluk.data;

  return (
    <Modal
      title="Atölyeye cihaz kabulü"
      open={acik}
      onCancel={kapat}
      onOk={() => form.submit()}
      okText={mod === "TEK" ? "Kabul et" : "Hepsini kabul et"}
      cancelText="Vazgeç"
      confirmLoading={gonder.isPending}
      width={920}
      destroyOnHidden
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Radio.Group
          value={mod}
          optionType="button"
          onChange={(e) => {
            setMod(e.target.value);
            setAdaylar([]);
            setHata(null);
          }}
          options={[
            { value: "TEK", label: "Tek cihaz" },
            { value: "TOPLU", label: "Toplu kabul (aynı müşteri)" },
          ]}
        />
        {hata && <Alert type="error" showIcon title={hata} />}
        {adaylar.length > 0 && (
          <Alert
            type="warning"
            title="Bu seriyle birden çok aktif ekipman var; kabul edilecek olanı seçin"
            description={
              <List
                size="small"
                dataSource={adaylar}
                renderItem={(a) => (
                  <List.Item
                    actions={[
                      <Button
                        key="sec"
                        size="small"
                        onClick={() => kaydet(form.getFieldsValue(true) as FormDegeri, a.id)}
                      >
                        Bunu seç
                      </Button>,
                    ]}
                  >
                    #{a.id} · {[a.marka, a.model].filter(Boolean).join(" ")} · {a.seri}
                    {a.account_id ? ` · hesap ${a.account_id}` : ""}
                  </List.Item>
                )}
              />
            }
          />
        )}
        <Form<FormDegeri>
          form={form}
          layout="vertical"
          onFinish={(v) => kaydet(v)}
          initialValues={{
            service_type: "ARIZA_ONARIMI",
            receive_type: "ELDEN",
            oncelik: "NORMAL",
            cihaz: { tip: "TELSIZ" },
            cihazlar: [{ tip: "TELSIZ" }],
            aksesuarlar: [],
          }}
        >
          <Form.Item
            name="musteri"
            label="Müşteri / lokasyon"
            rules={[{ required: true, message: "Müşteri seçin" }]}
          >
            <MusteriLokasyonSecici
              onSahaOnerisi={(o) => {
                setIrtibatlar(o?.irtibatlar ?? (o?.irtibat ? [{ ...o.irtibat, unvan: null }] : []));
                form.setFieldValue("contact_id", o?.irtibat?.id ?? null);
              }}
            />
          </Form.Item>
          <Row gutter={8}>
            <Col xs={24} md={6}>
              <Form.Item name="contact_id" label="İrtibat">
                <Select
                  allowClear
                  placeholder="Lokasyon irtibatı"
                  options={(irtibatlar ?? []).map((i) => ({ value: i.id, label: i.ad }))}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="service_type" label="Servis türü" rules={[{ required: true }]}>
                <Select options={(s?.servis_turleri ?? []).map((t) => ({ value: t.kod, label: t.ad }))} />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="receive_type" label="Geliş şekli" rules={[{ required: true }]}>
                <Select options={(s?.teslim_tipleri ?? []).map((t) => ({ value: t.kod, label: t.ad }))} />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="oncelik" label="Öncelik">
                <Select options={ONCELIKLER} />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="estimated_finish_date" label="Tahmini bitiş">
                <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="customer_complaint"
            label={mod === "TEK" ? "Müşteri şikâyeti" : "Ortak şikâyet (cihazda ayrıca yazılmazsa)"}
            rules={[{ required: true, whitespace: true, min: 3, message: "En az 3 karakter" }]}
          >
            <Input.TextArea rows={2} maxLength={4000} />
          </Form.Item>
          <Form.Item name="physical_condition" label="Fiziksel durum">
            <Input.TextArea rows={1} maxLength={2000} placeholder="Çizik, kırık, eksik parça…" />
          </Form.Item>

          <Divider titlePlacement="start" style={{ margin: "8px 0" }}>
            {mod === "TEK" ? "Cihaz" : "Cihazlar"}
          </Divider>
          {mod === "TEK" ? (
            <>
              <CihazAlanlari ad={["cihaz"]} sozluk={s} />
              <Row gutter={8}>
                <Col xs={12} md={6}>
                  <Form.Item
                    name={["cihaz", "warranty_start"]}
                    label="Garanti başlangıcı"
                    tooltip="Yalnız kütükte olmayan, yeni açılan ekipmana yazılır"
                  >
                    <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item
                    name={["cihaz", "warranty_end"]}
                    label="Garanti bitişi"
                    tooltip="Boşsa garanti durumu 'Belirsiz' olur; sunucu kabulde hesaplayıp dondurur"
                  >
                    <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
              {gecmis.data && <SeriGecmisiKutusu gecmis={gecmis.data} />}
            </>
          ) : (
            <Form.List name="cihazlar">
              {(alanlar, { add, remove }) => (
                <Space orientation="vertical" style={{ width: "100%" }} size={0}>
                  {alanlar.map(({ key, name }, i) => (
                    <Row key={key} gutter={8} align="top">
                      <Col flex="28px" style={{ paddingTop: 6 }}>
                        <Typography.Text type="secondary">{i + 1}.</Typography.Text>
                      </Col>
                      <Col flex="auto">
                        <CihazAlanlari ad={[name]} kok={["cihazlar", name]} sozluk={s} kompakt />
                        <Form.Item name={[name, "customer_complaint"]} style={{ marginTop: -16 }}>
                          <Input maxLength={4000} placeholder="Bu cihaza özel şikâyet (isteğe bağlı)" />
                        </Form.Item>
                      </Col>
                      <Col flex="32px">
                        <Button
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          aria-label="Cihazı çıkar"
                          disabled={alanlar.length === 1}
                          onClick={() => remove(name)}
                        />
                      </Col>
                    </Row>
                  ))}
                  <Button
                    size="small"
                    icon={<PlusOutlined />}
                    disabled={alanlar.length >= 100}
                    onClick={() => add({ tip: "TELSIZ" })}
                  >
                    Cihaz ekle
                  </Button>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Her cihaz ayrı atölye kaydı ve ayrı servis işi olur; ortak kabul grubu numarası
                    ve tek kabul fişi üretilir. Bir cihazda hata varsa hiçbiri kabul edilmez.
                  </Typography.Text>
                </Space>
              )}
            </Form.List>
          )}

          <Divider titlePlacement="start" style={{ margin: "8px 0" }}>
            Aksesuarlar{mod === "TOPLU" ? " (her cihaz için)" : ""}
          </Divider>
          <AksesuarListesi sozluk={s} />

          <Divider titlePlacement="start" style={{ margin: "8px 0" }}>
            Ek bilgiler
          </Divider>
          <Row gutter={8}>
            <Col xs={12} md={6}>
              <Form.Item name="logo_form_no" label="Logo form no">
                <Input maxLength={80} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="logo_main_service_no" label="Logo ana servis no">
                <Input maxLength={80} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="integration_company" label="Entegratör firma">
                <Input maxLength={150} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item name="project_name" label="Proje">
                <Input maxLength={150} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={1} maxLength={4000} />
          </Form.Item>
        </Form>
      </Space>
    </Modal>
  );
}
