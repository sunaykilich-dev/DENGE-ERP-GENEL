/**
 * Servis işinde cihaz başına bilgi (2026-11-24 sahip kararı).
 *
 * - "Müşteri şikâyeti" ve "Notlar" YALNIZ personel içindir (müşteri belgesine
 *   basılmaz) — alanlar "Yalnız personel" etiketiyle ayrılır.
 * - "Cihaz durumu" (seçim + açıklama) ve "Onarım bilgisi" onarım fişinde
 *   müşteriye gider.
 *
 * `CihazBilgisiAlanlari`: açılış formunda bir Form.List gibi kullanılır
 * (alan adı `["cihaz_bilgileri", anahtar, ...]`). `CihazlarBolumu`: iş
 * detayında cihaz listesi + düzenleme penceresi.
 */
import { useMutation } from "@tanstack/react-query";
import { App, Button, Card, Col, Form, Input, Modal, Row, Select, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import {
  CIHAZ_DURUMLARI,
  teknikServisApi,
  type CihazBilgisi,
  type IsSerisi,
} from "../api/teknikServis";

const YALNIZ_PERSONEL = (
  <Tag color="default" style={{ marginLeft: 6, fontWeight: 400 }}>
    Yalnız personel
  </Tag>
);
const MUSTERIYE = (
  <Tag color="blue" style={{ marginLeft: 6, fontWeight: 400 }}>
    Onarım fişinde
  </Tag>
);

/** Bir cihazın dört alanı; `onek` form içindeki yol (ör. ["cihaz_bilgileri", "SN1"]). */
export function CihazBilgisiAlanlari({ onek }: { onek: (string | number)[] }) {
  return (
    <>
      <Row gutter={12}>
        <Col xs={24} sm={10}>
          <Form.Item name={[...onek, "cihaz_durumu"]} label={<>Cihaz durumu{MUSTERIYE}</>}>
            <Select
              allowClear
              placeholder="Seçin"
              options={CIHAZ_DURUMLARI.map((d) => ({ value: d.kod, label: d.ad }))}
            />
          </Form.Item>
        </Col>
        <Col xs={24} sm={14}>
          <Form.Item name={[...onek, "cihaz_durumu_aciklama"]} label="Durum açıklaması">
            <Input maxLength={500} placeholder="Ör. Kasada çizik, adaptörü yok" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name={[...onek, "musteri_sikayeti"]} label={<>Müşteri şikâyeti{YALNIZ_PERSONEL}</>}>
        <Input.TextArea rows={2} maxLength={4000} />
      </Form.Item>
      <Form.Item name={[...onek, "notlar"]} label={<>Notlar{YALNIZ_PERSONEL}</>}>
        <Input.TextArea rows={2} maxLength={4000} />
      </Form.Item>
      <Form.Item name={[...onek, "onarim_bilgisi"]} label={<>Onarım bilgisi{MUSTERIYE}</>}>
        <Input.TextArea rows={2} maxLength={4000} placeholder="Yapılan onarım (sonradan da girilebilir)" />
      </Form.Item>
    </>
  );
}

function Satir({ etiket, deger }: { etiket: string; deger?: string | null }) {
  if (!deger) return null;
  return (
    <div>
      <Typography.Text type="secondary">{etiket}: </Typography.Text>
      <span style={{ whiteSpace: "pre-wrap" }}>{deger}</span>
    </div>
  );
}

/** İş detayında cihazlar: her cihazın bilgisi + düzenleme (iş kapanana kadar). */
export function CihazlarBolumu({
  isId,
  seriler,
  duzenlenebilir,
  onKaydedildi,
}: {
  isId: number;
  seriler: IsSerisi[];
  duzenlenebilir: boolean;
  onKaydedildi: () => void;
}) {
  const { message } = App.useApp();
  const [secili, setSecili] = useState<IsSerisi | null>(null);
  const [form] = Form.useForm<{ c: CihazBilgisi }>();

  useEffect(() => {
    if (secili) {
      form.setFieldsValue({
        c: {
          cihaz_durumu: secili.cihaz_durumu ?? undefined,
          cihaz_durumu_aciklama: secili.cihaz_durumu_aciklama ?? undefined,
          musteri_sikayeti: secili.musteri_sikayeti ?? undefined,
          notlar: secili.notlar ?? undefined,
          onarim_bilgisi: secili.onarim_bilgisi ?? undefined,
        },
      });
    }
  }, [secili, form]);

  const kaydet = useMutation({
    mutationFn: (g: CihazBilgisi) => teknikServisApi.cihazNotuKaydet(isId, secili!.id, g),
    onSuccess: () => {
      message.success("Cihaz bilgisi kaydedildi");
      setSecili(null);
      onKaydedildi();
    },
    onError: (e: Error) => void message.error(e.message),
  });

  if (!seriler.length) return null;
  return (
    <>
      <Space orientation="vertical" style={{ width: "100%" }} size={8}>
        {seriler.map((s, i) => (
          <Card
            key={s.id}
            size="small"
            title={
              <Space size={6}>
                <span>Cihaz {i + 1}</span>
                <Typography.Text className="mono">{s.seri_no}</Typography.Text>
                {s.cihaz_durumu_adi && <Tag>{s.cihaz_durumu_adi}</Tag>}
              </Space>
            }
            extra={
              duzenlenebilir && (
                <Button size="small" onClick={() => setSecili(s)}>
                  Düzenle
                </Button>
              )
            }
          >
            <Satir etiket="Durum açıklaması" deger={s.cihaz_durumu_aciklama} />
            <Satir etiket="Müşteri şikâyeti" deger={s.musteri_sikayeti} />
            <Satir etiket="Notlar" deger={s.notlar} />
            <Satir etiket="Onarım bilgisi" deger={s.onarim_bilgisi} />
            {!s.cihaz_durumu_aciklama && !s.musteri_sikayeti && !s.notlar && !s.onarim_bilgisi && (
              <Typography.Text type="secondary">Bilgi girilmedi.</Typography.Text>
            )}
          </Card>
        ))}
      </Space>
      <Modal
        title={secili ? `Cihaz bilgisi — ${secili.seri_no}` : ""}
        open={!!secili}
        onCancel={() => setSecili(null)}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        destroyOnHidden
        width={620}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => {
            // Boşaltılan alan da gönderilir (null) ki silinebilsin.
            const c = v.c ?? {};
            kaydet.mutate({
              cihaz_durumu: c.cihaz_durumu ?? null,
              cihaz_durumu_aciklama: c.cihaz_durumu_aciklama ?? null,
              musteri_sikayeti: c.musteri_sikayeti ?? null,
              notlar: c.notlar ?? null,
              onarim_bilgisi: c.onarim_bilgisi ?? null,
            });
          }}
        >
          <CihazBilgisiAlanlari onek={["c"]} />
        </Form>
      </Modal>
    </>
  );
}
