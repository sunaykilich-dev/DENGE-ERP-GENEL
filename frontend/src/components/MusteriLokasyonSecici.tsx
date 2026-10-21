import { useQuery } from "@tanstack/react-query";
import { App, AutoComplete, Button, Form, Input, List, Modal, Select, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import {
  anaVeriApi,
  AnaVeriHatasi,
  type LokasyonSatiri,
  type MusteriSatiri,
} from "../api/anaVeri";
import { useAuth } from "../auth/AuthContext";

export interface MusteriLokasyonSecimi {
  musteriId: number | null;
  musteriAdi?: string | null;
  lokasyonId: number | null;
}

const ESLESEN_ETIKET: Record<MusteriSatiri["eslesen"], string> = {
  unvan: "unvan",
  takma_ad: "eski yazım",
  tesis: "tesis adı",
  vkn: "VKN",
};

/** Kullanıcı yazmayı bırakınca (300 ms) sunucuya sorar; her tuşta değil. */
function useGecikmeli(deger: string, ms = 300) {
  const [gecikmeli, setGecikmeli] = useState(deger);
  useEffect(() => {
    const t = setTimeout(() => setGecikmeli(deger), ms);
    return () => clearTimeout(t);
  }, [deger, ms]);
  return gecikmeli;
}

/**
 * Servis formlarının müşteri → lokasyon seçicisi (TS-015; form entegrasyonu TS-034).
 *
 * Arama SUNUCUDA (`/musteri-ara`, `servis.gor`): yanıt yalnız ad + il +
 * doğrulama rozeti taşır, VKN/IBAN/telefon göstermez. "Hızlı ekle" yalnız
 * `servis.yaz` + `lokasyon.yaz` olanda görünür; benzer kayıt varsa sunucu
 * 409 + aday listesi döner ve kullanıcıya "Bunu mu demek istediniz?" sorulur.
 */
export default function MusteriLokasyonSecici({
  value,
  onChange,
  disabled,
}: {
  value?: MusteriLokasyonSecimi;
  onChange?: (v: MusteriLokasyonSecimi) => void;
  disabled?: boolean;
}) {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const hizliEkleyebilir = yetkili("servis.yaz") && yetkili("lokasyon.yaz");
  const [metin, setMetin] = useState(value?.musteriAdi ?? "");
  const aranan = useGecikmeli(metin.trim());
  const [hizliAcik, setHizliAcik] = useState(false);
  const [adaylar, setAdaylar] = useState<MusteriSatiri[] | null>(null);
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const [form] = Form.useForm();

  const musteriler = useQuery({
    queryKey: ["musteri-ara", aranan],
    queryFn: () => anaVeriApi.musteriAra(aranan),
    enabled: aranan.length >= 2 && !disabled,
  });
  const lokasyonlar = useQuery({
    queryKey: ["lokasyon-ara", value?.musteriId],
    queryFn: () => anaVeriApi.lokasyonAra(value!.musteriId!),
    enabled: !!value?.musteriId,
  });

  const sec = (m: MusteriSatiri) => {
    setMetin(m.unvan);
    onChange?.({ musteriId: m.id, musteriAdi: m.unvan, lokasyonId: null });
  };

  async function hizliKaydet(v: Record<string, string>, onayBenzer = false) {
    setGonderiliyor(true);
    try {
      const s = await anaVeriApi.hizliMusteri({
        unvan: v.unvan,
        il: v.il,
        tesis_adi: v.tesis_adi || undefined,
        onay_benzer: onayBenzer,
      });
      message.success("Müşteri açıldı (doğrulanmamış)");
      setHizliAcik(false);
      setAdaylar(null);
      form.resetFields();
      setMetin(s.hesap.unvan);
      onChange?.({
        musteriId: s.hesap.id,
        musteriAdi: s.hesap.unvan,
        lokasyonId: s.lokasyon?.id ?? null,
      });
    } catch (e) {
      if (e instanceof AnaVeriHatasi && e.status === 409 && Array.isArray(e.detay?.adaylar)) {
        setAdaylar(e.detay.adaylar as MusteriSatiri[]);
      } else message.error((e as Error).message);
    } finally {
      setGonderiliyor(false);
    }
  }

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Space.Compact style={{ width: "100%" }}>
        <AutoComplete
          style={{ width: "100%" }}
          value={metin}
          disabled={disabled}
          placeholder="Müşteri ara (unvan, tesis, eski yazım)…"
          onChange={(t: string) => {
            setMetin(t);
            if (value?.musteriId) onChange?.({ musteriId: null, lokasyonId: null });
          }}
          onSelect={(_: string, o: { musteri: MusteriSatiri }) => sec(o.musteri)}
          notFoundContent={
            aranan.length >= 2 && !musteriler.isFetching ? "Eşleşen müşteri yok" : null
          }
          options={(musteriler.data ?? []).map((m) => ({
            value: `${m.id}`,
            musteri: m,
            label: (
              <Space size={4} wrap>
                <span>{m.unvan}</span>
                {m.il && <Typography.Text type="secondary">· {m.il}</Typography.Text>}
                {m.eslesen !== "unvan" && <Tag>{ESLESEN_ETIKET[m.eslesen]}</Tag>}
                {!m.dogrulandi && <Tag color="orange">Doğrulanmamış</Tag>}
              </Space>
            ),
          }))}
        />
        {hizliEkleyebilir && !disabled && (
          <Button
            onClick={() => {
              form.setFieldsValue({ unvan: metin });
              setAdaylar(null);
              setHizliAcik(true);
            }}
          >
            Hızlı ekle
          </Button>
        )}
      </Space.Compact>

      <Select<number>
        style={{ width: "100%" }}
        allowClear
        disabled={disabled || !value?.musteriId}
        placeholder={value?.musteriId ? "Lokasyon (tesis) seçin" : "Önce müşteri seçin"}
        value={value?.lokasyonId ?? undefined}
        loading={lokasyonlar.isFetching}
        onChange={(id) =>
          onChange?.({
            musteriId: value?.musteriId ?? null,
            musteriAdi: value?.musteriAdi,
            lokasyonId: id ?? null,
          })
        }
        options={(lokasyonlar.data ?? []).map((l: LokasyonSatiri) => ({
          value: l.id,
          label: [l.tesis_adi, l.ilce, l.il].filter(Boolean).join(" · "),
        }))}
        notFoundContent="Bu müşterinin aktif tesisi yok"
      />

      <Modal
        title="Hızlı müşteri ekle"
        open={hizliAcik}
        onCancel={() => setHizliAcik(false)}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={gonderiliyor}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Yalnız ad ve il istenir; kayıt "Doğrulanmamış" açılır ve yönetici doğrular. VKN/IBAN
          buradan girilmez.
        </Typography.Paragraph>
        <Form form={form} layout="vertical" onFinish={(v) => void hizliKaydet(v)}>
          <Form.Item name="unvan" label="Unvan" rules={[{ required: true, whitespace: true, min: 2, max: 200 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="il" label="İl" rules={[{ required: true, whitespace: true }]}>
            <Input placeholder="Ör. İstanbul" />
          </Form.Item>
          <Form.Item name="tesis_adi" label="Tesis adı (isteğe bağlı)">
            <Input placeholder="Ör. Akyaka AVM" />
          </Form.Item>
        </Form>
        {adaylar && (
          <>
            <Typography.Text strong>Bunu mu demek istediniz?</Typography.Text>
            <List
              size="small"
              dataSource={adaylar}
              renderItem={(m) => (
                <List.Item
                  actions={[
                    <Button
                      key="sec"
                      size="small"
                      onClick={() => {
                        sec(m);
                        setHizliAcik(false);
                      }}
                    >
                      Bunu seç
                    </Button>,
                  ]}
                >
                  <Space size={4} wrap>
                    <span>{m.unvan}</span>
                    {m.il && <Typography.Text type="secondary">· {m.il}</Typography.Text>}
                    <Tag>{ESLESEN_ETIKET[m.eslesen]}</Tag>
                  </Space>
                </List.Item>
              )}
            />
            <Button
              danger
              size="small"
              loading={gonderiliyor}
              onClick={() => void hizliKaydet(form.getFieldsValue(), true)}
            >
              Hiçbiri değil, yine de ekle
            </Button>
          </>
        )}
      </Modal>
    </Space>
  );
}
