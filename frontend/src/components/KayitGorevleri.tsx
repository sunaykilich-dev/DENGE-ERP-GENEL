import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, Select, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { gorevApi, ONCELIK_ETIKET, ONCELIK_RENK } from "../api/gorevler";
import { useAuth } from "../auth/AuthContext";

/**
 * Bir ERP kaydına bağlı görev kartları — kayıt ekranına gömülür.
 *
 * Panoya gitmeden "bu hesapta/iş emrinde ne bekliyor" sorusunun cevabı.
 * Kart buradan da açılabilir; pano seçimi gerekiyor çünkü kart bir panoya
 * ait olmak zorunda — ama kullanıcı pano seçmeyi düşünmek zorunda kalmasın
 * diye tek pano varsa kendiliğinden seçilir.
 */
export default function KayitGorevleri({
  entity,
  entityId,
}: {
  entity: string;
  entityId: number;
}) {
  const { yetkili } = useAuth();
  const duzenleyebilir = yetkili("gorev.yaz");
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [baslik, setBaslik] = useState("");
  const [panoSecim, setPanoSecim] = useState<number>();

  const kartlar = useQuery({
    queryKey: ["kayit-gorevleri", entity, entityId],
    queryFn: () => gorevApi.kaydinKartlari(entity, entityId),
  });
  const panolar = useQuery({
    queryKey: ["panolar"],
    queryFn: () => gorevApi.panolar(),
    enabled: duzenleyebilir,
  });

  const seciliPano =
    panolar.data?.find((p) => p.id === panoSecim) ??
    (panolar.data?.length === 1 ? panolar.data[0] : undefined);

  const ekle = useMutation({
    mutationFn: () =>
      gorevApi.kartAc(seciliPano!.id, {
        column_id: seciliPano!.kolonlar[0].id,
        title: baslik.trim(),
        entity,
        entity_id: entityId,
      }),
    onSuccess: () => {
      setBaslik("");
      message.success("Görev eklendi");
      void qc.invalidateQueries({ queryKey: ["kayit-gorevleri", entity, entityId] });
      void qc.invalidateQueries({ queryKey: ["pano-kartlar"] });
      void qc.invalidateQueries({ queryKey: ["panolar"] });
    },
    onError: (e: Error) => void message.error(e.message),
  });

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {kartlar.data?.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="Bu kayda bağlı görev yok"
          style={{ margin: "4px 0" }}
        />
      )}

      {(kartlar.data ?? []).map((k) => (
        <div
          key={k.id}
          style={{
            border: "1px solid #e6e3dc",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 13,
          }}
        >
          <Space size={6} wrap>
            <span
              style={{
                textDecoration: k.tamamlandi_at ? "line-through" : undefined,
                color: k.tamamlandi_at ? "#8c8c8c" : undefined,
              }}
            >
              {k.title}
            </span>
            {k.etiketler.map((e) => (
              <Tag key={e.id} color={e.renk}>
                {e.ad || "\u00a0"}
              </Tag>
            ))}
            {ONCELIK_RENK[k.oncelik] && (
              <Tag color={ONCELIK_RENK[k.oncelik]}>{ONCELIK_ETIKET[k.oncelik]}</Tag>
            )}
            {k.uyeler.map((u) => (
              <Tag key={u.id}>{u.ad}</Tag>
            ))}
            {k.due_date && (
              <Tag
                color={
                  !k.tamamlandi_at && dayjs(k.due_date).isBefore(dayjs(), "day") ? "red" : undefined
                }
              >
                {dayjs(k.due_date).format("D MMM")}
              </Tag>
            )}
          </Space>
        </div>
      ))}

      {duzenleyebilir && (
        <Space.Compact style={{ width: "100%" }}>
          {panolar.data && panolar.data.length > 1 && (
            <Select
              style={{ width: 170 }}
              value={seciliPano?.id}
              onChange={setPanoSecim}
              placeholder="Pano"
              options={panolar.data.map((p) => ({ value: p.id, label: p.title }))}
            />
          )}
          <input
            style={{
              flex: 1,
              border: "1px solid #d9d9d9",
              borderRadius: 6,
              padding: "4px 10px",
              fontSize: 13,
            }}
            placeholder="Yeni görev…"
            value={baslik}
            onChange={(e) => setBaslik(e.target.value)}
          />
          <Button
            disabled={!baslik.trim() || !seciliPano}
            loading={ekle.isPending}
            onClick={() => ekle.mutate()}
          >
            Ekle
          </Button>
        </Space.Compact>
      )}

      {duzenleyebilir && !panolar.data?.length && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Görev eklemek için önce <Link to="/gorevler">bir pano açın</Link>.
        </Typography.Text>
      )}
    </Space>
  );
}
