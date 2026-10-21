import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Checkbox,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useEffect, useState } from "react";

import {
  ADRES_TURLERI,
  ADRES_TURU_ETIKET,
  anaVeriApi,
  AnaVeriHatasi,
  type Irtibat,
} from "../api/anaVeri";
import { useAuth } from "../auth/AuthContext";

/**
 * Lokasyon (tesis) penceresi — HEM yeni HEM düzenleme (KartPenceresi kalıbı).
 *
 * Düzenlemede `version` geri gönderilir; başka biri kaydı değiştirdiyse 409
 * "yenileyin" mesajı çıkar. Hesap alanı yoktur: tesis başka cariye ancak
 * birleştirmeyle taşınır. Silme düğmesi yoktur, pasifleme vardır — servis
 * geçmişi lokasyona bağlı kalır.
 */
export default function LokasyonPenceresi({
  acik,
  hesapId,
  lokasyonId,
  onKapat,
}: {
  acik: boolean;
  hesapId: number;
  /** null ise YENİ lokasyon. */
  lokasyonId: number | null;
  onKapat: () => void;
}) {
  const yeni = lokasyonId === null;
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const yazabilir = yetkili("lokasyon.yaz");
  const [form] = Form.useForm();
  const [kisiForm] = Form.useForm();
  const [kisi, setKisi] = useState<Irtibat | "yeni" | null>(null);
  const tur = Form.useWatch("kind", form) as string | undefined;

  const kayit = useQuery({
    queryKey: ["lokasyon", lokasyonId],
    queryFn: () => anaVeriApi.lokasyon(lokasyonId!),
    enabled: acik && !yeni,
  });
  const l = kayit.data;

  useEffect(() => {
    if (!acik) return;
    if (yeni) {
      form.resetFields();
      form.setFieldsValue({ kind: "TESIS" });
    } else if (l) {
      form.setFieldsValue({
        kind: l.kind,
        site_name: l.site_name,
        label: l.label,
        line: l.line,
        district: l.district,
        city: l.city,
        access_note: l.access_note,
        primary_contact_id: l.primary_contact_id,
      });
    }
  }, [acik, yeni, l, form]);

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["hesap-lokasyonlari", hesapId] });
    void qc.invalidateQueries({ queryKey: ["lokasyon"] });
  };

  const hataGoster = (e: Error) => {
    if (e instanceof AnaVeriHatasi && e.status === 409 && e.detay?.mevcut) {
      const m = e.detay.mevcut as { tesis_adi: string | null };
      message.error(`${e.message} (mevcut: ${m.tesis_adi ?? "—"})`);
    } else if (e instanceof AnaVeriHatasi && e.status === 409) {
      message.error(`${e.message} Sayfayı yenileyip tekrar deneyin.`);
      tazele();
    } else message.error(e.message);
  };

  const kaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      yeni
        ? anaVeriApi.lokasyonAc({ ...v, hesap_id: hesapId })
        : anaVeriApi.lokasyonGuncelle(lokasyonId!, { ...v, version: l!.version }),
    onSuccess: () => {
      message.success(yeni ? "Lokasyon açıldı" : "Lokasyon güncellendi");
      tazele();
      onKapat();
    },
    onError: hataGoster,
  });

  const aktiflik = useMutation({
    mutationFn: (aktif: boolean) => anaVeriApi.lokasyonAktiflik(lokasyonId!, aktif),
    onSuccess: (x) => {
      message.success(x.is_active ? "Lokasyon aktifleştirildi" : "Lokasyon pasiflendi");
      tazele();
    },
    onError: hataGoster,
  });

  const dogrula = useMutation({
    mutationFn: () => anaVeriApi.lokasyonDogrula(lokasyonId!),
    onSuccess: () => {
      message.success("Lokasyon doğrulandı");
      tazele();
    },
    onError: hataGoster,
  });

  const kisiKaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      kisi === "yeni"
        ? anaVeriApi.irtibatEkle(lokasyonId!, v)
        : anaVeriApi.irtibatGuncelle((kisi as Irtibat).id, v),
    onSuccess: () => {
      message.success("İrtibat kaydedildi");
      setKisi(null);
      tazele();
    },
    onError: (e: Error) => message.error(e.message),
  });

  function kisiAc(k: Irtibat | "yeni") {
    setKisi(k);
    kisiForm.setFieldsValue(
      k === "yeni"
        ? { lokasyon_birincil: false }
        : {
            full_name: k.ad,
            title: k.gorev,
            phone: k.telefon,
            email: k.eposta,
            lokasyon_birincil: k.birincil,
          },
    );
  }

  const irtibatlar: Irtibat[] = l?.irtibatlar ?? [];

  return (
    <Drawer
      open={acik}
      onClose={onKapat}
      size={560}
      destroyOnHidden
      loading={!yeni && kayit.isLoading}
      title={
        <Space size={6} wrap>
          <span>{yeni ? "Yeni lokasyon" : (l?.site_name ?? l?.label ?? "Lokasyon")}</span>
          {l && !l.is_active && <Tag>pasif</Tag>}
          {l && !l.is_verified && <Tag color="orange">Doğrulanmamış</Tag>}
        </Space>
      }
      extra={
        <Space wrap>
          {!yeni && l && yetkili("hesap.birlestir") && !l.is_verified && (
            <Button size="small" loading={dogrula.isPending} onClick={() => dogrula.mutate()}>
              Doğrula
            </Button>
          )}
          {!yeni && l && yazabilir && (
            <Button
              size="small"
              loading={aktiflik.isPending}
              onClick={() => aktiflik.mutate(!l.is_active)}
            >
              {l.is_active ? "Pasifle" : "Aktifleştir"}
            </Button>
          )}
          {yazabilir && (
            <Button
              type="primary"
              size="small"
              loading={kaydet.isPending}
              onClick={() => form.submit()}
            >
              Kaydet
            </Button>
          )}
        </Space>
      }
    >
      <Form
        form={form}
        layout="vertical"
        disabled={!yazabilir}
        onFinish={(v) => {
          const govde: Record<string, unknown> = {
            site_name: v.site_name || null,
            label: v.label || null,
            line: v.line || null,
            district: v.district || null,
            city: v.city || null,
            access_note: v.access_note || null,
            primary_contact_id: v.primary_contact_id ?? null,
          };
          if (yeni) govde.kind = v.kind;
          kaydet.mutate(govde);
        }}
      >
        <Form.Item name="kind" label="Tür">
          <Select
            disabled={!yeni}
            options={ADRES_TURLERI.map((t) => ({ value: t, label: ADRES_TURU_ETIKET[t] }))}
          />
        </Form.Item>
        {tur === "TESIS" ? (
          <Form.Item
            name="site_name"
            label="Tesis adı"
            rules={[{ required: true, message: "Tesis adı girin" }]}
            extra="Ör. PİAZZA İSTANBUL AVM. Aynı carinin aynı adlı iki aktif tesisi olamaz."
          >
            <Input />
          </Form.Item>
        ) : (
          <Form.Item name="label" label="Etiket">
            <Input placeholder="Merkez" />
          </Form.Item>
        )}
        <Form.Item
          name="line"
          label="Açık adres"
          rules={tur === "TESIS" ? [] : [{ required: true, message: "Adres girin" }]}
        >
          <Input.TextArea rows={2} />
        </Form.Item>
        <Space size={12} style={{ display: "flex" }} wrap>
          <Form.Item name="district" label="İlçe" style={{ minWidth: 160 }}>
            <Input />
          </Form.Item>
          <Form.Item
            name="city"
            label="İl"
            style={{ minWidth: 160 }}
            rules={tur === "TESIS" ? [{ required: true, message: "İl girin" }] : []}
          >
            <Input />
          </Form.Item>
        </Space>
        <Form.Item
          name="access_note"
          label="Erişim notu"
          extra="Bina/kat, giriş kuralı, ulaşım — plan formu bunu önerir."
        >
          <Input.TextArea rows={2} />
        </Form.Item>
        {!yeni && (
          <Form.Item name="primary_contact_id" label="Birincil irtibat">
            <Select
              allowClear
              placeholder="Seçilmedi"
              options={irtibatlar.map((k) => ({ value: k.id, label: k.ad }))}
            />
          </Form.Item>
        )}
      </Form>

      {!yeni && (
        <>
          <Divider style={{ margin: "4px 0 12px" }}>İrtibatlar</Divider>
          {yazabilir && (
            <Button size="small" style={{ marginBottom: 8 }} onClick={() => kisiAc("yeni")}>
              İrtibat ekle
            </Button>
          )}
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={irtibatlar}
            scroll={{ x: 420 }}
            locale={{ emptyText: <Empty description="Bu lokasyonda irtibat yok" /> }}
            onRow={(k) => ({
              onClick: () => yazabilir && kisiAc(k),
              style: { cursor: yazabilir ? "pointer" : "default" },
            })}
            columns={[
              {
                title: "Ad",
                dataIndex: "ad",
                ellipsis: true,
                render: (x: string, k: Irtibat) => (
                  <Space size={4}>
                    <span>{x}</span>
                    {k.birincil && <Tag color="blue">birincil</Tag>}
                  </Space>
                ),
              },
              {
                title: "Telefon",
                dataIndex: "telefon",
                width: 150,
                className: "mono",
                render: (x: string | null) => x ?? "—",
              },
            ]}
          />
        </>
      )}

      <Modal
        title={kisi === "yeni" ? "İrtibat ekle" : "İrtibatı düzenle"}
        open={kisi !== null}
        onCancel={() => setKisi(null)}
        onOk={() => kisiForm.submit()}
        confirmLoading={kisiKaydet.isPending}
        okText="Kaydet"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Form form={kisiForm} layout="vertical" onFinish={(v) => kisiKaydet.mutate(v)}>
          <Form.Item name="full_name" label="Ad soyad" rules={[{ required: true, min: 2 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="title" label="Görev">
            <Input />
          </Form.Item>
          <Form.Item name="phone" label="Telefon" extra="05xx… — kayıtta tek biçime çevrilir.">
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="email" label="E-posta">
            <Input type="email" />
          </Form.Item>
          <Form.Item name="lokasyon_birincil" valuePropName="checked">
            <Checkbox>Bu lokasyonun birincil irtibatı</Checkbox>
          </Form.Item>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            İrtibat kişisel veridir; değişiklikler denetim izine yazılır.
          </Typography.Text>
        </Form>
      </Modal>
    </Drawer>
  );
}
