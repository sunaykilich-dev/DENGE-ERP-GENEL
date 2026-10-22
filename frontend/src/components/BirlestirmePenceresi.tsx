/**
 * Hesap / lokasyon birleştirme penceresi (TS-192, E14-12). Doldurur: D3-C
 * (iskelet D3-S). Önizleme çakışmaları gösterir; uygulama sunucuda tek
 * transaction (`services/hesap_birlestir.py`), hak ediş referanslı hesapta 409.
 *
 * Akış: hedef seç → önizle (DB'ye yazmaz; taşınacak satır sayıları, engeller)
 * → gerekçe → birleştir. Önizlemede görülen sayılar sunucuya `beklenen` olarak
 * geri gider; arada veri değiştiyse sunucu 409 "yeniden önizleyin" der.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, AutoComplete, Descriptions, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";

import {
  anaVeriApi,
  type BirlestirmeOnizleme,
  type BirlestirmeTuru,
} from "../api/anaVeri";

export interface BirlestirmePenceresiProps {
  acik: boolean;
  kapat: () => void;
  /** Varsayılan "HESAP". */
  tur?: BirlestirmeTuru;
  /** Birleşip kapanacak (kaynak) kayıt. */
  kaynak?: { id: number; ad: string | null };
  /** LOKASYON birleştirmesinde iki tesisin ortak hesabı. */
  hesapId?: number;
  onBitti?: (hedefId: number) => void;
}

const TABLO_ADLARI: Record<string, string> = {
  "service_orders.customer_id": "Servis işleri",
  "service_orders.address_id": "Servis işleri (lokasyon)",
  "addresses.account_id": "Tesisler / adresler",
  "contacts.account_id": "İrtibatlar",
  "contacts.address_id": "İrtibatlar (lokasyon)",
  "service_equipment.account_id": "Ekipman",
  "service_equipment.address_id": "Ekipman (lokasyon)",
  "maintenance_contracts.account_id": "Bakım sözleşmeleri",
  "maintenance_contracts.address_id": "Bakım sözleşmeleri (tesis)",
  "quotes.customer_id": "Teklifler",
  "attachments.entity_id": "Ekler",
  "account_aliases.account_id": "Takma adlar",
};

export default function BirlestirmePenceresi({
  acik,
  kapat,
  tur = "HESAP",
  kaynak,
  hesapId,
  onBitti,
}: BirlestirmePenceresiProps) {
  const { message } = App.useApp();
  const [hedef, setHedef] = useState<number | null>(null);
  const [arama, setArama] = useState("");
  const [onizleme, setOnizleme] = useState<BirlestirmeOnizleme | null>(null);
  const [gerekce, setGerekce] = useState("");
  const [hata, setHata] = useState<string | null>(null);

  const musteriler = useQuery({
    queryKey: ["birlestir-musteri", arama],
    queryFn: () => anaVeriApi.musteriAra(arama),
    enabled: acik && tur === "HESAP" && arama.trim().length >= 2,
  });
  const tesisler = useQuery({
    queryKey: ["birlestir-tesis", hesapId],
    queryFn: () => anaVeriApi.lokasyonAra(hesapId!),
    enabled: acik && tur === "LOKASYON" && hesapId != null,
  });

  const sifirla = () => {
    setHedef(null);
    setArama("");
    setOnizleme(null);
    setGerekce("");
    setHata(null);
  };

  const onizle = useMutation({
    mutationFn: (hedefId: number) =>
      anaVeriApi.birlestirmeOnizle({ tur, kaynak_id: kaynak!.id, hedef_id: hedefId }),
    onSuccess: (o) => {
      setOnizleme(o);
      setHata(null);
    },
    onError: (e: Error) => {
      setOnizleme(null);
      setHata(e.message);
    },
  });

  const uygula = useMutation({
    mutationFn: () =>
      anaVeriApi.birlestirmeUygula({
        tur,
        kaynak_id: kaynak!.id,
        hedef_id: hedef!,
        gerekce,
        beklenen: onizleme!.tasinacak,
      }),
    onSuccess: () => {
      message.success("Birleştirildi");
      const h = hedef!;
      sifirla();
      kapat();
      onBitti?.(h);
    },
    onError: (e: Error) => {
      setHata(e.message);
      if (hedef != null) onizle.mutate(hedef); // güncel sayılarla yeniden önizle
    },
  });

  const hedefSec = (id: number) => {
    setHedef(id);
    onizle.mutate(id);
  };

  const engelli = !!onizleme?.engeller.length;

  return (
    <Modal
      title={tur === "HESAP" ? "Müşteri birleştir" : "Lokasyon birleştir"}
      open={acik}
      onCancel={() => {
        sifirla();
        kapat();
      }}
      onOk={() => uygula.mutate()}
      okText="Birleştir"
      cancelText="Vazgeç"
      okButtonProps={{
        danger: true,
        disabled: !onizleme || engelli || gerekce.trim().length < 5 || !kaynak,
      }}
      confirmLoading={uygula.isPending}
      destroyOnHidden
      width={640}
    >
      <Space orientation="vertical" style={{ width: "100%" }} size="middle">
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
          <strong>{kaynak?.ad ?? "—"}</strong> kaydı seçeceğiniz hedefe birleşir ve kapanır; bağlı
          servis kayıtları, irtibatlar, tesisler ve ekler hedefe taşınır. Eski ad takma ad olur
          (aramada hedefi bulur). İşlem geri alınamaz; mobilite hak ediş kaydı olan hesap bu
          ekrandan birleştirilemez.
        </Typography.Paragraph>

        {tur === "HESAP" ? (
          <AutoComplete
            style={{ width: "100%" }}
            placeholder="Hedef müşteri ara (en az 2 harf)"
            value={arama}
            onChange={setArama}
            onSelect={(v: string) => hedefSec(Number(v))}
            options={(musteriler.data ?? [])
              .filter((m) => m.id !== kaynak?.id)
              .map((m) => ({
                value: String(m.id),
                label: (
                  <Space size={4}>
                    {m.unvan}
                    {m.il && <Typography.Text type="secondary">· {m.il}</Typography.Text>}
                    {!m.dogrulandi && <Tag color="gold">doğrulanmamış</Tag>}
                  </Space>
                ),
              }))}
          />
        ) : (
          <Select
            style={{ width: "100%" }}
            placeholder="Hedef tesis"
            value={hedef ?? undefined}
            onChange={(v: number) => hedefSec(v)}
            loading={tesisler.isLoading}
            options={(tesisler.data ?? [])
              .filter((t) => t.id !== kaynak?.id)
              .map((t) => ({ value: t.id, label: [t.tesis_adi, t.il].filter(Boolean).join(" · ") }))}
          />
        )}

        {onizleme && (
          <>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Kaynak (kapanacak)">{onizleme.kaynak.ad}</Descriptions.Item>
              <Descriptions.Item label="Hedef (kalacak)">{onizleme.hedef.ad}</Descriptions.Item>
            </Descriptions>
            <Table
              size="small"
              rowKey="anahtar"
              pagination={false}
              locale={{ emptyText: "Taşınacak bağlı kayıt yok" }}
              dataSource={Object.entries(onizleme.tasinacak).map(([anahtar, adet]) => ({ anahtar, adet }))}
              columns={[
                {
                  title: "Taşınacak",
                  dataIndex: "anahtar",
                  render: (a: string) => TABLO_ADLARI[a] ?? a,
                },
                { title: "Adet", dataIndex: "adet", width: 80, align: "right" },
              ]}
            />
            {Object.keys(onizleme.doldurulacak).length > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Hedefte boş olup kaynaktan doldurulacak: {Object.keys(onizleme.doldurulacak).join(", ")}
              </Typography.Text>
            )}
            {onizleme.engeller.map((e) => (
              <Alert key={e} type="error" showIcon title={e} />
            ))}
            {onizleme.cakisan_tesisler.length > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Aynı adlı tesisler: {onizleme.cakisan_tesisler.map((t) => t.tesis_adi).join(", ")}
              </Typography.Text>
            )}
            {onizleme.uyarilar.map((u) => (
              <Alert key={u} type="warning" showIcon title={u} />
            ))}
            <Input.TextArea
              rows={2}
              maxLength={1000}
              placeholder="Gerekçe (en az 5 karakter)"
              value={gerekce}
              onChange={(e) => setGerekce(e.target.value)}
            />
          </>
        )}
        {hata && <Alert type="error" showIcon title={hata} />}
      </Space>
    </Modal>
  );
}
