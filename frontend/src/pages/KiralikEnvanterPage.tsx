/**
 * Kiralık Envanter — cihazlar, depo bakiyeleri, toplu hareketler, katalog
 * (TS-111, TS-115, TS-118, TS-121, TS-122; TS-102 kiralama tarafı).
 *
 * - Envanter yalnız `hareket_yaz()` üzerinden değişir: giriş, transfer, kontrol,
 *   bulundu, hurda uçları hareket yazar; düzenleme formu durum/depo/ürün/birim
 *   göndermez (sunucu 400). Hareket defteri ekleme-yalnızdır.
 * - Depo seçicileri yalnız `kiralama_deposu=true` depoları listeler.
 * - Dönüş kontrolünde UYGUN dışındaki sonuçta açıklama zorunludur; arızalı seri
 *   cihaz için atölye kaydı açılabilir (atölye kabulü D2-B'ye bağlıdır).
 * - Toplu giriş: önizleme hiçbir şey yazmaz; onay aynı dosyanın sha256'sıyla
 *   gönderilir, dosya değiştiyse sunucu 409 döner.
 * - `?uzun=1` uzun süredir kontrolde bekleyenleri açar (uyarı bağlantısı).
 * - TS-195: "Depo sayımı" (onaysız fark hiçbir şeyi değiştirmez) ve
 *   "Raporlar" (`servis_rapor.gor`) sekmeleri.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
} from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import {
  type CihazSatiri,
  type EnvanterSuzgeci,
  GIRIS_DURUMLARI,
  HAREKET_ADLARI,
  type HareketOut,
  HURDA_KAYNAK_DURUMLARI,
  type KatalogOut,
  KIRALAMA_DISI_BIRIMLER,
  KIRALIK_DURUM_ADLARI,
  KIRALIK_DURUM_RENKLERI,
  kiralamaApi,
  KONTROL_KAYNAK_DURUMLARI,
  KONTROL_SONUC_ADLARI,
  type TopluOnizleme,
} from "../api/kiralama";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { useAuth } from "../auth/AuthContext";
import KiralamaRaporlari from "../components/KiralamaRaporlari";
import KiralikSayim from "../components/KiralikSayim";
import Statistic from "../components/Statistic";

const SAYFA_BOYU = 50;
const KIRALAMA_BIRIMLERI = BIRIM_KODLARI.filter((b) => !KIRALAMA_DISI_BIRIMLER.includes(b));
const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");
const hataMesaji = (e: unknown) => (e as Error).message;

function DurumEtiketi({ durum }: { durum: string | null | undefined }) {
  if (!durum) return <>—</>;
  return <Tag color={KIRALIK_DURUM_RENKLERI[durum]}>{KIRALIK_DURUM_ADLARI[durum] ?? durum}</Tag>;
}

function suzgecOku(p: URLSearchParams): EnvanterSuzgeci {
  return {
    q: p.get("q") ?? undefined,
    durum: p.get("durum") ?? undefined,
    depo_id: p.get("depo_id") ? Number(p.get("depo_id")) : undefined,
    product_id: p.get("product_id") ? Number(p.get("product_id")) : undefined,
    birim: p.get("birim") ?? undefined,
    uzun: p.get("uzun") === "1" || p.get("uzun") === "true" ? true : undefined,
  };
}

function suzgecYaz(s: EnvanterSuzgeci, sekme?: string | null): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, v === true ? "1" : String(v));
  }
  if (sekme) p.set("sekme", sekme);
  return p;
}

function useDepolar() {
  return useQuery({ queryKey: ["kiralama-depolar"], queryFn: kiralamaApi.depolar });
}

function useKatalog() {
  return useQuery({ queryKey: ["kiralama-katalog-tum"], queryFn: () => kiralamaApi.katalog(undefined, true) });
}

export default function KiralikEnvanterPage() {
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const [arama, setArama] = useSearchParams();
  const sekme = arama.get("sekme") ?? "cihaz";
  const envanterci = yetkili("kiralama.envanter");

  const tazele = () => {
    for (const k of ["kiralik", "kiralik-bakiye", "kiralik-toplu-hareket", "kiralik-kart", "kiralama-katalog-tum", "kiralik-hazir"])
      void qc.invalidateQueries({ queryKey: [k] });
  };

  const bakiyeler = useQuery({ queryKey: ["kiralik-bakiye"], queryFn: kiralamaApi.bakiyeler });
  const sayac = useMemo(() => {
    const t: Record<string, number> = {};
    for (const b of bakiyeler.data ?? []) t[b.durum] = (t[b.durum] ?? 0) + b.adet;
    return t;
  }, [bakiyeler.data]);

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Row gutter={[12, 12]}>
        {["HAZIR", "KONTROLDE", "HAZIR_DEGIL", "KIRADA", "ATOLYEDE", "KAYIP"].map((d) => (
          <Col key={d} xs={12} sm={8} lg={4}>
            <Card
              size="small"
              hoverable
              loading={bakiyeler.isLoading}
              onClick={() => setArama(suzgecYaz({ durum: d }, "cihaz"))}
            >
              <Statistic title={KIRALIK_DURUM_ADLARI[d]} value={sayac[d] ?? 0} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card title="Kiralık Envanter" extra={envanterci && <EnvanterIslemleri onBitti={tazele} />}>
        <Tabs
          activeKey={sekme}
          onChange={(s) => setArama(suzgecYaz({}, s))}
          items={[
            { key: "cihaz", label: "Seri cihazlar", children: <CihazSekmesi onDegisti={tazele} /> },
            { key: "bakiye", label: "Depo bakiyeleri", children: <BakiyeSekmesi /> },
            { key: "hareket", label: "Toplu ürün hareketleri", children: <TopluHareketSekmesi /> },
            { key: "katalog", label: "Kiralama kataloğu", children: <KatalogSekmesi onDegisti={tazele} /> },
            {
              key: "sayim",
              label: "Depo sayımı",
              children: <KiralikSayim onDegisti={tazele} />,
            },
            ...(yetkili("servis_rapor.gor")
              ? [{ key: "rapor", label: "Raporlar", children: <KiralamaRaporlari /> }]
              : []),
          ]}
        />
      </Card>
    </Space>
  );
}

// --- Seri cihazlar ------------------------------------------------------------------

function CihazSekmesi({ onDegisti }: { onDegisti: () => void }) {
  const { yetkili } = useAuth();
  const [arama, setArama] = useSearchParams();
  const suzgec = useMemo(() => suzgecOku(arama), [arama]);
  const [sayfa, setSayfa] = useState(1);
  const [aramaMetni, setAramaMetni] = useState(suzgec.q ?? "");
  const [secili, setSecili] = useState<CihazSatiri[]>([]);
  const [kartId, setKartId] = useState<number | null>(null);
  const [pencere, setPencere] = useState<null | "kontrol" | "transfer" | "hurda" | "bulundu">(null);
  const depolar = useDepolar();
  const katalog = useKatalog();
  const envanterci = yetkili("kiralama.envanter");
  const aktarabilir = yetkili("kiralama.gor", "servis_rapor.disaaktar");

  const degistir = (s: EnvanterSuzgeci) => {
    setArama(suzgecYaz(s, "cihaz"));
    setSayfa(1);
    setSecili([]);
  };

  const liste = useQuery({
    queryKey: ["kiralik", suzgec, sayfa],
    queryFn: () => kiralamaApi.envanter(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });

  const bitti = () => {
    setSecili([]);
    setPencere(null);
    onDegisti();
  };

  return (
    <Space orientation="vertical" size="small" style={{ width: "100%" }}>
      <Row gutter={[8, 8]}>
        <Col xs={24} md={7}>
          <Input.Search
            allowClear
            placeholder="Seri no, ürün…"
            value={aramaMetni}
            onChange={(e) => setAramaMetni(e.target.value)}
            onSearch={(q) => degistir({ ...suzgec, q: q.trim() || undefined })}
          />
        </Col>
        <Col xs={12} md={4}>
          <Select
            allowClear
            style={{ width: "100%" }}
            placeholder="Durum"
            value={suzgec.durum}
            onChange={(v) => degistir({ ...suzgec, durum: v })}
            options={Object.entries(KIRALIK_DURUM_ADLARI).map(([k, v]) => ({ value: k, label: v }))}
          />
        </Col>
        <Col xs={12} md={5}>
          <Select
            allowClear
            style={{ width: "100%" }}
            placeholder="Depo"
            value={suzgec.depo_id}
            onChange={(v) => degistir({ ...suzgec, depo_id: v })}
            options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
          />
        </Col>
        <Col xs={12} md={5}>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            style={{ width: "100%" }}
            placeholder="Ürün"
            value={suzgec.product_id}
            onChange={(v) => degistir({ ...suzgec, product_id: v })}
            options={(katalog.data ?? [])
              .filter((k) => k.seri_takipli)
              .map((k) => ({ value: k.product_id, label: `${k.urun_kodu} — ${k.urun_adi}` }))}
          />
        </Col>
        <Col xs={12} md={3}>
          <Select
            allowClear
            style={{ width: "100%" }}
            placeholder="Birim"
            value={suzgec.birim}
            onChange={(v) => degistir({ ...suzgec, birim: v })}
            options={KIRALAMA_BIRIMLERI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
          />
        </Col>
      </Row>
      <Space wrap>
        <Checkbox checked={!!suzgec.uzun} onChange={(e) => degistir({ ...suzgec, uzun: e.target.checked || undefined })}>
          Uzun süredir kontrolde
        </Checkbox>
        {aktarabilir && (
          <Button size="small" onClick={() => window.open(kiralamaApi.envanterExcelYolu(suzgec), "_blank")}>
            Excel
          </Button>
        )}
        {envanterci && secili.length > 0 && (
          <>
            <Typography.Text>{secili.length} cihaz seçili</Typography.Text>
            <Button size="small" onClick={() => setPencere("kontrol")}>
              Dönüş kontrolü
            </Button>
            <Button size="small" onClick={() => setPencere("transfer")}>
              Transfer
            </Button>
            <Button size="small" disabled={secili.length !== 1} onClick={() => setPencere("bulundu")}>
              Bulundu
            </Button>
            <Button size="small" danger disabled={secili.length !== 1} onClick={() => setPencere("hurda")}>
              Hurdaya ayır
            </Button>
            <Button size="small" type="link" onClick={() => setSecili([])}>
              Seçimi kaldır
            </Button>
          </>
        )}
      </Space>
      <Table<CihazSatiri>
        rowKey="id"
        size="small"
        scroll={{ x: 900 }}
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar ?? []}
        locale={{ emptyText: <Empty description="Bu süzgeçte cihaz yok" /> }}
        rowSelection={
          envanterci
            ? {
                selectedRowKeys: secili.map((s) => s.id),
                onChange: (_, satirlar) => setSecili(satirlar.filter(Boolean)),
              }
            : undefined
        }
        pagination={{
          current: sayfa,
          pageSize: SAYFA_BOYU,
          total: liste.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} cihaz`,
        }}
        onRow={(r) => ({ onClick: () => setKartId(r.id), style: { cursor: "pointer" } })}
        columns={[
          { title: "Seri no", dataIndex: "serial_no", width: 160, render: (v) => <span className="mono">{v}</span> },
          { title: "Ürün", key: "urun", ellipsis: true, render: (_, r) => `${r.urun_kodu ?? ""} ${r.urun_adi ?? ""}` },
          { title: "Birim", dataIndex: "birim", width: 120, render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
          { title: "Depo", dataIndex: "depo_adi", width: 150, render: (v) => v ?? "—" },
          {
            title: "Durum",
            key: "durum",
            width: 180,
            render: (_, r) => (
              <Space size={4} wrap>
                <DurumEtiketi durum={r.durum} />
                {r.kontrolde_gun != null && <Tag>{r.kontrolde_gun} gün</Tag>}
              </Space>
            ),
          },
          {
            title: "Kiralama",
            dataIndex: "kiralama_id",
            width: 100,
            render: (v: number | null) =>
              v ? (
                <Link to={`/kiralamalar/${v}`} onClick={(e) => e.stopPropagation()}>
                  #{v}
                </Link>
              ) : (
                "—"
              ),
          },
          { title: "Eksik", dataIndex: "eksik_notu", ellipsis: true, render: (v) => v ?? "" },
        ]}
      />

      {kartId && <CihazCekmecesi id={kartId} onKapat={() => setKartId(null)} onDegisti={onDegisti} />}
      {pencere === "kontrol" && <KontrolPenceresi cihazlar={secili} onKapat={() => setPencere(null)} onBitti={bitti} />}
      {pencere === "transfer" && <TransferPenceresi cihazlar={secili} onKapat={() => setPencere(null)} onBitti={bitti} />}
      {pencere === "hurda" && secili[0] && (
        <HurdaPenceresi cihaz={secili[0]} onKapat={() => setPencere(null)} onBitti={bitti} />
      )}
      {pencere === "bulundu" && secili[0] && (
        <BulunduPenceresi cihaz={secili[0]} onKapat={() => setPencere(null)} onBitti={bitti} />
      )}
    </Space>
  );
}

function HareketTablosu({ hareketler, loading }: { hareketler: HareketOut[]; loading?: boolean }) {
  return (
    <Table<HareketOut>
      size="small"
      rowKey="id"
      loading={loading}
      pagination={false}
      dataSource={hareketler}
      scroll={{ x: 800 }}
      columns={[
        { title: "Zaman", dataIndex: "at", width: 140, render: zaman },
        {
          title: "Hareket",
          dataIndex: "kind",
          width: 120,
          render: (k: string, r) => (
            <Space size={4}>
              {HAREKET_ADLARI[k] ?? k}
              {r.reverses_id && <Tag color="red">ters</Tag>}
            </Space>
          ),
        },
        { title: "Adet", dataIndex: "qty", width: 60, align: "right" },
        {
          title: "Depo",
          key: "depo",
          render: (_, r) => [r.from_depo, r.to_depo].filter(Boolean).join(" → ") || "—",
        },
        {
          title: "Durum",
          key: "durum",
          width: 220,
          render: (_, r) => (
            <Space size={2}>
              <DurumEtiketi durum={r.from_durum} />→<DurumEtiketi durum={r.to_durum} />
            </Space>
          ),
        },
        {
          title: "Kiralama",
          dataIndex: "rental_no",
          width: 110,
          render: (v: string | null, r) => (v && r.rental_id ? <Link to={`/kiralamalar/${r.rental_id}`}>{v}</Link> : "—"),
        },
        { title: "Not", dataIndex: "note", ellipsis: true, render: (v) => v ?? "" },
      ]}
    />
  );
}

function CihazCekmecesi({ id, onKapat, onDegisti }: { id: number; onKapat: () => void; onDegisti: () => void }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{ serial_no: string; eksik_notu?: string; notes?: string }>();
  const kart = useQuery({ queryKey: ["kiralik-kart", id], queryFn: () => kiralamaApi.cihaz(id), retry: false });
  const kaydet = useMutation({
    mutationFn: (v: { serial_no: string; eksik_notu?: string; notes?: string }) =>
      kiralamaApi.cihazGuncelle(id, {
        version: kart.data!.version,
        serial_no: v.serial_no,
        eksik_notu: v.eksik_notu?.trim() || null,
        notes: v.notes?.trim() || null,
      }),
    onSuccess: (k) => {
      message.success("Kaydedildi");
      qc.setQueryData(["kiralik-kart", id], k);
      onDegisti();
    },
    onError: (e) => message.error(hataMesaji(e)),
  });
  const c = kart.data;
  return (
    <Drawer open onClose={onKapat} width={Math.min(900, window.innerWidth)} title={c ? `Kiralık cihaz ${c.serial_no}` : "Kiralık cihaz"}>
      {kart.isError && <Alert type="error" showIcon message={hataMesaji(kart.error)} />}
      {c && (
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Descriptions size="small" bordered column={{ xs: 1, md: 2 }}>
            <Descriptions.Item label="Ürün">{`${c.urun_kodu ?? ""} ${c.urun_adi ?? ""}`}</Descriptions.Item>
            <Descriptions.Item label="Birim">{BIRIM_ETIKETLERI[c.birim] ?? c.birim}</Descriptions.Item>
            <Descriptions.Item label="Depo">{c.depo_adi ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Durum">
              <DurumEtiketi durum={c.durum} />
            </Descriptions.Item>
            {c.kiralama_id && (
              <Descriptions.Item label="Aktif tahsis">
                <Link to={`/kiralamalar/${c.kiralama_id}`}>Kiralama #{c.kiralama_id}</Link>
              </Descriptions.Item>
            )}
          </Descriptions>
          {yetkili("kiralama.envanter") && (
            <Card size="small" title="Bilgileri düzenle">
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                Durum, depo ve ürün buradan değişmez; transfer, kontrol, hurda işlemlerini kullanın.
              </Typography.Paragraph>
              <Form
                form={form}
                layout="vertical"
                initialValues={{ serial_no: c.serial_no, eksik_notu: c.eksik_notu ?? undefined, notes: c.notes ?? undefined }}
                onFinish={(v) => kaydet.mutate(v)}
              >
                <Row gutter={8}>
                  <Col xs={24} md={8}>
                    <Form.Item name="serial_no" label="Seri no" rules={[{ required: true, whitespace: true, max: 200 }]}>
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={16}>
                    <Form.Item name="eksik_notu" label="Eksik notu">
                      <Input maxLength={300} />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item name="notes" label="Not">
                  <Input.TextArea rows={2} maxLength={4000} />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={kaydet.isPending}>
                  Kaydet
                </Button>
              </Form>
            </Card>
          )}
          <Typography.Text strong>Hareketler</Typography.Text>
          <HareketTablosu hareketler={c.hareketler} />
        </Space>
      )}
    </Drawer>
  );
}

// --- Bakiyeler ve toplu hareketler ------------------------------------------------

function BakiyeSekmesi() {
  const bakiyeler = useQuery({ queryKey: ["kiralik-bakiye"], queryFn: kiralamaApi.bakiyeler });
  const gruplar = useMemo(() => {
    const g = new Map<string, NonNullable<typeof bakiyeler.data>>();
    for (const b of bakiyeler.data ?? []) {
      const ad = b.depo_adi ?? "Depo dışında (kirada / kayıp / atölyede)";
      g.set(ad, [...(g.get(ad) ?? []), b]);
    }
    return [...g.entries()];
  }, [bakiyeler]);
  if (!bakiyeler.isLoading && gruplar.length === 0) return <Empty description="Envanter boş" />;
  return (
    <Row gutter={[12, 12]}>
      {gruplar.map(([depo, satirlar]) => (
        <Col key={depo} xs={24} lg={12}>
          <Card size="small" title={depo} extra={`${satirlar.reduce((s, r) => s + r.adet, 0)} adet`}>
            <Table
              size="small"
              rowKey={(r) => `${r.product_id}-${r.durum}-${r.seri_takipli}`}
              pagination={false}
              dataSource={satirlar}
              columns={[
                {
                  title: "Ürün",
                  key: "urun",
                  render: (_, r) => (
                    <Space size={4}>
                      <span className="mono">{r.urun_kodu}</span>
                      {r.urun_adi}
                      {!r.seri_takipli && <Tag>toplu</Tag>}
                    </Space>
                  ),
                },
                { title: "Durum", dataIndex: "durum", width: 120, render: (d: string) => <DurumEtiketi durum={d} /> },
                { title: "Adet", dataIndex: "adet", width: 70, align: "right" },
              ]}
            />
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function TopluHareketSekmesi() {
  const depolar = useDepolar();
  const katalog = useKatalog();
  const [urun, setUrun] = useState<number | undefined>();
  const [depo, setDepo] = useState<number | undefined>();
  const [sayfa, setSayfa] = useState(1);
  const liste = useQuery({
    queryKey: ["kiralik-toplu-hareket", urun, depo, sayfa],
    queryFn: () => kiralamaApi.topluHareketler(urun, depo, 100, (sayfa - 1) * 100),
  });
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Space wrap>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          style={{ width: 280 }}
          placeholder="Ürün"
          value={urun}
          onChange={(v) => {
            setUrun(v);
            setSayfa(1);
          }}
          options={(katalog.data ?? [])
            .filter((k) => !k.seri_takipli)
            .map((k) => ({ value: k.product_id, label: `${k.urun_kodu} — ${k.urun_adi}` }))}
        />
        <Select
          allowClear
          style={{ width: 200 }}
          placeholder="Depo"
          value={depo}
          onChange={(v) => {
            setDepo(v);
            setSayfa(1);
          }}
          options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
        />
      </Space>
      <HareketTablosu hareketler={liste.data?.kayitlar ?? []} loading={liste.isLoading} />
      {(liste.data?.toplam ?? 0) > 100 && (
        <Space>
          <Button size="small" disabled={sayfa === 1} onClick={() => setSayfa(sayfa - 1)}>
            Önceki
          </Button>
          <Typography.Text>
            {sayfa} / {Math.ceil((liste.data?.toplam ?? 0) / 100)}
          </Typography.Text>
          <Button size="small" disabled={sayfa * 100 >= (liste.data?.toplam ?? 0)} onClick={() => setSayfa(sayfa + 1)}>
            Sonraki
          </Button>
        </Space>
      )}
    </Space>
  );
}

// --- Katalog (TS-118) -------------------------------------------------------------

interface UrunAday {
  id: number;
  code: string;
  name: string;
  identity_kind?: string | null;
}

function KatalogSekmesi({ onDegisti }: { onDegisti: () => void }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const envanterci = yetkili("kiralama.envanter");
  const [birim, setBirim] = useState<string | undefined>();
  const [ekleAcik, setEkleAcik] = useState(false);
  const katalog = useQuery({ queryKey: ["kiralama-katalog-liste", birim], queryFn: () => kiralamaApi.katalog(birim) });
  const qc = useQueryClient();
  const guncelle = useMutation({
    mutationFn: (g: { p: KatalogOut; alanlar: { is_active?: boolean; kategori?: string | null; sira?: number } }) =>
      kiralamaApi.katalogGuncelle(g.p.id, { version: g.p.version, ...g.alanlar }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kiralama-katalog-liste"] });
      onDegisti();
    },
    onError: (e) => message.error(hataMesaji(e)),
  });

  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Space wrap>
        <Select
          allowClear
          style={{ width: 220 }}
          placeholder="Birim"
          value={birim}
          onChange={setBirim}
          options={KIRALAMA_BIRIMLERI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
        />
        {envanterci && (
          <Button type="primary" onClick={() => setEkleAcik(true)}>
            Kataloğa ürün ekle
          </Button>
        )}
      </Space>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        IMEI'li ürünler kiralama kataloğuna alınamaz. Envanteri olan ürünün seri takibi (kimlik tipi) ürün kartında
        değiştirilemez.
      </Typography.Text>
      <Table<KatalogOut>
        size="small"
        rowKey="id"
        loading={katalog.isLoading}
        dataSource={katalog.data ?? []}
        pagination={{ pageSize: 50, showSizeChanger: false }}
        columns={[
          { title: "Kod", dataIndex: "urun_kodu", width: 140, render: (v) => <span className="mono">{v}</span> },
          { title: "Ürün", dataIndex: "urun_adi", ellipsis: true },
          { title: "Birim", dataIndex: "birim", width: 140, render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
          { title: "Takip", dataIndex: "seri_takipli", width: 90, render: (s: boolean) => (s ? <Tag color="blue">Seri</Tag> : <Tag>Toplu</Tag>) },
          { title: "Kategori", dataIndex: "kategori", width: 140, render: (v) => v ?? "—" },
          { title: "Sıra", dataIndex: "sira", width: 70, align: "right" },
          {
            title: "Aktif",
            dataIndex: "is_active",
            width: 80,
            render: (a: boolean, p) => (
              <Switch
                size="small"
                checked={a}
                disabled={!envanterci}
                loading={guncelle.isPending && guncelle.variables?.p.id === p.id}
                onChange={(v) => guncelle.mutate({ p, alanlar: { is_active: v } })}
              />
            ),
          },
        ]}
      />
      {ekleAcik && (
        <KatalogEklePenceresi
          onKapat={() => setEkleAcik(false)}
          onBitti={() => {
            setEkleAcik(false);
            void qc.invalidateQueries({ queryKey: ["kiralama-katalog-liste"] });
            onDegisti();
          }}
        />
      )}
    </Space>
  );
}

function KatalogEklePenceresi({ onKapat, onBitti }: { onKapat: () => void; onBitti: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm<{ product_id: number; birim: string; kategori?: string; sira?: number }>();
  const [q, setQ] = useState("");
  const urunler = useQuery({
    queryKey: ["urun-ara-kiralama", q],
    queryFn: () => api.get<UrunAday[]>(`/api/urunler?${new URLSearchParams({ q, limit: "30" })}`),
    enabled: q.trim().length >= 2,
  });
  const ekle = useMutation({
    mutationFn: (v: { product_id: number; birim: string; kategori?: string; sira?: number }) =>
      kiralamaApi.katalogEkle({ ...v, kategori: v.kategori?.trim() || null, sira: v.sira ?? 0 }),
    onSuccess: () => {
      message.success("Ürün kataloğa eklendi");
      onBitti();
    },
    onError: (e) => message.error(hataMesaji(e)),
  });
  return (
    <Modal open title="Kiralama kataloğuna ürün ekle" onCancel={onKapat} onOk={() => form.submit()} okText="Ekle" cancelText="Vazgeç" confirmLoading={ekle.isPending} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={(v) => ekle.mutate(v)}>
        <Form.Item name="product_id" label="Ürün" rules={[{ required: true, message: "Ürün seçin" }]}>
          <Select
            showSearch
            filterOption={false}
            onSearch={setQ}
            placeholder="Ürün kodu ya da adı yazın"
            loading={urunler.isFetching}
            notFoundContent={urunler.isError ? hataMesaji(urunler.error) : q.length >= 2 ? "Eşleşen ürün yok" : null}
            options={(urunler.data ?? []).map((u) => ({
              value: u.id,
              label: `${u.code} — ${u.name}${u.identity_kind === "SERI_NO" ? " (seri)" : ""}`,
            }))}
          />
        </Form.Item>
        <Form.Item name="birim" label="Birim" rules={[{ required: true, message: "Birim seçin" }]}>
          <Select options={KIRALAMA_BIRIMLERI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))} />
        </Form.Item>
        <Row gutter={8}>
          <Col span={16}>
            <Form.Item name="kategori" label="Kategori">
              <Input maxLength={40} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="sira" label="Sıra">
              <InputNumber min={0} precision={0} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
}

// --- İşlemler (giriş, toplu giriş, toplu transfer/kontrol/hurda) ------------------

function EnvanterIslemleri({ onBitti }: { onBitti: () => void }) {
  const [pencere, setPencere] = useState<null | "giris" | "toplu" | "transfer" | "kontrol" | "hurda" | "bulundu">(null);
  const kapat = () => setPencere(null);
  const bitti = () => {
    setPencere(null);
    onBitti();
  };
  return (
    <Space wrap>
      <Button type="primary" onClick={() => setPencere("giris")}>
        Envanter girişi
      </Button>
      <Button onClick={() => setPencere("toplu")}>Excel'den toplu giriş</Button>
      <Button onClick={() => setPencere("transfer")}>Toplu ürün transferi</Button>
      <Button onClick={() => setPencere("kontrol")}>Toplu ürün kontrolü</Button>
      <Button onClick={() => setPencere("bulundu")}>Toplu bulundu</Button>
      <Button danger onClick={() => setPencere("hurda")}>
        Toplu hurda
      </Button>
      {pencere === "giris" && <GirisPenceresi onKapat={kapat} onBitti={bitti} />}
      {pencere === "toplu" && <TopluGirisPenceresi onKapat={kapat} onBitti={bitti} />}
      {pencere === "transfer" && <TransferPenceresi cihazlar={[]} onKapat={kapat} onBitti={bitti} />}
      {pencere === "kontrol" && <KontrolPenceresi cihazlar={[]} onKapat={kapat} onBitti={bitti} />}
      {pencere === "hurda" && <HurdaPenceresi onKapat={kapat} onBitti={bitti} />}
      {pencere === "bulundu" && <BulunduPenceresi onKapat={kapat} onBitti={bitti} />}
    </Space>
  );
}

function useIslem(onBitti: () => void, mesaj = "Kaydedildi") {
  const { message } = App.useApp();
  return useMutation({
    mutationFn: (f: () => Promise<unknown>) => f(),
    onSuccess: () => {
      message.success(mesaj);
      onBitti();
    },
    onError: (e) => message.error(hataMesaji(e)),
  });
}

function UrunSecici({ seri, value, onChange }: { seri?: boolean; value?: number; onChange?: (v: number) => void }) {
  const katalog = useKatalog();
  return (
    <Select
      showSearch
      optionFilterProp="label"
      value={value}
      onChange={onChange}
      placeholder="Katalogdaki ürün"
      options={(katalog.data ?? [])
        .filter((k) => seri === undefined || k.seri_takipli === seri)
        .map((k) => ({ value: k.product_id, label: `${k.urun_kodu} — ${k.urun_adi}${k.seri_takipli ? " (seri)" : ""}` }))}
    />
  );
}

function DepoSecici({ value, onChange }: { value?: number; onChange?: (v: number) => void }) {
  const depolar = useDepolar();
  return (
    <Select
      value={value}
      onChange={onChange}
      placeholder="Kiralama deposu"
      options={(depolar.data ?? []).map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
    />
  );
}

function GirisPenceresi({ onKapat, onBitti }: { onKapat: () => void; onBitti: () => void }) {
  const [form] = Form.useForm<{ product_id: number; depo_id: number; durum: string; seriler?: string; adet?: number; not?: string }>();
  const katalog = useKatalog();
  const urunId = Form.useWatch("product_id", form);
  const seri = katalog.data?.find((k) => k.product_id === urunId)?.seri_takipli;
  const islem = useIslem(onBitti, "Envanter girişi yapıldı");
  return (
    <Modal open title="Envanter girişi" onCancel={onKapat} onOk={() => form.submit()} okText="Giriş yap" cancelText="Vazgeç" confirmLoading={islem.isPending} destroyOnHidden>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ durum: "HAZIR" }}
        onFinish={(v) =>
          islem.mutate(() =>
            kiralamaApi.giris({
              product_id: v.product_id,
              depo_id: v.depo_id,
              durum: v.durum,
              seriler: seri
                ? (v.seriler ?? "")
                    .split(/[\n,;]+/)
                    .map((s) => s.trim())
                    .filter(Boolean)
                : null,
              adet: seri ? null : (v.adet ?? null),
              not: v.not?.trim() || undefined,
            }),
          )
        }
      >
        <Form.Item name="product_id" label="Ürün" rules={[{ required: true, message: "Ürün seçin" }]}>
          <UrunSecici />
        </Form.Item>
        <Form.Item name="depo_id" label="Depo" rules={[{ required: true, message: "Depo seçin" }]}>
          <DepoSecici />
        </Form.Item>
        <Form.Item name="durum" label="Giriş durumu">
          <Radio.Group options={GIRIS_DURUMLARI.map((d) => ({ value: d, label: KIRALIK_DURUM_ADLARI[d] }))} />
        </Form.Item>
        {seri ? (
          <Form.Item name="seriler" label="Seri numaraları (her satıra bir)" rules={[{ required: true, whitespace: true }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
        ) : (
          <Form.Item name="adet" label="Adet" rules={[{ required: true, message: "Adet girin" }]}>
            <InputNumber min={1} precision={0} style={{ width: "100%" }} />
          </Form.Item>
        )}
        <Form.Item name="not" label="Not">
          <Input maxLength={300} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function TopluGirisPenceresi({ onKapat, onBitti }: { onKapat: () => void; onBitti: () => void }) {
  const { message } = App.useApp();
  const [dosya, setDosya] = useState<File | null>(null);
  const [onizleme, setOnizleme] = useState<TopluOnizleme | null>(null);
  const onizle = useMutation({
    mutationFn: (f: File) => kiralamaApi.topluOnizleme(f),
    onSuccess: setOnizleme,
    onError: (e) => message.error(hataMesaji(e)),
  });
  const onayla = useMutation({
    mutationFn: () => kiralamaApi.topluOnayla(dosya!, onizleme!.sha256),
    onSuccess: (r) => {
      message.success(`${r.yazilan_satir} satır yazıldı (${r.toplam_adet} adet); ${r.atlanan_satir} satır atlandı`);
      onBitti();
    },
    onError: (e) => message.error(hataMesaji(e)),
  });
  return (
    <Modal
      open
      width={900}
      title="Excel'den toplu envanter girişi"
      onCancel={onKapat}
      okText={onizleme ? `${onizleme.gecerli} satırı yaz` : "Önizle"}
      cancelText="Vazgeç"
      okButtonProps={{ disabled: !dosya || (!!onizleme && onizleme.gecerli === 0) }}
      confirmLoading={onizle.isPending || onayla.isPending}
      onOk={() => (onizleme ? onayla.mutate() : dosya && onizle.mutate(dosya))}
      destroyOnHidden
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Önizleme hiçbir şey yazmaz. Onayda dosya yeniden doğrulanır; yalnız hatasız satırlar yazılır. Dosya önizlemeden
          sonra değiştiyse işlem reddedilir.{" "}
          <a href={kiralamaApi.sablonYolu()} target="_blank" rel="noreferrer">
            Şablonu indir
          </a>
        </Typography.Paragraph>
        <Upload
          accept=".xlsx,.xls,.csv"
          maxCount={1}
          beforeUpload={(f) => {
            setDosya(f);
            setOnizleme(null);
            return false;
          }}
          onRemove={() => {
            setDosya(null);
            setOnizleme(null);
          }}
        >
          <Button>Dosya seç</Button>
        </Upload>
        {onizleme && (
          <>
            <Space>
              <Tag>Toplam {onizleme.toplam}</Tag>
              <Tag color="green">Geçerli {onizleme.gecerli}</Tag>
              <Tag color={onizleme.hatali ? "red" : "default"}>Hatalı {onizleme.hatali}</Tag>
            </Space>
            <Table
              size="small"
              rowKey="satir_no"
              pagination={{ pageSize: 20, showSizeChanger: false }}
              dataSource={onizleme.satirlar}
              columns={[
                { title: "Satır", dataIndex: "satir_no", width: 60 },
                { title: "Ürün", dataIndex: "urun_kodu" },
                { title: "Seri", dataIndex: "seri_no", render: (v) => v ?? "" },
                { title: "Adet", dataIndex: "adet", width: 60 },
                { title: "Depo", dataIndex: "depo_kodu" },
                { title: "Durum", dataIndex: "durum", render: (d) => <DurumEtiketi durum={d} /> },
                {
                  title: "Hatalar",
                  dataIndex: "hatalar",
                  render: (h: string[]) =>
                    h.length ? <Typography.Text type="danger">{h.join("; ")}</Typography.Text> : <Tag color="green">Tamam</Tag>,
                },
              ]}
            />
          </>
        )}
      </Space>
    </Modal>
  );
}

/** Seçili seri cihazlar ya da (seçim yoksa) toplu ürün transferi. Durum korunur. */
function TransferPenceresi({ cihazlar, onKapat, onBitti }: { cihazlar: CihazSatiri[]; onKapat: () => void; onBitti: () => void }) {
  const [form] = Form.useForm<{ hedef_depo_id: number; product_id?: number; kaynak_depo_id?: number; adet?: number; durum?: string; not?: string }>();
  const islem = useIslem(onBitti, "Transfer yapıldı");
  const seri = cihazlar.length > 0;
  return (
    <Modal open title={seri ? `Transfer (${cihazlar.length} cihaz)` : "Toplu ürün transferi"} onCancel={onKapat} onOk={() => form.submit()} okText="Transfer et" cancelText="Vazgeç" confirmLoading={islem.isPending} destroyOnHidden>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ durum: "HAZIR" }}
        onFinish={(v) =>
          islem.mutate(() =>
            kiralamaApi.transfer(
              seri
                ? { hedef_depo_id: v.hedef_depo_id, kiralik_idler: cihazlar.map((c) => c.id), not: v.not?.trim() || undefined }
                : {
                    hedef_depo_id: v.hedef_depo_id,
                    product_id: v.product_id,
                    kaynak_depo_id: v.kaynak_depo_id,
                    adet: v.adet,
                    durum: v.durum,
                    not: v.not?.trim() || undefined,
                  },
            ),
          )
        }
      >
        {!seri && (
          <>
            <Form.Item name="product_id" label="Ürün (seri takipsiz)" rules={[{ required: true }]}>
              <UrunSecici seri={false} />
            </Form.Item>
            <Form.Item name="kaynak_depo_id" label="Kaynak depo" rules={[{ required: true }]}>
              <DepoSecici />
            </Form.Item>
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item name="adet" label="Adet" rules={[{ required: true }]}>
                  <InputNumber min={1} precision={0} style={{ width: "100%" }} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="durum" label="Durum">
                  <Select options={GIRIS_DURUMLARI.map((d) => ({ value: d, label: KIRALIK_DURUM_ADLARI[d] }))} />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}
        <Form.Item name="hedef_depo_id" label="Hedef depo" rules={[{ required: true, message: "Hedef depo seçin" }]}>
          <DepoSecici />
        </Form.Item>
        <Form.Item name="not" label="Not">
          <Input maxLength={300} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** Dönüş kontrolü (TS-115): UYGUN → Hazır; EKSİK/ARIZALI → Hazır değil, açıklama zorunlu. */
function KontrolPenceresi({ cihazlar, onKapat, onBitti }: { cihazlar: CihazSatiri[]; onKapat: () => void; onBitti: () => void }) {
  const islem = useIslem(onBitti, "Kontrol kaydedildi");
  const seri = cihazlar.length > 0;
  const [satirlar, setSatirlar] = useState<Record<number, { sonuc: string; aciklama?: string; atolye?: boolean }>>(
    Object.fromEntries(cihazlar.map((c) => [c.id, { sonuc: "UYGUN" }])),
  );
  const [form] = Form.useForm<{ product_id: number; depo_id: number; adet: number; kaynak_durum: string; sonuc: string; aciklama?: string }>();
  const guncelle = (id: number, p: object) => setSatirlar((s) => ({ ...s, [id]: { ...s[id], ...p } }));
  const uygunsuz = cihazlar.filter((c) => !(KONTROL_KAYNAK_DURUMLARI as readonly string[]).includes(c.durum));

  const gonderSeri = () =>
    islem.mutate(() =>
      kiralamaApi.kontrol(
        cihazlar.map((c) => ({
          kiralik_id: c.id,
          sonuc: satirlar[c.id].sonuc,
          aciklama: satirlar[c.id].aciklama?.trim() || null,
          atolye_kaydi_ac: !!satirlar[c.id].atolye,
        })),
      ),
    );

  return (
    <Modal
      open
      width={seri ? 900 : 520}
      title={seri ? `Dönüş kontrolü (${cihazlar.length} cihaz)` : "Toplu ürün kontrolü"}
      onCancel={onKapat}
      onOk={() => (seri ? gonderSeri() : form.submit())}
      okText="Kaydet"
      cancelText="Vazgeç"
      okButtonProps={{ disabled: seri && uygunsuz.length > 0 }}
      confirmLoading={islem.isPending}
      destroyOnHidden
    >
      {seri ? (
        <Space orientation="vertical" style={{ width: "100%" }}>
          {uygunsuz.length > 0 && (
            <Alert
              type="warning"
              showIcon
              message={`Yalnız Kontrolde ya da Hazır değil durumundaki cihaz kontrol edilir: ${uygunsuz.map((c) => c.serial_no).join(", ")}`}
            />
          )}
          <Table<CihazSatiri>
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={cihazlar}
            columns={[
              { title: "Seri", dataIndex: "serial_no", width: 150 },
              { title: "Durum", dataIndex: "durum", width: 110, render: (d: string) => <DurumEtiketi durum={d} /> },
              {
                title: "Sonuç",
                key: "sonuc",
                width: 130,
                render: (_, c) => (
                  <Select
                    style={{ width: "100%" }}
                    value={satirlar[c.id]?.sonuc}
                    onChange={(v) => guncelle(c.id, { sonuc: v, atolye: v === "ARIZALI" ? satirlar[c.id]?.atolye : false })}
                    options={Object.entries(KONTROL_SONUC_ADLARI).map(([k, v]) => ({ value: k, label: v }))}
                  />
                ),
              },
              {
                title: "Açıklama",
                key: "aciklama",
                render: (_, c) => (
                  <Input
                    maxLength={500}
                    status={satirlar[c.id]?.sonuc !== "UYGUN" && !satirlar[c.id]?.aciklama?.trim() ? "error" : undefined}
                    placeholder={satirlar[c.id]?.sonuc !== "UYGUN" ? "Zorunlu" : ""}
                    value={satirlar[c.id]?.aciklama}
                    onChange={(e) => guncelle(c.id, { aciklama: e.target.value })}
                  />
                ),
              },
              {
                title: "Atölye",
                key: "atolye",
                width: 80,
                render: (_, c) => (
                  <Checkbox
                    disabled={satirlar[c.id]?.sonuc !== "ARIZALI"}
                    checked={!!satirlar[c.id]?.atolye}
                    onChange={(e) => guncelle(c.id, { atolye: e.target.checked })}
                  />
                ),
              },
            ]}
          />
        </Space>
      ) : (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ kaynak_durum: "KONTROLDE", sonuc: "UYGUN" }}
          onFinish={(v) =>
            islem.mutate(() =>
              kiralamaApi.kontrol([
                {
                  sonuc: v.sonuc,
                  product_id: v.product_id,
                  depo_id: v.depo_id,
                  adet: v.adet,
                  kaynak_durum: v.kaynak_durum,
                  aciklama: v.aciklama?.trim() || null,
                },
              ]),
            )
          }
        >
          <Form.Item name="product_id" label="Ürün (seri takipsiz)" rules={[{ required: true }]}>
            <UrunSecici seri={false} />
          </Form.Item>
          <Form.Item name="depo_id" label="Depo" rules={[{ required: true }]}>
            <DepoSecici />
          </Form.Item>
          <Row gutter={8}>
            <Col span={8}>
              <Form.Item name="adet" label="Adet" rules={[{ required: true }]}>
                <InputNumber min={1} precision={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="kaynak_durum" label="Kaynak durum">
                <Select options={KONTROL_KAYNAK_DURUMLARI.map((d) => ({ value: d, label: KIRALIK_DURUM_ADLARI[d] }))} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="sonuc" label="Sonuç">
                <Select options={Object.entries(KONTROL_SONUC_ADLARI).map(([k, v]) => ({ value: k, label: v }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="aciklama"
            label="Açıklama"
            dependencies={["sonuc"]}
            rules={[
              ({ getFieldValue }) => ({
                validator: (_, v?: string) =>
                  getFieldValue("sonuc") === "UYGUN" || v?.trim()
                    ? Promise.resolve()
                    : Promise.reject(new Error("Uygun dışındaki sonuçta açıklama zorunlu")),
              }),
            ]}
          >
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}

function HurdaPenceresi({ cihaz, onKapat, onBitti }: { cihaz?: CihazSatiri; onKapat: () => void; onBitti: () => void }) {
  const [form] = Form.useForm<{ gerekce: string; product_id?: number; depo_id?: number; kaynak_durum?: string; adet?: number }>();
  const islem = useIslem(onBitti, "Envanterden çıkarıldı");
  return (
    <Modal open title={cihaz ? `Hurdaya ayır — ${cihaz.serial_no}` : "Toplu ürün hurda çıkışı"} onCancel={onKapat} onOk={() => form.submit()} okText="Hurdaya ayır" okButtonProps={{ danger: true }} cancelText="Vazgeç" confirmLoading={islem.isPending} destroyOnHidden>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Kayıt silinmez; gerekçeli HURDA hareketi yazılır. Kirada ya da hazır cihaz hurdaya ayrılamaz.
      </Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ kaynak_durum: "HAZIR_DEGIL" }}
        onFinish={(v) =>
          islem.mutate(() =>
            kiralamaApi.hurda(
              cihaz
                ? { gerekce: v.gerekce.trim(), kiralik_id: cihaz.id }
                : { gerekce: v.gerekce.trim(), product_id: v.product_id, depo_id: v.depo_id, kaynak_durum: v.kaynak_durum, adet: v.adet },
            ),
          )
        }
      >
        {!cihaz && (
          <>
            <Form.Item name="product_id" label="Ürün (seri takipsiz)" rules={[{ required: true }]}>
              <UrunSecici seri={false} />
            </Form.Item>
            <Form.Item name="depo_id" label="Depo">
              <DepoSecici />
            </Form.Item>
            <Row gutter={8}>
              <Col span={12}>
                <Form.Item name="kaynak_durum" label="Kaynak durum">
                  <Select options={HURDA_KAYNAK_DURUMLARI.map((d) => ({ value: d, label: KIRALIK_DURUM_ADLARI[d] }))} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="adet" label="Adet" rules={[{ required: true }]}>
                  <InputNumber min={1} precision={0} style={{ width: "100%" }} />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}
        <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]}>
          <Input.TextArea rows={2} maxLength={300} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function BulunduPenceresi({ cihaz, onKapat, onBitti }: { cihaz?: CihazSatiri; onKapat: () => void; onBitti: () => void }) {
  const [form] = Form.useForm<{ gerekce: string; depo_id: number; product_id?: number; adet?: number }>();
  const islem = useIslem(onBitti, "Cihaz depoya alındı (kontrolde)");
  return (
    <Modal open title={cihaz ? `Bulundu — ${cihaz.serial_no}` : "Kayıp toplu ürün bulundu"} onCancel={onKapat} onOk={() => form.submit()} okText="Kaydet" cancelText="Vazgeç" confirmLoading={islem.isPending} destroyOnHidden>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Yalnız kayıp kayıtlar için; cihaz seçilen depoya "Kontrolde" olarak girer.
      </Typography.Paragraph>
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) =>
          islem.mutate(() =>
            kiralamaApi.bulundu(
              cihaz
                ? { gerekce: v.gerekce.trim(), depo_id: v.depo_id, kiralik_id: cihaz.id }
                : { gerekce: v.gerekce.trim(), depo_id: v.depo_id, product_id: v.product_id, adet: v.adet },
            ),
          )
        }
      >
        {!cihaz && (
          <Row gutter={8}>
            <Col span={16}>
              <Form.Item name="product_id" label="Ürün (seri takipsiz)" rules={[{ required: true }]}>
                <UrunSecici seri={false} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="adet" label="Adet" rules={[{ required: true }]}>
                <InputNumber min={1} precision={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
        )}
        <Form.Item name="depo_id" label="Depo" rules={[{ required: true, message: "Depo seçin" }]}>
          <DepoSecici />
        </Form.Item>
        <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, message: "Gerekçe zorunlu" }]}>
          <Input.TextArea rows={2} maxLength={300} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
