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
 *
 * Rol testi tur 2 (B12, KARARLAR 2026-11-04 §7.15): kabul birimi sabit
 * HABERLESME değildir. `form-verileri` birimsiz sorulur; sunucu kullanıcının
 * birimini seçip yanıtta `birim` döner ve kabul o birimle gönderilir. Birden
 * çok görünür birimi olan kullanıcı birimi pencerede seçebilir (atölye
 * listesindeki birim süzgeci varsayılandır). Telsiz birimlerinde (HABERLESME,
 * POC) marka sözlükten, diğerlerinde serbest metindir (kütükteki markalar
 * öneri olarak gelir). Ekipman tipi zorunlu değil: boşsa sunucu birimin
 * varsayılan tipini kullanır.
 *
 * 2026-11-24 sahip belgesi: aksesuarlar HER CİHAZ için kutucuklarla (adetli)
 * seçilir; model marka listesinden gelir (`atolye.model_ekle` yeni model
 * ekler); garanti tarihleri kütükteki ekipmandan dolar; irtibat müşterinin
 * tüm kişilerinden seçilir ya da pencereden eklenir; girilmiş form "Vazgeç"te
 * onay sorar (pencere dışına tıklamak kapatmaz — main.tsx).
 */
import { CopyOutlined, DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Col,
  DatePicker,
  Divider,
  AutoComplete,
  Form,
  Input,
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

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { AksesuarSecici, aksesuarTemizle } from "./AksesuarSecici";
import { BIRIM_ETIKETLERI } from "../api/personel";
import { useSirket } from "../auth/SirketContext";
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
import { ELLE_GEREKCELERI } from "./barkod/elleGerekce";
import SeriAlani from "./barkod/SeriAlani";
import MusteriLokasyonSecici, {
  type MusteriLokasyonSecimi,
  type SahaOnerisi,
} from "./MusteriLokasyonSecici";

/** Marka sözlüğü kullanılan telsiz birimleri (sunucu: `atolye.TELSIZ_BIRIMLERI`). */
const TELSIZ_BIRIMLERI = new Set(["HABERLESME", "POC"]);

interface CihazSatiri {
  tip?: string;
  marka?: string;
  marka_diger?: string;
  model?: string;
  seri?: string;
  okuma_kaynagi?: "OKUTMA" | "ELLE";
  elle_gerekce?: string;
  elle_aciklama?: string;
  customer_complaint?: string;
  warranty_start?: Dayjs | null;
  warranty_end?: Dayjs | null;
  /** Toplu kabulde cihaza özel aksesuarlar. */
  aksesuarlar?: AksesuarGirdisi[];
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

/** Seri okuma kaynağı (yalnız bilinen kaynak gider: okutuldu ya da nedenli elle). */
function okumaAlanlari(c: CihazSatiri): Partial<EkipmanGirdisi> {
  if (!c.seri?.trim()) return {};
  if (c.okuma_kaynagi === "OKUTMA") return { okuma_kaynagi: "OKUTMA" };
  if (c.elle_gerekce)
    return {
      okuma_kaynagi: "ELLE",
      elle_gerekce: c.elle_gerekce,
      elle_aciklama: c.elle_aciklama?.trim() || null,
    };
  return {};
}

function ekipmanGovdesi(c: CihazSatiri): EkipmanGirdisi {
  return {
    ...okumaAlanlari(c),
    // Boş tip gönderilmez: sunucu birimin varsayılan tipini kullanır.
    ...(c.tip ? { tip: c.tip } : {}),
    marka: c.marka?.trim() || null,
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
  const markaDiger = Form.useWatch([...(kok ?? ad), "marka_diger"]);
  const form = Form.useFormInstance();
  const seri = Form.useWatch([...(kok ?? ad), "seri"]) as string | undefined;
  const okumaKaynagi = Form.useWatch([...(kok ?? ad), "okuma_kaynagi"]);
  const elleGerekce = Form.useWatch([...(kok ?? ad), "elle_gerekce"]);
  // Tekil kabulde cihazlı iş açılır: seri okutulur, elle girilirse neden sorulur.
  const okutmaSorulur = !kompakt && !!sozluk?.seri_okutma_zorunlu;
  const tipler = sozluk?.ekipman_tipleri ?? [];
  const markalar = sozluk?.markalar ?? Object.keys(MARKA_ADLARI);
  // Telsiz birimi değilse marka serbest metin; kütükteki markalar öneri.
  const telsiz = !sozluk?.birim || TELSIZ_BIRIMLERI.has(sozluk.birim);
  const varsayilanTip = tipler[0] ? (TIP_ETIKETLERI[tipler[0]] ?? tipler[0]) : null;
  return (
    <Row gutter={8}>
      <Col xs={12} md={kompakt ? 4 : 6}>
        <Form.Item name={[...ad, "tip"]} label={kompakt ? undefined : "Tip"}>
          <Select
            allowClear
            placeholder={varsayilanTip ? `Tip (boşsa ${varsayilanTip})` : "Tip"}
            options={tipler.map((t) => ({ value: t, label: TIP_ETIKETLERI[t] ?? t }))}
          />
        </Form.Item>
      </Col>
      <Col xs={12} md={kompakt ? 4 : 6}>
        <Form.Item
          name={[...ad, "marka"]}
          label={kompakt ? undefined : "Marka"}
          rules={[{ required: true, whitespace: true, message: "Marka zorunlu" }]}
        >
          {telsiz ? (
            <Select
              placeholder="Marka"
              options={markalar.map((m) => ({ value: m, label: MARKA_ADLARI[m] ?? m }))}
            />
          ) : (
            <AutoComplete
              placeholder="Marka (yazın)"
              maxLength={60}
              options={markalar.filter((m) => m !== "DIGER").map((m) => ({ value: m }))}
              filterOption={(girdi, o) =>
                String(o?.value ?? "").toLocaleLowerCase("tr").includes(girdi.toLocaleLowerCase("tr"))
              }
            />
          )}
        </Form.Item>
      </Col>
      {telsiz && marka === "DIGER" && (
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
          <ModelSecici marka={(telsiz && marka === "DIGER" ? markaDiger : marka) as string | undefined} />
        </Form.Item>
      </Col>
      <Col xs={12} md={kompakt ? 4 : 6}>
        <Form.Item
          name={[...ad, "seri"]}
          label={kompakt ? undefined : "Seri no"}
          rules={[{ required: true, whitespace: true, message: "Seri numarası zorunlu" }]}
        >
          {/* KARARLAR 2026-11-20 §4: barkod okuyucu seriyi yazıp Enter'a basar;
              Enter formu göndermez, okunan seri alanda kalır. Kamera düğmesi
              telefonla okutur; kaynak (okutuldu/elle) ayrı alana yazılır. */}
          <SeriAlani
            placeholder="Seri no (barkod okutun)"
            onKaynak={(k) => form.setFieldValue([...(kok ?? ad), "okuma_kaynagi"], k)}
          />
        </Form.Item>
        <Form.Item name={[...ad, "okuma_kaynagi"]} hidden>
          <Input />
        </Form.Item>
      </Col>
      {okutmaSorulur && !!seri?.trim() && okumaKaynagi !== "OKUTMA" && (
        <Col xs={24} md={12}>
          <Form.Item
            name={[...ad, "elle_gerekce"]}
            label="Seri okutulmadı: neden?"
            rules={[{ required: true, message: "Elle girilen seri için neden seçin" }]}
          >
            <Select options={ELLE_GEREKCELERI.map((g) => ({ value: g.kod, label: g.ad }))} />
          </Form.Item>
        </Col>
      )}
      {okutmaSorulur && !!seri?.trim() && okumaKaynagi !== "OKUTMA" && elleGerekce === "DIGER" && (
        <Col xs={24} md={12}>
          <Form.Item
            name={[...ad, "elle_aciklama"]}
            label="Açıklama"
            rules={[{ required: true, whitespace: true, message: "Açıklama yazın" }]}
          >
            <Input maxLength={200} />
          </Form.Item>
        </Col>
      )}
    </Row>
  );
}

/**
 * Model seçimi: markanın kayıtlı modelleri. `atolye.model_ekle` izni olan
 * kullanıcı, listede olmayan adı yazıp "ekle" seçeneğiyle listeye ekler.
 * Değer düz model adıdır (sunucu serbest metni de kabul eder).
 */
function ModelSecici({
  marka,
  value,
  onChange,
}: {
  marka?: string;
  value?: string;
  onChange?: (v: string | undefined) => void;
}) {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const [arama, setArama] = useState("");
  const temizMarka = marka?.trim() || "";
  const liste = useQuery({
    queryKey: ["atolye-modeller", temizMarka.toLocaleLowerCase("tr")],
    queryFn: () => atolyeApi.modeller(temizMarka),
    enabled: !!temizMarka,
    staleTime: 5 * 60_000,
  });
  const ekle = useMutation({
    mutationFn: (model: string) => atolyeApi.modelEkle(temizMarka, model),
    onSuccess: (m) => {
      void qc.invalidateQueries({ queryKey: ["atolye-modeller"] });
      message.success(`Model eklendi: ${m.model}`);
      onChange?.(m.model);
      setArama("");
    },
    onError: (e: Error) => void message.error(e.message),
  });
  const adlar = (liste.data ?? []).map((m) => m.model);
  // Eski kayıttan gelen ya da listede olmayan değer de görünsün.
  if (value && !adlar.some((a) => a.toLocaleLowerCase("tr") === value.toLocaleLowerCase("tr")))
    adlar.unshift(value);
  const yazilan = arama.trim();
  const eklenebilir =
    yetkili("atolye.model_ekle") &&
    !!temizMarka &&
    !!yazilan &&
    !adlar.some((a) => a.toLocaleLowerCase("tr") === yazilan.toLocaleLowerCase("tr"));
  const EKLE = "__yeni_model__";
  return (
    <Select
      showSearch={{
        searchValue: arama,
        onSearch: setArama,
        filterOption: (girdi, o) =>
          o?.value === EKLE ||
          String(o?.value ?? "").toLocaleLowerCase("tr").includes(girdi.toLocaleLowerCase("tr")),
      }}
      allowClear
      value={value || undefined}
      placeholder={temizMarka ? "Model" : "Önce marka"}
      disabled={!temizMarka && !value}
      loading={liste.isFetching || ekle.isPending}
      notFoundContent={
        yazilan ? "Listede yok — model ekleme yetkisi olan kişi ekleyebilir" : "Bu markada kayıtlı model yok"
      }
      options={[
        ...adlar.map((a) => ({ value: a, label: a })),
        ...(eklenebilir ? [{ value: EKLE, label: <Typography.Link>+ "{yazilan}" modelini ekle</Typography.Link> }] : []),
      ]}
      onChange={(v: string | undefined) => {
        if (v === EKLE) {
          ekle.mutate(yazilan);
          return;
        }
        onChange?.(v);
        setArama("");
      }}
      popupMatchSelectWidth={false}
    />
  );
}

export default function AtolyeKabulPenceresi({
  acik,
  kapat,
  bitti,
  birim,
}: {
  acik: boolean;
  kapat: () => void;
  /** Varsayılan kabul birimi (atölye listesindeki birim süzgeci); yoksa sunucu seçer. */
  birim?: string;
  /** Tek kabulde yeni kaydın detayı; toplu kabulde grup numarası ve servis işi kimlikleri. */
  bitti: (sonuc: { detay?: AtolyeDetay; grup?: number; soIdler: number[] }) => void;
}) {
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<FormDegeri>();
  const [mod, setMod] = useState<"TEK" | "TOPLU">("TEK");
  const [irtibatPenceresi, setIrtibatPenceresi] = useState(false);
  const [irtibatForm] = Form.useForm<{ ad: string; unvan?: string; telefon?: string }>();
  const [garantiKutukten, setGarantiKutukten] = useState(false);
  const [irtibatlar, setIrtibatlar] = useState<SahaOnerisi["irtibatlar"]>([]);
  const [adaylar, setAdaylar] = useState<
    { id: number; marka: string | null; model: string | null; seri: string | null; account_id: number | null }[]
  >([]);
  const [hata, setHata] = useState<string | null>(null);
  const [secilenBirim, setSecilenBirim] = useState<string | undefined>(birim);
  const { menuBirimleri } = useSirket();

  // Birim verilmezse sunucu kullanıcının birimini seçer ve yanıtta `birim` döner;
  // belirsizse 400 "Kabul birimini seçin" → pencerede birim seçici gösterilir.
  const sozluk = useQuery({
    queryKey: ["atolye-kabul-form-verileri", secilenBirim ?? null],
    queryFn: () => atolyeApi.formVerileri(secilenBirim),
    enabled: acik,
    staleTime: 5 * 60_000,
    retry: (n, e) => !(e instanceof ApiError && e.status === 400) && n < 2,
  });
  const birimSecenekleri = [...(menuBirimleri ?? [])].map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }));
  const birimSecilmeli = sozluk.error instanceof ApiError && sozluk.error.status === 400;

  const tekCihaz = Form.useWatch("cihaz", form);
  const [sorgulananSeri, setSorgulananSeri] = useState<{ tip: string; marka: string; seri: string } | null>(
    null,
  );
  useEffect(() => {
    if (mod !== "TEK") return;
    const seri = tekCihaz?.seri?.trim();
    const marka = (tekCihaz?.marka === "DIGER" ? tekCihaz?.marka_diger : tekCihaz?.marka)?.trim();
    // Tip boşsa birimin varsayılan tipi (sunucu kabulde de aynısını kullanır).
    const tip = tekCihaz?.tip ?? sozluk.data?.ekipman_tipleri[0];
    if (!seri || !marka || !tip) {
      setSorgulananSeri(null);
      return;
    }
    const t = setTimeout(() => setSorgulananSeri({ tip, marka, seri }), 400);
    return () => clearTimeout(t);
  }, [mod, tekCihaz?.tip, tekCihaz?.marka, tekCihaz?.marka_diger, tekCihaz?.seri, sozluk.data]);

  const gecmis = useQuery({
    queryKey: ["atolye-seri-gecmisi", sorgulananSeri],
    queryFn: () => atolyeApi.seriGecmisi(sorgulananSeri!),
    enabled: acik && !!sorgulananSeri,
  });

  // Garanti tarihleri kütükteki ekipmandan (tek eşleşmede) otomatik dolar;
  // elle girilmiş tarihin üstüne yazılmaz.
  useEffect(() => {
    if (mod !== "TEK") return;
    const adaylar = gecmis.data?.ekipmanlar ?? [];
    if (adaylar.length !== 1) return;
    const e = adaylar[0];
    const mevcut = form.getFieldValue("cihaz") as CihazSatiri | undefined;
    const yeni: Partial<CihazSatiri> = {};
    if (e.warranty_start && !mevcut?.warranty_start) yeni.warranty_start = dayjs(e.warranty_start);
    if (e.warranty_end && !mevcut?.warranty_end) yeni.warranty_end = dayjs(e.warranty_end);
    if (Object.keys(yeni).length) {
      form.setFieldsValue({ cihaz: { ...mevcut, ...yeni } as CihazSatiri });
      setGarantiKutukten(true);
    }
  }, [gecmis.data, mod, form]);

  // Firma seçilince müşterinin TÜM irtibatları listelenir (lokasyon irtibatı
  // seçiciden önerilir); tek kişi varsa kendiliğinden seçilir.
  const musteriId = (Form.useWatch("musteri", form) as MusteriLokasyonSecimi | undefined)?.musteriId ?? null;
  const kisiler = useQuery({
    queryKey: ["atolye-irtibatlar", musteriId],
    queryFn: () => atolyeApi.irtibatlar(musteriId!),
    enabled: acik && !!musteriId,
  });
  useEffect(() => {
    const k = kisiler.data ?? [];
    if (k.length === 1 && !form.getFieldValue("contact_id")) form.setFieldValue("contact_id", k[0].id);
  }, [kisiler.data, form]);
  const irtibatSecenekleri = (() => {
    const gorulen = new Set<number>();
    const satirlar: { value: number; label: string }[] = [];
    for (const k of kisiler.data ?? []) {
      gorulen.add(k.id);
      satirlar.push({ value: k.id, label: [k.ad, k.unvan, k.telefon].filter(Boolean).join(" · ") });
    }
    for (const i of irtibatlar ?? [])
      if (!gorulen.has(i.id)) satirlar.push({ value: i.id, label: i.ad });
    return satirlar;
  })();
  const irtibatEkle = useMutation({
    mutationFn: (g: { ad: string; unvan?: string; telefon?: string }) =>
      atolyeApi.irtibatEkle({
        musteri_id: musteriId!,
        ad: g.ad,
        unvan: g.unvan || null,
        telefon: g.telefon || null,
      }),
    onSuccess: (k) => {
      void qc.invalidateQueries({ queryKey: ["atolye-irtibatlar", musteriId] });
      form.setFieldValue("contact_id", k.id);
      setIrtibatPenceresi(false);
      message.success(`İrtibat eklendi: ${k.ad}`);
    },
    onError: (e: Error) => void message.error(e.message),
  });

  const vazgec = () => {
    if (!form.isFieldsTouched()) {
      kapat();
      return;
    }
    modal.confirm({
      title: "Girilen bilgiler kaydedilmedi",
      content: "Pencere kapanırsa bu kabul için yazdıklarınız silinir.",
      okText: "Kapat, sil",
      okButtonProps: { danger: true },
      cancelText: "Forma dön",
      onOk: kapat,
    });
  };

  useEffect(() => {
    if (acik) {
      form.resetFields();
      setSecilenBirim(birim);
      setMod("TEK");
      setAdaylar([]);
      setHata(null);
      setIrtibatlar([]);
      setGarantiKutukten(false);
    }
    // Pencere her açılışta listedeki birimle başlar.
  }, [acik, form, birim]);

  const gonder = useMutation({
    mutationFn: async (args: { v: FormDegeri; ekipmanId?: number }) => {
      const { v, ekipmanId } = args;
      const ortak: KabulOrtak = {
        // Sözlüğün (marka/tip listesi) birimiyle aynı birim gönderilir.
        ...(sozluk.data?.birim ? { birim: sozluk.data.birim } : {}),
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
      const aksesuarlar = aksesuarTemizle(v.aksesuarlar);
      if (mod === "TEK") {
        const ekipman = ekipmanId
          ? { ekipman_id: ekipmanId, ...(v.cihaz.tip ? { tip: v.cihaz.tip } : {}), ...okumaAlanlari(v.cihaz) }
          : ekipmanGovdesi(v.cihaz);
        const detay = await atolyeApi.kabul({ ...ortak, ekipman, aksesuarlar });
        return { detay, soIdler: [detay.so_id] };
      }
      const r = await atolyeApi.topluKabul({
        ...ortak,
        cihazlar: (v.cihazlar ?? []).map((c) => ({
          ...ekipmanGovdesi(c),
          aksesuarlar: aksesuarTemizle(c.aksesuarlar),
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
    if (!sozluk.data) {
      message.error(birimSecilmeli ? "Kabul birimini seçin" : "Form verileri yüklenemedi");
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
      onCancel={vazgec}
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
        {(birimSecenekleri.length > 1 || birimSecilmeli) && (
          <Space wrap>
            <Typography.Text>Kabul birimi:</Typography.Text>
            <Select
              size="small"
              style={{ minWidth: 180 }}
              placeholder="Birim seçin"
              status={birimSecilmeli ? "error" : undefined}
              value={secilenBirim ?? sozluk.data?.birim}
              options={birimSecenekleri}
              onChange={(b: string) => {
                setSecilenBirim(b);
                // Tip/marka listesi birime göre değişir; girilen cihaz alanları sıfırlanır.
                form.setFieldsValue({ cihaz: {}, cihazlar: [{ aksesuarlar: [] }] });
              }}
            />
          </Space>
        )}
        {birimSecilmeli && (
          <Alert type="warning" showIcon title="Kabul birimini seçin" description={(sozluk.error as Error).message} />
        )}
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
            cihaz: {},
            cihazlar: [{ aksesuarlar: [] }],
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
              <Form.Item
                label={
                  <Space size={8}>
                    <span>İrtibat</span>
                    {musteriId && (
                      <Typography.Link
                        style={{ fontSize: 12 }}
                        onClick={() => {
                          irtibatForm.resetFields();
                          setIrtibatPenceresi(true);
                        }}
                      >
                        + Yeni
                      </Typography.Link>
                    )}
                  </Space>
                }
              >
                <Form.Item name="contact_id" noStyle>
                  <Select
                    allowClear
                    showSearch={{ optionFilterProp: "label" }}
                    loading={kisiler.isFetching}
                    placeholder={musteriId ? "İlgili kişi seçin" : "Önce müşteri"}
                    notFoundContent="Bu müşteride kayıtlı kişi yok — + Yeni ile ekleyin"
                    options={irtibatSecenekleri}
                  />
                </Form.Item>
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
              {garantiKutukten && (
                <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: -12, marginBottom: 8 }}>
                  Garanti tarihleri cihaz kütüğünden getirildi.
                </Typography.Text>
              )}
              {gecmis.data && <SeriGecmisiKutusu gecmis={gecmis.data} />}
            </>
          ) : (
            <Form.List name="cihazlar">
              {(alanlar, { add, remove }) => (
                <Space orientation="vertical" style={{ width: "100%" }} size={0}>
                  {alanlar.map(({ key, name }, i) => (
                    <Row key={key} gutter={8} align="top" wrap={false}>
                      <Col flex="28px" style={{ paddingTop: 6 }}>
                        <Typography.Text type="secondary">{i + 1}.</Typography.Text>
                      </Col>
                      <Col flex="auto" style={{ minWidth: 0 }}>
                        <CihazAlanlari ad={[name]} kok={["cihazlar", name]} sozluk={s} kompakt />
                        <Form.Item name={[name, "customer_complaint"]} style={{ marginTop: -16 }}>
                          <Input maxLength={4000} placeholder="Bu cihaza özel şikâyet (isteğe bağlı)" />
                        </Form.Item>
                        <Space size={8} style={{ marginBottom: 4 }}>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            Aksesuarlar
                          </Typography.Text>
                          {i > 0 && (
                            <Button
                              size="small"
                              type="link"
                              icon={<CopyOutlined />}
                              style={{ padding: 0, height: "auto" }}
                              onClick={() =>
                                form.setFieldValue(
                                  ["cihazlar", name, "aksesuarlar"],
                                  (form.getFieldValue(["cihazlar", alanlar[i - 1].name, "aksesuarlar"]) ?? []).map(
                                    (a: AksesuarGirdisi) => ({ ...a }),
                                  ),
                                )
                              }
                            >
                              Üstteki cihazla aynı
                            </Button>
                          )}
                        </Space>
                        <Form.Item name={[name, "aksesuarlar"]} style={{ marginBottom: 16 }}>
                          <AksesuarSecici turler={s?.aksesuar_turleri ?? []} />
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
                    onClick={() => {
                      // Yeni cihaz bir öncekinin aksesuarlarıyla başlar (aynı tip cihazlar
                      // çoğunlukla aynı aksesuarla gelir); kutucuklardan değiştirilir.
                      const onceki = (form.getFieldValue("cihazlar") as CihazSatiri[] | undefined)?.at(-1);
                      add({ aksesuarlar: (onceki?.aksesuarlar ?? []).map((a) => ({ ...a })) });
                    }}
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

          {mod === "TEK" && (
            <>
              <Divider titlePlacement="start" style={{ margin: "8px 0" }}>
                Aksesuarlar
              </Divider>
              <Form.Item name="aksesuarlar">
                <AksesuarSecici turler={s?.aksesuar_turleri ?? []} />
              </Form.Item>
            </>
          )}

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
      <Modal
        title="Yeni irtibat"
        open={irtibatPenceresi}
        onCancel={() => setIrtibatPenceresi(false)}
        onOk={() => irtibatForm.submit()}
        okText="Ekle"
        cancelText="Vazgeç"
        confirmLoading={irtibatEkle.isPending}
        destroyOnHidden
        width={420}
      >
        <Form form={irtibatForm} layout="vertical" onFinish={(g) => irtibatEkle.mutate(g)}>
          <Form.Item
            name="ad"
            label="Ad soyad"
            rules={[{ required: true, whitespace: true, min: 2, message: "Ad soyad yazın" }]}
          >
            <Input maxLength={120} autoFocus />
          </Form.Item>
          <Form.Item name="unvan" label="Görevi">
            <Input maxLength={80} />
          </Form.Item>
          <Form.Item name="telefon" label="Telefon">
            <Input maxLength={30} placeholder="05xx xxx xx xx" />
          </Form.Item>
        </Form>
      </Modal>
    </Modal>
  );
}
