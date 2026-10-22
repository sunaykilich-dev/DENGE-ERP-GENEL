/**
 * Atölye (TS-090…101) — haberleşme/telsiz cihaz kabulü, teşhis, onarım, test,
 * müşteri onayı, dış servis, teslim/kargo.
 *
 * Tek karar: 1 atölye kaydı = 1 cihaz = 1 servis işi. Ekran bağlantısı
 * `/atolye/{so_id}` servis işi kimliğini taşır. Liste sunucuda süzülür ve
 * sayfalanır (`X-Toplam-Kayit`); KPI kutularının sayısı, tıklanınca açılan
 * listenin toplamıyla aynı sorgudan gelir (sayı = liste). Excel ekrandaki
 * süzgeci aynen alır.
 *
 * Durum yalnız durum penceresinden değişir; seçenekler ve engel metinleri
 * sunucudan gelir. Tamir bedeli yalnız `maliyet.gor` sahibine gösterilir
 * (anahtar yoksa alan hiç çizilmez). Parça ve süre bölümü salt okunurdur.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Grid,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Timeline,
  Tooltip,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  atolyeApi,
  DURUM_RENKLERI,
  GARANTI_RENKLERI,
  ONAY_KANALI_ADLARI,
  ONAY_KARARI_ADLARI,
  TEST_ADLARI,
  type AksesuarGirdisi,
  type AtolyeDetay,
  type AtolyeSatiri,
  type AtolyeSuzgeci,
  type FormVerileri,
  type SonrakiDurum,
} from "../api/atolye";
import { api } from "../api/client";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI, personelApi } from "../api/personel";
import { TIP_ETIKETLERI } from "../api/servisEkipman";
import { useAuth } from "../auth/AuthContext";
import AtolyeDurumPenceresi from "../components/AtolyeDurumPenceresi";
import AtolyeKabulPenceresi from "../components/AtolyeKabulPenceresi";
import EkYukleyici from "../components/EkYukleyici";
import KpiKutusu from "../components/KpiKutusu";
import ServisParcalari from "../components/ServisParcalari";

const SAYFA_BOYU = 50;
/** Toplu atamanın başlangıç ekibi (sabit referans: pencere her çizimde sıfırlanmasın). */
const BOS_EKIP: { id: number; lead: boolean }[] = [];

const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");
const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");
const dk = (n: number) => `${Math.floor(n / 60)} sa ${n % 60} dk`;

function suzgecOku(p: URLSearchParams): AtolyeSuzgeci {
  const sayi = (k: string) => (p.get(k) ? Number(p.get(k)) : undefined);
  return {
    q: p.get("q") ?? undefined,
    durum: p.get("durum") ?? undefined,
    durum_grubu: p.get("durum_grubu") ?? undefined,
    birim: p.get("birim") ?? undefined,
    marka: p.get("marka") ?? undefined,
    servis_turu: p.get("servis_turu") ?? undefined,
    yas: p.get("yas") ?? undefined,
    geciken: p.get("geciken") === "true" ? true : undefined,
    teknisyen_id: sayi("teknisyen_id"),
    kabul_grubu: sayi("kabul_grubu"),
    musteri_id: sayi("musteri_id"),
  };
}

function suzgecYaz(s: AtolyeSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  return p;
}

/** KPI kutusunun açtığı liste: taban süzgeç + kutunun kendi süzgeci (sunucunun `sorgu`'su). */
function kpiYolu(taban: AtolyeSuzgeci, sorgu: Record<string, unknown>): string {
  const s: AtolyeSuzgeci = { ...taban, durum: undefined, durum_grubu: undefined, yas: undefined, geciken: undefined };
  const durum = Array.isArray(sorgu.durum) ? String(sorgu.durum[0]) : undefined;
  const p = suzgecYaz({
    ...s,
    durum,
    durum_grubu: sorgu.durum_grubu as string | undefined,
    yas: sorgu.yas as string | undefined,
    geciken: (sorgu.geciken as boolean | undefined) || undefined,
  });
  return `/atolye?${p}`;
}

function DurumEtiketi({ kod, sozluk }: { kod: string; sozluk?: FormVerileri }) {
  return <Tag color={DURUM_RENKLERI[kod]}>{sozluk?.durumlar.find((d) => d.kod === kod)?.ad ?? kod}</Tag>;
}

function GarantiEtiketi({ kod, sozluk }: { kod: string; sozluk?: FormVerileri }) {
  return (
    <Tag color={GARANTI_RENKLERI[kod]}>{sozluk?.garanti_durumlari.find((d) => d.kod === kod)?.ad ?? kod}</Tag>
  );
}

// --- Atama ------------------------------------------------------------------------------

function AtamaPenceresi({
  soIdler,
  birim,
  mevcut,
  acik,
  kapat,
  bitti,
}: {
  soIdler: number[];
  birim: string;
  mevcut: { id: number; lead: boolean }[];
  acik: boolean;
  kapat: () => void;
  bitti: () => void;
}) {
  const { message } = App.useApp();
  const toplu = soIdler.length > 1;
  const [kisiler, setKisiler] = useState<number[]>([]);
  const [sorumlu, setSorumlu] = useState<number | undefined>();
  const [mod, setMod] = useState<"EKLE" | "DEGISTIR">("DEGISTIR");
  const aday = useQuery({
    queryKey: ["atanabilir", birim],
    queryFn: () => personelApi.atanabilir(birim),
    enabled: acik && !!birim,
  });

  useEffect(() => {
    if (acik) {
      setKisiler(mevcut.map((m) => m.id));
      setSorumlu(mevcut.find((m) => m.lead)?.id);
      setMod("DEGISTIR");
    }
  }, [acik, mevcut]);

  const rolu = (id: number): "SEF" | "TEKNISYEN" =>
    aday.data?.find((k) => k.id === id)?.saha_rolu === "SEF" ? "SEF" : "TEKNISYEN";

  const kaydet = useMutation({
    mutationFn: () => {
      const satirlar = kisiler.map((id) => ({ user_id: id, rol: rolu(id), is_lead: id === sorumlu }));
      return toplu
        ? atolyeApi.topluAta(soIdler, satirlar, mod).then(() => undefined)
        : atolyeApi.ata(soIdler[0], satirlar).then(() => undefined);
    },
    onSuccess: () => {
      message.success(toplu ? `${soIdler.length} kaydın ekibi güncellendi` : "Ekip güncellendi");
      bitti();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const secenekler = (aday.data ?? []).map((k) => ({
    value: k.id,
    label: `${k.ad}${k.giris_acik ? "" : " (girişsiz)"} · ${k.saha_rolu}`,
  }));

  return (
    <Modal
      title={toplu ? `Toplu atama (${soIdler.length} kayıt)` : "Usta / ekip ataması"}
      open={acik}
      onCancel={kapat}
      onOk={() => kaydet.mutate()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Atama servis işine yazılır (tek atama kaynağı). Hepsi ya da hiçbiri: seçilenlerden biri
          atanamıyorsa hiçbiri değişmez.
        </Typography.Text>
        {toplu && (
          <Radio.Group
            value={mod}
            onChange={(e) => setMod(e.target.value)}
            options={[
              { value: "DEGISTIR", label: "Ekibi bununla değiştir" },
              { value: "EKLE", label: "Mevcut ekibe ekle" },
            ]}
          />
        )}
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          placeholder="Personel seçin"
          loading={aday.isFetching}
          value={kisiler}
          onChange={(v) => {
            setKisiler(v);
            if (sorumlu && !v.includes(sorumlu)) setSorumlu(undefined);
          }}
          options={secenekler}
          optionFilterProp="label"
        />
        <Select
          allowClear
          style={{ width: "100%" }}
          placeholder="Sorumlu usta"
          value={sorumlu}
          onChange={setSorumlu}
          options={secenekler.filter((s) => kisiler.includes(s.value) && rolu(s.value) === "TEKNISYEN")}
        />
      </Space>
    </Modal>
  );
}

// --- Kayıt bilgileri formu (PATCH) ------------------------------------------------------

interface BilgiFormu {
  fault_reason_id?: number | null;
  is_repairable?: boolean | null;
  diagnosis_note?: string | null;
  repair_category?: string | null;
  repair_note?: string | null;
  test_result?: string | null;
  approval_decision?: string | null;
  approval_channel?: string | null;
  approved_by_name?: string | null;
  approval_note?: string | null;
  repair_amount?: number | null;
  external_vendor_id?: number | null;
  external_rma_no?: string | null;
  external_sent_at?: Dayjs | null;
  external_returned_at?: Dayjs | null;
  estimated_finish_date?: Dayjs | null;
  physical_condition?: string | null;
  notes?: string | null;
}

const TARIH_ALANLARI = ["external_sent_at", "external_returned_at", "estimated_finish_date"] as const;

function bilgiDegerleri(d: AtolyeDetay): BilgiFormu {
  return {
    fault_reason_id: d.fault_reason_id,
    is_repairable: d.is_repairable,
    diagnosis_note: d.diagnosis_note,
    repair_category: d.repair_category,
    repair_note: d.repair_note,
    test_result: d.test_result,
    approval_decision: d.approval_decision,
    approval_channel: d.approval_channel,
    approved_by_name: d.approved_by_name,
    approval_note: d.approval_note,
    repair_amount: "repair_amount" in d && d.repair_amount != null ? Number(d.repair_amount) : null,
    external_vendor_id: d.external_vendor?.id ?? null,
    external_rma_no: d.external_rma_no,
    external_sent_at: d.external_sent_at ? dayjs(d.external_sent_at) : null,
    external_returned_at: d.external_returned_at ? dayjs(d.external_returned_at) : null,
    estimated_finish_date: d.estimated_finish_date ? dayjs(d.estimated_finish_date) : null,
    physical_condition: d.physical_condition,
    notes: d.notes,
  };
}

function KayitBilgileri({
  d,
  sozluk,
  yazabilir,
  bedelGorur,
  guncellendi,
}: {
  d: AtolyeDetay;
  sozluk?: FormVerileri;
  yazabilir: boolean;
  bedelGorur: boolean;
  guncellendi: (d: AtolyeDetay) => void;
}) {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const [form] = Form.useForm<BilgiFormu>();
  const kapali = !d.acik;
  const duzenlenebilir = yazabilir && !kapali;
  const tedarikciler = useQuery({
    queryKey: ["hesaplar-tedarikci"],
    queryFn: () => api.get<{ id: number; title: string }[]>("/api/hesaplar?rol=TEDARIKCI&limit=200"),
    enabled: duzenlenebilir && yetkili("hesap.gor"),
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    form.setFieldsValue(bilgiDegerleri(d));
  }, [d, form]);

  const kaydet = useMutation({
    mutationFn: (v: BilgiFormu) => {
      const eski = bilgiDegerleri(d) as Record<string, unknown>;
      const govde: Record<string, unknown> = {};
      for (const [k, deger] of Object.entries(v)) {
        let yeni: unknown = deger;
        if ((TARIH_ALANLARI as readonly string[]).includes(k)) {
          yeni = deger ? (deger as Dayjs).format("YYYY-MM-DD") : null;
          const e = eski[k] as Dayjs | null;
          if ((e ? e.format("YYYY-MM-DD") : null) === yeni) continue;
        } else if ((eski[k] ?? null) === (yeni ?? null)) {
          continue;
        }
        if (yeni === "") yeni = null;
        govde[k] = yeni;
      }
      if (!bedelGorur) delete govde.repair_amount;
      return atolyeApi.guncelle(d.so_id, { version: d.version, ...govde });
    },
    onSuccess: (yeni) => {
      message.success("Kaydedildi");
      guncellendi(yeni);
    },
    onError: (e: Error) => message.error(e.message),
  });

  const tedarikciSecenek = [
    ...(d.external_vendor ? [{ value: d.external_vendor.id, label: d.external_vendor.title }] : []),
    ...(tedarikciler.data ?? [])
      .filter((t) => t.id !== d.external_vendor?.id)
      .map((t) => ({ value: t.id, label: t.title })),
  ];

  return (
    <Form<BilgiFormu>
      form={form}
      layout="vertical"
      disabled={!duzenlenebilir}
      onFinish={(v) => kaydet.mutate(v)}
    >
      <Typography.Title level={5}>Teşhis</Typography.Title>
      <Row gutter={8}>
        <Col xs={24} md={12}>
          <Form.Item name="fault_reason_id" label="Arıza nedeni">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={(sozluk?.ariza_nedenleri ?? []).map((n) => ({ value: n.id, label: n.ad }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="is_repairable" label="Onarılabilir mi?">
            <Radio.Group
              options={[
                { value: true, label: "Evet" },
                { value: false, label: "Hayır" },
              ]}
            />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="diagnosis_note" label="Teşhis notu">
        <Input.TextArea rows={2} maxLength={4000} />
      </Form.Item>
      {d.diagnosed_at && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Teşhis: {d.diagnosed_by ?? "—"} · {zaman(d.diagnosed_at)}
        </Typography.Text>
      )}

      <Typography.Title level={5} style={{ marginTop: 12 }}>
        Müşteri onayı
      </Typography.Title>
      <Row gutter={8}>
        <Col xs={12} md={6}>
          <Form.Item name="approval_decision" label="Karar">
            <Select
              allowClear
              options={(sozluk?.onay_kararlari ?? []).map((k) => ({ value: k, label: ONAY_KARARI_ADLARI[k] ?? k }))}
            />
          </Form.Item>
        </Col>
        <Col xs={12} md={6}>
          <Form.Item name="approval_channel" label="Kanal">
            <Select
              allowClear
              options={(sozluk?.onay_kanallari ?? []).map((k) => ({ value: k, label: ONAY_KANALI_ADLARI[k] ?? k }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="approved_by_name" label="Onaylayan" tooltip="Kişisel veri: olay geçmişine yazılmaz">
            <Input maxLength={120} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item
        name="approval_note"
        label="Onay notu"
        tooltip="'Onay gerekmez' kararında gerekçe olarak zorunludur"
      >
        <Input.TextArea rows={1} maxLength={2000} />
      </Form.Item>
      {d.teklifler.length > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Bağlı teklifler: {d.teklifler.map((t) => `${t.quote_no} (${t.status})`).join(", ")} — kabul
          edilmiş teklif onay sayılır.
        </Typography.Text>
      )}
      {bedelGorur && (
        <Form.Item name="repair_amount" label="Tamir bedeli (₺)" style={{ marginTop: 8 }}>
          <InputNumber min={0} precision={2} style={{ width: 200 }} />
        </Form.Item>
      )}

      <Typography.Title level={5} style={{ marginTop: 12 }}>
        Onarım ve test
      </Typography.Title>
      <Row gutter={8}>
        <Col xs={24} md={12}>
          <Form.Item name="repair_category" label="Onarım kategorisi">
            <Select
              allowClear
              options={(sozluk?.onarim_kategorileri ?? []).map((k) => ({ value: k.kod, label: k.ad }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="test_result" label="Test sonucu">
            <Select
              allowClear
              options={(sozluk?.test_sonuclari ?? []).map((k) => ({ value: k, label: TEST_ADLARI[k] ?? k }))}
            />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="repair_note" label="Yapılan işlem">
        <Input.TextArea rows={2} maxLength={4000} />
      </Form.Item>
      {d.tested_at && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Test: {d.tested_by ?? "—"} · {zaman(d.tested_at)}
        </Typography.Text>
      )}

      <Typography.Title level={5} style={{ marginTop: 12 }}>
        Dış servis
      </Typography.Title>
      <Row gutter={8}>
        <Col xs={24} md={12}>
          <Form.Item name="external_vendor_id" label="Firma">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={tedarikciSecenek}
              placeholder={yetkili("hesap.gor") ? "Tedarikçi seçin" : "Hesap görme yetkisi gerekir"}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="external_rma_no" label="Dış servis RMA no">
            <Input maxLength={60} />
          </Form.Item>
        </Col>
        <Col xs={12} md={12}>
          <Form.Item name="external_sent_at" label="Gönderim">
            <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col xs={12} md={12}>
          <Form.Item name="external_returned_at" label="Dönüş">
            <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
          </Form.Item>
        </Col>
      </Row>

      <Typography.Title level={5} style={{ marginTop: 12 }}>
        Genel
      </Typography.Title>
      <Row gutter={8}>
        <Col xs={12} md={8}>
          <Form.Item name="estimated_finish_date" label="Tahmini bitiş">
            <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={16}>
          <Form.Item name="physical_condition" label="Fiziksel durum">
            <Input maxLength={2000} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="notes" label="Not">
        <Input.TextArea rows={2} maxLength={4000} />
      </Form.Item>
      {duzenlenebilir && (
        <Button type="primary" htmlType="submit" loading={kaydet.isPending}>
          Kaydet
        </Button>
      )}
      {kapali && <Alert type="info" showIcon title="Teslim edilmiş ya da iptal edilmiş kayıt düzeltilemez" />}
    </Form>
  );
}

// --- Aksesuarlar ---------------------------------------------------------------------------

function Aksesuarlar({
  d,
  sozluk,
  yazabilir,
  guncellendi,
}: {
  d: AtolyeDetay;
  sozluk?: FormVerileri;
  yazabilir: boolean;
  guncellendi: (d: AtolyeDetay) => void;
}) {
  const { message } = App.useApp();
  const [duzenle, setDuzenle] = useState(false);
  const [form] = Form.useForm<{ aksesuarlar: AksesuarGirdisi[] }>();
  const ad = (k: string) => sozluk?.aksesuar_turleri.find((t) => t.kod === k)?.ad ?? k;

  const kaydet = useMutation({
    mutationFn: (v: { aksesuarlar: AksesuarGirdisi[] }) =>
      atolyeApi.aksesuarlar(
        d.so_id,
        d.version,
        (v.aksesuarlar ?? []).map((a) => ({ kind: a.kind, qty: a.qty, description: a.description || null })),
      ),
    onSuccess: (yeni) => {
      message.success("Aksesuar listesi güncellendi");
      setDuzenle(false);
      guncellendi(yeni);
    },
    onError: (e: Error) => message.error(e.message),
  });

  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={d.aksesuarlar}
        locale={{ emptyText: "Kabulde aksesuar alınmadı" }}
        columns={[
          { title: "Aksesuar", dataIndex: "kind", render: ad },
          { title: "Açıklama", dataIndex: "description", render: (v) => v ?? "—" },
          { title: "Adet", dataIndex: "qty", width: 60 },
          {
            title: "Teslimde",
            dataIndex: "returned",
            width: 110,
            render: (r: boolean | null, a) =>
              r === null ? (
                "—"
              ) : r ? (
                <Tag color="green">İade edildi</Tag>
              ) : (
                <Tooltip title={a.return_note}>
                  <Tag color="red">Eksik</Tag>
                </Tooltip>
              ),
          },
        ]}
      />
      {yazabilir && d.acik && !duzenle && (
        <Button
          size="small"
          onClick={() => {
            form.setFieldsValue({
              aksesuarlar: d.aksesuarlar.map((a) => ({ kind: a.kind, qty: a.qty, description: a.description })),
            });
            setDuzenle(true);
          }}
        >
          Listeyi düzenle
        </Button>
      )}
      {duzenle && (
        <Form form={form} layout="vertical" onFinish={(v) => kaydet.mutate(v)}>
          <Form.List name="aksesuarlar">
            {(alanlar, { add, remove }) => (
              <>
                {alanlar.map(({ key, name }) => (
                  <Row key={key} gutter={8}>
                    <Col span={8}>
                      <Form.Item name={[name, "kind"]} rules={[{ required: true }]}>
                        <Select options={(sozluk?.aksesuar_turleri ?? []).map((t) => ({ value: t.kod, label: t.ad }))} />
                      </Form.Item>
                    </Col>
                    <Col span={4}>
                      <Form.Item name={[name, "qty"]} rules={[{ required: true }]}>
                        <InputNumber min={1} max={99} style={{ width: "100%" }} />
                      </Form.Item>
                    </Col>
                    <Col span={9}>
                      <Form.Item
                        name={[name, "description"]}
                        dependencies={[["aksesuarlar", name, "kind"]]}
                        rules={[
                          ({ getFieldValue }) => ({
                            validator: (_, v) =>
                              getFieldValue(["aksesuarlar", name, "kind"]) === "DIGER" && !String(v ?? "").trim()
                                ? Promise.reject(new Error("'Diğer' aksesuarda açıklama zorunlu"))
                                : Promise.resolve(),
                          }),
                        ]}
                      >
                        <Input maxLength={120} placeholder="Açıklama" />
                      </Form.Item>
                    </Col>
                    <Col span={3}>
                      <Button danger type="text" onClick={() => remove(name)}>
                        Sil
                      </Button>
                    </Col>
                  </Row>
                ))}
                <Button size="small" onClick={() => add({ kind: "BATARYA", qty: 1 })}>
                  Satır ekle
                </Button>
              </>
            )}
          </Form.List>
          <Space style={{ marginTop: 8 }}>
            <Button type="primary" htmlType="submit" loading={kaydet.isPending}>
              Kaydet
            </Button>
            <Button onClick={() => setDuzenle(false)}>Vazgeç</Button>
          </Space>
        </Form>
      )}
    </Space>
  );
}

// --- Ekipman düzeltme ------------------------------------------------------------------------

function EkipmanDuzeltPenceresi({
  d,
  acik,
  kapat,
  bitti,
}: {
  d: AtolyeDetay;
  acik: boolean;
  kapat: () => void;
  bitti: (d: AtolyeDetay) => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<{ marka?: string; model?: string; seri?: string; gerekce: string }>();
  useEffect(() => {
    if (acik) form.setFieldsValue({ marka: d.ekipman.marka ?? "", model: d.ekipman.model ?? "", seri: d.ekipman.seri ?? "", gerekce: "" });
  }, [acik, d, form]);
  const kaydet = useMutation({
    mutationFn: (v: { marka?: string; model?: string; seri?: string; gerekce: string }) =>
      atolyeApi.ekipmanDuzelt(d.so_id, v),
    onSuccess: (yeni) => {
      message.success("Cihaz bilgisi düzeltildi");
      bitti(yeni);
    },
    onError: (e: Error) => message.error(e.message),
  });
  return (
    <Modal
      title="Cihaz bilgisini düzelt"
      open={acik}
      onCancel={kapat}
      onOk={() => form.submit()}
      okText="Düzelt"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Seri/marka/model tek kaynakta (ekipman kütüğü) düzeltilir; servis işinin seri satırı da
        güncellenir ve servis işi geçmişine gerekçesiyle yazılır.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={(v) => kaydet.mutate(v)}>
        <Form.Item name="marka" label="Marka">
          <Input maxLength={60} />
        </Form.Item>
        <Form.Item name="model" label="Model">
          <Input maxLength={80} />
        </Form.Item>
        <Form.Item name="seri" label="Seri no" rules={[{ required: true, whitespace: true }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, min: 5 }]}>
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// --- Detay -----------------------------------------------------------------------------------

function AtolyeDetayi({
  soId,
  sozluk,
  kapat,
  degisti,
}: {
  soId: number;
  sozluk?: FormVerileri;
  kapat: () => void;
  degisti: () => void;
}) {
  const { yetkili, kullanici } = useAuth();
  const qc = useQueryClient();
  const ekran = Grid.useBreakpoint();
  const [hedef, setHedef] = useState<SonrakiDurum | null>(null);
  const [atamaAcik, setAtamaAcik] = useState(false);
  const [ekipmanAcik, setEkipmanAcik] = useState(false);
  const yazabilir = yetkili("atolye.yaz");
  const atayabilir = yetkili("atolye.yaz", "servis.planla");
  const bedelGorur = !!kullanici?.sees_cost;

  const detay = useQuery({ queryKey: ["atolye-detay", soId], queryFn: () => atolyeApi.getir(soId) });
  const d = detay.data;
  const mevcutEkip = useMemo(
    () => (d?.ekip ?? []).map((e) => ({ id: e.id, lead: d?.sorumlu?.id === e.id })),
    [d],
  );
  const seriGecmisi = useQuery({
    queryKey: ["atolye-seri-gecmisi-ekipman", d?.ekipman.id],
    queryFn: () => atolyeApi.seriGecmisi({ ekipman_id: d!.ekipman.id }),
    enabled: !!d,
  });

  const guncellendi = (yeni: AtolyeDetay) => {
    qc.setQueryData(["atolye-detay", soId], yeni);
    void qc.invalidateQueries({ queryKey: ["atolye-seri-gecmisi-ekipman"] });
    degisti();
  };

  const genislik = ekran.md ? 820 : "100%";
  if (detay.isError) {
    return (
      <Drawer open onClose={kapat} title="Atölye kaydı" width={genislik}>
        <Empty description={(detay.error as Error).message} />
      </Drawer>
    );
  }

  return (
    <Drawer
      open
      onClose={kapat}
      width={genislik}
      loading={detay.isLoading}
      title={
        d ? (
          <Space wrap size={4}>
            <Typography.Text strong copyable>
              {d.atolye_no}
            </Typography.Text>
            <DurumEtiketi kod={d.status} sozluk={sozluk} />
            <GarantiEtiketi kod={d.warranty_status} sozluk={sozluk} />
            {d.geciken && <Tag color="red">Gecikmiş</Tag>}
            {d.tekrar_gelis && <Tag color="orange">Tekrar geliş</Tag>}
          </Space>
        ) : (
          "Atölye kaydı"
        )
      }
      extra={
        d && (
          <Space wrap>
            <Dropdown
              menu={{
                items: [
                  { key: "kabul", label: "Kabul fişi (PDF)" },
                  { key: "teslim", label: "Teslim tutanağı (PDF)", disabled: !d.delivered_at && d.status !== "KARGOYA_VERILDI" },
                  ...(d.intake_group_no ? [{ key: "grup", label: `Grup fişi (${d.intake_group_no})` }] : []),
                ],
                onClick: ({ key }) =>
                  window.open(
                    key === "kabul"
                      ? atolyeApi.kabulFisiYolu(d.so_id)
                      : key === "teslim"
                        ? atolyeApi.teslimTutanagiYolu(d.so_id)
                        : atolyeApi.grupFisiYolu(d.intake_group_no!),
                    "_blank",
                  ),
              }}
            >
              <Button>Belgeler</Button>
            </Dropdown>
          </Space>
        )
      }
    >
      {d && (
        <Space orientation="vertical" style={{ width: "100%" }}>
          {d.bekleme && (
            <Alert
              type="warning"
              showIcon
              title={`Servis işi beklemede: ${d.bekleme.neden_adi} (${zaman(d.bekleme.started_at)})`}
            />
          )}
          {yazabilir && d.sonraki_durumlar.length > 0 && (
            <Space wrap>
              {d.sonraki_durumlar.map((s) => (
                <Tooltip
                  key={s.hedef}
                  title={!s.yetkili ? "Bu geçiş için yetkiniz yok (servis.kapat)" : s.engel || undefined}
                >
                  <Button
                    size="small"
                    danger={s.hedef === "IPTAL"}
                    type={s.geri_alma || s.hedef === "IPTAL" ? "default" : "primary"}
                    ghost={!s.geri_alma && s.hedef !== "IPTAL"}
                    disabled={!s.yetkili || !!s.engel}
                    onClick={() => setHedef(s)}
                  >
                    {s.geri_alma ? `Geri al: ${s.ad}` : s.ad}
                  </Button>
                </Tooltip>
              ))}
            </Space>
          )}
          <Tabs
            items={[
              {
                key: "genel",
                label: "Genel",
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
                      <Descriptions.Item label="Servis işi">
                        <Link to={`/servis-isleri/${d.so_id}`}>{d.so_no}</Link>
                      </Descriptions.Item>
                      <Descriptions.Item label="Birim">{BIRIM_ETIKETLERI[d.birim] ?? d.birim}</Descriptions.Item>
                      <Descriptions.Item label="Müşteri" span={2}>
                        {d.musteri?.title ?? "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label="Cihaz" span={2}>
                        <Space wrap size={4}>
                          {TIP_ETIKETLERI[d.ekipman.tip] ?? d.ekipman.tip}
                          {[d.ekipman.marka, d.ekipman.model].filter(Boolean).join(" ")}
                          <Typography.Text className="mono" copyable>
                            {d.ekipman.seri}
                          </Typography.Text>
                          <Link to={`/servis-ekipman/${d.ekipman.id}`}>kütük</Link>
                          {yazabilir && (
                            <Button size="small" type="link" onClick={() => setEkipmanAcik(true)}>
                              düzelt
                            </Button>
                          )}
                        </Space>
                      </Descriptions.Item>
                      <Descriptions.Item label="Servis türü">
                        {sozluk?.servis_turleri.find((t) => t.kod === d.service_type)?.ad ?? d.service_type}
                      </Descriptions.Item>
                      <Descriptions.Item label="Geliş">
                        {sozluk?.teslim_tipleri.find((t) => t.kod === d.receive_type)?.ad ?? d.receive_type}
                      </Descriptions.Item>
                      <Descriptions.Item label="Kabul">
                        {zaman(d.received_at)} · {d.received_by.ad ?? "—"}
                      </Descriptions.Item>
                      <Descriptions.Item label="Bekleme">{d.bekleme_gunu} gün</Descriptions.Item>
                      <Descriptions.Item label="Garanti">
                        <GarantiEtiketi kod={d.warranty_status} sozluk={sozluk} />
                        {d.warranty_end_snapshot && ` bitiş ${tarih(d.warranty_end_snapshot)}`}
                      </Descriptions.Item>
                      <Descriptions.Item label="Tahmini bitiş">{tarih(d.estimated_finish_date)}</Descriptions.Item>
                      <Descriptions.Item label="Şikâyet" span={2}>
                        <Typography.Paragraph style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                          {d.customer_complaint}
                        </Typography.Paragraph>
                      </Descriptions.Item>
                      <Descriptions.Item label="Ekip" span={2}>
                        <Space wrap size={4}>
                          {d.ekip.length
                            ? d.ekip.map((e) => (
                                <Tag key={e.id} color={d.sorumlu?.id === e.id ? "blue" : undefined}>
                                  {e.ad}
                                  {d.sorumlu?.id === e.id ? " (sorumlu)" : ""}
                                </Tag>
                              ))
                            : "—"}
                          {atayabilir && d.acik && (
                            <Button size="small" type="link" onClick={() => setAtamaAcik(true)}>
                              ata
                            </Button>
                          )}
                        </Space>
                      </Descriptions.Item>
                      {d.intake_group_no && (
                        <Descriptions.Item label="Kabul grubu">
                          <Link to={`/atolye?kabul_grubu=${d.intake_group_no}`}>{d.intake_group_no}</Link>
                        </Descriptions.Item>
                      )}
                      {d.sonuc && (
                        <Descriptions.Item label="Sonuç">
                          {d.sonuc.sonuc} · {d.sonuc.cozum_kanali}
                        </Descriptions.Item>
                      )}
                      {(d.delivered_at || d.cargo_sent_at) && (
                        <Descriptions.Item label="Teslim" span={2}>
                          {d.delivery_type ?? "—"}
                          {d.cargo_company && ` · ${d.cargo_company} ${d.cargo_tracking_no ?? ""}`}
                          {d.delivered_at && ` · ${zaman(d.delivered_at)} · ${d.delivered_to_name ?? ""}`}
                          {d.delivery_note && ` · ${d.delivery_note}`}
                        </Descriptions.Item>
                      )}
                      {"repair_amount" in d && (
                        <Descriptions.Item label="Tamir bedeli">
                          {d.repair_amount != null
                            ? `${Number(d.repair_amount).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`
                            : "—"}
                        </Descriptions.Item>
                      )}
                    </Descriptions>
                  </Space>
                ),
              },
              {
                key: "bilgi",
                label: "Teşhis / onarım",
                children: (
                  <KayitBilgileri
                    d={d}
                    sozluk={sozluk}
                    yazabilir={yazabilir}
                    bedelGorur={bedelGorur}
                    guncellendi={guncellendi}
                  />
                ),
              },
              {
                key: "aksesuar",
                label: `Aksesuar (${d.aksesuarlar.length})`,
                children: <Aksesuarlar d={d} sozluk={sozluk} yazabilir={yazabilir} guncellendi={guncellendi} />,
              },
              {
                key: "parca",
                label: "Parça ve süre",
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      Salt okunur: parça hareketleri yedek parça ekranından, süre kayıtları sayaçtan
                      girilir.
                    </Typography.Text>
                    {/* TS-099: servis işi ve PB formuyla aynı parça bileşeni (TS-133), salt okunur. */}
                    <ServisParcalari soId={d.so_id} saltOkunur baslik="Kullanılan parçalar" />
                    <Descriptions size="small" bordered column={{ xs: 1, sm: 2 }}>
                      <Descriptions.Item label="Kişi-saat">{dk(d.sure.kisi_saat_dk)}</Descriptions.Item>
                      <Descriptions.Item label="Süre durumu">
                        {d.sure.sure_durumu}
                        {d.sure.sure_eksik && (
                          <Tag color="gold" style={{ marginLeft: 4 }}>
                            eksik
                          </Tag>
                        )}
                      </Descriptions.Item>
                      <Descriptions.Item label="Mola">{dk(d.sure.mola_dk)}</Descriptions.Item>
                      <Descriptions.Item label="Açık sayaç">{d.sure.acik_bolum_sayisi}</Descriptions.Item>
                      {Object.entries(d.sure.faaliyet_kirilimi).map(([k, v]) => (
                        <Descriptions.Item key={k} label={k}>
                          {dk(v)}
                        </Descriptions.Item>
                      ))}
                    </Descriptions>
                  </Space>
                ),
              },
              {
                key: "gecmis",
                label: "Geçmiş",
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    <Timeline
                      items={d.olaylar
                        .slice()
                        .reverse()
                        .map((o) => ({
                          key: o.id,
                          color: o.olay_turu === "ATOLYE" ? "blue" : "gray",
                          children: (
                            <Space orientation="vertical" size={0}>
                              <Typography.Text>{o.ozet}</Typography.Text>
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                {zaman(o.zaman)} · {o.kullanici ?? "sistem"}
                              </Typography.Text>
                            </Space>
                          ),
                        }))}
                    />
                    <Typography.Title level={5}>Bu cihazın atölye geçmişi</Typography.Title>
                    <Table
                      size="small"
                      rowKey="so_id"
                      pagination={false}
                      loading={seriGecmisi.isLoading}
                      dataSource={(seriGecmisi.data?.kayitlar ?? []).filter((k) => k.so_id !== d.so_id)}
                      locale={{ emptyText: "Önceki kayıt yok" }}
                      columns={[
                        {
                          title: "Atölye no",
                          dataIndex: "atolye_no",
                          render: (v, k) => <Link to={`/atolye/${k.so_id}`}>{v}</Link>,
                        },
                        { title: "Kabul", dataIndex: "received_at", render: tarih },
                        { title: "Durum", dataIndex: "status", render: (s) => <DurumEtiketi kod={s} sozluk={sozluk} /> },
                        { title: "Arıza", dataIndex: "ariza_nedeni", render: (v) => v ?? "—" },
                        { title: "Test", dataIndex: "test_result", render: (v) => (v ? TEST_ADLARI[v] : "—") },
                        { title: "Teslim", dataIndex: "delivered_at", render: tarih },
                      ]}
                    />
                  </Space>
                ),
              },
              {
                key: "ekler",
                label: "Ekler",
                children: (
                  <EkYukleyici
                    entity="service_orders"
                    entityId={d.so_id}
                    kind="IMZA"
                    baslik="İmzalı kabul fişi / teslim tutanağı"
                    aciklama="İmzalı taramayı buraya yükleyin (servis işinin eki olarak saklanır)."
                    yazabilir={yetkili("servis.yaz")}
                    yalnizTur={false}
                  />
                ),
              },
            ]}
          />
          <AtolyeDurumPenceresi
            detay={d}
            hedef={hedef}
            sozluk={sozluk}
            kapat={() => setHedef(null)}
            bitti={(yeni) => {
              setHedef(null);
              guncellendi(yeni);
            }}
          />
          <AtamaPenceresi
            soIdler={[d.so_id]}
            birim={d.birim}
            mevcut={mevcutEkip}
            acik={atamaAcik}
            kapat={() => setAtamaAcik(false)}
            bitti={() => {
              setAtamaAcik(false);
              void detay.refetch();
              degisti();
            }}
          />
          <EkipmanDuzeltPenceresi
            d={d}
            acik={ekipmanAcik}
            kapat={() => setEkipmanAcik(false)}
            bitti={(yeni) => {
              setEkipmanAcik(false);
              guncellendi(yeni);
            }}
          />
        </Space>
      )}
    </Drawer>
  );
}

// --- Sayfa -----------------------------------------------------------------------------------

export default function AtolyePage() {
  const { yetkili, kullanici } = useAuth();
  const qc = useQueryClient();
  const git = useNavigate();
  const { id } = useParams();
  const [arama, setArama] = useSearchParams();
  const yazabilir = yetkili("atolye.yaz");
  const atayabilir = yetkili("atolye.yaz", "servis.planla");
  const aktarabilir = yetkili("atolye.gor", "servis_rapor.disaaktar");
  const bedelGorur = !!kullanici?.sees_cost;

  const suzgec = useMemo(() => suzgecOku(arama), [arama]);
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number[]>([]);
  const [kabulAcik, setKabulAcik] = useState(false);
  const [topluAtaAcik, setTopluAtaAcik] = useState(false);
  const [aramaMetni, setAramaMetni] = useState(suzgec.q ?? "");
  const [markaMetni, setMarkaMetni] = useState(suzgec.marka ?? "");
  const soId = id ? Number(id) : null;
  const yolEki = arama.toString() ? `?${arama.toString()}` : "";

  const sozluk = useQuery({
    queryKey: ["atolye-form-verileri"],
    queryFn: () => atolyeApi.formVerileri(),
    staleTime: 5 * 60_000,
  });
  const ozet = useQuery({ queryKey: ["atolye-ozet", suzgec], queryFn: () => atolyeApi.ozet(suzgec) });
  const liste = useQuery({
    queryKey: ["atolye", suzgec, sayfa],
    queryFn: () => atolyeApi.liste(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });

  const suzgecDegistir = (yeni: AtolyeSuzgeci) => {
    setArama(suzgecYaz(yeni));
    setSayfa(1);
    setSecili([]);
  };
  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["atolye"] });
    void qc.invalidateQueries({ queryKey: ["atolye-ozet"] });
  };
  const s = sozluk.data;
  const seciliBirim =
    (liste.data?.kayitlar ?? []).find((k) => secili.includes(k.so_id))?.birim ?? suzgec.birim ?? "HABERLESME";
  const kpiAktif = (sorgu: Record<string, unknown>) =>
    kpiYolu(suzgec, sorgu) === `/atolye?${suzgecYaz(suzgec)}`;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Row gutter={[12, 12]}>
        {(ozet.data ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={6} xl={3}>
            <KpiKutusu
              kod={k.kod}
              baslik={k.baslik}
              tanim={k.tanim}
              deger={k.deger}
              yol={kpiYolu(suzgec, k.sorgu)}
              vurgu={kpiAktif(k.sorgu) ? "uyari" : k.kod === "GECIKEN" && k.deger > 0 ? "kritik" : "normal"}
            />
          </Col>
        ))}
      </Row>

      <Card
        title="Atölye"
        extra={
          <Space wrap>
            {yazabilir && (
              <Button type="primary" onClick={() => setKabulAcik(true)}>
                Cihaz kabul
              </Button>
            )}
            {aktarabilir && (
              <Button onClick={() => window.open(atolyeApi.excelYolu(suzgec), "_blank")}>Excel</Button>
            )}
          </Space>
        }
      >
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          <Row gutter={[8, 8]}>
            <Col xs={24} md={7}>
              <Input.Search
                allowClear
                placeholder="Atölye no, servis no, müşteri, seri…"
                value={aramaMetni}
                onChange={(e) => setAramaMetni(e.target.value)}
                onSearch={(q) => suzgecDegistir({ ...suzgec, q: q.trim() || undefined })}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Durum"
                value={suzgec.durum ?? suzgec.durum_grubu}
                onChange={(v?: string) =>
                  suzgecDegistir({
                    ...suzgec,
                    durum: v && v !== "ACIK" && v !== "KAPALI" ? v : undefined,
                    durum_grubu: v === "ACIK" || v === "KAPALI" ? v : undefined,
                  })
                }
                options={[
                  { value: "ACIK", label: "Açık kayıtlar" },
                  { value: "KAPALI", label: "Teslim / iptal" },
                  ...(s?.durumlar ?? []).map((d) => ({ value: d.kod, label: d.ad })),
                ]}
              />
            </Col>
            <Col xs={12} md={3}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Birim"
                value={suzgec.birim}
                onChange={(v) => suzgecDegistir({ ...suzgec, birim: v })}
                options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Servis türü"
                value={suzgec.servis_turu}
                onChange={(v) => suzgecDegistir({ ...suzgec, servis_turu: v })}
                options={(s?.servis_turleri ?? []).map((t) => ({ value: t.kod, label: t.ad }))}
              />
            </Col>
            <Col xs={12} md={3}>
              <Input
                allowClear
                placeholder="Marka"
                value={markaMetni}
                onChange={(e) => {
                  setMarkaMetni(e.target.value);
                  if (!e.target.value) suzgecDegistir({ ...suzgec, marka: undefined });
                }}
                onPressEnter={() => suzgecDegistir({ ...suzgec, marka: markaMetni.trim() || undefined })}
              />
            </Col>
            <Col xs={12} md={3}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Bekleme"
                value={suzgec.yas}
                onChange={(v) => suzgecDegistir({ ...suzgec, yas: v })}
                options={(s?.yas_kovalari ?? []).map((k) => ({ value: k, label: `${k} gün` }))}
              />
            </Col>
          </Row>
          <Space wrap>
            <Checkbox
              checked={!!suzgec.geciken}
              onChange={(e) => suzgecDegistir({ ...suzgec, geciken: e.target.checked || undefined })}
            >
              Tahmini bitişi geçenler
            </Checkbox>
            {suzgec.kabul_grubu && (
              <Tag closable onClose={() => suzgecDegistir({ ...suzgec, kabul_grubu: undefined })} color="blue">
                Kabul grubu {suzgec.kabul_grubu}
              </Tag>
            )}
            {suzgec.kabul_grubu && (
              <Button size="small" onClick={() => window.open(atolyeApi.grupFisiYolu(suzgec.kabul_grubu!), "_blank")}>
                Grup kabul fişi
              </Button>
            )}
            {Object.values(suzgec).some((v) => v !== undefined) && (
              <Button
                size="small"
                type="link"
                onClick={() => {
                  setAramaMetni("");
                  setMarkaMetni("");
                  suzgecDegistir({});
                }}
              >
                Süzgeci temizle
              </Button>
            )}
          </Space>

          {secili.length > 0 && atayabilir && (
            <Space wrap>
              <Typography.Text>{secili.length} kayıt seçili</Typography.Text>
              <Button size="small" onClick={() => setTopluAtaAcik(true)}>
                Toplu ata
              </Button>
              <Button size="small" onClick={() => setSecili([])}>
                Seçimi kaldır
              </Button>
            </Space>
          )}

          <Table<AtolyeSatiri>
            rowKey="so_id"
            size="small"
            scroll={{ x: 1000 }}
            loading={liste.isLoading}
            dataSource={liste.data?.kayitlar ?? []}
            locale={{ emptyText: <Empty description="Bu süzgeçte atölye kaydı yok" /> }}
            rowSelection={
              atayabilir
                ? {
                    selectedRowKeys: secili,
                    onChange: (k) => setSecili(k as number[]),
                    getCheckboxProps: (r) => ({ disabled: !r.acik }),
                    preserveSelectedRowKeys: true,
                  }
                : undefined
            }
            pagination={{
              current: sayfa,
              pageSize: SAYFA_BOYU,
              total: liste.data?.toplam ?? 0,
              showSizeChanger: false,
              onChange: setSayfa,
              showTotal: (t) => `${t.toLocaleString("tr-TR")} kayıt`,
            }}
            onRow={(r) => ({ onClick: () => git(`/atolye/${r.so_id}${yolEki}`), style: { cursor: "pointer" } })}
            columns={[
              {
                title: "Atölye no",
                dataIndex: "atolye_no",
                width: 150,
                render: (v: string, r) => (
                  <Space orientation="vertical" size={0}>
                    <span className="mono">{v}</span>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {r.so_no}
                    </Typography.Text>
                  </Space>
                ),
              },
              { title: "Müşteri", key: "m", ellipsis: true, render: (_, r) => r.musteri?.title ?? "—" },
              {
                title: "Cihaz",
                key: "c",
                ellipsis: true,
                render: (_, r) =>
                  r.ekipman ? (
                    <Space orientation="vertical" size={0}>
                      <span>{[r.ekipman.marka, r.ekipman.model].filter(Boolean).join(" ")}</span>
                      <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>
                        {r.ekipman.seri}
                      </Typography.Text>
                    </Space>
                  ) : (
                    "—"
                  ),
              },
              {
                title: "Durum",
                key: "d",
                width: 160,
                render: (_, r) => (
                  <Space size={4} wrap>
                    <DurumEtiketi kod={r.status} sozluk={s} />
                    {r.geciken && <Tag color="red">Gecikmiş</Tag>}
                  </Space>
                ),
              },
              {
                title: "Garanti",
                dataIndex: "warranty_status",
                width: 130,
                render: (g: string) => <GarantiEtiketi kod={g} sozluk={s} />,
              },
              { title: "Sorumlu", key: "s", width: 140, ellipsis: true, render: (_, r) => r.sorumlu?.ad ?? "—" },
              { title: "Kabul", dataIndex: "received_at", width: 100, render: tarih },
              { title: "Gün", dataIndex: "bekleme_gunu", width: 60, align: "right" },
              ...(bedelGorur
                ? [
                    {
                      title: "Bedel",
                      key: "b",
                      width: 100,
                      align: "right" as const,
                      render: (_: unknown, r: AtolyeSatiri) =>
                        r.repair_amount != null ? Number(r.repair_amount).toLocaleString("tr-TR") : "—",
                    },
                  ]
                : []),
            ]}
          />
        </Space>
      </Card>

      {soId && (
        <AtolyeDetayi
          soId={soId}
          sozluk={s}
          kapat={() => git(`/atolye${yolEki}`)}
          degisti={tazele}
        />
      )}

      <AtolyeKabulPenceresi
        acik={kabulAcik}
        kapat={() => setKabulAcik(false)}
        bitti={(r) => {
          setKabulAcik(false);
          tazele();
          if (r.detay) {
            git(`/atolye/${r.detay.so_id}`);
            window.open(atolyeApi.kabulFisiYolu(r.detay.so_id), "_blank");
          } else if (r.grup) {
            suzgecDegistir({ kabul_grubu: r.grup });
            window.open(atolyeApi.grupFisiYolu(r.grup), "_blank");
          }
        }}
      />

      <AtamaPenceresi
        soIdler={secili}
        birim={seciliBirim}
        mevcut={BOS_EKIP}
        acik={topluAtaAcik}
        kapat={() => setTopluAtaAcik(false)}
        bitti={() => {
          setTopluAtaAcik(false);
          setSecili([]);
          tazele();
        }}
      />
    </Space>
  );
}
