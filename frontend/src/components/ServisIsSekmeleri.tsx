/**
 * Servis işi detayının paketler arası sekmeleri (Dalga 1 bütünleştirmesi):
 *
 * - `ZamanSekmesi` (D1-G, TS-075): süre özeti tek kaynaktan (`sure_ozeti`);
 *   kayıt yoksa "Süre kaydı eksik" yazılır, 0 DEĞİL. `zaman.yaz` sahibi elle
 *   kayıt girer (`ManuelKayitPenceresi`).
 * - `PlanGecmisiSekmesi` (D1-D, TS-044): aktif ve pasif bütün plan satırları,
 *   planlayan ve neden ile.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Empty, List, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { DEGISIM_ETIKETLERI, PLAN_NEDENLERI, planlamaApi } from "../api/servisPlanlama";
import { FAALIYET_ADLARI, SURE_DURUMU_ADLARI, servisZaman, sureMetni } from "../api/servisZaman";
import { useAuth } from "../auth/AuthContext";
import { TAYIN } from "../fiori/etiketler";
import { ManuelKayitPenceresi } from "./SayacDugmeleri";

const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");

export function ZamanSekmesi({ isId, soNo }: { isId: number; soNo: string }) {
  const { yetkili } = useAuth();
  const [manuelAcik, setManuelAcik] = useState(false);
  const veri = useQuery({ queryKey: ["is-zamani", isId], queryFn: () => servisZaman.isZamani(isId) });
  if (veri.isError) return <Alert type="error" showIcon title={(veri.error as Error).message} />;
  const o = veri.data?.sure_ozeti;
  const bolumler = (veri.data?.bolumler ?? []).filter((b) => !b.iptal);
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      {o && (
        <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered>
          <Descriptions.Item label="Kişi-saat">
            {sureMetni(o.kisi_saat_dk) ?? <Typography.Text type="warning">Süre kaydı eksik</Typography.Text>}
          </Descriptions.Item>
          <Descriptions.Item label="Durum">
            <Tag color={o.sure_durumu === "TAM" ? "green" : o.sure_durumu === "BEKLENMIYOR" ? undefined : "orange"}>
              {SURE_DURUMU_ADLARI[o.sure_durumu] ?? o.sure_durumu}
            </Tag>
          </Descriptions.Item>
          {o.eksik_kisiler.length > 0 && (
            <Descriptions.Item label="Kaydı eksik" span={2}>
              {o.eksik_kisiler.join(", ")}
            </Descriptions.Item>
          )}
          {o.mola_dk != null && <Descriptions.Item label="Mola">{sureMetni(o.mola_dk)}</Descriptions.Item>}
        </Descriptions>
      )}
      {yetkili("zaman.yaz") && (
        <Button size="small" onClick={() => setManuelAcik(true)}>
          Elle süre gir
        </Button>
      )}
      <List
        size="small"
        loading={veri.isLoading}
        locale={{ emptyText: "Süre kaydı yok" }}
        dataSource={bolumler}
        renderItem={(b) => (
          <List.Item>
            <Space orientation="vertical" size={0}>
              <Typography.Text strong>
                {FAALIYET_ADLARI[b.faaliyet] ?? b.faaliyet} · {b.kisi_adi ?? "—"}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {zaman(b.started_at)} → {b.ended_at ? zaman(b.ended_at) : "sürüyor"}
                {b.sure_dk != null ? ` · ${b.sure_dk} dk` : ""}
                {b.kaynak !== "CANLI" ? ` · ${b.kaynak.replaceAll("_", " ").toLowerCase()}` : ""}
              </Typography.Text>
            </Space>
          </List.Item>
        )}
      />
      <ManuelKayitPenceresi
        isId={manuelAcik ? isId : null}
        soNo={soNo}
        acik={manuelAcik}
        onKapat={() => setManuelAcik(false)}
      />
    </Space>
  );
}

export function PlanGecmisiSekmesi({ isId }: { isId: number }) {
  const veri = useQuery({ queryKey: ["plan-gecmisi", isId], queryFn: () => planlamaApi.gecmis(isId) });
  if (veri.isError) return <Alert type="error" showIcon title={(veri.error as Error).message} />;
  if (!veri.isLoading && !veri.data?.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Plan yok" />;
  }
  return (
    <List
      size="small"
      loading={veri.isLoading}
      dataSource={(veri.data ?? []).slice().reverse()}
      renderItem={(p) => (
        <List.Item>
          <Space orientation="vertical" size={0}>
            <Space wrap size={4}>
              <Typography.Text strong>
                {dayjs(p.plan_tarihi).format("DD.MM.YYYY")}
                {p.baslangic_saati ? ` ${p.baslangic_saati.slice(0, 5)}` : ""} · {p.sure_dk} dk
              </Typography.Text>
              <Tag>{DEGISIM_ETIKETLERI[p.degisim] ?? p.degisim}</Tag>
              {p.aktif ? <Tag color="green">Aktif</Tag> : <Tag>Geçmiş</Tag>}
            </Space>
            <Typography.Text>
              {p.ekip.length ? `${TAYIN.tayinEdilen}: ` : ""}
              {p.ekip.map((e) => e.ad ?? `#${e.user_id}`).join(", ") || TAYIN.tayinEdilmemis}
            </Typography.Text>
            {(p.degisim_nedeni || p.iptal_nedeni) && (
              <Typography.Text type="secondary">
                {[
                  p.degisim_nedeni && PLAN_NEDENLERI[p.degisim_nedeni],
                  p.degisim_notu,
                  p.iptal_nedeni && `Geri alındı: ${PLAN_NEDENLERI[p.iptal_nedeni] ?? p.iptal_nedeni}`,
                  p.iptal_notu,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </Typography.Text>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {zaman(p.olusturma)} · {p.planlayan ?? "Sistem"}
            </Typography.Text>
          </Space>
        </List.Item>
      )}
    />
  );
}
