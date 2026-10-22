/**
 * Ekipman Kütüğü — liste, filtre, Excel, KPI, toplu işlem (TS-053/055/056).
 *
 * Veri yalnız sayfa açılınca gelir (giriş/panelde kütük çağrılmaz). Liste
 * sunucuda süzülür ve sayfalanır; toplam `X-Toplam-Kayit`. KPI kutularının
 * sayısı, tıklanınca açılan `?kpi=<kod>` listesinin toplamıyla aynı sorgudan
 * gelir (sayı = liste). Excel ekrandaki süzgeci (seçim varsa seçili satırları)
 * aynen alır. `/servis-ekipman/:id` kartı doğrudan açar (görev ve arama
 * bağlantıları buraya gelir).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import {
  DURUM_ETIKETLERI,
  DURUM_RENKLERI,
  EKIPMAN_TIPLERI,
  ekipmanApi,
  GARANTI_ETIKETLERI,
  TIP_ETIKETLERI,
  type EkipmanKarti as Kart,
  type EkipmanSatiri,
  type EkipmanSuzgeci,
  type GarantiSonucu,
} from "../api/servisEkipman";
import { useAuth } from "../auth/AuthContext";
import EkipmanFormu from "../components/EkipmanFormu";
import EkipmanKarti, { GarantiEtiketi } from "../components/EkipmanKarti";
import EkipmanTopluIslemleri from "../components/EkipmanTopluIslemleri";
import EkipmanVeriKalitesi from "../components/EkipmanVeriKalitesi";
import KpiKutusu from "../components/KpiKutusu";

const SAYFA_BOYU = 50;
const TOPLU_UST_SINIR = 200;

const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");

/** URL arama parametreleri ↔ süzgeç (KPI kutusu ve geri tuşu aynı listeyi açsın). */
function suzgecOku(p: URLSearchParams): EkipmanSuzgeci {
  const bool = (k: string) => (p.get(k) === "true" ? true : p.get(k) === "false" ? false : undefined);
  return {
    q: p.get("q") ?? undefined,
    birim: p.get("birim") ?? undefined,
    tip: p.get("tip") ?? undefined,
    durum: p.get("durum") ?? undefined,
    garanti: p.get("garanti") ?? undefined,
    seri_eksik: bool("seri_eksik"),
    lokasyonsuz: bool("lokasyonsuz"),
    sozlesmesiz: bool("sozlesmesiz"),
    serviste: bool("serviste"),
    pasifler_dahil: bool("pasifler_dahil"),
    kpi: p.get("kpi") ?? undefined,
    kalite: p.get("kalite") ?? undefined,
    hesap_id: p.get("hesap_id") ? Number(p.get("hesap_id")) : undefined,
    sozlesme_id: p.get("sozlesme_id") ? Number(p.get("sozlesme_id")) : undefined,
  };
}

function suzgecYaz(s: EkipmanSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  return p;
}

export default function ServisEkipmanPage() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const git = useNavigate();
  const { id } = useParams();
  const [arama, setArama] = useSearchParams();
  const yazabilir = yetkili("ekipman.yaz");
  const aktarabilir = yetkili("ekipman.gor", "servis_rapor.disaaktar");

  const suzgec = useMemo(() => suzgecOku(arama), [arama]);
  const [sayfa, setSayfa] = useState(1);
  const [secili, setSecili] = useState<number[]>([]);
  const [seciliSatirlar, setSeciliSatirlar] = useState<Record<number, EkipmanSatiri>>({});
  const [formAcik, setFormAcik] = useState(false);
  const [duzenlenen, setDuzenlenen] = useState<Kart | null>(null);
  const [topluDurumAcik, setTopluDurumAcik] = useState(false);
  const [garantiAcik, setGarantiAcik] = useState(false);
  const [onizleme, setOnizleme] = useState<GarantiSonucu | null>(null);
  const [topluForm] = Form.useForm<{ hedef: string; gerekce: string }>();
  const [aramaMetni, setAramaMetni] = useState(suzgec.q ?? "");

  const kartId = id ? Number(id) : null;
  const yolEki = arama.toString() ? `?${arama.toString()}` : "";

  // Veri Kalitesi paneli (TS-188): `?sekme=kalite[&liste=mukerrer|saha]`.
  const kalitePaneli = arama.get("sekme") === "kalite";
  const kaliteListesi = arama.get("liste");

  const suzgecDegistir = (yeni: EkipmanSuzgeci, panel?: { sekme?: string; liste?: string | null }) => {
    const p = suzgecYaz(yeni);
    const sekme = panel ? panel.sekme : arama.get("sekme");
    const liste = panel ? panel.liste : arama.get("liste");
    if (sekme) p.set("sekme", sekme);
    if (sekme && liste) p.set("liste", liste);
    setArama(p);
    setSayfa(1);
    setSecili([]);
  };

  const ozet = useQuery({ queryKey: ["servis-ekipman-ozet"], queryFn: ekipmanApi.ozet });
  const liste = useQuery({
    queryKey: ["servis-ekipman", suzgec, sayfa],
    queryFn: () => ekipmanApi.liste(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["servis-ekipman"] });
    void qc.invalidateQueries({ queryKey: ["servis-ekipman-ozet"] });
  };

  const topluDurum = useMutation({
    mutationFn: (v: { hedef: string; gerekce: string }) =>
      ekipmanApi.topluDurum({ idler: secili, hedef: v.hedef, gerekce: v.gerekce }),
    onSuccess: (r) => {
      message.success(`${r.length} ekipmanın durumu değişti`);
      setTopluDurumAcik(false);
      setSecili([]);
      tazele();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const garanti = useMutation({
    mutationFn: (uygula: boolean) =>
      ekipmanApi.topluGaranti({ idler: secili.length ? secili : null }, uygula),
    onSuccess: (r) => {
      if (r.uygulandi) {
        message.success(`${r.satir_sayisi} kayda garanti yazıldı`);
        setGarantiAcik(false);
        setOnizleme(null);
        tazele();
      } else {
        setOnizleme(r);
      }
    },
    onError: (e: Error) => message.error(e.message),
  });

  const kartAc = (r: EkipmanSatiri) => git(`/servis-ekipman/${r.id}${yolEki}`);
  const kartKapat = () => git(`/servis-ekipman${yolEki}`);

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Row gutter={[12, 12]}>
        {(ozet.data ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={6} xl={3}>
            <KpiKutusu
              kod={k.kod}
              baslik={k.baslik}
              tanim={k.tanim}
              deger={k.deger}
              yol={`/servis-ekipman?kpi=${k.kod}`}
              vurgu={suzgec.kpi === k.kod ? "uyari" : "normal"}
            />
          </Col>
        ))}
      </Row>

      {kalitePaneli && (
        <EkipmanVeriKalitesi
          liste={kaliteListesi}
          onListe={(l) => suzgecDegistir(suzgec, { sekme: "kalite", liste: l })}
          onKalite={(kod) => suzgecDegistir({ kalite: kod }, { sekme: "kalite", liste: null })}
        />
      )}

      <Card
        title="Ekipman Kütüğü"
        extra={
          <Space wrap>
            <Button
              type={kalitePaneli ? "primary" : "default"}
              ghost={kalitePaneli}
              onClick={() =>
                suzgecDegistir(suzgec, kalitePaneli ? { sekme: undefined } : { sekme: "kalite" })
              }
            >
              Veri Kalitesi
            </Button>
            {yazabilir && (
              <Button
                type="primary"
                onClick={() => {
                  setDuzenlenen(null);
                  setFormAcik(true);
                }}
              >
                Yeni ekipman
              </Button>
            )}
            {aktarabilir && (
              <Button onClick={() => window.open(ekipmanApi.excelYolu(suzgec, secili), "_blank")}>
                Excel{secili.length ? ` (${secili.length})` : ""}
              </Button>
            )}
          </Space>
        }
      >
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          <Row gutter={[8, 8]}>
            <Col xs={24} md={8}>
              <Input.Search
                allowClear
                placeholder="Seri, model, müşteri, tesis, bölge…"
                value={aramaMetni}
                onChange={(e) => setAramaMetni(e.target.value)}
                onSearch={(q) => suzgecDegistir({ ...suzgec, q: q.trim() || undefined })}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Birim"
                value={suzgec.birim}
                onChange={(v) => suzgecDegistir({ ...suzgec, birim: v })}
                options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Tip"
                value={suzgec.tip}
                onChange={(v) => suzgecDegistir({ ...suzgec, tip: v })}
                options={EKIPMAN_TIPLERI.map((t) => ({ value: t, label: TIP_ETIKETLERI[t] }))}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Durum"
                value={suzgec.durum}
                onChange={(v) => suzgecDegistir({ ...suzgec, durum: v })}
                options={Object.entries(DURUM_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))}
              />
            </Col>
            <Col xs={12} md={4}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Garanti"
                value={suzgec.garanti}
                onChange={(v) => suzgecDegistir({ ...suzgec, garanti: v })}
                options={Object.entries(GARANTI_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))}
              />
            </Col>
          </Row>
          <Space wrap>
            <Checkbox
              checked={!!suzgec.lokasyonsuz}
              onChange={(e) => suzgecDegistir({ ...suzgec, lokasyonsuz: e.target.checked || undefined })}
            >
              Lokasyonsuz
            </Checkbox>
            <Checkbox
              checked={!!suzgec.sozlesmesiz}
              onChange={(e) => suzgecDegistir({ ...suzgec, sozlesmesiz: e.target.checked || undefined })}
            >
              Sözleşmesiz
            </Checkbox>
            <Checkbox
              checked={!!suzgec.pasifler_dahil}
              onChange={(e) => suzgecDegistir({ ...suzgec, pasifler_dahil: e.target.checked || undefined })}
            >
              Pasifler dahil
            </Checkbox>
            {suzgec.kalite && (
              <Tag closable onClose={() => suzgecDegistir({ ...suzgec, kalite: undefined })} color="gold">
                Kalite: {suzgec.kalite}
              </Tag>
            )}
            {suzgec.kpi && (
              <Tag closable onClose={() => suzgecDegistir({ ...suzgec, kpi: undefined })} color="orange">
                KPI: {ozet.data?.find((k) => k.kod === suzgec.kpi)?.baslik ?? suzgec.kpi}
              </Tag>
            )}
            {Object.values(suzgec).some((v) => v !== undefined) && (
              <Button
                size="small"
                type="link"
                onClick={() => {
                  setAramaMetni("");
                  suzgecDegistir({});
                }}
              >
                Süzgeci temizle
              </Button>
            )}
          </Space>

          {secili.length > 0 && (yazabilir || yetkili("servis.yaz") || yetkili("bakim.yaz")) && (
            <Space wrap>
              <Typography.Text>{secili.length} ekipman seçili</Typography.Text>
              {yazabilir && (
                <Button
                  size="small"
                  disabled={secili.length > TOPLU_UST_SINIR}
                  onClick={() => {
                    topluForm.resetFields();
                    setTopluDurumAcik(true);
                  }}
                >
                  Durum değiştir
                </Button>
              )}
              <EkipmanTopluIslemleri
                secili={secili.map((i) => seciliSatirlar[i]).filter((s): s is EkipmanSatiri => !!s)}
                onBitti={() => {
                  setSecili([]);
                  tazele();
                }}
              />
              <Button size="small" onClick={() => setSecili([])}>
                Seçimi kaldır
              </Button>
            </Space>
          )}
          {yazabilir && (
            <Button
              size="small"
              onClick={() => {
                setOnizleme(null);
                setGarantiAcik(true);
                garanti.mutate(false);
              }}
            >
              Garanti hesapla{secili.length ? ` (${secili.length} seçili)` : ""}
            </Button>
          )}

          <Table<EkipmanSatiri>
            rowKey="id"
            size="small"
            scroll={{ x: 900 }}
            loading={liste.isLoading}
            dataSource={liste.data?.kayitlar ?? []}
            locale={{ emptyText: <Empty description="Bu süzgeçte ekipman yok" /> }}
            rowSelection={
              yazabilir || aktarabilir || yetkili("servis.yaz") || yetkili("bakim.yaz")
                ? {
                    selectedRowKeys: secili,
                    onChange: (k, satirlar) => {
                      setSecili(k as number[]);
                      // Sayfa değişse de seçili satırların verisi (müşteri, tür) elde kalsın.
                      setSeciliSatirlar((eski) => {
                        const yeni = { ...eski };
                        for (const s of satirlar) if (s) yeni[s.id] = s;
                        return yeni;
                      });
                    },
                    preserveSelectedRowKeys: true,
                  }
                : undefined
            }
            pagination={{
              current: sayfa,
              pageSize: SAYFA_BOYU,
              total: liste.data?.toplam ?? 0,
              showSizeChanger: false,
              onChange: setSayfa,
              showTotal: (t) => `${t.toLocaleString("tr-TR")} ekipman`,
            }}
            onRow={(r) => ({ onClick: () => kartAc(r), style: { cursor: "pointer" } })}
            columns={[
              {
                title: "Tip",
                dataIndex: "equipment_type",
                width: 130,
                render: (t: string) => TIP_ETIKETLERI[t] ?? t,
              },
              {
                title: "Seri no",
                dataIndex: "serial_no",
                width: 140,
                render: (s: string | null) =>
                  s ? <span className="mono">{s}</span> : <Tag color="gold">eksik</Tag>,
              },
              {
                title: "Marka / model",
                key: "mm",
                ellipsis: true,
                render: (_, r) => [r.brand, r.model].filter(Boolean).join(" ") || "—",
              },
              { title: "Müşteri", dataIndex: "hesap_unvan", ellipsis: true, render: (v) => v ?? "—" },
              {
                title: "Lokasyon",
                key: "lok",
                ellipsis: true,
                render: (_, r) => [r.lokasyon_adi, r.il].filter(Boolean).join(" · ") || "—",
              },
              {
                title: "Durum",
                key: "durum",
                width: 170,
                render: (_, r) => (
                  <Space size={4} wrap>
                    <Tag color={DURUM_RENKLERI[r.lifecycle_status]}>
                      {DURUM_ETIKETLERI[r.lifecycle_status] ?? r.lifecycle_status}
                    </Tag>
                    {r.serviste && <Tag color="volcano">Serviste</Tag>}
                    {!r.is_active && <Tag>Pasif</Tag>}
                  </Space>
                ),
              },
              {
                title: "Garanti",
                key: "garanti",
                width: 150,
                render: (_, r) => (
                  <Space size={4} orientation="vertical">
                    <GarantiEtiketi durum={r.garanti_durumu} />
                    {r.warranty_end && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {tarih(r.warranty_end)}
                      </Typography.Text>
                    )}
                  </Space>
                ),
              },
              {
                title: "Sözleşme",
                dataIndex: "sozlesme_sayisi",
                width: 90,
                align: "center",
                render: (n: number) => (n ? <Tag color="blue">{n}</Tag> : "—"),
              },
            ]}
          />
        </Space>
      </Card>

      <EkipmanKarti
        ekipmanId={kartId}
        onKapat={kartKapat}
        onDuzenle={(k) => {
          setDuzenlenen(k);
          setFormAcik(true);
        }}
        onDegisti={tazele}
      />

      <EkipmanFormu
        acik={formAcik}
        kayit={duzenlenen}
        onKapat={() => setFormAcik(false)}
        onKaydedildi={(k) => {
          setFormAcik(false);
          tazele();
          void qc.invalidateQueries({ queryKey: ["servis-ekipman-kart", k.id] });
          void qc.invalidateQueries({ queryKey: ["servis-ekipman-degisiklik", k.id] });
          if (!duzenlenen) git(`/servis-ekipman/${k.id}${yolEki}`);
        }}
      />

      <Modal
        title={`Toplu durum değişikliği (${secili.length} ekipman)`}
        open={topluDurumAcik}
        onCancel={() => setTopluDurumAcik(false)}
        onOk={() => topluForm.submit()}
        okText="Uygula"
        cancelText="Vazgeç"
        confirmLoading={topluDurum.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Seçilenlerden biri bu duruma geçemiyorsa hiçbiri değişmez ve liste gösterilir.
        </Typography.Paragraph>
        <Form form={topluForm} layout="vertical" onFinish={(v) => topluDurum.mutate(v)}>
          <Form.Item name="hedef" label="Yeni durum" rules={[{ required: true }]}>
            <Select options={Object.entries(DURUM_ETIKETLERI).map(([k, v]) => ({ value: k, label: v }))} />
          </Form.Item>
          <Form.Item name="gerekce" label="Gerekçe" rules={[{ required: true, whitespace: true, min: 5 }]}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Toplu garanti hesaplama"
        open={garantiAcik}
        onCancel={() => setGarantiAcik(false)}
        onOk={() => garanti.mutate(true)}
        okText="Uygula"
        okButtonProps={{ disabled: !onizleme || onizleme.satir_sayisi === 0 }}
        cancelText="Vazgeç"
        confirmLoading={garanti.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Yalnız garanti bitişi boş kayıtlar: başlangıç = kurulum (yoksa teslim) tarihi, süre = ürün
          kartındaki garanti ayı (ürün yoksa varsayılan ayar). Kaynak "Hesaplandı" yazılır; belgeli
          kayıtlara dokunulmaz.
        </Typography.Paragraph>
        {onizleme && (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text>
              <strong>{onizleme.satir_sayisi}</strong> kayda garanti yazılacak;{" "}
              {onizleme.baslangic_tarihsiz} kayıtta kurulum/teslim tarihi olmadığı için hesaplanamaz.
            </Typography.Text>
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              scroll={{ y: 240 }}
              dataSource={onizleme.ornekler}
              columns={[
                { title: "#", dataIndex: "id", width: 70 },
                { title: "Seri", dataIndex: "seri", render: (s) => s ?? "—" },
                { title: "Başlangıç", dataIndex: "baslangic", render: tarih },
                { title: "Bitiş", dataIndex: "bitis", render: tarih },
                { title: "Ay", dataIndex: "ay", width: 50 },
              ]}
            />
          </Space>
        )}
      </Modal>
    </Space>
  );
}
