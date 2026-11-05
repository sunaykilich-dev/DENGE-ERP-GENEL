/**
 * Bakım takvimi ve toplu karar tarihi girişi (sunucu `bakim_karar`).
 *
 * - `KararTarihleriPenceresi`: sözleşmelere karar tarihi (gerekirse yıllık
 *   adet, süre, güncel dönemde yapılan bakım adedi) girilir. Önce önizleme:
 *   hangi ayda bakım düşeceği, kaç dönemin gecikmiş açılacağı ve ilk turda kaç
 *   PB açılacağı görünür; "Uygula" aynı satırları yazar. Önizleme yazmaz.
 * - `BakimTakvimiSekmesi`: aktif sözleşmeler × 12 ay. Her dönem rozeti
 *   durumuyla renklenir (gecikmiş, PB açıldı, ileride…). PB işleri hedeften
 *   `on_acilis_gun` gün önce otomatik açılır; planlama ekranında lokasyon
 *   grubu olarak toplu planlanır.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  DatePicker,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import {
  bakimApi,
  hataMetni,
  type KararSonucu,
  type Sozlesme,
  TAKVIM_DURUMLARI,
  type TakvimDonemi,
  type TopluKararYaniti,
  type YillikTakvim,
} from "../api/bakim";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";

// Ay adları çağrı anında üretilir: dayjs yereli (tr) modül yüklendikten sonra ayarlanıyor.
const ayAdlari = () => Array.from({ length: 12 }, (_, i) => dayjs().month(i).format("MMM"));
const gun = (v: string | null | undefined) => (v ? dayjs(v).format("DD.MM.YYYY") : "—");

function DonemRozeti({ d }: { d: TakvimDonemi }) {
  const t = TAKVIM_DURUMLARI[d.durum] ?? { ad: d.durum, renk: "default" };
  const ipucu = [
    `Hedef: ${gun(d.hedef)}`,
    t.ad,
    d.pb_sayisi ? `${d.pb_sayisi} PB` : null,
    d.pb_acilis ? `PB açılışı: ${gun(d.pb_acilis)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <Tooltip title={ipucu}>
      <Tag color={t.renk} style={{ marginInlineEnd: 2 }}>
        {dayjs(d.hedef).format("DD")}
      </Tag>
    </Tooltip>
  );
}

function Lejant() {
  return (
    <Space wrap size={4}>
      {Object.entries(TAKVIM_DURUMLARI)
        .filter(([k]) => k !== "TASLAK_PLAN")
        .map(([k, v]) => (
          <Tag key={k} color={v.renk}>
            {v.ad}
          </Tag>
        ))}
    </Space>
  );
}

// =============================================================================
// Yıllık takvim
// =============================================================================

export function BakimTakvimiSekmesi() {
  const [yil, setYil] = useState(dayjs().year());
  const [birim, setBirim] = useState<string | undefined>();
  const veri = useQuery({
    queryKey: ["bakim", "takvim", yil, birim],
    queryFn: () => bakimApi.takvim(yil, birim),
  });
  type Satir = YillikTakvim["satirlar"][number];
  const aylar = veri.data?.aylar ?? [];

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          value={yil}
          onChange={setYil}
          style={{ width: 110 }}
          options={[-1, 0, 1, 2].map((f) => ({ value: dayjs().year() + f, label: dayjs().year() + f }))}
        />
        <Select
          allowClear
          placeholder="Birim"
          style={{ width: 160 }}
          value={birim}
          onChange={setBirim}
          options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
        />
        <Lejant />
      </Space>
      {veri.data && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          Bakım işleri her dönemin hedef tarihinden {veri.data.on_acilis_gun} gün önce cihaz başına
          bir PB olarak otomatik açılır; Servis Planlama ekranında aynı lokasyondakiler birlikte
          planlanır.
        </Typography.Paragraph>
      )}
      <Table<Satir>
        rowKey="sozlesme_id"
        size="small"
        loading={veri.isLoading}
        dataSource={veri.data?.satirlar}
        pagination={false}
        scroll={{ x: 1300 }}
        locale={{ emptyText: "Bu yıl için aktif sözleşme dönemi yok" }}
        columns={[
          {
            title: "Müşteri / tesis",
            fixed: "left",
            width: 240,
            render: (_, r) => (
              <>
                {r.musteri ?? "—"}
                <br />
                <Typography.Text type="secondary">
                  {[r.tesis, r.il].filter(Boolean).join(" · ")} · {r.contract_no}
                </Typography.Text>
              </>
            ),
          },
          {
            title: "Cihaz",
            width: 70,
            render: (_, r) =>
              r.eslesen_cihaz === r.cihaz_sayisi ? (
                r.cihaz_sayisi
              ) : (
                <Tooltip title="Eşleşmeyen kaleme PB açılmaz">
                  <Tag color="orange">
                    {r.eslesen_cihaz}/{r.cihaz_sayisi}
                  </Tag>
                </Tooltip>
              ),
          },
          {
            title: "Karar / adet",
            width: 110,
            render: (_, r) => (
              <>
                {gun(r.karar_tarihi)}
                <br />
                <Typography.Text type="secondary">yılda {r.annual_frequency ?? "—"}</Typography.Text>
              </>
            ),
          },
          ...ayAdlari().map((ad, i) => ({
            title: (
              <Tooltip title={aylar[i] ? `${aylar[i].donem} dönem · ${aylar[i].cihaz} cihaz` : undefined}>
                {ad}
                {aylar[i]?.cihaz ? (
                  <Typography.Text type="secondary" style={{ display: "block", fontSize: 11 }}>
                    {aylar[i].cihaz} cihaz
                  </Typography.Text>
                ) : null}
              </Tooltip>
            ),
            key: `ay${i + 1}`,
            width: 72,
            render: (_: unknown, r: Satir) =>
              (r.aylar[String(i + 1)] ?? []).map((d) => <DonemRozeti key={d.donem_id ?? d.hedef} d={d} />),
          })),
        ]}
      />
    </>
  );
}

// =============================================================================
// Toplu karar tarihi
// =============================================================================

interface Giris {
  karar?: Dayjs | null;
  adet?: number | null;
  sure?: number | null;
  yapilan?: number | null;
}

export function KararTarihleriPenceresi({ acik, onKapat }: { acik: boolean; onKapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [yalnizEksik, setYalnizEksik] = useState(true);
  const [girisler, setGirisler] = useState<Record<number, Giris>>({});
  const [onizleme, setOnizleme] = useState<TopluKararYaniti | null>(null);

  const liste = useQuery({
    queryKey: ["bakim", "sozlesmeler", "karar-penceresi"],
    queryFn: () => bakimApi.sozlesmeler({ limit: 200, offset: 0 }),
    enabled: acik,
  });
  const satirlar = useMemo(
    () =>
      (liste.data?.kayitlar ?? []).filter(
        (s) => s.status !== "PASIF" && (!yalnizEksik || !s.karar_tarihi || girisler[s.id]),
      ),
    [liste.data, yalnizEksik, girisler],
  );

  const degistir = (id: number, alan: keyof Giris, deger: unknown) => {
    setGirisler((g) => ({ ...g, [id]: { ...g[id], [alan]: deger } }));
    setOnizleme(null);
  };

  const govde = () =>
    Object.entries(girisler)
      .filter(([, g]) => g.karar)
      .map(([id, g]) => ({
        sozlesme_id: Number(id),
        karar_tarihi: g.karar!.format("YYYY-MM-DD"),
        sure_ay: g.sure ?? null,
        yillik_adet: g.adet ?? null,
        yapilan_adet: g.yapilan ?? null,
      }));

  const gonder = useMutation({
    mutationFn: (onizle: boolean) => bakimApi.topluKarar(govde(), onizle),
    onSuccess: (y) => {
      if (y.onizleme) {
        setOnizleme(y);
        return;
      }
      message.success(`${y.ozet.tamam} sözleşmeye karar tarihi işlendi, ${y.ozet.donem} bakım dönemi hesaplandı`);
      if (y.ozet.hata) message.warning(`${y.ozet.hata} satır hatalı; önizlemede gösterilen nedenleri düzeltin`);
      qc.invalidateQueries({ queryKey: ["bakim"] });
      setGirisler({});
      setOnizleme(null);
      onKapat();
    },
    onError: (e) => message.error(hataMetni(e)),
  });
  const girisSayisi = govde().length;

  return (
    <Modal
      open={acik}
      onCancel={onKapat}
      width={1100}
      title="Sözleşme karar tarihleri"
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onKapat}>Kapat</Button>
          <Button disabled={!girisSayisi} loading={gonder.isPending} onClick={() => gonder.mutate(true)}>
            Önizle ({girisSayisi})
          </Button>
          <Button
            type="primary"
            disabled={!onizleme || !onizleme.ozet.tamam}
            loading={gonder.isPending}
            onClick={() => gonder.mutate(false)}
          >
            Uygula
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="Karar tarihi sözleşmenin başlangıcıdır; bakım ayları yıllık adede göre eşit aralıkla hesaplanır."
        description="Süre boş bırakılırsa 12 ay. Karar tarihi geçmişteyse önceki dönemler sistem öncesi sayılır; bu dönemde yapılmış bakım varsa 'Yapılan' sütununa yazın, yoksa kalan geçmiş dönemler gecikmiş olarak açılır. Taslak sözleşme aktifleştirilir."
      />
      <Space style={{ marginBottom: 8 }}>
        <Switch checked={yalnizEksik} onChange={setYalnizEksik} />
        <Typography.Text>Yalnız karar tarihi girilmemiş sözleşmeler</Typography.Text>
      </Space>
      <Table<Sozlesme>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={satirlar}
        pagination={{ pageSize: 10, size: "small" }}
        scroll={{ x: 900 }}
        columns={[
          { title: "No", dataIndex: "contract_no", className: "mono", width: 110 },
          {
            title: "Müşteri / tesis",
            render: (_, r) => (
              <>
                {r.musteri ?? "—"}
                <br />
                <Typography.Text type="secondary">{[r.tesis, r.il].filter(Boolean).join(" · ")}</Typography.Text>
              </>
            ),
          },
          {
            title: "Mevcut",
            width: 120,
            render: (_, r) => (r.karar_tarihi ? `Karar ${gun(r.karar_tarihi)}` : gun(r.baslangic)),
          },
          {
            title: "Karar tarihi",
            width: 150,
            render: (_, r) => (
              <DatePicker
                format="DD.MM.YYYY"
                value={girisler[r.id]?.karar ?? null}
                onChange={(v) => degistir(r.id, "karar", v)}
              />
            ),
          },
          {
            title: "Yılda",
            width: 80,
            render: (_, r) => (
              <InputNumber
                min={1}
                max={12}
                style={{ width: 64 }}
                placeholder={r.annual_frequency ? String(r.annual_frequency) : "?"}
                value={girisler[r.id]?.adet ?? null}
                onChange={(v) => degistir(r.id, "adet", v)}
              />
            ),
          },
          {
            title: "Süre (ay)",
            width: 90,
            render: (_, r) => (
              <InputNumber
                min={1}
                max={120}
                style={{ width: 70 }}
                placeholder="12"
                value={girisler[r.id]?.sure ?? null}
                onChange={(v) => degistir(r.id, "sure", v)}
              />
            ),
          },
          {
            title: "Yapılan",
            width: 80,
            render: (_, r) => (
              <InputNumber
                min={0}
                max={12}
                style={{ width: 64 }}
                value={girisler[r.id]?.yapilan ?? null}
                onChange={(v) => degistir(r.id, "yapilan", v)}
              />
            ),
          },
        ]}
      />
      {onizleme && <OnizlemeTablosu y={onizleme} />}
    </Modal>
  );
}

function OnizlemeTablosu({ y }: { y: TopluKararYaniti }) {
  return (
    <>
      <Alert
        style={{ margin: "12px 0" }}
        type={y.ozet.hata ? "warning" : y.ozet.gecikmis_donem ? "warning" : "success"}
        showIcon
        message={`Önizleme: ${y.ozet.tamam} sözleşme, ${y.ozet.donem} bakım dönemi${
          y.ozet.hata ? `, ${y.ozet.hata} hatalı satır` : ""
        }`}
        description={[
          y.ozet.sistem_oncesi_kapanan ? `${y.ozet.sistem_oncesi_kapanan} geçmiş dönem sistem öncesi kapanacak.` : null,
          y.ozet.gecikmis_donem ? `${y.ozet.gecikmis_donem} geçmiş dönem gecikmiş olarak kalacak.` : null,
          `İlk otomatik üretim turunda ${y.ozet.ilk_turda_pb} PB işi açılacak.`,
        ]
          .filter(Boolean)
          .join(" ")}
      />
      <Table<KararSonucu>
        rowKey="sira"
        size="small"
        pagination={false}
        dataSource={y.satirlar}
        scroll={{ x: 900 }}
        columns={[
          {
            title: "Sözleşme",
            width: 260,
            render: (_, r) =>
              r.sonuc === "HATA" ? (
                <Typography.Text type="danger">{r.contract_no ?? `#${r.sozlesme_id}`}: {r.hata}</Typography.Text>
              ) : (
                <>
                  {r.musteri ?? "—"}
                  <br />
                  <Typography.Text type="secondary">
                    {r.tesis ?? ""} · {gun(r.baslangic)} – {gun(r.bitis)}
                  </Typography.Text>
                </>
              ),
          },
          {
            title: "Bakım ayları",
            render: (_, r) =>
              (r.donemler ?? []).map((d) => (
                <Tooltip key={d.hedef} title={`${gun(d.hedef)} · ${TAKVIM_DURUMLARI[d.durum]?.ad ?? d.durum}`}>
                  <Tag color={TAKVIM_DURUMLARI[d.durum]?.renk}>{dayjs(d.hedef).format("MMM YYYY")}</Tag>
                </Tooltip>
              )),
          },
          {
            title: "Cihaz",
            width: 70,
            render: (_, r) => (r.sonuc === "TAMAM" ? `${r.eslesen_cihaz}/${r.cihaz_sayisi}` : null),
          },
          {
            title: "İlk tur PB",
            width: 90,
            render: (_, r) => (r.sonuc === "TAMAM" ? r.ilk_turda_pb : null),
          },
        ]}
      />
    </>
  );
}
