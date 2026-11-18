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
  Form,
  Input,
  InputNumber,
  Modal,
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
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useSirket } from "../auth/SirketContext";
import Statistic from "../components/Statistic";
import { TEKLIF_DURUM_ADLARI } from "../fiori/etiketlerEk";
import SatisIsleri from "./SatisIsleri";
import TeklifDonusumu from "./TeklifDonusumu";
import TeklifFormu from "./TeklifFormu";

/**
 * Teklifler — satış ve birimli (teknik servis) teklif aynı ekranda (TS-140…148).
 *
 * Birimli teklif iç onaydan geçer (TASLAK → ONAY_BEKLIYOR → ONAYLANDI →
 * GONDERILDI …); düğmeler sunucunun `sonraki_durumlar` listesinden çizilir,
 * izin ve kural yine sunucuda. Satış teklifinin akışı aynen korunur
 * (iskonto onayı, karar, siparişe dönüştürme). Birimli teklif siparişe
 * DÖNÜŞMEZ (sunucu 409; düğme de gösterilmez).
 */

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
  service_order_id?: number | null;
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
  approved_at?: string | null;
  sent_channel?: string | null;
  sent_note?: string | null;
  public_url: string | null;
  kalemler: Kalem[];
}

interface Teklif {
  id: number;
  quote_no: string;
  customer_id: number;
  customer_title: string | null;
  owner_id: number | null;
  owner_ad?: string | null;
  status: string;
  title: string | null;
  lost_reason: string | null;
  lost_reason_kod?: string | null;
  lost_reason_adi?: string | null;
  version: number;
  onay_gerekiyor: boolean;
  iskonto_orani?: number | null;
  iskonto_limiti?: number | null;
  iskonto_onay_kademesi?: string | null;
  iskonto_onay_kademesi_adi?: string | null;
  guncel: Versiyon | null;
  versiyon_sayisi: number;
  birim?: string | null;
  service_order_id?: number | null;
  so_no?: string | null;
  contact_id?: number | null;
  address_id?: number | null;
  etkin_durum?: string | null;
  sonraki_durumlar?: string[];
  submitted_by_ad?: string | null;
  submitted_at?: string | null;
  approved_by_ad?: string | null;
  cancel_reason?: string | null;
  cancelled_at?: string | null;
  teklif_no_gosterim?: string | null;
  uyarilar?: string[];
}

interface Gonderim {
  id: number;
  kanal: string;
  alicilar: string[] | null;
  cc: string | null;
  sonuc: string;
  hata_ozeti: string | null;
  notlar: string | null;
  created_at: string;
  gonderen: string | null;
}

interface GecmisSatiri {
  zaman: string;
  eylem_adi: string;
  kullanici: string | null;
  eski_durum: string | null;
  yeni_durum: string | null;
  neden: string | null;
  kanal: string | null;
  versiyon: number | null;
}

interface KayipNedeni {
  kod: string;
  ad: string;
  aciklama_zorunlu: boolean;
}

/** Keşif istenebilen teklif durumları (sunucu `KESIF_ISTENEBILIR`). */
const KESIF_ACIK = ["TASLAK", "ONAY_BEKLIYOR", "ONAYLANDI", "GONDERILDI", "GORUNTULENDI", "REVIZE_EDILDI"];

interface Kpi {
  kod: string;
  baslik: string;
  deger: number;
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
  vat_rate?: number;
  service_order_id?: number | null;
}

const tl = (v: number | null | undefined, para = "TRY") =>
  v == null
    ? "—"
    : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ${
        para === "TRY" ? "₺" : para
      }`;

const DURUM_ADLARI = TEKLIF_DURUM_ADLARI;

const DURUM_RENGI: Record<string, string> = {
  TASLAK: "default",
  ONAY_BEKLIYOR: "gold",
  ONAYLANDI: "lime",
  GONDERILDI: "blue",
  GORUNTULENDI: "cyan",
  REVIZE_EDILDI: "purple",
  KABUL: "green",
  RED: "red",
  SURESI_DOLDU: "default",
  SIPARISE_DONUSTU: "green",
  IPTAL: "default",
};

const ELLE_KANALLAR = [
  { value: "ELDEN", label: "Elden teslim" },
  { value: "KARGO", label: "Kargo" },
  { value: "HARICI_EPOSTA", label: "Harici e-posta" },
  { value: "DIGER", label: "Diğer" },
];

const KANAL_ADLARI: Record<string, string> = {
  EPOSTA: "E-posta",
  ELDEN: "Elden",
  KARGO: "Kargo",
  HARICI_EPOSTA: "Harici e-posta",
  DIGER: "Diğer",
};

const durumAdi = (d: string | null | undefined) => (d ? (DURUM_ADLARI[d] ?? d) : "—");

/** Kalem satırları — revizyon ve taslak düzenleme formunda ortak. */
function KalemAlanlari({
  urunler,
  birimli,
  mobilite,
}: {
  urunler: Urun[];
  birimli: boolean;
  /** Abonelik / SIM paketi mobilite kalemidir; yalnız DENGE MOBİLİTE etkinken. */
  mobilite: boolean;
}) {
  const form = Form.useFormInstance();
  const tipler = [
    { value: "URUN", label: "Ürün" },
    { value: "HIZMET", label: "Hizmet" },
    ...(birimli
      ? [{ value: "ISCILIK", label: "İşçilik" }]
      : mobilite
        ? [
            { value: "ABONELIK", label: "Abonelik" },
            { value: "SIM_PAKETI", label: "SIM paketi" },
          ]
        : []),
    { value: "SERBEST", label: "Serbest" },
  ];
  return (
    <Form.List name="kalemler">
      {(alanlar, { add, remove }) => (
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          {alanlar.map(({ key, name, ...rest }) => {
            const tip: string = form.getFieldValue(["kalemler", name, "item_type"]) ?? "URUN";
            return (
              <Space key={key} align="start" wrap>
                <Form.Item {...rest} name={[name, "item_type"]} noStyle initialValue="URUN">
                  <Select style={{ width: 120 }} options={tipler} onChange={() => form.setFields([])} />
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
                      options={urunler.map((u) => ({ value: u.id, label: `${u.code} · ${u.name}` }))}
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
                      <Input
                        placeholder="Açıklama"
                        style={{ width: 280 }}
                        maxLength={birimli ? 500 : 300}
                      />
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
                {birimli && (
                  <Form.Item {...rest} name={[name, "vat_rate"]} noStyle initialValue={0.2}>
                    <Select
                      style={{ width: 90 }}
                      options={[0, 0.01, 0.1, 0.2].map((o) => ({ value: o, label: `KDV %${o * 100}` }))}
                    />
                  </Form.Item>
                )}
                <Form.Item {...rest} name={[name, "service_order_id"]} hidden>
                  <InputNumber />
                </Form.Item>
                <Button danger type="text" onClick={() => remove(name)}>
                  Sil
                </Button>
              </Space>
            );
          })}
          <Button onClick={() => add({ item_type: "URUN", qty: 1, discount_pct: 0 })}>Kalem ekle</Button>
        </Space>
      )}
    </Form.List>
  );
}

const kalemGovdesi = (k: KalemFormu) => ({
  item_type: k.item_type ?? "URUN",
  product_id: k.item_type === "URUN" ? k.product_id : null,
  description: k.description ?? null,
  qty: k.qty ?? 1,
  unit_price: k.item_type === "URUN" ? null : k.unit_price,
  discount_pct: k.discount_pct ?? 0,
  ...(k.vat_rate != null ? { vat_rate: k.vat_rate } : {}),
  ...(k.service_order_id ? { service_order_id: k.service_order_id } : {}),
});

export default function TekliflerPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili, kullanici } = useAuth();
  // Sipariş ekranı ve abonelik/SIM kalemleri yalnız DENGE MOBİLİTE'de (şirket
  // ucu yoksa süzgeç yok → canlı davranış).
  const { aktif: aktifSirket, destekleniyor: sirketDestekli } = useSirket();
  const mobilite = !sirketDestekli || aktifSirket?.kod === "MOBILITE";
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const servisIsiParam = params.get("servis_isi");

  const [durum, setDurum] = useState<string | undefined>();
  const [tur, setTur] = useState<"SATIS" | "SERVIS" | undefined>(
    (params.get("tur") as "SATIS" | "SERVIS" | null) ??
      ((kullanici?.birimler ?? []).length > 0 && !yetkili("siparis.gor") ? "SERVIS" : undefined),
  );
  const [birim, setBirim] = useState<string | undefined>();
  // Uyarı bağlantıları (`/teklifler?kpi=…&benim=1&kesif=…`) süzgeci URL'den açar.
  const [kpi, setKpi] = useState<string | undefined>(params.get("kpi") ?? undefined);
  const [benim, setBenim] = useState(params.get("benim") === "1");
  const [kesif, setKesif] = useState<string | undefined>(params.get("kesif") ?? undefined);
  const [donusumAcik, setDonusumAcik] = useState(false);
  const [arama, setArama] = useState("");
  const [sayfa, setSayfa] = useState(1);
  const [sekme, setSekme] = useState(servisIsiParam ? "yeni" : "liste");
  const [secili, setSecili] = useState<number | null>(null);
  const [revizeAcik, setRevizeAcik] = useState<null | "revize" | "duzenle">(null);
  const [gonderAcik, setGonderAcik] = useState(false);
  const [elleAcik, setElleAcik] = useState(false);
  const [revizeForm] = Form.useForm();
  const [gonderForm] = Form.useForm();
  const [elleForm] = Form.useForm();

  useEffect(() => {
    if (servisIsiParam) setSekme("yeni");
  }, [servisIsiParam]);

  const SAYFA = 50;
  const suzgec = new URLSearchParams();
  if (durum) suzgec.set("durum", durum);
  if (tur) suzgec.set("tur", tur);
  if (birim) suzgec.set("birim", birim);
  if (kpi) suzgec.set("kpi", kpi);
  if (benim && kullanici) suzgec.set("hazirlayan_id", String(kullanici.id));
  if (kesif) suzgec.set("kesif", kesif);
  if (arama.trim()) suzgec.set("q", arama.trim());

  const teklifler = useQuery({
    queryKey: ["teklifler", suzgec.toString(), sayfa],
    queryFn: () =>
      api.getSayfa<Teklif>(
        `/api/teklifler?${suzgec.toString()}&limit=${SAYFA}&offset=${(sayfa - 1) * SAYFA}`,
      ),
  });

  const ozetParam = new URLSearchParams();
  if (tur) ozetParam.set("tur", tur);
  if (birim) ozetParam.set("birim", birim);
  const ozet = useQuery({
    queryKey: ["teklifler", "ozet", ozetParam.toString()],
    queryFn: () => api.get<{ kpi: Kpi[]; takip_gun: number }>(`/api/teklifler/ozet?${ozetParam}`),
  });

  const detay = useQuery({
    queryKey: ["teklif", secili],
    queryFn: () => api.get<Teklif>(`/api/teklifler/${secili}`),
    enabled: secili != null,
  });
  const gonderimler = useQuery({
    queryKey: ["teklif", secili, "gonderimler"],
    queryFn: () => api.get<Gonderim[]>(`/api/teklifler/${secili}/gonderimler`),
    enabled: secili != null,
  });
  const gecmis = useQuery({
    queryKey: ["teklif", secili, "gecmis"],
    queryFn: () => api.get<GecmisSatiri[]>(`/api/teklifler/${secili}/gecmis`),
    enabled: secili != null,
  });

  const kayipNedenleri = useQuery({
    queryKey: ["kayip-nedenleri"],
    queryFn: () => api.get<KayipNedeni[]>("/api/satis-takip/kayip-nedenleri"),
    staleTime: Infinity,
  });

  const urunler = useQuery({
    queryKey: ["urunler-teklif"],
    queryFn: () => api.get<Urun[]>("/api/urunler?limit=500"),
    enabled: revizeAcik != null,
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["teklifler"] });
    void qc.invalidateQueries({ queryKey: ["teklif"] });
  };
  const hata = (e: ApiError) => message.error(e.message);
  const sonuc = (mesaj: string) => (t: Teklif) => {
    message.success(mesaj);
    for (const u of t?.uyarilar ?? []) message.warning(u);
    yenile();
  };

  const useEylem = (yol: string, mesaj: string) =>
    useMutation({
      mutationFn: ({ id, ...g }: { id: number } & Record<string, unknown>) =>
        api.post<Teklif>(`/api/teklifler/${id}/${yol}`, g),
      onSuccess: sonuc(mesaj),
      onError: hata,
    });

  const revize = useEylem("revize", "Yeni versiyon açıldı, önceki kilitlendi");
  const iskontoOnayla = useEylem("iskonto-onayla", "İskonto onaylandı");
  const onayaGonder = useEylem("onaya-gonder", "Teklif onaya gönderildi");
  const onayla = useEylem("onayla", "Teklif onaylandı");
  const geriCevir = useEylem("geri-cevir", "Teklif taslağa geri çevrildi");
  const iptal = useEylem("iptal", "Teklif iptal edildi");
  const karar = useEylem("karar", "Karar kaydedildi");
  const gonder = useMutation({
    mutationFn: ({ id, ...g }: { id: number; alicilar: string[]; mesaj?: string | null }) =>
      api.post<Teklif>(`/api/teklifler/${id}/gonder`, g),
    onSuccess: (t) => {
      sonuc("Teklif PDF ekiyle gönderildi")(t);
      setGonderAcik(false);
      gonderForm.resetFields();
    },
    onError: (e: ApiError) => {
      hata(e);
      // Başarısız deneme de günlüğe yazılır.
      void qc.invalidateQueries({ queryKey: ["teklif", secili, "gonderimler"] });
    },
  });
  const elleGonder = useMutation({
    mutationFn: ({ id, ...g }: { id: number; kanal: string; not: string }) =>
      api.post<Teklif>(`/api/teklifler/${id}/elle-gonderildi`, g),
    onSuccess: (t) => {
      sonuc("Gönderildi olarak işaretlendi")(t);
      setElleAcik(false);
      elleForm.resetFields();
    },
    onError: hata,
  });
  const duzenle = useMutation({
    mutationFn: ({ id, ...g }: { id: number } & Record<string, unknown>) =>
      api.put<Teklif>(`/api/teklifler/${id}`, g),
    onSuccess: (t) => {
      sonuc("Taslak güncellendi")(t);
      setRevizeAcik(null);
    },
    onError: hata,
  });
  const siparise = useMutation({
    mutationFn: (id: number) => api.post<{ order_no: string }>(`/api/siparisler/tekliften/${id}`),
    onSuccess: (o) => {
      message.success(`${o.order_no} siparişi açıldı`);
      yenile();
      navigate("/siparisler");
    },
    onError: hata,
  });

  const t = detay.data;
  const v = t?.guncel ?? null;
  const birimli = !!t?.birim;
  const sonraki = t?.sonraki_durumlar ?? [];

  function nedenSor(baslik: string, okText: string, calistir: (neden: string) => Promise<unknown>) {
    let neden = "";
    modal.confirm({
      title: baslik,
      content: (
        <Input.TextArea rows={3} placeholder="Neden (zorunlu)" onChange={(e) => (neden = e.target.value)} />
      ),
      okText,
      cancelText: "Vazgeç",
      onOk: () => {
        if (neden.trim().length < 5) {
          message.error("Neden en az 5 karakter olmalı");
          return Promise.reject();
        }
        return calistir(neden.trim());
      },
    });
  }

  function onayaGonderSor(teklif: Teklif) {
    let beklet = false;
    modal.confirm({
      title: `Onaya gönder · ${teklif.quote_no}`,
      content: teklif.service_order_id ? (
        <Checkbox onChange={(e) => (beklet = e.target.checked)}>
          {teklif.so_no} işini "teklif bekleniyor" beklemesine al
        </Checkbox>
      ) : (
        "Teklif servis yöneticisinin onayına gönderilecek."
      ),
      okText: "Onaya gönder",
      cancelText: "Vazgeç",
      onOk: () => onayaGonder.mutateAsync({ id: teklif.id, beklet }),
    });
  }

  /** S2.1: kaybedilme nedeni listeden seçilir; "Diğer"de açıklama zorunlu. */
  function redSor(id: number) {
    let kod: string | undefined;
    let aciklama = "";
    modal.confirm({
      title: "Teklif kaybedildi",
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Select
            style={{ width: "100%" }}
            placeholder="Kaybedilme nedeni"
            options={(kayipNedenleri.data ?? []).map((k) => ({ value: k.kod, label: k.ad }))}
            onChange={(x: string) => (kod = x)}
          />
          <Input.TextArea
            rows={3}
            maxLength={300}
            placeholder="Açıklama (Diğer seçildiyse zorunlu)"
            onChange={(e) => (aciklama = e.target.value)}
          />
        </Space>
      ),
      okText: "Kaybedildi olarak kaydet",
      cancelText: "Vazgeç",
      onOk: () => {
        if (!kod) {
          message.error("Kaybedilme nedenini seçin");
          return Promise.reject();
        }
        if (kod === "DIGER" && aciklama.trim().length < 3) {
          message.error("'Diğer' seçildiğinde açıklama zorunlu");
          return Promise.reject();
        }
        return karar.mutateAsync({
          id,
          kabul: false,
          kayip_nedeni_kod: kod,
          red_nedeni: aciklama.trim() || null,
        });
      },
    });
  }

  function formuAc(mod: "revize" | "duzenle") {
    if (!v || !t) return;
    revizeForm.setFieldsValue({
      valid_until: v.valid_until ? dayjs(v.valid_until) : undefined,
      title: t.title ?? undefined,
      kalemler: v.kalemler.map((k) => ({
        item_type: k.item_type,
        product_id: k.product_id ?? undefined,
        description: k.item_type === "URUN" ? undefined : k.description,
        qty: Number(k.qty),
        unit_price: Number(k.unit_price),
        discount_pct: Number(k.discount_pct),
        vat_rate: birimli ? Number(k.vat_rate) : undefined,
        service_order_id: k.service_order_id ?? null,
      })),
    });
    setRevizeAcik(mod);
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

  const disaAktarabilir = yetkili("rapor.disaaktar") || yetkili("servis_rapor.disaaktar");
  const gonderilebilir =
    t && v && (birimli ? ["ONAYLANDI", "GONDERILDI", "GORUNTULENDI"].includes(t.status) : !v.accepted_at);

  const listeEkrani = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Row gutter={[12, 12]}>
        {(ozet.data?.kpi ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={4}>
            <Card
              size="small"
              hoverable
              data-kpi={k.kod}
              onClick={() => {
                setKpi(kpi === k.kod ? undefined : k.kod);
                setSayfa(1);
              }}
              style={{ height: "100%", borderColor: kpi === k.kod ? "#de3a11" : undefined }}
            >
              <Statistic title={k.baslik} value={k.deger} />
            </Card>
          </Col>
        ))}
      </Row>
      <Card
        title="Teklifler"
        extra={
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="No, müşteri, konu"
              style={{ width: 200 }}
              onSearch={(x) => {
                setArama(x);
                setSayfa(1);
              }}
            />
            <Select
              allowClear
              placeholder="Tür"
              style={{ width: 120 }}
              value={tur}
              onChange={(x) => {
                setTur(x);
                setSayfa(1);
              }}
              options={[
                { value: "SATIS", label: "Satış" },
                { value: "SERVIS", label: "Servis" },
              ]}
            />
            {(kullanici?.birimler ?? []).length > 0 && (
              <Select
                allowClear
                placeholder="Birim"
                style={{ width: 140 }}
                value={birim}
                onChange={(x) => {
                  setBirim(x);
                  setSayfa(1);
                }}
                options={(kullanici?.birimler ?? []).map((b) => ({ value: b, label: b }))}
              />
            )}
            <Select
              allowClear
              placeholder="Durum"
              style={{ width: 170 }}
              value={durum}
              onChange={(x) => {
                setDurum(x);
                setSayfa(1);
              }}
              options={Object.keys(DURUM_ADLARI).map((d) => ({ value: d, label: DURUM_ADLARI[d] }))}
            />
            {kpi && (
              <Tag closable onClose={() => setKpi(undefined)} color="orange">
                {ozet.data?.kpi.find((k) => k.kod === kpi)?.baslik ?? kpi}
              </Tag>
            )}
            {benim && (
              <Tag closable onClose={() => setBenim(false)} color="orange">
                Hazırladığım teklifler
              </Tag>
            )}
            {kesif && (
              <Tag closable onClose={() => setKesif(undefined)} color="orange">
                {kesif === "TAMAMLANDI" ? "Keşfi tamamlanan" : "Keşfi süren"}
              </Tag>
            )}
            {disaAktarabilir && (
              <Button href={`/api/teklifler/disa-aktar.xlsx?${suzgec.toString()}`}>Excel</Button>
            )}
            {yetkili("teklif.gor", "servis_rapor.gor") && (kullanici?.birimler ?? []).length > 0 && (
              <Button onClick={() => setDonusumAcik(true)}>Dönüşüm raporu</Button>
            )}
          </Space>
        }
      >
        <TeklifDonusumu
          acik={donusumAcik}
          onKapat={() => setDonusumAcik(false)}
          birimler={kullanici?.birimler ?? []}
        />
        <Table
          rowKey="id"
          size="small"
          loading={teklifler.isLoading}
          dataSource={teklifler.data?.kayitlar ?? []}
          pagination={{
            current: sayfa,
            pageSize: SAYFA,
            total: teklifler.data?.toplam ?? 0,
            showSizeChanger: false,
            onChange: setSayfa,
            showTotal: (n) => `${n.toLocaleString("tr-TR")} teklif`,
          }}
          scroll={{ x: true }}
          onRow={(r) => ({ onClick: () => setSecili(r.id), style: { cursor: "pointer" } })}
          columns={[
            {
              title: "Teklif no",
              width: 160,
              className: "mono",
              render: (_: unknown, r: Teklif) => r.teklif_no_gosterim ?? r.quote_no,
            },
            {
              title: "Birim",
              dataIndex: "birim",
              width: 110,
              render: (x: string | null) => (x ? <Tag>{x}</Tag> : "Satış"),
            },
            { title: "Müşteri", dataIndex: "customer_title" },
            {
              title: "Konu / iş",
              render: (_: unknown, r: Teklif) => r.so_no ?? r.title ?? "—",
            },
            { title: "Ver.", dataIndex: "versiyon_sayisi", width: 60, className: "mono" },
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
              width: 200,
              render: (_: unknown, r: Teklif) => (
                <Space size={4} wrap>
                  <Tag color={DURUM_RENGI[r.etkin_durum ?? r.status]}>
                    {durumAdi(r.etkin_durum ?? r.status)}
                  </Tag>
                  {r.onay_gerekiyor && (
                    <Tooltip
                      title={`İskonto limiti aşıldı; ${r.iskonto_onay_kademesi_adi ?? "yönetici"} onayı olmadan gönderilemez`}
                    >
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
        title={t ? `${t.teklif_no_gosterim ?? t.quote_no} · ${t.customer_title ?? ""}` : "Teklif"}
        open={secili != null}
        size={860}
        onClose={() => setSecili(null)}
        loading={detay.isLoading}
        extra={
          t && (
            <Space wrap>
              <Button href={`/api/teklifler/${t.id}/pdf`} target="_blank">
                PDF
              </Button>
              {yetkili("teklif.yaz") && gonderilebilir && (
                <>
                  <Button onClick={() => setGonderAcik(true)}>E-posta ile gönder</Button>
                  <Button onClick={() => setElleAcik(true)}>Elle gönderildi</Button>
                </>
              )}
              {!birimli && mobilite && yetkili("siparis.yaz") && t.status === "KABUL" && (
                <Button type="primary" loading={siparise.isPending} onClick={() => siparise.mutate(t.id)}>
                  Siparişe dönüştür
                </Button>
              )}
            </Space>
          )
        }
      >
        {t && v && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            {(t.uyarilar ?? []).map((u) => (
              <Alert key={u} type="warning" showIcon title={u} />
            ))}
            {!birimli && t.onay_gerekiyor && (
              <Alert
                type="warning"
                showIcon
                title={`%${t.iskonto_orani ?? v.max_discount_pct} iskonto, hazırlayanın limitini (%${
                  t.iskonto_limiti ?? "—"
                }) aşıyor`}
                description={`${t.iskonto_onay_kademesi_adi ?? "Yönetici"} onaylamadan teklif gönderilemez. Fiyat ya da iskonto değişirse onay düşer.`}
                action={
                  yetkili("teklif.iskonto_onayla", "teklif.iskonto_ust_onay") ? (
                    <Button
                      size="small"
                      type="primary"
                      loading={iskontoOnayla.isPending}
                      onClick={() => iskontoOnayla.mutate({ id: t.id })}
                    >
                      Onayla
                    </Button>
                  ) : undefined
                }
              />
            )}
            {birimli && t.status === "ONAY_BEKLIYOR" && (
              <Alert
                type="info"
                showIcon
                title="İç onay bekleniyor"
                description={`${t.submitted_by_ad ?? ""} ${
                  t.submitted_at ? dayjs(t.submitted_at).format("DD.MM.YYYY HH:mm") : ""
                } tarihinde onaya gönderdi. Hazırlayan ya da gönderen kendi teklifini onaylayamaz.`}
              />
            )}
            {t.status === "IPTAL" && (
              <Alert type="error" showIcon title="Teklif iptal edildi" description={t.cancel_reason} />
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
              <Descriptions.Item label="Tür">
                {birimli ? <Tag>{t.birim}</Tag> : "Satış"}
                {t.so_no && (
                  <Typography.Link
                    onClick={() => navigate(`/servis-isleri/${t.service_order_id}`)}
                    style={{ marginLeft: 6 }}
                  >
                    {t.so_no}
                  </Typography.Link>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Durum">
                <Tag color={DURUM_RENGI[t.etkin_durum ?? t.status]}>
                  {durumAdi(t.etkin_durum ?? t.status)}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Versiyon">
                <span className="mono">
                  v{v.version_no} / {t.versiyon_sayisi}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Para birimi">
                {v.currency}
                {v.fx_rate ? ` · ${v.fx_rate} (${v.fx_source ?? ""})` : ""}
              </Descriptions.Item>
              <Descriptions.Item label="Hazırlayan">{t.owner_ad ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Onaylayan">{t.approved_by_ad ?? "—"}</Descriptions.Item>
              <Descriptions.Item label="Ara toplam">{tl(v.subtotal, v.currency)}</Descriptions.Item>
              <Descriptions.Item label="İskonto">{tl(v.discount_total, v.currency)}</Descriptions.Item>
              <Descriptions.Item label="KDV">{tl(v.vat_total, v.currency)}</Descriptions.Item>
              <Descriptions.Item label="Genel toplam">
                <strong>{tl(v.grand_total, v.currency)}</strong>
              </Descriptions.Item>
              <Descriptions.Item label="Geçerlilik">
                {v.valid_until ? dayjs(v.valid_until).format("DD.MM.YYYY") : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Gönderim">
                {v.sent_at ? dayjs(v.sent_at).format("DD.MM.YYYY HH:mm") : "—"}
                {v.sent_channel ? ` · ${KANAL_ADLARI[v.sent_channel] ?? v.sent_channel}` : ""}
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
              {(t.lost_reason_adi || v.reject_reason) && (
                <Descriptions.Item label="Kaybedilme nedeni" span={2}>
                  {t.lost_reason_adi ? <Tag>{t.lost_reason_adi}</Tag> : null}
                  {t.lost_reason ?? (t.lost_reason_adi ? "" : v.reject_reason)}
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
                {t.status === "TASLAK" && (
                  <Button onClick={() => formuAc("duzenle")}>Düzenle</Button>
                )}
                <Button
                  onClick={() => formuAc("revize")}
                  disabled={
                    ["KABUL", "SIPARISE_DONUSTU", "IPTAL"].includes(t.status) ||
                    (birimli && t.status === "TASLAK")
                  }
                >
                  Revize et
                </Button>
                {birimli && sonraki.includes("ONAY_BEKLIYOR") && (
                  <Button type="primary" loading={onayaGonder.isPending} onClick={() => onayaGonderSor(t)}>
                    Onaya gönder
                  </Button>
                )}
                {birimli && yetkili("teklif.onayla") && sonraki.includes("ONAYLANDI") && (
                  <Button type="primary" loading={onayla.isPending} onClick={() => onayla.mutate({ id: t.id })}>
                    Onayla
                  </Button>
                )}
                {birimli &&
                  yetkili("teklif.onayla") &&
                  ["ONAY_BEKLIYOR", "ONAYLANDI"].includes(t.status) && (
                    <Button
                      onClick={() =>
                        nedenSor("Taslağa geri çevir", "Geri çevir", (neden) =>
                          geriCevir.mutateAsync({ id: t.id, neden }),
                        )
                      }
                    >
                      Geri çevir
                    </Button>
                  )}
                {(birimli ? sonraki.includes("KABUL") : v.sent_at && !v.accepted_at && !v.rejected_at) && (
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
                {birimli && sonraki.includes("IPTAL") && (
                  <Button
                    danger
                    type="text"
                    onClick={() =>
                      nedenSor("Teklifi iptal et", "İptal et", (neden) => iptal.mutateAsync({ id: t.id, neden }))
                    }
                  >
                    İptal et
                  </Button>
                )}
              </Space>
            )}

            <Tabs
              size="small"
              items={[
                {
                  key: "kalemler",
                  label: `Kalemler (${v.kalemler.length})`,
                  children: (
                    <Table
                      rowKey="id"
                      size="small"
                      dataSource={v.kalemler}
                      pagination={false}
                      columns={kalemKolonlari}
                    />
                  ),
                },
                {
                  key: "servis-isleri",
                  label: "Keşif ve servis işleri",
                  children: (
                    <SatisIsleri
                      kaynak="teklif"
                      id={t.id}
                      birim={t.birim}
                      kesifAcik={KESIF_ACIK.includes(t.status)}
                      isAcilabilir={["KABUL", "SIPARISE_DONUSTU"].includes(t.status)}
                    />
                  ),
                },
                {
                  key: "gonderimler",
                  label: `Gönderimler (${gonderimler.data?.length ?? 0})`,
                  children: (
                    <Table<Gonderim>
                      rowKey="id"
                      size="small"
                      loading={gonderimler.isLoading}
                      dataSource={gonderimler.data ?? []}
                      pagination={false}
                      columns={[
                        {
                          title: "Zaman",
                          dataIndex: "created_at",
                          className: "mono",
                          render: (x: string) => dayjs(x).format("DD.MM.YYYY HH:mm"),
                        },
                        {
                          title: "Kanal",
                          dataIndex: "kanal",
                          render: (x: string) => KANAL_ADLARI[x] ?? x,
                        },
                        {
                          title: "Alıcı",
                          render: (_: unknown, g: Gonderim) =>
                            [...(g.alicilar ?? []), ...(g.cc ? [`cc: ${g.cc}`] : [])].join(", ") ||
                            g.notlar ||
                            "—",
                        },
                        { title: "Gönderen", dataIndex: "gonderen" },
                        {
                          title: "Sonuç",
                          dataIndex: "sonuc",
                          render: (x: string) =>
                            x === "BASARILI" ? <Tag color="green">başarılı</Tag> : <Tag color="red">hata</Tag>,
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "gecmis",
                  label: "Geçmiş",
                  children: (
                    <Timeline
                      items={(gecmis.data ?? []).map((g) => ({
                        content: (
                          <Space orientation="vertical" size={0}>
                            <Typography.Text strong>
                              {dayjs(g.zaman).format("DD.MM.YYYY HH:mm")} · {g.eylem_adi}
                            </Typography.Text>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              {g.kullanici ?? "Müşteri / sistem"}
                              {g.yeni_durum ? ` · ${durumAdi(g.eski_durum)} → ${durumAdi(g.yeni_durum)}` : ""}
                              {g.kanal ? ` · ${KANAL_ADLARI[g.kanal] ?? g.kanal}` : ""}
                              {g.neden ? ` · ${g.neden}` : ""}
                            </Typography.Text>
                          </Space>
                        ),
                      }))}
                    />
                  ),
                },
              ]}
            />
          </Space>
        )}
      </Drawer>

      <Modal
        title={t ? `Gönder · ${t.teklif_no_gosterim ?? t.quote_no}` : "Gönder"}
        open={gonderAcik}
        onCancel={() => setGonderAcik(false)}
        onOk={() => gonderForm.submit()}
        confirmLoading={gonder.isPending}
        okText="Gönder"
        cancelText="Vazgeç"
      >
        <Typography.Paragraph type="secondary">
          Gönderim versiyonu KİLİTLER. En çok 3 alıcı; size bilgi kopyası (CC) gider. Boş bırakılırsa
          irtibat ya da müşteri kartındaki adres kullanılır.
        </Typography.Paragraph>
        <Form
          form={gonderForm}
          layout="vertical"
          onFinish={(d) =>
            t && gonder.mutate({ id: t.id, alicilar: d.alicilar ?? [], mesaj: d.mesaj || null })
          }
        >
          <Form.Item
            name="alicilar"
            label="Alıcılar"
            rules={[
              {
                validator: (_, x: string[] | undefined) =>
                  (x ?? []).length > 3
                    ? Promise.reject(new Error("En çok 3 alıcı"))
                    : (x ?? []).some((a) => !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a))
                      ? Promise.reject(new Error("Geçersiz e-posta adresi"))
                      : Promise.resolve(),
              },
            ]}
          >
            <Select mode="tags" tokenSeparators={[",", " ", ";"]} placeholder="ad@firma.com" open={false} />
          </Form.Item>
          <Form.Item name="mesaj" label="Mesaj">
            <Input.TextArea rows={3} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Gönderildi olarak işaretle"
        open={elleAcik}
        onCancel={() => setElleAcik(false)}
        onOk={() => elleForm.submit()}
        confirmLoading={elleGonder.isPending}
        okText="Kaydet"
        cancelText="Vazgeç"
      >
        <Form
          form={elleForm}
          layout="vertical"
          onFinish={(d) => t && elleGonder.mutate({ id: t.id, kanal: d.kanal, not: d.not })}
        >
          <Form.Item name="kanal" label="Kanal" rules={[{ required: true, message: "Kanal seçin" }]}>
            <Select options={ELLE_KANALLAR} />
          </Form.Item>
          <Form.Item
            name="not"
            label="Not"
            rules={[{ required: true, min: 3, message: "Gönderim notu zorunlu (en az 3 karakter)" }]}
          >
            <Input.TextArea rows={2} maxLength={300} placeholder="Kime, nasıl iletildi" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t ? `${revizeAcik === "duzenle" ? "Düzenle" : "Revize"} · ${t.quote_no}` : "Revize"}
        open={revizeAcik != null}
        onCancel={() => setRevizeAcik(null)}
        onOk={() => revizeForm.submit()}
        confirmLoading={revize.isPending || duzenle.isPending}
        okText={revizeAcik === "duzenle" ? "Kaydet" : "Yeni versiyon aç"}
        cancelText="Vazgeç"
        width={960}
      >
        {revizeAcik === "revize" && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            title="Önceki versiyon kilitlenir ve görüntülenebilir kalır"
            description="Kalem fiyatları kaynak versiyondan taşınır — ürün kartındaki güncel fiyat değil, müşteriye gösterilen fiyat esastır."
          />
        )}
        <Form
          form={revizeForm}
          layout="vertical"
          onFinish={(d) => {
            if (!t || !v) return;
            const kalemler = (d.kalemler ?? []).map(kalemGovdesi);
            const gecerlilik = d.valid_until ? dayjs(d.valid_until).format("YYYY-MM-DD") : null;
            if (revizeAcik === "duzenle") {
              duzenle.mutate({
                id: t.id,
                version: t.version,
                customer_id: t.customer_id,
                title: d.title || null,
                currency: v.currency,
                fx_rate: v.fx_rate,
                fx_date: v.fx_date,
                valid_until: gecerlilik,
                birim: t.birim ?? null,
                service_order_id: t.service_order_id ?? null,
                contact_id: t.contact_id ?? null,
                address_id: t.address_id ?? null,
                kalemler,
              });
            } else {
              revize.mutate(
                { id: t.id, valid_until: gecerlilik, notes: d.notes || null, kalemler },
                { onSuccess: () => setRevizeAcik(null) },
              );
            }
          }}
        >
          <Space wrap align="start">
            {revizeAcik === "duzenle" && (
              <Form.Item name="title" label="Konu">
                <Input style={{ width: 320 }} maxLength={200} />
              </Form.Item>
            )}
            <Form.Item name="valid_until" label="Geçerlilik">
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            {revizeAcik === "revize" && (
              <Form.Item name="notes" label="Not">
                <Input style={{ width: 420 }} placeholder="Revizyon gerekçesi" />
              </Form.Item>
            )}
          </Space>
          <Form.Item label="Kalemler">
            <KalemAlanlari urunler={urunler.data ?? []} birimli={birimli} mobilite={mobilite} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );

  return (
    <Tabs
      activeKey={sekme}
      onChange={(k) => {
        setSekme(k);
        if (k === "liste" && servisIsiParam) setParams({});
      }}
      items={[
        { key: "liste", label: "Teklifler", children: listeEkrani },
        ...(yetkili("teklif.yaz")
          ? [
              {
                key: "yeni",
                label: "Yeni teklif",
                children: (
                  <TeklifFormu
                    servisIsiId={servisIsiParam ? Number(servisIsiParam) : undefined}
                    onKaydedildi={(id) => {
                      setSekme("liste");
                      if (servisIsiParam) setParams({});
                      if (id) setSecili(id);
                    }}
                  />
                ),
              },
            ]
          : []),
      ]}
    />
  );
}
