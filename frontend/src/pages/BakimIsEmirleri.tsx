/**
 * Planlı bakım iş emirleri (sunucu `bakim_is_emri`).
 *
 * Yıllık bakımlar açılmadan önce burada iş emri olarak bekler: her satır bir
 * bakım dönemi (müşteri/tesis × hedef tarih) ve o dönemde açılacak cihaz iş
 * emirleri. Yönetici satırları seçip "İş emirlerini aç" der; önce önizleme
 * (kaç iş açılacak, atlananlar), onayla cihaz başına bir PB açılır ve Servis
 * Planlama'ya düşer. Açılmış iş tekrar açılmaz.
 *
 * 2026-11-18 (UI/UX revize S2): ayrı "PB Üretimi" sekmesi kaldırıldı; aynı işi
 * bu sekme yapar. Gece otomatiği anahtarı ve üretim kayıtları (başka ekranı
 * yok) bu sekmenin başlığındadır; sunucu kuralları değişmedi (%100 eşleştirme
 * olmadan otomatik açılamaz, `bakim.otomatik_uretim_ayarla`).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Modal, Select, Space, Switch, Table, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import {
  bakimApi,
  hataMetni,
  PLANLI_IS_DURUMLARI,
  type PlanliIs,
  type TopluAcSonucu,
  type UretimKaydi,
} from "../api/bakim";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { useAuth } from "../auth/AuthContext";

const gun = (v: string) => dayjs(v).format("DD.MM.YYYY");
const ZAMANI_GELEN = new Set(["GECIKMIS", "ILK_TURDA", "KISMEN"]);

function OnizlemeOzeti({ y }: { y: TopluAcSonucu }) {
  const bulunamayan = y.satirlar.filter((s) => s.sonuc === "BULUNAMADI").length;
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Typography.Text>
        <b>{y.acilan}</b> cihaz iş emri açılacak. Her biri Servis Planlama ekranına düşer.
      </Typography.Text>
      {bulunamayan > 0 && (
        <Alert type="warning" showIcon title={`${bulunamayan} dönem bulunamadı ya da yetki dışında`} />
      )}
      {y.atlanan.map((a, i) => (
        <Alert
          key={i}
          type="warning"
          showIcon
          title={`${a.musteri ?? a.contract_no}: ${a.neden}`}
        />
      ))}
    </Space>
  );
}

/** Gece otomatiği (eski "PB Üretimi" sekmesinden) + üretim kayıtları bağlantısı. */
function OtomatikUretim() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [kayitAcik, setKayitAcik] = useState(false);
  const otomatik = useQuery({ queryKey: ["bakim", "otomatik-uretim"], queryFn: bakimApi.otomatikUretim });
  const kayitlar = useQuery({
    queryKey: ["bakim", "uretim-kayitlari"],
    queryFn: () => bakimApi.uretimKayitlari(),
    enabled: kayitAcik,
  });
  const ayarla = useMutation({
    mutationFn: bakimApi.otomatikUretimAyarla,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bakim", "otomatik-uretim"] }),
    onError: (e) => void message.error(hataMetni(e)),
  });
  const o = otomatik.data;
  if (!o) return null;
  return (
    <Space wrap size={8} style={{ marginBottom: 12 }}>
      <Tooltip
        title={
          o.oran.yuzde < 100
            ? `%100 eşleştirme olmadan otomatik üretim açılamaz (şu an %${o.oran.yuzde}, ${o.oran.eslesen}/${o.oran.toplam})`
            : `Eşleştirme %${o.oran.yuzde} (${o.oran.eslesen}/${o.oran.toplam})`
        }
      >
        <Space size={6}>
          <Switch
            size="small"
            checked={o.acik}
            disabled={!o.degistirebilir}
            loading={ayarla.isPending}
            onChange={(v) => ayarla.mutate(v)}
            aria-label="Otomatik PB üretimi (gece)"
          />
          <Typography.Text>Otomatik PB üretimi (gece)</Typography.Text>
          {o.oran.yuzde < 100 && <Tag color="gold">Eşleştirme %{o.oran.yuzde}</Tag>}
        </Space>
      </Tooltip>
      <Button type="link" size="small" style={{ paddingInline: 0 }} onClick={() => setKayitAcik(true)}>
        Üretim kayıtları
      </Button>
      <Modal
        title="Üretim kayıtları"
        open={kayitAcik}
        onCancel={() => setKayitAcik(false)}
        footer={null}
        width={720}
        destroyOnHidden
      >
        <Table<UretimKaydi>
          rowKey="id"
          size="small"
          loading={kayitlar.isLoading}
          dataSource={kayitlar.data?.kayitlar}
          pagination={false}
          scroll={{ x: 560 }}
          columns={[
            { title: "Tarih", dataIndex: "created_at", render: (v) => dayjs(v).format("DD.MM.YYYY HH:mm") },
            { title: "Tetik", dataIndex: "tetik" },
            { title: "Üretilen", dataIndex: "generated_count", render: (v) => v ?? "—" },
            {
              title: "Atlanan",
              render: (_, r) =>
                r.skipped.length ? (
                  <Typography.Text type="danger">
                    {r.skipped.map((a) => `${a.contract_no}: ${a.neden_kodu}`).join(", ")}
                  </Typography.Text>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      </Modal>
    </Space>
  );
}

export default function BakimIsEmirleriSekmesi() {
  const { yetkili } = useAuth();
  const yazabilir = yetkili("bakim.yaz");
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [ufuk, setUfuk] = useState(12);
  const [birim, setBirim] = useState<string | undefined>();
  const [hepsi, setHepsi] = useState(false);
  const [secim, setSecim] = useState<number[]>([]);

  const bit = dayjs().add(ufuk, "month").format("YYYY-MM-DD");
  const veri = useQuery({
    queryKey: ["bakim", "planli-isler", bit, birim, hepsi],
    queryFn: () => bakimApi.planliIsler({ bit, birim, yalniz_acilmamis: !hepsi }),
  });
  const satirlar = veri.data?.satirlar ?? [];
  const secilenler = satirlar.filter((r) => secim.includes(r.donem_id));
  const secilenCihaz = secilenler.reduce((t, r) => t + r.acilacak, 0);

  const ac = useMutation({
    mutationFn: (onizleme: boolean) => bakimApi.planliIsleriAc(secim, onizleme),
    onError: (e) => void message.error(hataMetni(e)),
  });

  const baslat = async () => {
    const on = await ac.mutateAsync(true);
    modal.confirm({
      title: "İş emirlerini aç",
      width: 560,
      content: <OnizlemeOzeti y={on} />,
      okText: on.acilan ? `${on.acilan} iş emrini aç` : "Tamam",
      okButtonProps: { disabled: on.acilan === 0 },
      cancelText: "Vazgeç",
      onOk: async () => {
        const y = await ac.mutateAsync(false);
        message.success(`${y.acilan} bakım iş emri açıldı`);
        setSecim([]);
        await qc.invalidateQueries({ queryKey: ["bakim"] });
      },
    });
  };

  return (
    <>
      <OtomatikUretim />
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="Yıllık bakımlar burada iş emri olarak bekler"
        description={
          "Açmak istediğiniz dönemleri seçip “İş emirlerini aç” deyin: her cihaz için bir " +
          "planlı bakım iş emri açılır ve Servis Planlama ekranına düşer. Açılmış iş tekrar açılmaz."
        }
      />
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          value={ufuk}
          onChange={(v) => {
            setUfuk(v);
            setSecim([]);
          }}
          style={{ width: 150 }}
          options={[1, 3, 6, 12, 24].map((a) => ({ value: a, label: `Önümüzdeki ${a} ay` }))}
        />
        <Select
          allowClear
          placeholder="Birim"
          style={{ width: 160 }}
          value={birim}
          onChange={(v) => {
            setBirim(v);
            setSecim([]);
          }}
          options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
        />
        <Space size={6}>
          <Switch checked={hepsi} onChange={setHepsi} size="small" />
          <Typography.Text>Açılmışları da göster</Typography.Text>
        </Space>
        {yazabilir && (
          <>
            <Button
              onClick={() =>
                setSecim(
                  satirlar.filter((r) => r.acilacak > 0 && ZAMANI_GELEN.has(r.durum)).map((r) => r.donem_id),
                )
              }
            >
              Zamanı gelenleri seç
            </Button>
            <Button
              type="primary"
              disabled={secilenCihaz === 0}
              loading={ac.isPending}
              onClick={() => void baslat()}
            >
              İş emirlerini aç{secilenCihaz ? ` (${secilenCihaz})` : ""}
            </Button>
          </>
        )}
      </Space>
      {veri.data?.kesildi && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8 }}
          title="Liste uzun; ufku ya da birimi daraltın"
        />
      )}
      <Table<PlanliIs>
        rowKey="donem_id"
        size="small"
        loading={veri.isLoading}
        dataSource={satirlar}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        rowSelection={
          yazabilir
            ? {
                selectedRowKeys: secim,
                onChange: (k) => setSecim(k as number[]),
                getCheckboxProps: (r) => ({ disabled: r.acilacak === 0 }),
              }
            : undefined
        }
        locale={{ emptyText: "Açılmayı bekleyen bakım iş emri yok" }}
        summary={() =>
          veri.data ? (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0} colSpan={yazabilir ? 5 : 4}>
                <Typography.Text type="secondary">
                  {satirlar.length} dönem · açılacak {veri.data.toplam_acilacak} cihaz iş emri
                </Typography.Text>
              </Table.Summary.Cell>
            </Table.Summary.Row>
          ) : null
        }
        columns={[
          {
            title: "Bakım tarihi",
            width: 170,
            render: (_, r) => {
              const d = PLANLI_IS_DURUMLARI[r.durum] ?? { ad: r.durum, renk: "default" };
              return (
                <Space orientation="vertical" size={0}>
                  <Typography.Text strong>{gun(r.hedef)}</Typography.Text>
                  <Tag color={d.renk}>{d.ad}</Tag>
                </Space>
              );
            },
          },
          {
            title: "Müşteri / tesis",
            render: (_, r) => (
              <>
                {r.musteri ?? "—"}
                <br />
                <Typography.Text type="secondary">
                  {[r.tesis, r.il, BIRIM_ETIKETLERI[r.birim as keyof typeof BIRIM_ETIKETLERI] ?? r.birim]
                    .filter(Boolean)
                    .join(" · ")}{" "}
                  · {r.contract_no}
                  {r.yillik_adet ? ` · yılda ${r.yillik_adet}, ${r.sira}. bakım` : ""}
                </Typography.Text>
              </>
            ),
          },
          {
            title: "Cihaz iş emirleri",
            render: (_, r) => (
              <Space wrap size={4}>
                {r.turler.map((t) => (
                  <Tag key={t.tur}>
                    {t.adet} × {t.ad}
                  </Tag>
                ))}
                {r.eslesmemis > 0 && (
                  <Tooltip title="Sözleşme kalemi cihaza bağlı değil; Sözleşmeler › Eşleştirme sekmesinden bağlayın">
                    <Tag color="orange">{r.eslesmemis} cihaz eşleşmemiş</Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          {
            title: "Açılan / açılacak",
            width: 150,
            align: "right",
            render: (_, r) => (
              <>
                {r.acilan > 0 && <Typography.Text type="secondary">{r.acilan} açık · </Typography.Text>}
                <Typography.Text strong={r.acilacak > 0}>{r.acilacak} açılacak</Typography.Text>
              </>
            ),
          },
        ]}
      />
    </>
  );
}
