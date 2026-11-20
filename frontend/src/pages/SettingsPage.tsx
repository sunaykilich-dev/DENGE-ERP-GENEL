import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, Input, InputNumber, Select, Space, Switch } from "antd";
import { useEffect } from "react";

import { api, type ApiError } from "../api/client";
import IskontoLimitleri from "../components/IskontoLimitleri";

/** Anahtarları kullanıcıya anlamlı başlıklar altında toplar. */
const GRUPLAR: { baslik: string; aciklama?: string; anahtarlar: string[] }[] = [
  {
    baslik: "Vergi ve kesinti",
    aciklama:
      "Hak ediş satırı oluşurken kullanılan oran satırın içine dondurulur; burada yapılan " +
      "değişiklik geçmiş dökümleri etkilemez. Canlıya çıkmadan önce mali müşavire teyit ettirin.",
    anahtarlar: [
      "kdv_oran_varsayilan",
      "stopaj_smm_oran",
      "damga_vergisi_oran",
      "stopaj_gider_pusulasi_oran",
    ],
  },
  {
    baslik: "Satış ve teklif",
    aciklama: "İskonto limitleri sayfanın altındaki \"İskonto yetkisi\" kartından ayrıca kaydedilir.",
    anahtarlar: ["teklif_varsayilan_gecerlilik_gun"],
  },
  {
    baslik: "Servis operasyonu",
    aciklama:
      "Tayinsiz servis işi bu kadar mesai dakikası bekleyince Operasyon Merkezi'nde \"gecikti\" olur ve " +
      "anlık e-posta seçen kullanıcılara bildirim gider. Süre yalnız mesai saatinde sayılır.",
    anahtarlar: ["servis_tayin_suresi_kritik_dk", "servis_tayin_suresi_dk"],
  },
  { baslik: "Cihaz ve stok", anahtarlar: ["varsayilan_garanti_ay", "bayi_stok_yaslanma_gun"] },
  {
    baslik: "Hat",
    aciklama:
      "Taahhüt uyarısı önemlidir: indirim taahhüde bağlı, taahhüt düşerse hat maliyeti katlanır.",
    anahtarlar: ["kota_uyari_yuzde_1", "kota_uyari_yuzde_2", "atil_hat_gun", "hat_taahhut_uyari_gun"],
  },
  {
    baslik: "Abonelik ve tahsilat",
    anahtarlar: ["abonelik_yenileme_hatirlatma_gun", "odeme_gecikme_uyari_gun"],
  },
  {
    baslik: "Takip platformu",
    aciklama:
      "Çoklu cihaz desteği kapalıyken ERP platforma yalnız birincil takip cihazını bağlar; " +
      "kamera işlemleri kuyrukta bekler ve destek açılınca otomatik oynatılır.",
    anahtarlar: [
      "platform_base_url",
      "platform_api_key",
      "platform_coklu_cihaz_destegi",
      "webhook_signing_key",
    ],
  },
  { baslik: "Operatör", anahtarlar: ["operator_adaptor", "operator_api_key"] },
  {
    baslik: "Bildirim (e-posta)",
    anahtarlar: ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from"],
  },
  { baslik: "Muhasebe", anahtarlar: ["muhasebe_sablonu"] },
  {
    baslik: "KVKK",
    aciklama:
      "Saklama süresi dolan hesaplar KVKK ekranında listelenir. Otomatik imha yoktur; " +
      "karar insana bırakılır.",
    anahtarlar: ["kvkk_saklama_yili"],
  },
  {
    baslik: "Erişim yeri",
    aciklama:
      "\"Yalnız ofis ağından\" işaretli roller (varsayılan muhasebe) yalnız bu ağlardan giriş " +
      "yapar ve işlem yapar; saha rolleri her yerden çalışır. Liste boşsa kısıt uygulanmaz. " +
      "Ağları CIDR biçiminde girin (ör. 10.10.0.0/16 ya da tek adres 88.255.1.20).",
    anahtarlar: ["ofis_ag_listesi"],
  },
];

const ETIKET: Record<string, string> = {
  kdv_oran_varsayilan: "Varsayılan KDV oranı",
  stopaj_smm_oran: "Serbest meslek makbuzu gelir vergisi stopajı",
  damga_vergisi_oran: "Damga vergisi oranı",
  stopaj_gider_pusulasi_oran: "Gider pusulası stopaj oranı",
  teklif_varsayilan_gecerlilik_gun: "Teklif geçerlilik süresi (gün)",
  varsayilan_garanti_ay: "Varsayılan garanti süresi (ay)",
  bayi_stok_yaslanma_gun: "Bayi stok yaşlanma uyarısı (gün)",
  kota_uyari_yuzde_1: "Kota uyarısı 1 (%)",
  kota_uyari_yuzde_2: "Kota uyarısı 2 (%)",
  atil_hat_gun: "Atıl hat eşiği (gün)",
  hat_taahhut_uyari_gun: "Taahhüt bitişi uyarısı (gün kala)",
  abonelik_yenileme_hatirlatma_gun: "Abonelik yenileme hatırlatması (gün önce)",
  odeme_gecikme_uyari_gun: "Ödeme gecikme uyarısı (gün)",
  platform_base_url: "Platform API adresi",
  platform_api_key: "Platform API anahtarı",
  platform_coklu_cihaz_destegi: "Platform çoklu cihaz destekliyor",
  webhook_signing_key: "Webhook imza anahtarı",
  operator_adaptor: "Operatör adaptörü",
  operator_api_key: "Operatör API anahtarı",
  smtp_host: "SMTP sunucusu",
  smtp_port: "SMTP portu",
  smtp_user: "SMTP kullanıcısı",
  smtp_password: "SMTP parolası",
  smtp_from: "Gönderen adresi",
  muhasebe_sablonu: "Muhasebe dışa aktarım şablonu",
  kvkk_saklama_yili: "Kişisel veri saklama süresi (yıl)",
  ofis_ag_listesi: "Ofis ağları (CIDR)",
  servis_tayin_suresi_kritik_dk: "Tayin süresi, kritik iş (dk)",
  servis_tayin_suresi_dk: "Tayin süresi, diğer işler (dk)",
};

const GIZLI = new Set([
  "platform_api_key",
  "operator_api_key",
  "smtp_password",
  "webhook_signing_key",
]);

export default function SettingsPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [form] = Form.useForm();

  const ayarlar = useQuery({
    queryKey: ["ayarlar"],
    queryFn: () => api.get<Record<string, unknown>>("/api/ayarlar"),
  });

  useEffect(() => {
    if (ayarlar.data) form.setFieldsValue(ayarlar.data);
  }, [ayarlar.data, form]);

  const kaydet = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api.patch<Record<string, unknown>>("/api/ayarlar", { values }),
    onSuccess: () => {
      message.success("Parametreler kaydedildi");
      void qc.invalidateQueries({ queryKey: ["ayarlar"] });
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  function alan(anahtar: string) {
    const deger = ayarlar.data?.[anahtar];
    if (typeof deger === "boolean") {
      return (
        <Form.Item key={anahtar} name={anahtar} label={ETIKET[anahtar] ?? anahtar} valuePropName="checked">
          <Switch />
        </Form.Item>
      );
    }
    if (GIZLI.has(anahtar)) {
      return (
        <Form.Item
          key={anahtar}
          name={anahtar}
          label={ETIKET[anahtar] ?? anahtar}
          extra="Kayıtlı değer maskelenir; boş bırakmak yerine maskeyi olduğu gibi bırakırsanız değişmez."
        >
          <Input.Password className="mono" />
        </Form.Item>
      );
    }
    if (Array.isArray(deger)) {
      return (
        <Form.Item key={anahtar} name={anahtar} label={ETIKET[anahtar] ?? anahtar}>
          <Select mode="tags" tokenSeparators={[",", " "]} placeholder="10.10.0.0/16" open={false} />
        </Form.Item>
      );
    }
    if (typeof deger === "number") {
      return (
        <Form.Item key={anahtar} name={anahtar} label={ETIKET[anahtar] ?? anahtar}>
          <InputNumber style={{ width: 220 }} step={anahtar.includes("oran") ? 0.001 : 1} />
        </Form.Item>
      );
    }
    return (
      <Form.Item key={anahtar} name={anahtar} label={ETIKET[anahtar] ?? anahtar}>
        <Input />
      </Form.Item>
    );
  }

  return (
    <Form form={form} layout="vertical" onFinish={(v) => kaydet.mutate(v)}>
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {GRUPLAR.map((g) => (
          <Card key={g.baslik} title={g.baslik} loading={ayarlar.isLoading}>
            {g.aciklama && (
              <Alert type="info" showIcon title={g.aciklama} style={{ marginBottom: 16 }} />
            )}
            {g.anahtarlar.map(alan)}
          </Card>
        ))}
        <Button type="primary" htmlType="submit" loading={kaydet.isPending}>
          Kaydet
        </Button>
        <IskontoLimitleri />
      </Space>
    </Form>
  );
}
