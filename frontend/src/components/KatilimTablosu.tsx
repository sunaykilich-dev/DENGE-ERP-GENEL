/**
 * Oturumda toplu katılım girişi (TS-158).
 *
 * Kursun o yıl açık planı olan kişiler önceden listelenir; plan dışı kişi
 * eklenebilir. Sunucu satırları TEK transaction'da yazar: ilk hatada hiçbir
 * satır yazılmaz ve yanıt hatalı satırın numarasını taşır (`{satir, mesaj}`).
 * Tamamlama kuralı tek kişilik girişle aynıdır (en eski açık plan kapanır).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, InputNumber, Select, Space, Switch, Table, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import type { ApiError } from "../api/client";
import { egitimApi, type KatilimAdayi, type Oturum } from "../api/egitim";

interface Satir {
  user_id: number;
  ad: string;
  planli: boolean;
  katildi: boolean;
  on_puan: number | null;
  son_puan: number | null;
}

export default function KatilimTablosu({ oturum, yazabilir }: { oturum: Oturum; yazabilir: boolean }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [satirlar, setSatirlar] = useState<Satir[]>([]);
  const [hataliSatir, setHataliSatir] = useState<number | null>(null);
  const [arama, setArama] = useState("");

  const adaylar = useQuery({
    queryKey: ["egitim-katilimcilar", oturum.id],
    queryFn: () => egitimApi.katilimcilar(oturum.id),
  });
  const kisiler = useQuery({
    queryKey: ["egitim-kisiler", "katilim", arama],
    queryFn: () => egitimApi.kisiler({ q: arama }, 30, 0),
    enabled: yazabilir,
  });

  useEffect(() => {
    if (!adaylar.data) return;
    setSatirlar(
      adaylar.data.map((a: KatilimAdayi) => ({
        user_id: a.user_id,
        ad: a.ad,
        planli: a.planli,
        katildi: a.katildi ?? true,
        on_puan: a.on_puan,
        son_puan: a.son_puan,
      })),
    );
  }, [adaylar.data]);

  const degistir = (i: number, alan: Partial<Satir>) =>
    setSatirlar((s) => s.map((x, j) => (j === i ? { ...x, ...alan } : x)));

  const kaydet = useMutation({
    mutationFn: () =>
      egitimApi.topluKatilim(
        oturum.id,
        satirlar.map((s) => ({ user_id: s.user_id, katildi: s.katildi, on_puan: s.on_puan, son_puan: s.son_puan })),
      ),
    onSuccess: (r) => {
      setHataliSatir(null);
      message.success(`${r.yazilan} katılım kaydedildi`);
      void qc.invalidateQueries({ queryKey: ["egitim-katilimcilar", oturum.id] });
      void qc.invalidateQueries({ queryKey: ["egitim-oturumlar"] });
      void qc.invalidateQueries({ queryKey: ["egitim-planlar"] });
    },
    onError: (e: ApiError) => {
      const govde = e.govde as { detail?: { satir?: number; mesaj?: string } } | undefined;
      const satir = govde?.detail && typeof govde.detail === "object" ? govde.detail.satir : undefined;
      setHataliSatir(satir ?? null);
      message.error(satir ? `${satir}. satır: ${govde?.detail?.mesaj ?? ""} — hiçbir satır kaydedilmedi` : e.message);
    },
  });

  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      {yazabilir && (
        <Space wrap>
          <Select
            showSearch
            filterOption={false}
            onSearch={setArama}
            placeholder="Plan dışı kişi ekle"
            style={{ minWidth: 240 }}
            value={null}
            options={(kisiler.data?.kayitlar ?? [])
              .filter((k) => !satirlar.some((s) => s.user_id === k.id))
              .map((k) => ({ value: k.id, label: k.ad }))}
            onChange={(id: number) => {
              const k = kisiler.data?.kayitlar.find((x) => x.id === id);
              if (k)
                setSatirlar((s) => [
                  ...s,
                  { user_id: k.id, ad: k.ad, planli: false, katildi: true, on_puan: null, son_puan: null },
                ]);
            }}
          />
          <Button type="primary" disabled={!satirlar.length} loading={kaydet.isPending} onClick={() => kaydet.mutate()}>
            Katılımı kaydet
          </Button>
        </Space>
      )}
      <Table<Satir>
        size="small"
        rowKey="user_id"
        loading={adaylar.isLoading}
        dataSource={satirlar}
        pagination={false}
        scroll={{ x: 520 }}
        locale={{ emptyText: <Empty description="Bu oturum için planlı kişi yok" /> }}
        rowClassName={(_, i) => (hataliSatir === i + 1 ? "satir-hatali" : "")}
        columns={[
          { title: "#", width: 44, render: (_, __, i) => i + 1 },
          {
            title: "Personel",
            dataIndex: "ad",
            render: (ad: string, s) => (
              <Space size={4}>
                <Typography.Text type={hataliSatir != null && satirlar[hataliSatir - 1] === s ? "danger" : undefined}>
                  {ad}
                </Typography.Text>
                {!s.planli && <Tag>Plan dışı</Tag>}
              </Space>
            ),
          },
          {
            title: "Katıldı",
            width: 80,
            render: (_, s, i) => (
              <Switch size="small" checked={s.katildi} disabled={!yazabilir} onChange={(v) => degistir(i, { katildi: v })} />
            ),
          },
          {
            title: "Ön sınav",
            width: 100,
            render: (_, s, i) => (
              <InputNumber
                size="small"
                min={0}
                max={100}
                disabled={!yazabilir}
                value={s.on_puan}
                onChange={(v) => degistir(i, { on_puan: v })}
              />
            ),
          },
          {
            title: "Son sınav",
            width: 100,
            render: (_, s, i) => (
              <InputNumber
                size="small"
                min={0}
                max={100}
                disabled={!yazabilir}
                value={s.son_puan}
                onChange={(v) => degistir(i, { son_puan: v })}
              />
            ),
          },
        ]}
      />
    </Space>
  );
}
