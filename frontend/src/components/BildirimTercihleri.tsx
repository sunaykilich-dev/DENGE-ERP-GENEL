/**
 * Kullanıcı menüsündeki "Bildirim tercihleri" penceresi (TS-200, E10-06).
 * Doldurdu: D3-F (iskelet ve kullanıcı menüsü bağlantısı D3-S).
 *
 * Uçlar: `GET/PUT /api/teknik-servis/bildirim-tercihlerim` (`servis.gor`,
 * yalnız kendi satırı; kimlik oturumdan gelir). AppLayout menü kalemini
 * `BILDIRIM_TERCIHLERI_ETKIN` true iken ve yalnız `servis.gor` sahibine gösterir.
 *
 * Alıcı listesi saklanmaz: e-posta gönderim anında kapsamınızla hesaplanır
 * (yalnız görebildiğiniz işlerin bildirimi gelir). E-posta adresi burada
 * düzenlenmez (Kullanıcılar ekranı); yalnız tanımlı olup olmadığı gösterilir.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Checkbox, Modal, Skeleton, Space, Typography } from "antd";
import { useState } from "react";

import type { ApiError } from "../api/client";
import { operasyonApi } from "../api/servisOperasyon";

export const BILDIRIM_TERCIHLERI_ETKIN: boolean = true;

export interface BildirimTercihleriProps {
  acik: boolean;
  kapat: () => void;
}

interface Taslak {
  anlik_eposta: boolean;
  gunluk_ozet: boolean;
}

export default function BildirimTercihleriPenceresi({ acik, kapat }: BildirimTercihleriProps) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [taslak, setTaslak] = useState<Taslak | null>(null);
  const veri = useQuery({
    queryKey: ["bildirim-tercihim"],
    queryFn: operasyonApi.tercihim,
    enabled: acik,
  });
  const deger: Taslak | null =
    taslak ?? (veri.data ? { anlik_eposta: veri.data.anlik_eposta, gunluk_ozet: veri.data.gunluk_ozet } : null);

  const kaydet = useMutation({
    mutationFn: (t: Taslak) => operasyonApi.tercihimYaz(t),
    onSuccess: (r) => {
      qc.setQueryData(["bildirim-tercihim"], r);
      message.success("Bildirim tercihleriniz kaydedildi");
      setTaslak(null);
      kapat();
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const vazgec = () => {
    setTaslak(null);
    kapat();
  };

  return (
    <Modal
      title="Bildirim tercihleri"
      open={acik}
      onCancel={vazgec}
      onOk={() => deger && kaydet.mutate(deger)}
      okText="Kaydet"
      cancelText="Vazgeç"
      okButtonProps={{ disabled: !deger }}
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      {veri.isLoading && <Skeleton active paragraph={{ rows: 3 }} />}
      {veri.isError && <Alert type="error" showIcon title={(veri.error as ApiError).message} />}
      {veri.data && deger && (
        <Space orientation="vertical" style={{ width: "100%" }} size="middle">
          {!veri.data.servis_eposta_acik && (
            <Alert
              type="info"
              showIcon
              title="Servis e-postaları şu an sistem genelinde kapalı."
              description="Tercihiniz kaydedilir; yönetici e-postayı açtığında uygulanır."
            />
          )}
          {!veri.data.eposta_tanimli && (
            <Alert
              type="warning"
              showIcon
              title="Hesabınızda e-posta adresi tanımlı değil."
              description="Adres tanımlanana kadar e-posta gönderilmez. Adres için sistem yöneticisine başvurun."
            />
          )}
          <Checkbox
            checked={deger.anlik_eposta}
            onChange={(e) => setTaslak({ ...deger, anlik_eposta: e.target.checked })}
          >
            SLA aşıldığında ve müdahale geciktiğinde anında e-posta al
          </Checkbox>
          <Checkbox
            checked={deger.gunluk_ozet}
            onChange={(e) => setTaslak({ ...deger, gunluk_ozet: e.target.checked })}
          >
            Her gün {veri.data.gunluk_ozet_saati}'da günlük SLA özeti al
          </Checkbox>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Yalnız görme yetkiniz olan servis işlerinin bildirimleri gelir. E-postalarda fiyat ve
            iletişim telefonu yer almaz; ayrıntı için ERP bağlantısı verilir.
          </Typography.Text>
        </Space>
      )}
    </Modal>
  );
}
