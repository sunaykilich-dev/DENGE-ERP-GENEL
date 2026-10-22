/**
 * Plan Penceresi — tekli / toplu / yeniden plan (TS-041/043/045/046/047).
 *
 * Tek pencere üç işi görür; kural sunucudadır, pencere yalnız yansıtır:
 * - **tekli:** `PUT /isler/{id}/plan`; mevcut plan ön dolumu ve iyimser kilit
 *   (`beklenen_aktif_plan_id`); ekip alanlarına dokunulmadıysa ekip
 *   gönderilmez (sunucu mevcut ekibi korur). Saha önerisi yalnız BOŞ alanları
 *   doldurur.
 * - **toplu:** `POST /toplu-plan` — aynı müşteri + lokasyon + birim, plansız
 *   işler tek ziyarete; ekip zorunlu. PB toplu planlama da bu pencereyi kullanır.
 * - **yeniden:** `POST /yeniden-plan` — ziyaret kartında seçilen işler;
 *   tarih/saat değişirse neden zorunlu.
 * - **Çakışma (409 `PLAN_CAKISMA`):** liste + gerekçe (≥10 karakter) ile
 *   "Gerekçeyle Kaydet". Kapsam dışı çakışan iş "başka birim işi" olarak
 *   maskeli gelir. Diğer 409'larda iş no listesi ya da "yenileyin" mesajı.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Checkbox,
  Col,
  DatePicker,
  Descriptions,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Row,
  Select,
  Tag,
  TimePicker,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState } from "react";

import type { ApiError } from "../api/client";
import { personelApi } from "../api/personel";
import {
  type Cakisma,
  PLAN_NEDENLERI,
  type Plan,
  type PlanGirdisi,
  planCakismasi,
  planlamaApi,
  sorunluIsler,
} from "../api/servisPlanlama";

export type PlanModu = "tekli" | "toplu" | "yeniden";

export interface PlanPenceresiProps {
  acik: boolean;
  mod: PlanModu;
  isIdler: number[];
  /** İşlerin birimi: ekip ve araç seçenekleri bu birimden gelir. */
  birim: string;
  baslik?: string;
  /** Tekli/yeniden planda ön dolum (aktif plan). */
  mevcut?: Plan | null;
  /** Yeni planın önerilen günü (takvimde tıklanan gün). */
  varsayilanGun?: string;
  /**
   * Yeni plan için ön dolum (TS-190 bölge önerisi: önceki ziyaret bittikten
   * sonraki saat ve aynı ekip). Mevcut plan varsa yok sayılır.
   */
  varsayilan?: { baslangic_saati?: string | null; teknisyen_idler?: number[]; arac_id?: number | null };
  onKapat: () => void;
  onKaydedildi: () => void;
}

interface PlanFormu {
  plan_tarihi: Dayjs;
  baslangic_saati?: Dayjs | null;
  sure_dk: number;
  sef_idler?: number[];
  sef_sahada?: boolean;
  teknisyen_idler?: number[];
  sorumlu_id?: number | null;
  arac_id?: number | null;
  saha_bolgesi?: string;
  saha_notu?: string;
  plan_notu?: string;
  degisim_nedeni?: string;
  degisim_notu?: string;
}

const EKIP_ALANLARI = ["sef_idler", "sef_sahada", "teknisyen_idler", "sorumlu_id"] as const;
const nedenSecenekleri = Object.entries(PLAN_NEDENLERI).map(([value, label]) => ({ value, label }));
const ALAN_ADLARI: Record<string, string> = {
  tesis_adi: "Tesis",
  il: "İl",
  ilce: "İlçe",
  acik_adres: "Açık adres",
  erisim_notu: "Erişim notu",
  irtibat_adi: "Saha yetkilisi",
  irtibat_telefon: "Telefon",
};
const CAKISMA_TURLERI: Record<string, string> = {
  KISI: "Personel",
  ARAC: "Araç",
  MUSAITLIK: "Müsaitlik bloğu",
};

export default function PlanPenceresi({
  acik,
  mod,
  isIdler,
  birim,
  baslik,
  mevcut,
  varsayilanGun,
  varsayilan,
  onKapat,
  onKaydedildi,
}: PlanPenceresiProps) {
  const { message } = App.useApp();
  const [form] = Form.useForm<PlanFormu>();
  const [cakismalar, setCakismalar] = useState<Cakisma[] | null>(null);
  const [gerekce, setGerekce] = useState("");
  const [bekleyen, setBekleyen] = useState<PlanGirdisi | null>(null);

  const kisiler = useQuery({
    queryKey: ["atanabilir", birim],
    queryFn: () => personelApi.atanabilir(birim),
    enabled: acik && !!birim,
  });
  const araclar = useQuery({
    queryKey: ["servis-araclar", birim, true],
    queryFn: () => planlamaApi.araclar(birim, true),
    enabled: acik && !!birim,
  });
  const tekIs = mod === "tekli" && isIdler.length === 1 ? isIdler[0] : null;
  const oneri = useQuery({
    queryKey: ["saha-onerisi", tekIs],
    queryFn: () => planlamaApi.sahaOnerisi(tekIs!),
    enabled: acik && tekIs != null,
  });

  useEffect(() => {
    if (!acik) return;
    setCakismalar(null);
    setGerekce("");
    form.resetFields();
    const sefler = mevcut?.ekip.filter((u) => u.rol === "SEF") ?? [];
    form.setFieldsValue({
      plan_tarihi: dayjs(mevcut?.plan_tarihi ?? varsayilanGun ?? undefined),
      baslangic_saati: mevcut
        ? mevcut.baslangic_saati
          ? dayjs(mevcut.baslangic_saati, "HH:mm")
          : null
        : dayjs(varsayilan?.baslangic_saati ?? "09:00", "HH:mm"),
      sure_dk: mevcut?.sure_dk ?? 60,
      sef_idler: sefler.map((u) => u.user_id),
      sef_sahada: sefler.some((u) => u.sahaya_gidiyor),
      teknisyen_idler: mevcut
        ? mevcut.ekip.filter((u) => u.rol === "TEKNISYEN").map((u) => u.user_id)
        : varsayilan?.teknisyen_idler,
      arac_id: mevcut ? mevcut.arac_id : (varsayilan?.arac_id ?? null),
      saha_bolgesi: mevcut?.saha_bolgesi ?? undefined,
      saha_notu: mevcut?.saha_notu ?? undefined,
      plan_notu: mevcut?.plan_notu ?? undefined,
    });
  }, [acik, mevcut, varsayilanGun, varsayilan, form]);

  // Saha önerisi yalnız boş alanları doldurur (kullanıcının yazdığı ezilmez).
  useEffect(() => {
    if (!oneri.data) return;
    for (const a of oneri.data.alanlar) {
      if (a.alan !== "saha_bolgesi" && a.alan !== "saha_notu") continue;
      if (!form.getFieldValue(a.alan) && !form.isFieldTouched(a.alan)) {
        form.setFieldValue(a.alan, String(a.deger));
      }
    }
  }, [oneri.data, form]);

  const kaydet = useMutation({
    mutationFn: async (g: PlanGirdisi) => {
      if (mod === "tekli") return planlamaApi.planla(isIdler[0], g);
      if (mod === "toplu") return planlamaApi.topluPlan(isIdler, g);
      return planlamaApi.yenidenPlan(isIdler, g);
    },
    onSuccess: (sonuc) => {
      message.success(
        mod === "toplu" ? `${isIdler.length} iş tek ziyarette planlandı` : "Plan kaydedildi",
      );
      const uyarilar = sonuc?.uyarilar ?? [];
      if (uyarilar.length) {
        // TS-198: yetkinlik eksikliği planı engellemez, yalnız uyarır.
        Modal.warning({
          title: "Yetkinlik uyarısıyla atandı",
          content: (
            <ul style={{ paddingLeft: 18, margin: 0 }}>
              {uyarilar.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          ),
        });
      }
      setCakismalar(null);
      onKaydedildi();
    },
    onError: (e: ApiError, g) => {
      const liste = planCakismasi(e);
      if (liste) {
        setBekleyen(g);
        setCakismalar(liste);
        return;
      }
      const isler = sorunluIsler(e);
      if (isler.length) {
        message.error(e.message);
      } else if (e.cakisma) {
        message.error(`${e.message} Gerekirse sayfayı yenileyip tekrar deneyin.`);
      } else {
        message.error(e.message);
      }
    },
  });

  const girdiUret = (v: PlanFormu): PlanGirdisi => {
    const ekipDegisti = mod !== "tekli" || EKIP_ALANLARI.some((a) => form.isFieldTouched(a));
    const sefler = v.sef_idler ?? [];
    const teknisyenler = v.teknisyen_idler ?? [];
    return {
      plan_tarihi: v.plan_tarihi.format("YYYY-MM-DD"),
      baslangic_saati: v.baslangic_saati ? v.baslangic_saati.format("HH:mm") : null,
      sure_dk: v.sure_dk,
      ekip:
        mod === "yeniden" && !EKIP_ALANLARI.some((a) => form.isFieldTouched(a))
          ? null
          : ekipDegisti
            ? {
                sef_idler: sefler,
                sahaya_giden_sefler: v.sef_sahada ? sefler : [],
                teknisyen_idler: teknisyenler,
                sorumlu_id: v.sorumlu_id ?? null,
              }
            : null,
      arac_id: v.arac_id ?? null,
      saha_bolgesi: v.saha_bolgesi || null,
      saha_notu: v.saha_notu || null,
      plan_notu: v.plan_notu || null,
      degisim_nedeni: v.degisim_nedeni || null,
      degisim_notu: v.degisim_notu || null,
      beklenen_aktif_plan_id: mod === "tekli" ? (mevcut?.id ?? null) : null,
    };
  };

  const gonder = async () => {
    const v = await form.validateFields();
    kaydet.mutate(girdiUret(v));
  };

  const sefSecenekleri = (kisiler.data ?? [])
    .filter((k) => k.saha_rolu === "SEF")
    .map((k) => ({ value: k.id, label: k.giris_acik ? k.ad : `${k.ad} (girişsiz)` }));
  const teknisyenSecenekleri = (kisiler.data ?? [])
    .filter((k) => k.saha_rolu === "TEKNISYEN" || k.saha_rolu === "STAJYER")
    .map((k) => ({ value: k.id, label: k.saha_rolu === "STAJYER" ? `${k.ad} (stajyer)` : k.ad }));
  const kisiAdi = (id: number | null) =>
    (kisiler.data ?? []).find((k) => k.id === id)?.ad ?? (id ? `#${id}` : "");
  const aracSecenekleri = (araclar.data ?? []).map((a) => ({
    value: a.id,
    label: a.birim ? a.plaka : `${a.plaka} (ortak havuz)`,
  }));
  const secilenTeknisyenler: number[] = Form.useWatch("teknisyen_idler", form) ?? [];
  const nedenGerekli = mod === "yeniden" || (mod === "tekli" && !!mevcut);
  const lokasyonOnerisi = (oneri.data?.alanlar ?? []).filter((a) => a.alan in ALAN_ADLARI);

  const pencereBasligi =
    baslik ??
    (mod === "toplu"
      ? `Toplu Plan (${isIdler.length} iş)`
      : mod === "yeniden"
        ? `Seçilenleri Taşı (${isIdler.length} iş)`
        : mevcut
          ? "Planı Düzenle"
          : "Planla");

  return (
    <>
      <Modal
        open={acik}
        title={pencereBasligi}
        onCancel={onKapat}
        onOk={() => void gonder()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        width={720}
        style={{ maxWidth: "calc(100vw - 16px)" }}
        destroyOnHidden
      >
        {lokasyonOnerisi.length > 0 && (
          <Descriptions
            size="small"
            column={{ xs: 1, sm: 2 }}
            style={{ marginBottom: 12 }}
            items={lokasyonOnerisi.map((a) => ({
              key: a.alan,
              label: ALAN_ADLARI[a.alan],
              children:
                a.alan === "irtibat_telefon" ? (
                  <a href={`tel:${a.deger}`}>{a.deger}</a>
                ) : (
                  String(a.deger)
                ),
            }))}
          />
        )}
        <Form form={form} layout="vertical" requiredMark="optional">
          <Row gutter={12}>
            <Col xs={24} sm={8}>
              <Form.Item name="plan_tarihi" label="Plan tarihi" rules={[{ required: true }]}>
                <DatePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={12} sm={8}>
              <Form.Item name="baslangic_saati" label="Saat (boş = belirsiz)">
                <TimePicker format="HH:mm" minuteStep={5} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={12} sm={8}>
              <Form.Item
                name="sure_dk"
                label="Planlanan süre (dk)"
                rules={[{ required: true, type: "number", min: 15, max: 1440 }]}
              >
                <InputNumber min={15} max={1440} step={15} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col xs={24} sm={12}>
              <Form.Item name="sef_idler" label="Şef (sorumlu)">
                <Select
                  mode="multiple"
                  allowClear
                  options={sefSecenekleri}
                  loading={kisiler.isLoading}
                  optionFilterProp="label"
                  maxCount={5}
                />
              </Form.Item>
              <Form.Item name="sef_sahada" valuePropName="checked" style={{ marginTop: -12 }}>
                <Checkbox>Şef sahaya gidiyor (çakışma kontrolüne girer)</Checkbox>
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item
                name="teknisyen_idler"
                label="Teknisyenler"
                rules={
                  mod === "toplu"
                    ? [
                        ({ getFieldValue }) => ({
                          validator: (_, v: number[] | undefined) =>
                            (v?.length ?? 0) > 0 || (getFieldValue("sef_idler")?.length ?? 0) > 0
                              ? Promise.resolve()
                              : Promise.reject(new Error("Toplu planda en az bir kişi seçin")),
                        }),
                      ]
                    : []
                }
              >
                <Select
                  mode="multiple"
                  allowClear
                  options={teknisyenSecenekleri}
                  loading={kisiler.isLoading}
                  optionFilterProp="label"
                  maxCount={30}
                />
              </Form.Item>
              {secilenTeknisyenler.length > 1 && (
                <Form.Item name="sorumlu_id" label="Sorumlu teknisyen">
                  <Select
                    allowClear
                    placeholder="İlk seçilen"
                    options={secilenTeknisyenler.map((id) => ({ value: id, label: kisiAdi(id) }))}
                  />
                </Form.Item>
              )}
            </Col>
          </Row>
          <Row gutter={12}>
            <Col xs={24} sm={12}>
              <Form.Item name="arac_id" label="Servis aracı">
                <Select allowClear options={aracSecenekleri} loading={araclar.isLoading} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="saha_bolgesi" label="Saha bölgesi (bina/kat)">
                <Input maxLength={200} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="saha_notu" label="Saha notu (ulaşım/otopark)">
            <Input maxLength={500} />
          </Form.Item>
          <Form.Item name="plan_notu" label="Plan notu">
            <Input.TextArea maxLength={1000} autoSize={{ minRows: 1, maxRows: 4 }} />
          </Form.Item>
          {nedenGerekli && (
            <Row gutter={12}>
              <Col xs={24} sm={10}>
                <Form.Item
                  name="degisim_nedeni"
                  label="Değişiklik nedeni"
                  tooltip="Tarih veya saat değişiyorsa zorunlu"
                >
                  <Select allowClear options={nedenSecenekleri} />
                </Form.Item>
              </Col>
              <Col xs={24} sm={14}>
                <Form.Item
                  name="degisim_notu"
                  label="Açıklama"
                  dependencies={["degisim_nedeni"]}
                  rules={[
                    ({ getFieldValue }) => ({
                      validator: (_, v: string | undefined) =>
                        getFieldValue("degisim_nedeni") === "DIGER" && !v?.trim()
                          ? Promise.reject(new Error("'Diğer' nedeninde açıklama zorunlu"))
                          : Promise.resolve(),
                    }),
                  ]}
                >
                  <Input maxLength={500} />
                </Form.Item>
              </Col>
            </Row>
          )}
        </Form>
      </Modal>

      <Modal
        open={cakismalar !== null}
        title="Plan çakışıyor"
        onCancel={() => setCakismalar(null)}
        okText="Gerekçeyle Kaydet"
        cancelText="Vazgeç"
        okButtonProps={{ disabled: gerekce.trim().length < 10, loading: kaydet.isPending }}
        onOk={() => bekleyen && kaydet.mutate({ ...bekleyen, cakisma_gerekcesi: gerekce.trim() })}
        style={{ maxWidth: "calc(100vw - 16px)" }}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="Seçilen kişi veya araç bu saatte başka bir işte (ya da müsait değil)."
        />
        <List
          size="small"
          dataSource={cakismalar ?? []}
          renderItem={(c) => (
            <List.Item>
              <span>
                <Tag>{CAKISMA_TURLERI[c.tur] ?? c.tur}</Tag>
                {c.user_id ? kisiAdi(c.user_id) : null} {c.saat_araligi}{" "}
                {c.maskeli ? (
                  <Typography.Text type="secondary">({c.birim} birimi işi)</Typography.Text>
                ) : (
                  c.so_no
                )}
              </span>
            </List.Item>
          )}
        />
        <Input.TextArea
          value={gerekce}
          onChange={(e) => setGerekce(e.target.value)}
          placeholder="Çakışmaya rağmen kaydetme gerekçesi (en az 10 karakter)"
          maxLength={500}
          autoSize={{ minRows: 2, maxRows: 4 }}
        />
      </Modal>
    </>
  );
}
