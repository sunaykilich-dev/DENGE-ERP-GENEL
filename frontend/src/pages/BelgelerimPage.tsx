import { CheckOutlined, ExclamationCircleOutlined, FilePdfOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Checkbox, Empty, Input, List, Modal, Space, Spin, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import type { ApiError } from "../api/client";
import { type Belgem, DURUM_ETIKETLERI, ikBelgeApi } from "../api/ikBelgeler";
import { useAuth } from "../auth/AuthContext";
import OzlukDosyasi from "../components/OzlukDosyasi";

/**
 * Belgelerim (KARARLAR 2026-10-28 §11): personelin kendi bordroları ve
 * imzalaması istenen form/talimat/taahhütnameleri. Masaüstü ve mobilde aynı
 * sade liste: belgeyi aç → "Onaylıyorum" ya da "İtiraz et". Onay ve itiraz
 * parola tekrarı (iki adımlı doğrulaması açıksa tek kullanımlık kod) ister.
 */
export default function BelgelerimPage() {
  const liste = useQuery({ queryKey: ["belgelerim"], queryFn: ikBelgeApi.belgelerim });
  const qc = useQueryClient();
  const [yanit, setYanit] = useState<{ belge: Belgem; onay: boolean } | null>(null);

  const ac = (b: Belgem) => {
    window.open(ikBelgeApi.belgemDosyaUrl(b.id), "_blank", "noopener");
    // Açmak "görüldü" kaydıdır; liste kısa süre sonra tazelenir.
    window.setTimeout(() => {
      void qc.invalidateQueries({ queryKey: ["belgelerim"] });
      void qc.invalidateQueries({ queryKey: ["belgelerim-ozet"] });
    }, 1200);
  };

  const belgeler = liste.data ?? [];
  const bekleyen = belgeler.filter((b) => b.durum === "GONDERILDI" || b.durum === "GORULDU");
  const yanitlanan = belgeler.filter((b) => !bekleyen.includes(b));

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size="middle">
      <Card title="Belgelerim">
        {liste.isLoading && <Spin />}
        {liste.error && <Alert type="error" title={(liste.error as Error).message} />}
        {liste.data && belgeler.length === 0 && <Empty description="Size gönderilmiş belge yok" />}
        {bekleyen.length > 0 && (
          <Alert
            style={{ marginBottom: 12 }}
            type="warning"
            showIcon
            title={`${bekleyen.length} belge onayınızı bekliyor`}
            description="Belgeyi açıp okuyun, sonra onaylayın ya da gerekçe yazarak itiraz edin."
          />
        )}
        {[...bekleyen, ...yanitlanan].length > 0 && (
          <List
            itemLayout="vertical"
            dataSource={[...bekleyen, ...yanitlanan]}
            renderItem={(b) => <BelgeSatiri belge={b} onAc={ac} onYanit={(onay) => setYanit({ belge: b, onay })} />}
          />
        )}
        {yanit && <YanitPenceresi belge={yanit.belge} onay={yanit.onay} kapat={() => setYanit(null)} />}
      </Card>
      {/* Özlük dosyası (2026-11-20): İK'nın yüklediği kendi belgeleri, salt okunur. */}
      <Card title="Özlük dosyam">
        <OzlukDosyasi benim />
      </Card>
    </Space>
  );
}

function BelgeSatiri({
  belge: b,
  onAc,
  onYanit,
}: {
  belge: Belgem;
  onAc: (b: Belgem) => void;
  onYanit: (onay: boolean) => void;
}) {
  const durum = DURUM_ETIKETLERI[b.durum];
  const bekliyor = b.durum === "GONDERILDI" || b.durum === "GORULDU";
  const gecikti = bekliyor && b.son_tarih && dayjs().isAfter(dayjs(b.son_tarih), "day");
  return (
    <List.Item
      key={b.id}
      actions={[
        <Button key="ac" icon={<FilePdfOutlined />} onClick={() => onAc(b)}>
          Belgeyi aç
        </Button>,
        ...(bekliyor
          ? [
              <Button
                key="onay"
                type="primary"
                icon={<CheckOutlined />}
                disabled={b.durum === "GONDERILDI"}
                onClick={() => onYanit(true)}
              >
                Onaylıyorum
              </Button>,
              <Button
                key="itiraz"
                danger
                icon={<ExclamationCircleOutlined />}
                disabled={b.durum === "GONDERILDI"}
                onClick={() => onYanit(false)}
              >
                İtiraz et
              </Button>,
            ]
          : []),
      ]}
    >
      <List.Item.Meta
        title={
          <Space wrap>
            <Tag>{b.tur_adi}</Tag>
            <span>{b.baslik}</span>
            <Tag color={durum.renk}>{durum.ad}</Tag>
            {gecikti && <Tag color="red">Son tarih geçti</Tag>}
          </Space>
        }
        description={
          <Space orientation="vertical" size={0}>
            <span>
              Gönderildi: {dayjs(b.gonderildi_at).format("DD.MM.YYYY HH:mm")}
              {b.son_tarih && ` · Son tarih: ${dayjs(b.son_tarih).format("DD.MM.YYYY")}`}
            </span>
            {b.yanit_at && <span>Yanıt: {dayjs(b.yanit_at).format("DD.MM.YYYY HH:mm")}</span>}
            {b.durum === "GONDERILDI" && (
              <Typography.Text type="secondary">Onaylamak için önce belgeyi açın.</Typography.Text>
            )}
          </Space>
        }
      />
      {b.aciklama && <Typography.Paragraph>{b.aciklama}</Typography.Paragraph>}
      {b.itiraz_gerekcesi && (
        <Typography.Paragraph type="danger">İtirazınız: {b.itiraz_gerekcesi}</Typography.Paragraph>
      )}
    </List.Item>
  );
}

function YanitPenceresi({ belge, onay, kapat }: { belge: Belgem; onay: boolean; kapat: () => void }) {
  const { message } = App.useApp();
  const { kullanici } = useAuth();
  const qc = useQueryClient();
  const kodlu = !!kullanici?.mfa_enabled;
  const [okudum, setOkudum] = useState(false);
  const [gerekce, setGerekce] = useState("");
  const [sir, setSir] = useState("");

  const gonder = useMutation({
    mutationFn: () => {
      const d = kodlu ? { kod: sir } : { parola: sir };
      return onay ? ikBelgeApi.onayla(belge.id, d) : ikBelgeApi.itiraz(belge.id, gerekce, d);
    },
    onSuccess: () => {
      void message.success(onay ? "Belge onaylandı" : "İtirazınız İK'ya iletildi");
      void qc.invalidateQueries({ queryKey: ["belgelerim"] });
      void qc.invalidateQueries({ queryKey: ["belgelerim-ozet"] });
      kapat();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const hazir = sir.length > 0 && (onay ? okudum : gerekce.trim().length >= 5);
  return (
    <Modal
      open
      title={onay ? "Belgeyi onayla" : "İtiraz et"}
      okText={onay ? "Onaylıyorum" : "İtirazı gönder"}
      okButtonProps={{ disabled: !hazir, danger: !onay, loading: gonder.isPending }}
      cancelText="Vazgeç"
      onOk={() => gonder.mutate()}
      onCancel={kapat}
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Typography.Text strong>{belge.baslik}</Typography.Text>
        {onay ? (
          <Checkbox checked={okudum} onChange={(e) => setOkudum(e.target.checked)}>
            Belgeyi okudum, içeriğini onaylıyorum.
          </Checkbox>
        ) : (
          <Input.TextArea
            rows={4}
            maxLength={2000}
            placeholder="İtiraz gerekçeniz (en az 5 karakter)"
            value={gerekce}
            onChange={(e) => setGerekce(e.target.value)}
          />
        )}
        <Input.Password
          autoComplete={kodlu ? "one-time-code" : "current-password"}
          placeholder={kodlu ? "Doğrulama uygulamasındaki kod" : "Parolanız"}
          value={sir}
          onChange={(e) => setSir(e.target.value)}
          onPressEnter={() => hazir && gonder.mutate()}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Kimliğinizi doğrulamak için {kodlu ? "kodu" : "parolanızı"} yeniden girin. Yanıtınız tarih,
          IP ve belge özetiyle kaydedilir; sonradan değiştirilemez.
        </Typography.Text>
      </Space>
    </Modal>
  );
}
