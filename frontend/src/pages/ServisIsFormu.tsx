/**
 * Servis İşi Formu — açılış/düzenleme formu (TS-033/034).
 *
 * - Müşteri → lokasyon seçimi `MusteriLokasyonSecici` ile SUNUCUDA aranır
 *   (300 ms gecikmeli); seçilen lokasyonun birincil irtibatı forma önerilir,
 *   kullanıcı değiştirebilir. Kart IBAN/VKN göstermez. Hızlı müşteri ekleme
 *   `servis.yaz + lokasyon.yaz` olana görünür (seçicinin kendi kuralı).
 * - Seri girildikçe açık işte aynı seri sorulur (yalnız uyarı); kayıtta
 *   sunucu 409 `MUKERRER` dönerse kullanıcı listeyi görüp "yine de aç" der.
 * - "Telefonla/uzaktan çözüldü" (`servis.uzaktan_coz`): açılış + sonuç tek
 *   istekte (iş TAMAMLANDI doğar; şef ayrıca kapatır).
 * - Düzenlemede `version` gönderilir (iyimser kilit): başkası değiştirdiyse
 *   409 → çağıran kaydı yeniler. Kapalı işte düzeltme gerekçe ister.
 */
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Col,
  DatePicker,
  Divider,
  Form,
  Input,
  Radio,
  Row,
  Select,
  Space,
  Switch,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "../api/client";
import {
  ONCELIK_ADLARI,
  teknikServisApi,
  type FormVerileri,
  type IsDetayi,
  type IsGirdisi,
  type MukerrerSonucu,
} from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import MusteriLokasyonSecici, {
  type MusteriLokasyonSecimi,
  type SahaOnerisi,
} from "../components/MusteriLokasyonSecici";

interface FormDegeri {
  birim: string;
  tur: string;
  oncelik: string;
  talep_kanali: string;
  reported_at: Dayjs | null;
  musteri: MusteriLokasyonSecimi;
  iletisim_ad?: string;
  iletisim_telefon?: string;
  konu: string;
  aciklama?: string;
  seriler: string[];
  proje?: string;
  sistem?: string;
  uzaktan: boolean;
  cozum_kanali?: "TELEFON" | "UZAKTAN";
  yapilan_islem?: string;
  ariza_nedeni_id?: number;
  gerekce?: string;
  /** Yalnız düzenlemede ve `servis.kapat` ile (E01-16; gerekçe zorunlu). */
  kategori?: string;
}

const KAPALI = ["TAMAMLANDI", "KAPATILDI", "IPTAL"];

/** Kişiyi listeleyen mükerrer satırı (yalnız kullanıcının görebildiği işler). */
function MukerrerUyarisi({ m }: { m: MukerrerSonucu | null }) {
  if (!m || (!m.mukerrer.length && !m.kapsam_disi_var && !m.ayni_lokasyon.length)) return null;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size={4}>
      {(m.mukerrer.length > 0 || m.kapsam_disi_var) && (
        <Alert
          type="warning"
          showIcon
          message="Aynı seri numarasıyla açık servis işi var"
          description={
            m.mukerrer.length
              ? m.mukerrer.map((x) => x.so_no).join(", ")
              : "Başka birimde açık kayıt var (numarası gösterilmez)."
          }
        />
      )}
      {m.ayni_lokasyon.length > 0 && (
        <Alert
          type="info"
          showIcon
          message={`Bu müşteri ve lokasyonda açık iş var: ${m.ayni_lokasyon.map((x) => x.so_no).join(", ")}`}
        />
      )}
    </Space>
  );
}

export default function ServisIsFormu({
  is: mevcut,
  formVerileri,
  onKaydedildi,
  onVazgec,
  onCakisma,
}: {
  /** Verilirse düzenleme; yoksa yeni iş. */
  is?: IsDetayi | null;
  formVerileri?: FormVerileri;
  onKaydedildi: (d: IsDetayi) => void;
  onVazgec: () => void;
  /** 409 (başkası değiştirdi): çağıran kaydı yeniden yükler. */
  onCakisma?: () => void;
}) {
  const { message, modal } = App.useApp();
  const { kullanici, yetkili } = useAuth();
  const [form] = Form.useForm<FormDegeri>();
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const [mukerrer, setMukerrer] = useState<MukerrerSonucu | null>(null);
  const [onerilenIrtibat, setOnerilenIrtibat] = useState<SahaOnerisi["irtibat"]>(null);
  const [irtibatlar, setIrtibatlar] = useState<NonNullable<SahaOnerisi["irtibatlar"]>>([]);
  const duzenleme = !!mevcut;
  const kapali = !!mevcut && KAPALI.includes(mevcut.status);
  const musteriDuzeltebilir = !duzenleme || (yetkili("servis.planla") && mevcut?.tur !== "PB");
  const uzaktanYetkili = yetkili("servis.uzaktan_coz");
  const kategoriDuzeltebilir = duzenleme && yetkili("servis.kapat") && mevcut?.tur !== "PB";

  const birim = Form.useWatch("birim", form);
  const uzaktan = Form.useWatch("uzaktan", form);
  const seriler = Form.useWatch("seriler", form);
  const musteri = Form.useWatch("musteri", form);
  const kategoriDegeri = Form.useWatch("kategori", form);

  const arizaNedenleri = useQuery({
    queryKey: ["ariza-nedenleri", birim],
    queryFn: () => teknikServisApi.arizaNedenleri(birim),
    enabled: !!birim && !!uzaktan,
  });

  const baslangic = useMemo<Partial<FormDegeri>>(() => {
    if (mevcut) {
      return {
        birim: mevcut.birim,
        tur: mevcut.tur,
        oncelik: mevcut.oncelik,
        talep_kanali: mevcut.talep_kanali ?? undefined,
        reported_at: mevcut.reported_at ? dayjs(mevcut.reported_at) : null,
        musteri: {
          musteriId: mevcut.customer_id,
          musteriAdi: mevcut.musteri?.title ?? null,
          lokasyonId: mevcut.address_id,
        },
        iletisim_ad: mevcut.iletisim_ad ?? undefined,
        iletisim_telefon: mevcut.iletisim_telefon ?? undefined,
        konu: mevcut.konu,
        aciklama: mevcut.aciklama ?? undefined,
        seriler: mevcut.seriler.map((s) => s.seri_no),
        proje: mevcut.proje ?? undefined,
        sistem: mevcut.sistem ?? undefined,
        uzaktan: false,
        kategori: mevcut.kategori,
      };
    }
    const birimler = formVerileri?.birimler ?? [];
    const varsayilanBirim =
      birimler.find((b) => b.kod === kullanici?.birincil_birim)?.kod ??
      (birimler.length === 1 ? birimler[0].kod : undefined);
    return {
      birim: varsayilanBirim,
      oncelik: "NORMAL",
      talep_kanali: "TELEFON",
      reported_at: dayjs(),
      musteri: { musteriId: null, lokasyonId: null },
      seriler: [],
      uzaktan: false,
    };
  }, [mevcut, formVerileri, kullanici]);

  useEffect(() => {
    form.resetFields();
    form.setFieldsValue(baslangic);
  }, [baslangic, form]);

  // Canlı mükerrer uyarısı (yalnız uyarı; asıl kontrol kayıtta sunucuda).
  useEffect(() => {
    const seri = (seriler ?? []).map((s) => s.trim()).filter(Boolean);
    const t = setTimeout(() => {
      if (!seri.length && !musteri?.musteriId) {
        setMukerrer(null);
        return;
      }
      teknikServisApi
        .mukerrerKontrol({
          seri,
          musteri_id: musteri?.musteriId ?? undefined,
          adres_id: musteri?.lokasyonId ?? undefined,
          haric_id: mevcut?.id,
        })
        .then(setMukerrer)
        .catch(() => setMukerrer(null));
    }, 400);
    return () => clearTimeout(t);
  }, [seriler, musteri?.musteriId, musteri?.lokasyonId, mevcut?.id]);

  /** Lokasyon irtibat listesinden seçim: ad/telefon dolar, kayıtta `contact_id` gider. */
  const irtibatSec = (id: number) => {
    const k = irtibatlar.find((x) => x.id === id);
    if (!k) return;
    setOnerilenIrtibat({ id: k.id, ad: k.ad, telefon: k.telefon });
    form.setFieldsValue({
      iletisim_ad: k.ad,
      iletisim_telefon: k.telefon && !k.telefon.includes("*") ? k.telefon : undefined,
    });
  };

  /** Lokasyonun birincil irtibatı önerilir; kullanıcı yazdıysa ezilmez. */
  const sahaOnerisi = (o: SahaOnerisi | null) => {
    setOnerilenIrtibat(o?.irtibat ?? null);
    setIrtibatlar(o?.irtibatlar ?? []);
    if (!o?.irtibat) return;
    const v = form.getFieldsValue(["iletisim_ad", "iletisim_telefon"]);
    if (!v.iletisim_ad && !v.iletisim_telefon) {
      form.setFieldsValue({
        iletisim_ad: o.irtibat.ad,
        iletisim_telefon: o.irtibat.telefon && !o.irtibat.telefon.includes("*") ? o.irtibat.telefon : undefined,
      });
    }
  };

  function govdeKur(v: FormDegeri): IsGirdisi {
    const irtibatAyni =
      !!onerilenIrtibat && (v.iletisim_ad ?? "").trim() === onerilenIrtibat.ad.trim();
    return {
      birim: v.birim,
      tur: v.tur,
      konu: v.konu.trim(),
      customer_id: v.musteri.musteriId as number,
      address_id: v.musteri.lokasyonId ?? null,
      contact_id: irtibatAyni ? onerilenIrtibat?.id : null,
      oncelik: v.oncelik,
      talep_kanali: v.talep_kanali,
      reported_at: v.reported_at ? v.reported_at.toISOString() : null,
      iletisim_ad: v.iletisim_ad?.trim() || null,
      iletisim_telefon: v.iletisim_telefon?.trim() || null,
      proje: v.proje?.trim() || null,
      sistem: v.sistem?.trim() || null,
      aciklama: v.aciklama?.trim() || null,
      seriler: (v.seriler ?? []).map((s) => s.trim()).filter(Boolean),
    };
  }

  async function yeniKaydet(v: FormDegeri, mukerrerGec = false) {
    const govde = { ...govdeKur(v), mukerrer_gec: mukerrerGec };
    try {
      const sonuc =
        v.uzaktan && uzaktanYetkili
          ? await teknikServisApi.uzaktanCozuldu({
              ...govde,
              cozum_kanali: v.cozum_kanali ?? "TELEFON",
              yapilan_islem: (v.yapilan_islem ?? "").trim(),
              ariza_nedeni_id: v.ariza_nedeni_id ?? null,
            })
          : await teknikServisApi.ac(govde);
      message.success(`${sonuc.so_no} açıldı`);
      for (const u of sonuc.uyarilar ?? []) {
        if (u.kod === "AYNI_LOKASYON") message.info(`Aynı lokasyonda açık iş: ${u.so_no}`);
      }
      onKaydedildi(sonuc);
    } catch (e) {
      const detay = (e instanceof ApiError ? (e.govde as { detail?: unknown })?.detail : null) as
        | { kod?: string; mesaj?: string; mevcut_isler?: { so_no: string }[] }
        | null;
      if (e instanceof ApiError && e.status === 409 && detay?.kod === "MUKERRER") {
        modal.confirm({
          title: "Mükerrer kayıt olabilir",
          content: (
            <Space orientation="vertical">
              <span>{detay.mesaj}</span>
              <Typography.Text type="secondary">
                Aynı cihaz için ikinci bir iş açmak istediğinizden emin misiniz?
              </Typography.Text>
            </Space>
          ),
          okText: "Yine de aç",
          cancelText: "Vazgeç",
          onOk: () => yeniKaydet(v, true),
        });
        return;
      }
      message.error((e as Error).message);
    }
  }

  async function duzenlemeKaydet(v: FormDegeri) {
    if (!mevcut) return;
    const g = govdeKur(v);
    const degisen: Record<string, unknown> = { version: mevcut.version };
    const alanlar: (keyof IsGirdisi)[] = [
      "konu",
      "aciklama",
      "oncelik",
      "tur",
      "proje",
      "sistem",
      "talep_kanali",
      "reported_at",
      "iletisim_ad",
      "iletisim_telefon",
    ];
    const eski: Record<string, unknown> = {
      konu: mevcut.konu,
      aciklama: mevcut.aciklama,
      oncelik: mevcut.oncelik,
      tur: mevcut.tur,
      proje: mevcut.proje,
      sistem: mevcut.sistem,
      talep_kanali: mevcut.talep_kanali,
      reported_at: mevcut.reported_at ? dayjs(mevcut.reported_at).toISOString() : null,
      iletisim_ad: mevcut.iletisim_ad,
      iletisim_telefon: mevcut.iletisim_telefon,
    };
    for (const a of alanlar) if ((g[a] ?? null) !== (eski[a] ?? null)) degisen[a] = g[a];
    // Maskeli telefon geri gönderilmez (yetkisi olmayan görmüş olur, değiştirmemiştir).
    if (typeof degisen.iletisim_telefon === "string" && degisen.iletisim_telefon.includes("*"))
      delete degisen.iletisim_telefon;
    if (musteriDuzeltebilir) {
      if (g.customer_id !== mevcut.customer_id) degisen.customer_id = g.customer_id;
      if ((g.address_id ?? null) !== (mevcut.address_id ?? null)) degisen.address_id = g.address_id;
    }
    if (kategoriDuzeltebilir && v.kategori && v.kategori !== mevcut.kategori) {
      degisen.kategori = v.kategori;
    }
    if (kapali || v.gerekce || degisen.kategori) degisen.gerekce = v.gerekce?.trim() || undefined;
    const yeniSeriler = g.seriler ?? [];
    const eskiSeriler = mevcut.seriler.map((s) => s.seri_no);
    const seriDegisti = JSON.stringify(yeniSeriler) !== JSON.stringify(eskiSeriler);
    try {
      let sonuc: IsDetayi = mevcut;
      if (Object.keys(degisen).length > 1 || degisen.gerekce) {
        sonuc = await teknikServisApi.guncelle(mevcut.id, degisen);
      }
      if (seriDegisti) {
        sonuc = await teknikServisApi.seriler(mevcut.id, yeniSeriler, v.gerekce?.trim() || undefined);
      }
      message.success("Kaydedildi");
      onKaydedildi(sonuc);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && /yenile|sürüm|değiş/i.test(e.message)) {
        message.warning(`${e.message} — kayıt yeniden yüklendi, değişikliğinizi tekrar yapın.`);
        onCakisma?.();
        return;
      }
      message.error((e as Error).message);
    }
  }

  async function gonder(v: FormDegeri) {
    if (!v.musteri?.musteriId) {
      message.error("Müşteri seçin");
      return;
    }
    setGonderiliyor(true);
    try {
      if (duzenleme) await duzenlemeKaydet(v);
      else await yeniKaydet(v);
    } finally {
      setGonderiliyor(false);
    }
  }

  const turler = (formVerileri?.turler ?? []).filter((t) => t.ekrandan || t.kod === mevcut?.tur);

  return (
    <Form<FormDegeri> form={form} layout="vertical" onFinish={(v) => void gonder(v)} disabled={gonderiliyor}>
      {kapali && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="Kapalı işte düzeltme yalnız kapatma yetkisiyle ve gerekçeyle yapılır."
        />
      )}
      <Row gutter={12}>
        <Col xs={24} sm={12}>
          <Form.Item name="birim" label="Birim" rules={[{ required: true, message: "Birim seçin" }]}>
            <Select
              disabled={duzenleme}
              options={(formVerileri?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item name="tur" label="İş türü" rules={[{ required: true, message: "Tür seçin" }]}>
            <Select
              disabled={mevcut?.tur === "PB"}
              options={turler.map((t) => ({ value: t.kod, label: t.ad }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item name="oncelik" label="Öncelik">
            <Radio.Group
              optionType="button"
              options={(formVerileri?.oncelikler ?? ["KRITIK", "YUKSEK", "NORMAL"]).map((o) => ({
                value: o,
                label: ONCELIK_ADLARI[o] ?? o,
              }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item
            name="talep_kanali"
            label="Talep kanalı"
            rules={[{ required: true, message: "Talep kanalı seçin" }]}
          >
            <Select
              options={(formVerileri?.talep_kanallari ?? [])
                .filter((k) => k.kod !== "BAKIM_OTOMATIK")
                .map((k) => ({ value: k.kod, label: k.ad }))}
            />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item
        name="musteri"
        label="Müşteri ve lokasyon"
        rules={[
          {
            validator: (_, v: MusteriLokasyonSecimi | undefined) =>
              v?.musteriId ? Promise.resolve() : Promise.reject(new Error("Müşteri seçin")),
          },
        ]}
      >
        <MusteriLokasyonSecici disabled={!musteriDuzeltebilir} onSahaOnerisi={sahaOnerisi} />
      </Form.Item>

      {irtibatlar.length > 0 && (
        <Form.Item label="Lokasyon irtibatından seç">
          <Select
            allowClear
            placeholder="İrtibat seçin (isteğe bağlı)"
            value={
              irtibatlar.some((k) => k.id === onerilenIrtibat?.id) ? onerilenIrtibat?.id : undefined
            }
            onChange={(id?: number) => (id ? irtibatSec(id) : undefined)}
            options={irtibatlar.map((k) => ({
              value: k.id,
              label: [k.ad, k.unvan].filter(Boolean).join(" · "),
            }))}
          />
        </Form.Item>
      )}
      <Row gutter={12}>
        <Col xs={24} sm={12}>
          <Form.Item
            name="iletisim_ad"
            label="Saha yetkilisi"
            extra={onerilenIrtibat ? `Lokasyonun birincil irtibatı: ${onerilenIrtibat.ad}` : undefined}
          >
            <Input maxLength={120} placeholder="Ad Soyad" />
          </Form.Item>
        </Col>
        <Col xs={24} sm={12}>
          <Form.Item name="iletisim_telefon" label="Telefon">
            <Input maxLength={20} inputMode="tel" placeholder="05xx xxx xx xx" />
          </Form.Item>
        </Col>
      </Row>

      <Form.Item name="konu" label="Konu" rules={[{ required: true, whitespace: true, max: 200 }]}>
        <Input placeholder="Ör. Kamera görüntü vermiyor" />
      </Form.Item>
      <Form.Item name="aciklama" label="Açıklama">
        <Input.TextArea rows={3} maxLength={4000} />
      </Form.Item>
      <Form.Item
        name="seriler"
        label="Seri numaraları"
        extra="Enter ile ekleyin. Seri metin olarak saklanır (baştaki sıfır korunur)."
      >
        <Select mode="tags" tokenSeparators={[",", ";"]} open={false} disabled={mevcut?.tur === "PB"} />
      </Form.Item>
      <MukerrerUyarisi m={mukerrer} />

      <Row gutter={12} style={{ marginTop: 12 }}>
        <Col xs={24} sm={12}>
          <Form.Item name="reported_at" label="Bildirim anı" extra="En çok 7 gün geriye girilebilir.">
            <DatePicker
              showTime={{ format: "HH:mm" }}
              format="DD.MM.YYYY HH:mm"
              style={{ width: "100%" }}
              disabledDate={(d) => d.isAfter(dayjs(), "day") || d.isBefore(dayjs().subtract(7, "day"), "day")}
            />
          </Form.Item>
        </Col>
        <Col xs={12} sm={6}>
          <Form.Item name="proje" label="Proje">
            <Input maxLength={120} />
          </Form.Item>
        </Col>
        <Col xs={12} sm={6}>
          <Form.Item name="sistem" label="Sistem">
            <Input maxLength={120} />
          </Form.Item>
        </Col>
      </Row>

      {!duzenleme && uzaktanYetkili && (
        <>
          <Divider style={{ margin: "8px 0 12px" }} />
          <Form.Item name="uzaktan" valuePropName="checked" label="Açılışta çözüldü">
            <Switch checkedChildren="Telefonla/uzaktan çözüldü" unCheckedChildren="Hayır" />
          </Form.Item>
          {uzaktan && (
            <>
              <Form.Item name="cozum_kanali" label="Çözüm kanalı" initialValue="TELEFON">
                <Radio.Group
                  optionType="button"
                  options={[
                    { value: "TELEFON", label: "Telefonla" },
                    { value: "UZAKTAN", label: "Uzaktan bağlantı" },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="yapilan_islem"
                label="Yapılan işlem"
                rules={[{ required: true, whitespace: true, message: "Yapılan işlemi yazın" }]}
              >
                <Input.TextArea rows={2} maxLength={4000} />
              </Form.Item>
              <Form.Item name="ariza_nedeni_id" label="Arıza nedeni">
                <Select
                  allowClear
                  loading={arizaNedenleri.isFetching}
                  options={(arizaNedenleri.data ?? [])
                    .filter((n) => n.is_active)
                    .map((n) => ({ value: n.id, label: n.ad }))}
                />
              </Form.Item>
            </>
          )}
        </>
      )}

      {kategoriDuzeltebilir && (
        <Form.Item
          name="kategori"
          label="Kategori"
          extra="Türden türetilir; yalnız gerekçeyle düzeltilir."
        >
          <Select
            options={(formVerileri?.kategoriler ?? [])
              .filter((k) => k.kod !== "PLANLI_BAKIM")
              .map((k) => ({ value: k.kod, label: k.ad }))}
          />
        </Form.Item>
      )}
      {duzenleme && (
        <Form.Item
          name="gerekce"
          label="Düzeltme gerekçesi"
          rules={
            kapali || (kategoriDuzeltebilir && kategoriDegeri && kategoriDegeri !== mevcut?.kategori)
              ? [{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]
              : []
          }
        >
          <Input maxLength={500} placeholder={kapali ? "Zorunlu" : "Müşteri/seri düzeltmesinde önerilir"} />
        </Form.Item>
      )}

      <Space style={{ width: "100%", justifyContent: "flex-end" }}>
        <Button onClick={onVazgec}>Vazgeç</Button>
        <Button type="primary" htmlType="submit" loading={gonderiliyor}>
          {duzenleme ? "Kaydet" : "İşi aç"}
        </Button>
      </Space>
    </Form>
  );
}

