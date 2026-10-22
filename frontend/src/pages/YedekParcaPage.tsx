/**
 * Yedek Parça — servis stoğu, hareket geçmişi, parça talepleri, sayım, iş
 * emri parçaları ve servis depoları (TS-130…138).
 *
 * - Üstte tıklanabilir KPI kutuları (`KpiKutusu`): sayı sunucudan
 *   (`/stok/ozet`), tıklama aynı süzgeçle sekmeyi açar ("sayı = liste").
 * - Stok: parça başına toplam (yalnız erişilebilir servis depoları) + depo
 *   kırılımı; durum (Stok yok / Az stok / Yeterli) sunucunun TEK kuralından.
 * - Hareketler: tür, depo, parça, iş no, belge no (ILIKE), tarih süzgeci;
 *   sunucu sayfalaması; Excel `parca.gor + servis_rapor.disaaktar`.
 *   Maliyet sütunu yalnız sunucu `unit_cost` anahtarını gönderdiyse.
 * - Giriş (belge no), zayi, transfer `parca.yonet`; işe çıkış/iade/talep
 *   `parca.kullan` — "İş emri parçaları" sekmesinde `ServisParcalari`.
 * - Sayım: açılış anı görüntüsü, sayılan adet girişi, gerekçeli onay; sayım
 *   açıkken stok değiştiyse sunucu sapmaları döndürür, kullanıcı değişimi
 *   kabul ederek yeniden onaylar. Onaysız sayım hiçbir bakiyeyi değiştirmez.
 * - Depolar: servis deposu ve teknisyen araç deposu tanımı `sistem.ayar`.
 * - 375 px'te tablolar yatay kaydırılır, sayfa kaymaz.
 */
import { DownloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { BIRIM_ETIKETLERI, BIRIM_KODLARI, personelApi } from "../api/personel";
import { teknikServisApi } from "../api/teknikServis";
import {
  type Depo,
  HAREKET_TURU_ADLARI,
  type Hareket,
  type HareketSuzgeci,
  OLCU_BIRIMLERI,
  parcaApi,
  parcaHatasi,
  SAYIM_DURUM_ADLARI,
  type Sayim,
  type SayimSatiri,
  STOK_DURUM_ADLARI,
  STOK_DURUM_RENKLERI,
  type StokSatiri,
  type StokSuzgeci,
  TALEP_DURUM_ADLARI,
  type Talep,
} from "../api/yedekParca";
import { useAuth } from "../auth/AuthContext";
import KpiKutusu from "../components/KpiKutusu";
import ParcaHareketPenceresi, { type ParcaHareketTuru } from "../components/ParcaHareketPenceresi";
import ParcaTuketimRaporu from "../components/ParcaTuketimRaporu";
import ServisParcalari from "../components/ServisParcalari";

const SAYFA = 25;
const zaman = (v: string | null | undefined) => (v ? dayjs(v).format("DD.MM.YYYY HH:mm") : "—");
const para = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
const indir = (yol: string) => window.open(yol, "_blank");

export default function YedekParcaPage() {
  const { yetkili } = useAuth();
  const [params, setParams] = useSearchParams();
  const sekme = params.get("sekme") ?? "stok";
  const [pencere, setPencere] = useState<ParcaHareketTuru | null>(null);
  const [kartAcik, setKartAcik] = useState(false);

  const ozet = useQuery({ queryKey: ["parca", "ozet"], queryFn: parcaApi.ozet });
  const bugun = dayjs().format("YYYY-MM-DD");
  const kutular = [
    { kod: "az_stok", baslik: "Az stok", deger: ozet.data?.az_stok, yol: "/yedek-parca?sekme=stok&durum=AZ", vurgu: "uyari" as const, tanim: "Asgari stoku tanımlı ve toplamı asgarinin altında olan parçalar" },
    { kod: "stok_yok", baslik: "Stok yok", deger: ozet.data?.stok_yok, yol: "/yedek-parca?sekme=stok&durum=YOK", vurgu: "kritik" as const, tanim: "Erişebildiğiniz servis depolarında toplamı 0 olan aktif parçalar" },
    { kod: "acik_talep", baslik: "Açık talep", deger: ozet.data?.acik_talep, yol: "/yedek-parca?sekme=talepler&durum=ACIK", vurgu: "normal" as const, tanim: "Karşılanmamış parça talepleri" },
    { kod: "acik_sayim", baslik: "Açık sayım", deger: ozet.data?.acik_sayim, yol: "/yedek-parca?sekme=sayimlar&durum=ACIK", vurgu: "normal" as const, tanim: "Onay bekleyen stok sayımları" },
    { kod: "bugun_cikis", baslik: "Bugünkü çıkış", deger: ozet.data?.bugun_cikis, yol: `/yedek-parca?sekme=hareketler&tur=CIKIS_SERVIS&bas=${bugun}&bit=${bugun}`, vurgu: "normal" as const, tanim: "Bugün servis işlerine yapılan parça çıkışı satırları" },
  ];

  const sekmeDegistir = (k: string) => setParams(new URLSearchParams({ sekme: k }));

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Row gutter={[12, 12]}>
        {kutular.map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={4}>
            <KpiKutusu {...k} deger={k.deger ?? 0} yukleniyor={ozet.isLoading} />
          </Col>
        ))}
      </Row>
      <Card
        title="Yedek Parça"
        extra={
          yetkili("parca.yonet") ? (
            <Space wrap>
              <Button type="primary" onClick={() => setPencere("GIRIS")}>
                Giriş
              </Button>
              <Button onClick={() => setPencere("TRANSFER")}>Transfer</Button>
              <Button onClick={() => setPencere("ZAYI")}>Zayi</Button>
              <Button onClick={() => setKartAcik(true)}>Yeni parça kartı</Button>
            </Space>
          ) : null
        }
      >
        <Tabs
          activeKey={sekme}
          onChange={sekmeDegistir}
          items={[
            { key: "stok", label: "Stok", children: <StokSekmesi /> },
            { key: "hareketler", label: "Hareketler", children: <HareketSekmesi /> },
            { key: "talepler", label: "Parça Talepleri", children: <TalepSekmesi /> },
            { key: "sayimlar", label: "Sayım", children: <SayimSekmesi /> },
            ...(yetkili("servis.gor")
              ? [{ key: "isler", label: "İş Emri Parçaları", children: <IsSekmesi /> }]
              : []),
            { key: "depolar", label: "Depolar", children: <DepoSekmesi /> },
            ...(yetkili("servis_rapor.gor")
              ? [{ key: "tuketim", label: "Tüketim raporu", children: <ParcaTuketimRaporu /> }]
              : []),
          ]}
        />
      </Card>
      <ParcaHareketPenceresi tur={pencere} onKapat={() => setPencere(null)} />
      <KartPenceresi acik={kartAcik} onKapat={() => setKartAcik(false)} />
    </Space>
  );
}

// --- Stok ---------------------------------------------------------------------

function useDepolar(pasifler = false) {
  return useQuery({ queryKey: ["parca", "depolar", pasifler], queryFn: () => parcaApi.depolar(pasifler) });
}

function StokSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const [duzenle, setDuzenle] = useState<StokSatiri | null>(null);
  const depolar = useDepolar();
  const s: StokSuzgeci = {
    q: params.get("q") ?? undefined,
    depo_id: params.get("depo_id") ? Number(params.get("depo_id")) : undefined,
    durum: params.get("durum") ?? undefined,
    esikli: params.get("esikli") === "1",
    pasifler: params.get("pasifler") === "1",
  };
  const guncelle = (k: string, v: string | undefined) => {
    const yeni = new URLSearchParams(params);
    yeni.set("sekme", "stok");
    if (v) yeni.set(k, v);
    else yeni.delete(k);
    setParams(yeni);
    setSayfa(1);
  };
  const liste = useQuery({
    queryKey: ["parca", "stok", s, sayfa],
    queryFn: () => parcaApi.stok(s, SAYFA, (sayfa - 1) * SAYFA),
  });
  const [form] = Form.useForm<{ min_stok: number | null; birim: string | null }>();
  const kaydet = useMutation({
    mutationFn: (d: { min_stok: number | null; birim: string | null }) =>
      parcaApi.kartGuncelle({ product_id: duzenle!.product_id, version: duzenle!.version, ...d }),
    onSuccess: async () => {
      message.success("Parça kartı güncellendi");
      setDuzenle(null);
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <Input.Search
          allowClear
          placeholder="Kod, ad, marka, model"
          defaultValue={s.q}
          onSearch={(v) => guncelle("q", v.trim() || undefined)}
          style={{ width: 240 }}
        />
        <Select
          allowClear
          placeholder="Depo"
          value={s.depo_id}
          onChange={(v) => guncelle("depo_id", v ? String(v) : undefined)}
          options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
          style={{ width: 200 }}
        />
        <Select
          allowClear
          placeholder="Durum"
          value={s.durum}
          onChange={(v) => guncelle("durum", v)}
          options={Object.entries(STOK_DURUM_ADLARI).map(([value, label]) => ({ value, label }))}
          style={{ width: 140 }}
        />
        <Checkbox checked={s.esikli} onChange={(e) => guncelle("esikli", e.target.checked ? "1" : undefined)}>
          Yalnız asgari stoku tanımlı
        </Checkbox>
        <Checkbox checked={s.pasifler} onChange={(e) => guncelle("pasifler", e.target.checked ? "1" : undefined)}>
          Pasifler dahil
        </Checkbox>
        {yetkili("parca.gor", "servis_rapor.disaaktar") && (
          <Button icon={<DownloadOutlined />} onClick={() => indir(parcaApi.stokExcelYolu(s))}>
            Excel
          </Button>
        )}
      </Space>
      {liste.isError && <Alert type="error" showIcon message={parcaHatasi(liste.error).mesaj} />}
      <Table<StokSatiri>
        size="small"
        rowKey="product_id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: true }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showSizeChanger: false,
          showTotal: (t) => `${t} parça`,
        }}
        expandable={{
          rowExpandable: (r) => r.depolar.length > 0,
          expandedRowRender: (r) => (
            <Space wrap>
              {r.depolar.map((d) => (
                <Tag key={d.depo_id}>
                  {d.depo_adi}: {d.adet} {r.birim}
                </Tag>
              ))}
            </Space>
          ),
        }}
        columns={[
          { title: "Kod", dataIndex: "kod", key: "kod" },
          {
            title: "Parça",
            key: "ad",
            render: (_, r) => (
              <Space size={4}>
                {r.ad}
                {!r.is_active && <Tag>Pasif</Tag>}
              </Space>
            ),
          },
          { title: "Marka / Model", key: "mm", render: (_, r) => [r.marka, r.model].filter(Boolean).join(" ") || "—" },
          { title: "Toplam", key: "t", align: "right", render: (_, r) => `${r.toplam} ${r.birim}` },
          { title: "Asgari", key: "a", align: "right", render: (_, r) => r.min_stok ?? "—" },
          {
            title: "Durum",
            key: "d",
            render: (_, r) => <Tag color={STOK_DURUM_RENKLERI[r.durum]}>{STOK_DURUM_ADLARI[r.durum] ?? r.durum}</Tag>,
          },
          ...(yetkili("parca.yonet")
            ? [
                {
                  title: "",
                  key: "i",
                  render: (_: unknown, r: StokSatiri) => (
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        setDuzenle(r);
                        form.setFieldsValue({ min_stok: r.min_stok, birim: r.birim });
                      }}
                    >
                      Stok alanları
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        open={duzenle !== null}
        title={duzenle ? `${duzenle.kod} — stok alanları` : ""}
        onCancel={() => setDuzenle(null)}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(d) => kaydet.mutate(d)}>
          <Form.Item name="min_stok" label="Asgari stok (az stok uyarısı eşiği)">
            <InputNumber min={0} max={1_000_000} precision={0} />
          </Form.Item>
          <Form.Item name="birim" label="Ölçü birimi">
            <Select allowClear options={OLCU_BIRIMLERI.map((b) => ({ value: b, label: b }))} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}

// --- Hareketler ---------------------------------------------------------------

function HareketSekmesi() {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const depolar = useDepolar(true);
  const s: HareketSuzgeci = {
    tur: params.get("tur") ?? undefined,
    depo_id: params.get("depo_id") ? Number(params.get("depo_id")) : undefined,
    so_no: params.get("so_no") ?? undefined,
    belge: params.get("belge") ?? undefined,
    bas: params.get("bas") ?? undefined,
    bit: params.get("bit") ?? undefined,
  };
  const guncelle = (degisen: Record<string, string | undefined>) => {
    const yeni = new URLSearchParams(params);
    yeni.set("sekme", "hareketler");
    for (const [k, v] of Object.entries(degisen)) {
      if (v) yeni.set(k, v);
      else yeni.delete(k);
    }
    setParams(yeni);
    setSayfa(1);
  };
  const liste = useQuery({
    queryKey: ["parca", "hareketler", s, sayfa],
    queryFn: () => parcaApi.hareketler(s, SAYFA, (sayfa - 1) * SAYFA),
  });
  const tersKayit = useMutation({
    mutationFn: ({ id, gerekce }: { id: number; gerekce: string }) => parcaApi.tersKayit(id, gerekce),
    onSuccess: async () => {
      message.success("Ters kayıt yazıldı");
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });
  const tersSor = (h: Hareket) => {
    let metin = "";
    modal.confirm({
      title: `Ters kayıt: ${h.tur_adi} — ${h.kod} (${h.adet})`,
      content: (
        <Input.TextArea
          rows={2}
          maxLength={300}
          placeholder="Gerekçe (en az 3 karakter)"
          onChange={(e) => {
            metin = e.target.value;
          }}
        />
      ),
      okText: "Ters kaydı yaz",
      cancelText: "Vazgeç",
      onOk: () => {
        if (metin.trim().length < 3) {
          message.error("Gerekçe en az 3 karakter olmalı");
          return Promise.reject(new Error("gerekçe"));
        }
        tersKayit.mutate({ id: h.id, gerekce: metin.trim() });
        return Promise.resolve();
      },
    });
  };
  const maliyetli = (liste.data?.kayitlar ?? []).some((h) => "unit_cost" in h);
  const aralik: [Dayjs | null, Dayjs | null] | null =
    s.bas || s.bit ? [s.bas ? dayjs(s.bas) : null, s.bit ? dayjs(s.bit) : null] : null;

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <Select
          allowClear
          placeholder="Hareket türü"
          value={s.tur}
          onChange={(v) => guncelle({ tur: v })}
          options={Object.entries(HAREKET_TURU_ADLARI).map(([value, label]) => ({ value, label }))}
          style={{ width: 170 }}
        />
        <Select
          allowClear
          placeholder="Depo"
          value={s.depo_id}
          onChange={(v) => guncelle({ depo_id: v ? String(v) : undefined })}
          options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
          style={{ width: 180 }}
        />
        <Input.Search
          allowClear
          placeholder="İş no"
          defaultValue={s.so_no}
          onSearch={(v) => guncelle({ so_no: v.trim() || undefined })}
          style={{ width: 150 }}
        />
        <Input.Search
          allowClear
          placeholder="Belge no"
          defaultValue={s.belge}
          onSearch={(v) => guncelle({ belge: v.trim() || undefined })}
          style={{ width: 150 }}
        />
        <DatePicker.RangePicker
          value={aralik}
          format="DD.MM.YYYY"
          allowEmpty={[true, true]}
          onChange={(v) =>
            guncelle({ bas: v?.[0]?.format("YYYY-MM-DD"), bit: v?.[1]?.format("YYYY-MM-DD") })
          }
        />
        {yetkili("parca.gor", "servis_rapor.disaaktar") && (
          <Button icon={<DownloadOutlined />} onClick={() => indir(parcaApi.hareketExcelYolu(s))}>
            Excel
          </Button>
        )}
      </Space>
      {liste.isError && <Alert type="error" showIcon message={parcaHatasi(liste.error).mesaj} />}
      <Table<Hareket>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: true }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showSizeChanger: false,
          showTotal: (t) => `${t} hareket`,
        }}
        columns={[
          { title: "Tarih", key: "t", render: (_, h) => zaman(h.created_at) },
          {
            title: "Tür",
            key: "tur",
            render: (_, h) => (
              <Space size={4}>
                {h.tur_adi}
                {h.ters_kaydi_var && <Tag>Ters kaydı var</Tag>}
              </Space>
            ),
          },
          { title: "Parça", key: "p", render: (_, h) => `${h.kod} — ${h.ad}` },
          { title: "Depo", dataIndex: "depo_adi", key: "d" },
          { title: "Adet", key: "a", align: "right", render: (_, h) => `${h.adet > 0 ? "+" : ""}${h.adet} ${h.birim}` },
          { title: "İş no", key: "so", render: (_, h) => h.so_no ?? "—" },
          { title: "Belge no", key: "b", render: (_, h) => h.document_no ?? "—" },
          { title: "Not", key: "n", render: (_, h) => h.notes ?? "", ellipsis: true },
          { title: "Kullanıcı", key: "k", render: (_, h) => h.kullanici ?? "—" },
          ...(maliyetli
            ? [
                { title: "Birim maliyet", key: "m", align: "right" as const, render: (_: unknown, h: Hareket) => para(h.unit_cost) },
                { title: "Tutar", key: "tt", align: "right" as const, render: (_: unknown, h: Hareket) => para(h.tutar) },
              ]
            : []),
          ...(yetkili("parca.yonet")
            ? [
                {
                  title: "",
                  key: "i",
                  render: (_: unknown, h: Hareket) =>
                    h.tur !== "TERS_KAYIT" &&
                    h.tur !== "SAYIM_FAZLASI" &&
                    h.tur !== "SAYIM_EKSIGI" &&
                    !h.ters_kaydi_var ? (
                      <Button size="small" type="link" onClick={() => tersSor(h)}>
                        Ters kayıt
                      </Button>
                    ) : null,
                },
              ]
            : []),
        ]}
      />
    </Space>
  );
}

// --- Talepler -----------------------------------------------------------------

function TalepSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const durum = params.get("durum") ?? undefined;
  const benim = params.get("benim") === "1";
  const guncelle = (k: string, v: string | undefined) => {
    const yeni = new URLSearchParams(params);
    yeni.set("sekme", "talepler");
    if (v) yeni.set(k, v);
    else yeni.delete(k);
    setParams(yeni);
    setSayfa(1);
  };
  const liste = useQuery({
    queryKey: ["parca", "talepler", durum, benim, sayfa],
    queryFn: () => parcaApi.talepler({ durum, benim }, SAYFA, (sayfa - 1) * SAYFA),
  });
  const iptal = useMutation({
    mutationFn: (id: number) => parcaApi.talepIptal(id, "Kullanıcı iptal etti"),
    onSuccess: async () => {
      message.success("Talep iptal edildi");
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <Select
          allowClear
          placeholder="Durum"
          value={durum}
          onChange={(v) => guncelle("durum", v)}
          options={Object.entries(TALEP_DURUM_ADLARI).map(([value, label]) => ({ value, label }))}
          style={{ width: 160 }}
        />
        <Checkbox checked={benim} onChange={(e) => guncelle("benim", e.target.checked ? "1" : undefined)}>
          Yalnız benim taleplerim
        </Checkbox>
      </Space>
      <Typography.Text type="secondary">
        Talep, aynı işe aynı parçadan talep adedi kadar çıkış yapılınca kendiliğinden karşılanır; iş
        kapanınca açık talepler iptal olur.
      </Typography.Text>
      <Table<Talep>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: true }}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showSizeChanger: false,
          showTotal: (t) => `${t} talep`,
        }}
        columns={[
          { title: "Tarih", key: "t", render: (_, t) => zaman(t.created_at) },
          {
            title: "İş no",
            key: "so",
            render: (_, t) => (
              <Link to={`/yedek-parca?sekme=isler&so=${t.service_order_id}`}>{t.so_no}</Link>
            ),
          },
          { title: "Parça", key: "p", render: (_, t) => `${t.kod} — ${t.ad}` },
          { title: "Adet", dataIndex: "adet", key: "a", align: "right" },
          {
            title: "Durum",
            key: "d",
            render: (_, t) => (
              <Space size={4}>
                <Tag color={t.durum === "ACIK" ? "gold" : t.durum === "KARSILANDI" ? "green" : "default"}>
                  {TALEP_DURUM_ADLARI[t.durum] ?? t.durum}
                </Tag>
                {t.beklemeye_bagli && t.durum === "ACIK" && <Tag color="blue">İş bekliyor</Tag>}
              </Space>
            ),
          },
          { title: "Karşılanma", key: "k", render: (_, t) => zaman(t.karsilanma_at) },
          { title: "Not / iptal nedeni", key: "n", render: (_, t) => t.iptal_nedeni ?? t.notes ?? "" },
          ...(yetkili("parca.kullan")
            ? [
                {
                  title: "",
                  key: "i",
                  render: (_: unknown, t: Talep) =>
                    t.durum === "ACIK" ? (
                      <Button size="small" type="link" danger onClick={() => iptal.mutate(t.id)}>
                        İptal
                      </Button>
                    ) : null,
                },
              ]
            : []),
        ]}
      />
    </Space>
  );
}

// --- Sayım --------------------------------------------------------------------

function SayimSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const durum = params.get("durum") ?? undefined;
  const depolar = useDepolar();
  const liste = useQuery({
    queryKey: ["parca", "sayimlar", durum, sayfa],
    queryFn: () => parcaApi.sayimlar(durum, SAYFA, (sayfa - 1) * SAYFA),
  });
  const [form] = Form.useForm<{ depo_id: number; notes?: string }>();
  const ac = useMutation({
    mutationFn: (d: { depo_id: number; notes?: string }) => parcaApi.sayimAc(d.depo_id, d.notes?.trim() || null),
    onSuccess: async (s) => {
      message.success(`${s.count_no} açıldı`);
      setYeniAcik(false);
      form.resetFields();
      await qc.invalidateQueries({ queryKey: ["parca"] });
      setSecili(s.id);
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <Select
          allowClear
          placeholder="Durum"
          value={durum}
          onChange={(v) => {
            const yeni = new URLSearchParams({ sekme: "sayimlar" });
            if (v) yeni.set("durum", v);
            setParams(yeni);
            setSayfa(1);
          }}
          options={Object.entries(SAYIM_DURUM_ADLARI).map(([value, label]) => ({ value, label }))}
          style={{ width: 160 }}
        />
        {yetkili("parca.yonet") && (
          <Button type="primary" onClick={() => setYeniAcik(true)}>
            Yeni sayım
          </Button>
        )}
      </Space>
      <Table<Sayim>
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: true }}
        onRow={(r) => ({ onClick: () => setSecili(r.id), style: { cursor: "pointer" } })}
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showSizeChanger: false,
        }}
        columns={[
          { title: "Sayım no", dataIndex: "count_no", key: "no" },
          { title: "Depo", dataIndex: "depo_adi", key: "d" },
          {
            title: "Durum",
            key: "s",
            render: (_, r) => (
              <Tag color={r.durum === "ACIK" ? "gold" : r.durum === "ONAYLANDI" ? "green" : "default"}>
                {SAYIM_DURUM_ADLARI[r.durum] ?? r.durum}
              </Tag>
            ),
          },
          { title: "Başlangıç", key: "b", render: (_, r) => zaman(r.baslangic_at) },
          { title: "Onay", key: "o", render: (_, r) => zaman(r.onay_at) },
        ]}
      />
      <Modal
        open={yeniAcik}
        title="Yeni stok sayımı"
        onCancel={() => setYeniAcik(false)}
        onOk={() => form.submit()}
        okText="Sayımı aç"
        cancelText="Vazgeç"
        confirmLoading={ac.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          Sayım açıldığı andaki sistem adetleri görüntü olarak saklanır. Onaya kadar hiçbir bakiye
          değişmez; onayda fark güncel bakiyeye göre yazılır.
        </Typography.Paragraph>
        <Form form={form} layout="vertical" onFinish={(d) => ac.mutate(d)}>
          <Form.Item name="depo_id" label="Depo" rules={[{ required: true, message: "Depo seçin" }]}>
            <Select options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))} />
          </Form.Item>
          <Form.Item name="notes" label="Not">
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>
      <SayimCekmecesi sayimId={secili} onKapat={() => setSecili(null)} />
    </Space>
  );
}

function SayimCekmecesi({ sayimId, onKapat }: { sayimId: number | null; onKapat: () => void }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [sayilan, setSayilan] = useState<Record<number, number | null>>({});
  const [gerekce, setGerekce] = useState("");
  const [sapma, setSapma] = useState<string | null>(null);
  const sorgu = useQuery({
    queryKey: ["parca", "sayim", sayimId],
    queryFn: () => parcaApi.sayim(sayimId!),
    enabled: sayimId !== null,
  });
  const sayim = sorgu.data;
  const acik = sayim?.durum === "ACIK" && yetkili("parca.yonet");
  const tazele = () => qc.invalidateQueries({ queryKey: ["parca"] });
  const kaydet = useMutation({
    mutationFn: () =>
      parcaApi.sayimSatirlari(
        sayimId!,
        Object.entries(sayilan).map(([pid, adet]) => ({ product_id: Number(pid), sayilan_adet: adet })),
      ),
    onSuccess: async () => {
      message.success("Sayılan adetler kaydedildi");
      setSayilan({});
      await tazele();
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });
  const onayla = useMutation({
    mutationFn: (kabul: boolean) => parcaApi.sayimOnayla(sayimId!, gerekce.trim(), kabul),
    onSuccess: async () => {
      message.success("Sayım onaylandı; farklar stoğa yazıldı");
      setSapma(null);
      await tazele();
    },
    onError: (e) => {
      const h = parcaHatasi(e);
      if (h.sapmalar) setSapma(h.mesaj);
      else message.error(h.mesaj);
    },
  });
  const iptal = useMutation({
    mutationFn: () => parcaApi.sayimIptal(sayimId!, gerekce.trim()),
    onSuccess: async () => {
      message.success("Sayım iptal edildi");
      await tazele();
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });
  return (
    <Drawer
      open={sayimId !== null}
      onClose={() => {
        setSayilan({});
        setSapma(null);
        setGerekce("");
        onKapat();
      }}
      title={sayim ? `${sayim.count_no} — ${sayim.depo_adi ?? ""}` : "Sayım"}
      size="large"
    >
      {sayim && (
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            <Tag>{SAYIM_DURUM_ADLARI[sayim.durum] ?? sayim.durum}</Tag>
            <Typography.Text type="secondary">Başlangıç: {zaman(sayim.baslangic_at)}</Typography.Text>
            {sayim.gerekce && <Typography.Text type="secondary">Gerekçe: {sayim.gerekce}</Typography.Text>}
          </Space>
          <Table<SayimSatiri>
            size="small"
            rowKey="product_id"
            pagination={false}
            dataSource={sayim.satirlar}
            scroll={{ x: true }}
            columns={[
              { title: "Parça", key: "p", render: (_, r) => `${r.kod} — ${r.ad}` },
              { title: "Sistem (açılış)", dataIndex: "sistem_adet", key: "s", align: "right" },
              {
                title: "Sayılan",
                key: "c",
                render: (_, r) =>
                  acik ? (
                    <InputNumber
                      min={0}
                      max={1_000_000}
                      precision={0}
                      value={r.product_id in sayilan ? sayilan[r.product_id] : r.sayilan_adet}
                      onChange={(v) => setSayilan((o) => ({ ...o, [r.product_id]: v ?? null }))}
                    />
                  ) : (
                    (r.sayilan_adet ?? "—")
                  ),
              },
              { title: "Fark", key: "f", align: "right", render: (_, r) => (r.fark == null ? "—" : r.fark) },
              {
                title: "Onay anında",
                key: "o",
                align: "right",
                render: (_, r) => r.onay_anindaki_adet ?? "—",
              },
            ]}
          />
          {acik && (
            <>
              <Button disabled={Object.keys(sayilan).length === 0} loading={kaydet.isPending} onClick={() => kaydet.mutate()}>
                Sayılan adetleri kaydet
              </Button>
              {sapma && (
                <Alert
                  type="warning"
                  showIcon
                  message={sapma}
                  action={
                    <Button size="small" onClick={() => onayla.mutate(true)} loading={onayla.isPending}>
                      Değişimi kabul et ve onayla
                    </Button>
                  }
                />
              )}
              <Input.TextArea
                rows={2}
                maxLength={500}
                placeholder="Onay / iptal gerekçesi (zorunlu)"
                value={gerekce}
                onChange={(e) => setGerekce(e.target.value)}
              />
              <Space wrap>
                <Button
                  type="primary"
                  disabled={gerekce.trim().length < 3 || Object.keys(sayilan).length > 0}
                  loading={onayla.isPending}
                  onClick={() => onayla.mutate(false)}
                >
                  Sayımı onayla
                </Button>
                <Button danger disabled={gerekce.trim().length < 3} loading={iptal.isPending} onClick={() => iptal.mutate()}>
                  Sayımı iptal et
                </Button>
              </Space>
              {Object.keys(sayilan).length > 0 && (
                <Typography.Text type="secondary">Onaydan önce sayılan adetleri kaydedin.</Typography.Text>
              )}
            </>
          )}
        </Space>
      )}
    </Drawer>
  );
}

// --- İş emri parçaları ----------------------------------------------------------

function IsSekmesi() {
  const [params, setParams] = useSearchParams();
  const soId = params.get("so") ? Number(params.get("so")) : null;
  const [q, setQ] = useState("");
  const isler = useQuery({
    queryKey: ["parca", "is-arama", q],
    queryFn: () => teknikServisApi.liste({ q, kapali_dahil: true }, 10, 0),
    enabled: q.length >= 2,
  });
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Select
        showSearch
        filterOption={false}
        placeholder="İş no, müşteri veya konu ile servis işi arayın"
        onSearch={(v) => setQ(v.trim())}
        value={soId ?? undefined}
        onChange={(v) => setParams(new URLSearchParams({ sekme: "isler", so: String(v) }))}
        loading={isler.isFetching}
        options={(isler.data?.kayitlar ?? []).map((i) => ({
          value: i.id,
          label: `${i.so_no} — ${i.musteri?.title ?? i.customer_name_raw ?? ""} — ${i.konu}`,
        }))}
        notFoundContent={q.length < 2 ? "En az 2 karakter yazın" : "İş bulunamadı"}
        style={{ width: "100%", maxWidth: 560 }}
      />
      {soId !== null ? (
        <ServisParcalari soId={soId} />
      ) : (
        <Typography.Text type="secondary">
          Servis işine parça çıkışı, iade ve parça talebi için işi seçin. Aynı bölüm servis işi, planlı
          bakım formu ve atölye kaydında da görünür.
        </Typography.Text>
      )}
    </Space>
  );
}

// --- Depolar ------------------------------------------------------------------

function DepoSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const depolar = useDepolar(true);
  const [duzenle, setDuzenle] = useState<Depo | "yeni" | null>(null);
  const [form] = Form.useForm<{
    code?: string;
    name: string;
    birim?: string | null;
    arac: boolean;
    user_id?: number | null;
    is_active?: boolean;
  }>();
  const tanimci = yetkili("sistem.ayar");
  const personel = useQuery({
    queryKey: ["parca", "personel"],
    queryFn: () => personelApi.liste({ durum: "CALISIYOR" }, 200, 0),
    enabled: tanimci && yetkili("personel.gor") && duzenle !== null,
  });
  const kaydet = useMutation({
    mutationFn: async (d: {
      code?: string;
      name: string;
      birim?: string | null;
      arac: boolean;
      user_id?: number | null;
      is_active?: boolean;
    }) => {
      if (duzenle === "yeni") {
        return parcaApi.depoOlustur({
          code: d.code!.trim(),
          name: d.name.trim(),
          birim: d.birim ?? null,
          location_type: d.arac ? "TEKNISYEN" : "BOLGE_DEPO",
          user_id: d.arac ? (d.user_id ?? null) : null,
        });
      }
      const depo = duzenle as Depo;
      return parcaApi.depoGuncelle(depo.id, {
        name: d.name.trim(),
        birim: d.birim ?? null,
        is_active: d.is_active,
        ...(depo.location_type === "TEKNISYEN" ? { user_id: d.user_id ?? null } : {}),
      });
    },
    onSuccess: async () => {
      message.success("Depo kaydedildi");
      setDuzenle(null);
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });
  const arac = Form.useWatch("arac", form);
  const aracDeposu = duzenle === "yeni" ? arac : duzenle?.location_type === "TEKNISYEN";

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        Servis depoları mobilite depolarından ayrıdır: mobilite stok ekranları bu depoları göstermez.
        Teknisyen yalnız birim depolarını ve kendi araç deposunu görür.
      </Typography.Text>
      {tanimci && (
        <Button
          onClick={() => {
            setDuzenle("yeni");
            form.resetFields();
            form.setFieldsValue({ arac: false });
          }}
        >
          Yeni servis deposu
        </Button>
      )}
      <Table<Depo>
        size="small"
        rowKey="id"
        loading={depolar.isLoading}
        dataSource={depolar.data}
        pagination={false}
        scroll={{ x: true }}
        columns={[
          { title: "Kod", dataIndex: "code", key: "c" },
          { title: "Ad", dataIndex: "name", key: "n" },
          { title: "Birim", key: "b", render: (_, d) => (d.birim ? (BIRIM_ETIKETLERI[d.birim] ?? d.birim) : "Ortak") },
          {
            title: "Tür",
            key: "t",
            render: (_, d) =>
              d.location_type === "TEKNISYEN" ? <Tag color="blue">{d.kendi_araci ? "Araç deposu (benim)" : "Araç deposu"}</Tag> : "Depo",
          },
          { title: "Durum", key: "a", render: (_, d) => (d.is_active ? <Tag color="green">Aktif</Tag> : <Tag>Pasif</Tag>) },
          ...(tanimci
            ? [
                {
                  title: "",
                  key: "i",
                  render: (_: unknown, d: Depo) => (
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        setDuzenle(d);
                        form.setFieldsValue({
                          name: d.name,
                          birim: d.birim,
                          user_id: d.user_id,
                          is_active: d.is_active,
                          arac: d.location_type === "TEKNISYEN",
                        });
                      }}
                    >
                      Düzenle
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        open={duzenle !== null}
        title={duzenle === "yeni" ? "Yeni servis deposu" : "Depoyu düzenle"}
        onCancel={() => setDuzenle(null)}
        onOk={() => form.submit()}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(d) => kaydet.mutate(d)}>
          {duzenle === "yeni" && (
            <Form.Item name="code" label="Kod" rules={[{ required: true }, { max: 20 }]}>
              <Input maxLength={20} />
            </Form.Item>
          )}
          <Form.Item name="name" label="Ad" rules={[{ required: true }, { min: 2 }, { max: 100 }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="birim" label="Birim (boş = ortak depo)">
            <Select allowClear options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))} />
          </Form.Item>
          {duzenle === "yeni" && (
            <Form.Item name="arac" label="Teknisyen araç deposu" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
          {aracDeposu && (
            <Form.Item name="user_id" label="Teknisyen" rules={[{ required: true, message: "Teknisyen seçin" }]}>
              <Select
                showSearch
                optionFilterProp="label"
                loading={personel.isLoading}
                options={(personel.data?.kayitlar ?? []).map((p) => ({ value: p.id, label: p.full_name }))}
                notFoundContent={yetkili("personel.gor") ? "Personel bulunamadı" : "Personel listesi için yetkiniz yok"}
              />
            </Form.Item>
          )}
          {duzenle !== "yeni" && (
            <Form.Item name="is_active" label="Aktif" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Space>
  );
}

// --- Parça kartı ----------------------------------------------------------------

function KartPenceresi({ acik, onKapat }: { acik: boolean; onKapat: () => void }) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{
    code: string;
    name: string;
    brand?: string;
    model?: string;
    supplier_code?: string;
    birim?: string;
    min_stok?: number;
  }>();
  const kaydet = useMutation({
    mutationFn: (d: {
      code: string;
      name: string;
      brand?: string;
      model?: string;
      supplier_code?: string;
      birim?: string;
      min_stok?: number;
    }) =>
      parcaApi.kartOlustur({
        ...d,
        code: d.code.trim(),
        name: d.name.trim(),
        brand: d.brand?.trim() || null,
        model: d.model?.trim() || null,
        supplier_code: d.supplier_code?.trim() || null,
        birim: d.birim ?? null,
        min_stok: d.min_stok ?? null,
      }),
    onSuccess: async (k) => {
      message.success(`${k.code} parça kartı açıldı`);
      form.resetFields();
      onKapat();
      await qc.invalidateQueries({ queryKey: ["parca"] });
    },
    onError: (e) => message.error(parcaHatasi(e).mesaj),
  });
  return (
    <Modal
      open={acik}
      title="Yeni yedek parça kartı"
      onCancel={onKapat}
      onOk={() => form.submit()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        Yedek parça adetle (seri numarasız) izlenir; fiyat bilgisi katalogdan yönetilir.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" initialValues={{ birim: "ADET" }} onFinish={(d) => kaydet.mutate(d)}>
        <Form.Item name="code" label="Kod" rules={[{ required: true }, { max: 40 }]}>
          <Input maxLength={40} />
        </Form.Item>
        <Form.Item name="name" label="Ad" rules={[{ required: true }, { min: 2 }, { max: 160 }]}>
          <Input maxLength={160} />
        </Form.Item>
        <Row gutter={12}>
          <Col xs={24} sm={12}>
            <Form.Item name="brand" label="Marka" rules={[{ max: 60 }]}>
              <Input maxLength={60} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="model" label="Model" rules={[{ max: 80 }]}>
              <Input maxLength={80} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="supplier_code" label="Tedarikçi kodu" rules={[{ max: 60 }]}>
              <Input maxLength={60} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="birim" label="Birim">
              <Select options={OLCU_BIRIMLERI.map((b) => ({ value: b, label: b }))} />
            </Form.Item>
          </Col>
          <Col xs={12} sm={6}>
            <Form.Item name="min_stok" label="Asgari stok">
              <InputNumber min={0} max={1_000_000} precision={0} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
}
