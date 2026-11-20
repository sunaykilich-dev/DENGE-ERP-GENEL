/**
 * İzin onayı e-posta bağlantısı (KARARLAR 2026-11-20 §7). OTURUMSUZ açılır.
 *
 * E-postadaki "Onayla / Reddet" düğmesi bu sayfayı açar; karar burada,
 * sayfadaki düğmeyle verilir (e-posta tarayıcılarının bağlantıyı açması onay
 * sayılmasın). Bağlantı tek kullanımlıktır; karar verilince ya da talep bir
 * üst yöneticiye geçince geçersiz olur.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, ConfigProvider, Descriptions, Input, Result, Space, Spin } from "antd";
import trTR from "antd/locale/tr_TR";
import dayjs from "dayjs";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { izinApi } from "../api/izin";

export default function IzinKararPage() {
  const { token = "" } = useParams();
  const [arama] = useSearchParams();
  const onerilen = arama.get("karar") === "RED" ? "RED" : "ONAY";
  const [gerekce, setGerekce] = useState("");
  const ozet = useQuery({ queryKey: ["izin-karar", token], queryFn: () => izinApi.publicGetir(token), retry: false });
  const karar = useMutation({
    mutationFn: (k: "ONAY" | "RED") => izinApi.publicKarar(token, k, gerekce.trim() || null),
  });

  let icerik: React.ReactNode;
  if (ozet.isLoading) icerik = <Spin style={{ display: "block", margin: 48 }} />;
  else if (karar.isSuccess)
    icerik = (
      <Result
        status={karar.variables === "ONAY" ? "success" : "info"}
        title={karar.variables === "ONAY" ? "İzin onaylandı" : "İzin reddedildi"}
        subTitle={`Talebin durumu: ${karar.data.durum_adi}. Bu sayfayı kapatabilirsiniz.`}
      />
    );
  else if (ozet.isError || !ozet.data)
    icerik = (
      <Result
        status="warning"
        title="Bağlantı geçersiz"
        subTitle="Bu bağlantı kullanılmış ya da talep bir üst yöneticiye geçmiş olabilir. ERP'de İzin Talepleri › Onayımda ekranına bakın."
      />
    );
  else {
    const o = ozet.data;
    icerik = (
      <Card title="İzin onayı">
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="Personel">{o.personel}</Descriptions.Item>
            <Descriptions.Item label="Tür">{o.tur_adi}</Descriptions.Item>
            <Descriptions.Item label="Tarih">
              {dayjs(o.baslangic).format("DD.MM.YYYY")} – {dayjs(o.bitis).format("DD.MM.YYYY")} ({o.gun_sayisi} gün)
            </Descriptions.Item>
            <Descriptions.Item label="Vekil">{o.vekil}</Descriptions.Item>
            <Descriptions.Item label="İzinde bulunacağı il">{o.izin_ili}</Descriptions.Item>
            <Descriptions.Item label="Onay basamağı">
              {o.basamak} / {o.basamak_sayisi} ({o.onaylayici})
            </Descriptions.Item>
          </Descriptions>
          <Input.TextArea
            rows={2}
            maxLength={500}
            placeholder={onerilen === "RED" ? "Red gerekçesi (zorunlu)" : "Not (isteğe bağlı; red için zorunlu)"}
            value={gerekce}
            onChange={(e) => setGerekce(e.target.value)}
          />
          {karar.isError && <Alert type="error" showIcon title={(karar.error as Error).message} />}
          <Space>
            <Button
              type={onerilen === "ONAY" ? "primary" : "default"}
              size="large"
              loading={karar.isPending && karar.variables === "ONAY"}
              onClick={() => karar.mutate("ONAY")}
            >
              Onayla
            </Button>
            <Button
              danger
              type={onerilen === "RED" ? "primary" : "default"}
              size="large"
              disabled={!gerekce.trim()}
              loading={karar.isPending && karar.variables === "RED"}
              onClick={() => karar.mutate("RED")}
            >
              Reddet
            </Button>
          </Space>
        </Space>
      </Card>
    );
  }
  return (
    <ConfigProvider locale={trTR}>
      <div style={{ maxWidth: 560, margin: "24px auto", padding: 12 }}>{icerik}</div>
    </ConfigProvider>
  );
}
