import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, InputNumber, Space, Table, Typography } from "antd";
import { useEffect, useState } from "react";

import { api, type ApiError } from "../api/client";

/**
 * İskonto yetkisi (KARARLAR 2026-11-09 S1.1/S1.2).
 *
 * Rol limitleri genel ayar ucuna (`iskonto_rol_limitleri`) TAM tablo olarak
 * yazılır; "Diğer roller" tabloda olmayan rollerin limitidir. Kişi limiti
 * doluysa rol limitinin yerine geçer (boş = rol limiti). Satış müdürü
 * limitini aşan iskonto Genel Müdür / ADMIN onayına gider.
 */

interface Kisi {
  id: number;
  ad: string;
  rol: string | null;
  rol_adi: string | null;
  rol_limiti: number;
  kisi_limiti: number | null;
  etkin_limit: number;
  version: number;
}

interface Limitler {
  rol_limitleri: Record<string, number>;
  roller: { kod: string; ad: string }[];
  kisiler: Kisi[];
}

export default function IskontoLimitleri() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const veri = useQuery({
    queryKey: ["iskonto-limitleri"],
    queryFn: () => api.get<Limitler>("/api/satis-takip/iskonto-limitleri"),
  });
  const [tablo, setTablo] = useState<Record<string, number>>({});
  const [kisiDegeri, setKisiDegeri] = useState<Record<number, number | null>>({});

  useEffect(() => {
    if (veri.data) setTablo(veri.data.rol_limitleri);
  }, [veri.data]);

  const yenile = () => void qc.invalidateQueries({ queryKey: ["iskonto-limitleri"] });

  const rolKaydet = useMutation({
    mutationFn: () => api.patch("/api/ayarlar", { values: { iskonto_rol_limitleri: tablo } }),
    onSuccess: () => {
      message.success("Rol limitleri kaydedildi");
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });
  const kisiKaydet = useMutation({
    mutationFn: (k: Kisi) =>
      api.put<Kisi>(`/api/satis-takip/iskonto-limitleri/kisi/${k.id}`, {
        iskonto_limiti_yuzde: k.id in kisiDegeri ? kisiDegeri[k.id] : k.kisi_limiti,
        version: k.version,
      }),
    onSuccess: (k) => {
      message.success(`${k.ad}: etkin limit %${k.etkin_limit}`);
      setKisiDegeri((d) => {
        const yeni = { ...d };
        delete yeni[k.id];
        return yeni;
      });
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  const roller = [
    ...(veri.data?.roller ?? []).filter((r) => r.kod !== "ADMIN"),
    { kod: "DIGER", ad: "Diğer roller" },
  ];

  return (
    <Card title="İskonto yetkisi" loading={veri.isLoading}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="Ölçü: en yüksek kalem iskontosu ile toplam iskonto oranından büyük olanı."
        description={
          "Limitin altındaki teklif onaysız gönderilir. Üstü Satış Müdürü onayına, Satış Müdürü " +
          "limitinin üstü Genel Müdür / sistem yöneticisi onayına düşer. Onaydan sonra fiyat ya da " +
          "iskonto değişirse onay düşer."
        }
      />
      <Typography.Title level={5}>Rol limitleri (%)</Typography.Title>
      <Space wrap align="end" style={{ marginBottom: 16 }}>
        {roller.map((r) => (
          <Space key={r.kod} orientation="vertical" size={2}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {r.ad}
            </Typography.Text>
            <InputNumber
              min={0}
              max={100}
              step={1}
              value={tablo[r.kod]}
              placeholder={r.kod === "DIGER" ? "10" : `Diğer: ${tablo.DIGER ?? 10}`}
              onChange={(x) =>
                setTablo((t) => {
                  const yeni = { ...t };
                  if (x == null) delete yeni[r.kod];
                  else yeni[r.kod] = Number(x);
                  return yeni;
                })
              }
            />
          </Space>
        ))}
        <Button type="primary" loading={rolKaydet.isPending} onClick={() => rolKaydet.mutate()}>
          Rol limitlerini kaydet
        </Button>
      </Space>
      <Typography.Title level={5}>Kişiye özel limit</Typography.Title>
      <Table<Kisi>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={veri.data?.kisiler ?? []}
        columns={[
          { title: "Kişi", dataIndex: "ad" },
          { title: "Rol", dataIndex: "rol_adi" },
          { title: "Rol limiti", dataIndex: "rol_limiti", className: "mono", render: (x: number) => `%${x}` },
          {
            title: "Kişi limiti",
            render: (_: unknown, k: Kisi) => (
              <InputNumber
                min={0}
                max={100}
                placeholder="rol limiti"
                value={k.id in kisiDegeri ? kisiDegeri[k.id] : k.kisi_limiti}
                onChange={(x) => setKisiDegeri((d) => ({ ...d, [k.id]: x == null ? null : Number(x) }))}
              />
            ),
          },
          { title: "Etkin", dataIndex: "etkin_limit", className: "mono", render: (x: number) => `%${x}` },
          {
            title: "",
            width: 90,
            render: (_: unknown, k: Kisi) => (
              <Button
                size="small"
                disabled={!(k.id in kisiDegeri)}
                loading={kisiKaydet.isPending && kisiKaydet.variables?.id === k.id}
                onClick={() => kisiKaydet.mutate(k)}
              >
                Kaydet
              </Button>
            ),
          },
        ]}
      />
    </Card>
  );
}
