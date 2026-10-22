/**
 * Ekipman Formu — ekipman ekle/düzenle (TS-050).
 *
 * Tek form, yeni + düzenle. Müşteri → lokasyon seçimi ortak seçiciden
 * (`MusteriLokasyonSecici`, sunucuda arama); irtibat, seçilen lokasyonun
 * irtibatlarından (yalnız `hesap.gor` olana, KVKK) ya da serbest ad.
 *
 * Sunucu aynı tip + marka + seri ile aktif kayıt bulursa 409 döner; form o
 * zaman "Farklı cihaz olduğunu onaylıyorum" gerekçe alanını açar ve aynı
 * isteği gerekçeyle yeniden gönderir. Durum burada değişmez (yalnız yeni
 * kayıtta başlangıç durumu seçilir); durum değişikliği gerekçeli ayrı işlemdir.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, App, Col, DatePicker, Form, Input, Modal, Row, Select } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState } from "react";

import { anaVeriApi } from "../api/anaVeri";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import {
  BASLANGIC_DURUMLARI,
  DURUM_ETIKETLERI,
  EKIPMAN_TIPLERI,
  ekipmanApi,
  EkipmanHatasi,
  GARANTI_KAYNAKLARI,
  TIP_ETIKETLERI,
  type EkipmanKarti,
} from "../api/servisEkipman";
import { useAuth } from "../auth/AuthContext";
import MusteriLokasyonSecici, { type MusteriLokasyonSecimi } from "./MusteriLokasyonSecici";

interface FormDegerleri {
  birim: string;
  equipment_type: string;
  musteri?: MusteriLokasyonSecimi;
  contact_id?: number | null;
  contact_name_raw?: string;
  brand?: string;
  model?: string;
  serial_no?: string;
  zone?: string;
  delivery_date?: Dayjs | null;
  install_date?: Dayjs | null;
  warranty_start?: Dayjs | null;
  warranty_end?: Dayjs | null;
  warranty_source?: string | null;
  lifecycle_status?: string;
  notes?: string;
  duplicate_ack_reason?: string;
}

const gun = (d?: Dayjs | null) => (d ? d.format("YYYY-MM-DD") : null);
const bos = (s?: string | null) => (s && s.trim() ? s.trim() : null);

export default function EkipmanFormu({
  acik,
  kayit,
  onKapat,
  onKaydedildi,
}: {
  acik: boolean;
  /** Düzenlenen kayıt; `null` = yeni kayıt. */
  kayit: EkipmanKarti | null;
  onKapat: () => void;
  onKaydedildi: (k: EkipmanKarti) => void;
}) {
  const { message } = App.useApp();
  const { kullanici, yetkili } = useAuth();
  const [form] = Form.useForm<FormDegerleri>();
  const [mukerrer, setMukerrer] = useState<string | null>(null);
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const secim = Form.useWatch("musteri", form);
  const lokasyonId = secim?.lokasyonId ?? null;

  const tumBirimler = kullanici?.role.scope === "TUMU" || !(kullanici?.birimler ?? []).length;
  const birimler = tumBirimler ? BIRIM_KODLARI : (kullanici?.birimler ?? []);

  const irtibatlar = useQuery({
    queryKey: ["lokasyon-kart", lokasyonId],
    queryFn: () => anaVeriApi.lokasyon(lokasyonId!),
    enabled: acik && lokasyonId != null && yetkili("hesap.gor"),
  });

  useEffect(() => {
    if (!acik) return;
    setMukerrer(null);
    form.resetFields();
    if (kayit) {
      form.setFieldsValue({
        birim: kayit.birim,
        equipment_type: kayit.equipment_type,
        musteri: {
          musteriId: kayit.account_id,
          musteriAdi: kayit.hesap_unvan,
          lokasyonId: kayit.address_id,
        },
        contact_id: kayit.contact_id,
        contact_name_raw: kayit.contact_name_raw ?? undefined,
        brand: kayit.brand ?? undefined,
        model: kayit.model ?? undefined,
        serial_no: kayit.serial_no ?? undefined,
        zone: kayit.zone ?? undefined,
        delivery_date: kayit.delivery_date ? dayjs(kayit.delivery_date) : null,
        install_date: kayit.install_date ? dayjs(kayit.install_date) : null,
        warranty_start: kayit.warranty_start ? dayjs(kayit.warranty_start) : null,
        warranty_end: kayit.warranty_end ? dayjs(kayit.warranty_end) : null,
        warranty_source: kayit.warranty_source,
        notes: kayit.notes ?? undefined,
      });
    } else {
      form.setFieldsValue({
        birim: kullanici?.birincil_birim ?? birimler[0],
        equipment_type: "XRAY",
        lifecycle_status: "BILINMIYOR",
      });
    }
    // Pencere her açılışta bir kez doldurulur (form/kullanıcı bağımlılığı bilerek yok).
  }, [acik, kayit]); // oxlint-disable-line react-hooks/exhaustive-deps

  async function kaydet(v: FormDegerleri) {
    if (!v.musteri?.musteriId) {
      message.error("Müşteri seçin");
      return;
    }
    const govde: Record<string, unknown> = {
      birim: v.birim,
      equipment_type: v.equipment_type,
      account_id: v.musteri.musteriId,
      address_id: v.musteri.lokasyonId ?? null,
      contact_id: v.contact_id ?? null,
      contact_name_raw: bos(v.contact_name_raw),
      brand: bos(v.brand),
      model: bos(v.model),
      serial_no: bos(v.serial_no),
      zone: bos(v.zone),
      delivery_date: gun(v.delivery_date),
      install_date: gun(v.install_date),
      warranty_start: gun(v.warranty_start),
      warranty_end: gun(v.warranty_end),
      warranty_source: v.warranty_source ?? null,
      notes: bos(v.notes),
    };
    if (mukerrer !== null) govde.duplicate_ack_reason = bos(v.duplicate_ack_reason);
    setGonderiliyor(true);
    try {
      const sonuc = kayit
        ? await ekipmanApi.guncelle(kayit.id, { ...govde, version: kayit.version })
        : await ekipmanApi.olustur({ ...govde, lifecycle_status: v.lifecycle_status });
      message.success(kayit ? "Ekipman kaydedildi" : "Ekipman eklendi");
      onKaydedildi(sonuc);
    } catch (e) {
      if (e instanceof EkipmanHatasi && e.status === 409 && e.detay?.kod === "MUKERRER_SERI") {
        setMukerrer(e.message);
      } else if (e instanceof EkipmanHatasi && e.cakisma) {
        message.error(`${e.message} Sayfayı yenileyip tekrar deneyin.`);
      } else {
        message.error((e as Error).message);
      }
    } finally {
      setGonderiliyor(false);
    }
  }

  return (
    <Modal
      title={kayit ? `Ekipman #${kayit.id} düzenle` : "Yeni ekipman"}
      open={acik}
      onCancel={onKapat}
      onOk={() => form.submit()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={gonderiliyor}
      width={720}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={(v) => void kaydet(v)}>
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item name="birim" label="Birim" rules={[{ required: true }]}>
              <Select options={birimler.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="equipment_type" label="Tip" rules={[{ required: true }]}>
              <Select options={EKIPMAN_TIPLERI.map((t) => ({ value: t, label: TIP_ETIKETLERI[t] ?? t }))} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="musteri" label="Müşteri ve lokasyon" required>
          <MusteriLokasyonSecici />
        </Form.Item>
        <Row gutter={12}>
          {yetkili("hesap.gor") && (
            <Col xs={24} sm={12}>
              <Form.Item name="contact_id" label="Lokasyon irtibatı">
                <Select
                  allowClear
                  disabled={lokasyonId == null}
                  loading={irtibatlar.isFetching}
                  placeholder={lokasyonId == null ? "Önce lokasyon seçin" : "İrtibat seçin"}
                  options={(irtibatlar.data?.irtibatlar ?? []).map((k) => ({
                    value: k.id,
                    label: k.gorev ? `${k.ad} (${k.gorev})` : k.ad,
                  }))}
                />
              </Form.Item>
            </Col>
          )}
          <Col xs={24} sm={yetkili("hesap.gor") ? 12 : 24}>
            <Form.Item
              name="contact_name_raw"
              label="İrtibat (serbest ad)"
              extra="Kişisel veridir; listede görünmez."
              rules={[{ max: 120 }]}
            >
              <Input />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col xs={24} sm={8}>
            <Form.Item name="brand" label="Marka" rules={[{ max: 60 }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} sm={8}>
            <Form.Item name="model" label="Model" rules={[{ max: 80 }]}>
              <Input />
            </Form.Item>
          </Col>
          <Col xs={24} sm={8}>
            <Form.Item
              name="serial_no"
              label="Seri no"
              rules={[{ max: 200 }]}
              extra="Olduğu gibi saklanır (baştaki sıfır, - . / korunur)."
            >
              <Input className="mono" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="zone" label="Bölge (ör. B Kapısı Giriş)" rules={[{ max: 120 }]}>
          <Input />
        </Form.Item>
        <Row gutter={12}>
          <Col xs={12} sm={6}>
            <Form.Item name="delivery_date" label="Teslim">
              <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="install_date" label="Kurulum">
              <DatePicker
                format="DD.MM.YYYY"
                style={{ width: "100%" }}
                disabledDate={(d) => d.isAfter(dayjs(), "day")}
              />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="warranty_start" label="Garanti başlangıç">
              <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item
              name="warranty_end"
              label="Garanti bitiş"
              dependencies={["warranty_start"]}
              rules={[
                ({ getFieldValue }) => ({
                  validator(_, d?: Dayjs | null) {
                    const b = getFieldValue("warranty_start") as Dayjs | null;
                    return d && b && d.isBefore(b, "day")
                      ? Promise.reject(new Error("Bitiş başlangıçtan önce olamaz"))
                      : Promise.resolve();
                  },
                }),
              ]}
            >
              <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item name="warranty_source" label="Garanti kaynağı">
              <Select
                allowClear
                options={Object.entries(GARANTI_KAYNAKLARI).map(([k, v]) => ({ value: k, label: v }))}
              />
            </Form.Item>
          </Col>
          {!kayit && (
            <Col xs={24} sm={12}>
              <Form.Item name="lifecycle_status" label="Durum">
                <Select
                  options={BASLANGIC_DURUMLARI.map((d) => ({ value: d, label: DURUM_ETIKETLERI[d] }))}
                />
              </Form.Item>
            </Col>
          )}
        </Row>
        <Form.Item name="notes" label="Not">
          <Input.TextArea rows={2} maxLength={4000} />
        </Form.Item>
        {mukerrer !== null && (
          <>
            <Alert type="warning" showIcon style={{ marginBottom: 12 }} title={mukerrer} />
            <Form.Item
              name="duplicate_ack_reason"
              label="Farklı cihaz olduğunu onaylıyorum — gerekçe"
              rules={[{ required: true, whitespace: true, min: 5 }]}
            >
              <Input.TextArea rows={2} maxLength={1000} />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  );
}
