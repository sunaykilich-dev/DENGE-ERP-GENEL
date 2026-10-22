/**
 * Kiralamalar — liste, KPI, kiralama kartı ve aşama işlemleri (TS-110…120, TS-122).
 *
 * - KPI kutuları `/api/kiralama/ozet`ten gelir; kutudaki sayı tıklanınca açılan
 *   `?kpi=<kod>` listesinin `X-Toplam-Kayit`'ıyla aynı sorgudur (sayı = liste).
 * - `/kiralamalar/:id` kartı doğrudan açar (görev/uyarı bağlantıları buraya gelir).
 * - Durum YALNIZ işlem düğmeleriyle değişir (planla, tahsis, sevk, aşama, iade,
 *   iptal, kapat); düzenleme formu durum/birim göndermez.
 * - Fiyat/maliyet alanı yoktur (kiralama bedeli ERP'de tutulmaz).
 * - Müşteri seçimi ortak `MusteriLokasyonSecici` ile; kalemler yalnız birimin
 *   aktif kiralama kataloğundan seçilir; depo seçicileri yalnız
 *   `kiralama_deposu=true` depoları listeler (`/api/kiralama/depolar`).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  ASAMA_HEDEFLERI,
  IADE_SONUC_ADLARI,
  IRTIBAT_ROL_ADLARI,
  KIRALAMA_DISI_BIRIMLER,
  KIRALAMA_DURUM_ADLARI,
  KIRALAMA_DURUM_RENKLERI,
  kiralamaApi,
  type KiralamaKarti,
  type KiralamaSatiri,
  type KiralamaSuzgeci,
  type Musaitlik,
  OLAY_ADLARI,
  SERVIS_ISI_TURLERI,
  type TahsisOut,
} from "../api/kiralama";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { useAuth } from "../auth/AuthContext";
import KiralamaDegisimPenceresi from "../components/KiralamaDegisimPenceresi";
import KpiKutusu from "../components/KpiKutusu";
import MusteriLokasyonSecici, { type MusteriLokasyonSecimi } from "../components/MusteriLokasyonSecici";

const SAYFA_BOYU = 50;
const KIRALAMA_BIRIMLERI = BIRIM_KODLARI.filter((b) => !KIRALAMA_DISI_BIRIMLER.includes(b));
const KAPALI = ["KAPANDI", "IPTAL"];
const SEVK_SONRASI = ["SEVK_EDILDI", "KURULUM_YAPILDI", "DEVREYE_ALINDI", "TOPLANDI"];
/** Sahada değişim bu durumlarda (sunucu `DEGISIM_DURUMLARI`). */
const DEGISIM_DURUMLARI = ["SEVK_EDILDI", "KURULUM_YAPILDI", "DEVREYE_ALINDI"];

const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");
const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");
const hataMesaji = (e: unknown) => (e as Error).message;

function suzgecOku(p: URLSearchParams): KiralamaSuzgeci {
  return {
    q: p.get("q") ?? undefined,
    durum: p.get("durum") ?? undefined,
    birim: p.get("birim") ?? undefined,
    musteri: p.get("musteri") ? Number(p.get("musteri")) : undefined,
    kpi: p.get("kpi") ?? undefined,
  };
}

function suzgecYaz(s: KiralamaSuzgeci): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null || v === "") continue;
    p.set(k, String(v));
  }
  return p;
}

export function KiralamaDurumu({ durum }: { durum: string }) {
  return <Tag color={KIRALAMA_DURUM_RENKLERI[durum]}>{KIRALAMA_DURUM_ADLARI[durum] ?? durum}</Tag>;
}

// --- Liste --------------------------------------------------------------------------

export default function KiralamalarPage() {
  const { yetkili } = useAuth();
  const git = useNavigate();
  const qc = useQueryClient();
  const { id } = useParams();
  const [arama, setArama] = useSearchParams();
  const suzgec = useMemo(() => suzgecOku(arama), [arama]);
  const [sayfa, setSayfa] = useState(1);
  const [aramaMetni, setAramaMetni] = useState(suzgec.q ?? "");
  const [formAcik, setFormAcik] = useState(false);
  const [duzenlenen, setDuzenlenen] = useState<KiralamaKarti | null>(null);

  const yazabilir = yetkili("kiralama.yaz");
  const aktarabilir = yetkili("kiralama.gor", "servis_rapor.disaaktar");
  const yolEki = arama.toString() ? `?${arama.toString()}` : "";

  const suzgecDegistir = (yeni: KiralamaSuzgeci) => {
    setArama(suzgecYaz(yeni));
    setSayfa(1);
  };

  const ozet = useQuery({ queryKey: ["kiralama-ozet"], queryFn: kiralamaApi.ozet });
  const liste = useQuery({
    queryKey: ["kiralama", suzgec, sayfa],
    queryFn: () => kiralamaApi.liste(suzgec, SAYFA_BOYU, (sayfa - 1) * SAYFA_BOYU),
  });

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["kiralama"] });
    void qc.invalidateQueries({ queryKey: ["kiralama-ozet"] });
    void qc.invalidateQueries({ queryKey: ["kiralama-kart"] });
    void qc.invalidateQueries({ queryKey: ["kiralama-gecmis"] });
  };

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Row gutter={[12, 12]}>
        {(ozet.data ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={4}>
            <KpiKutusu
              kod={k.kod}
              baslik={k.baslik}
              tanim={k.tanim}
              deger={k.deger}
              yol={`/kiralamalar?kpi=${k.kod}`}
              vurgu={
                suzgec.kpi === k.kod
                  ? "uyari"
                  : (k.kod === "geciken" || k.kod === "eksik_tahsis") && k.deger > 0
                    ? "kritik"
                    : "normal"
              }
            />
          </Col>
        ))}
      </Row>

      <Card
        title="Kiralamalar"
        extra={
          <Space wrap>
            {yazabilir && (
              <Button
                type="primary"
                onClick={() => {
                  setDuzenlenen(null);
                  setFormAcik(true);
                }}
              >
                Yeni kiralama
              </Button>
            )}
            {aktarabilir && (
              <Button onClick={() => window.open(kiralamaApi.excelYolu(suzgec), "_blank")}>Excel</Button>
            )}
          </Space>
        }
      >
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          <Row gutter={[8, 8]}>
            <Col xs={24} md={10}>
              <Input.Search
                allowClear
                placeholder="Kiralama no, müşteri, proje, yer…"
                value={aramaMetni}
                onChange={(e) => setAramaMetni(e.target.value)}
                onSearch={(q) => suzgecDegistir({ ...suzgec, q: q.trim() || undefined })}
              />
            </Col>
            <Col xs={12} md={5}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Durum"
                value={suzgec.durum}
                onChange={(v) => suzgecDegistir({ ...suzgec, durum: v })}
                options={Object.entries(KIRALAMA_DURUM_ADLARI).map(([k, v]) => ({ value: k, label: v }))}
              />
            </Col>
            <Col xs={12} md={5}>
              <Select
                allowClear
                style={{ width: "100%" }}
                placeholder="Birim"
                value={suzgec.birim}
                onChange={(v) => suzgecDegistir({ ...suzgec, birim: v })}
                options={KIRALAMA_BIRIMLERI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
              />
            </Col>
          </Row>
          <Space wrap>
            {suzgec.kpi && (
              <Tag closable color="orange" onClose={() => suzgecDegistir({ ...suzgec, kpi: undefined })}>
                KPI: {ozet.data?.find((k) => k.kod === suzgec.kpi)?.baslik ?? suzgec.kpi}
              </Tag>
            )}
            {suzgec.musteri && (
              <Tag closable onClose={() => suzgecDegistir({ ...suzgec, musteri: undefined })}>
                Müşteri #{suzgec.musteri}
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

          <Table<KiralamaSatiri>
            rowKey="id"
            size="small"
            scroll={{ x: 1000 }}
            loading={liste.isLoading}
            dataSource={liste.data?.kayitlar ?? []}
            locale={{ emptyText: <Empty description="Bu süzgeçte kiralama yok" /> }}
            pagination={{
              current: sayfa,
              pageSize: SAYFA_BOYU,
              total: liste.data?.toplam ?? 0,
              showSizeChanger: false,
              onChange: setSayfa,
              showTotal: (t) => `${t.toLocaleString("tr-TR")} kiralama`,
            }}
            onRow={(r) => ({
              onClick: () => git(`/kiralamalar/${r.id}${yolEki}`),
              style: { cursor: "pointer" },
            })}
            columns={[
              { title: "No", dataIndex: "rental_no", width: 120, render: (v) => <span className="mono">{v}</span> },
              { title: "Birim", dataIndex: "birim", width: 110, render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
              { title: "Müşteri", dataIndex: "musteri", ellipsis: true, render: (v) => v ?? "—" },
              {
                title: "Proje / yer",
                key: "proje",
                ellipsis: true,
                render: (_, r) => [r.proje_adi, r.lokasyon_metni].filter(Boolean).join(" · ") || "—",
              },
              {
                title: "Tarih",
                key: "tarih",
                width: 190,
                render: (_, r) => (
                  <Space size={4}>
                    <span>
                      {tarih(r.baslangic)} – {tarih(r.bitis)}
                    </span>
                    {r.geciken && <Tag color="red">Gecikti</Tag>}
                  </Space>
                ),
              },
              {
                title: "Kalemler",
                key: "kalem",
                ellipsis: true,
                render: (_, r) => r.kalem_ozeti.join(", ") || "—",
              },
              {
                title: "Tahsis",
                key: "tahsis",
                width: 90,
                align: "center",
                render: (_, r) => (
                  <Typography.Text type={r.tahsis_adet < r.kalem_adet ? "warning" : undefined}>
                    {r.tahsis_adet}/{r.kalem_adet}
                  </Typography.Text>
                ),
              },
              {
                title: "Durum",
                key: "durum",
                width: 170,
                render: (_, r) => (
                  <Space size={4} wrap>
                    <KiralamaDurumu durum={r.status} />
                    {r.iade_gosterimi === "KISMI" && <Tag color="gold">Kısmi iade</Tag>}
                  </Space>
                ),
              },
            ]}
          />
        </Space>
      </Card>

      {id && (
        <KiralamaCekmecesi
          kiralamaId={Number(id)}
          onKapat={() => git(`/kiralamalar${yolEki}`)}
          onDegisti={tazele}
          onDuzenle={(k) => {
            setDuzenlenen(k);
            setFormAcik(true);
          }}
        />
      )}

      {formAcik && (
        <KiralamaFormu
          kayit={duzenlenen}
          onKapat={() => setFormAcik(false)}
          onKaydedildi={(k) => {
            setFormAcik(false);
            tazele();
            if (!duzenlenen) git(`/kiralamalar/${k.id}${yolEki}`);
          }}
        />
      )}
    </Space>
  );
}

// --- Form (oluşturma / düzenleme) -----------------------------------------------------

interface FormDegerleri {
  birim: string;
  musteri: MusteriLokasyonSecimi;
  proje_adi?: string;
  lokasyon_metni?: string;
  tarihler: [Dayjs, Dayjs];
  notes?: string;
  kalemler: { id?: number; product_id: number; qty: number; note?: string }[];
  irtibatlar: { id?: number; contact_id: number; rol: string }[];
}

function MusaitlikEtiketi({
  productId,
  tarihler,
  haric,
}: {
  productId?: number;
  tarihler?: [Dayjs, Dayjs];
  haric?: number;
}) {
  const bas = tarihler?.[0]?.format("YYYY-MM-DD");
  const bit = tarihler?.[1]?.format("YYYY-MM-DD");
  const m = useQuery({
    queryKey: ["kiralama-musaitlik", productId, bas, bit, haric],
    queryFn: () => kiralamaApi.musaitlik(productId!, bas!, bit!, haric),
    enabled: !!productId && !!bas && !!bit && bit > bas,
    retry: false,
  });
  if (!productId || !m.data) return null;
  const d: Musaitlik = m.data;
  return (
    <Typography.Text type={d.musait > 0 ? "secondary" : "danger"} style={{ fontSize: 12 }}>
      Müsait {d.musait} / {d.toplam} (rezerve {d.rezerve}
      {d.kontrolde ? `, kontrolde ${d.kontrolde}` : ""})
    </Typography.Text>
  );
}

function KiralamaFormu({
  kayit,
  onKapat,
  onKaydedildi,
}: {
  kayit: KiralamaKarti | null;
  onKapat: () => void;
  onKaydedildi: (k: KiralamaKarti) => void;
}) {
  const { message } = App.useApp();
  const { kullanici } = useAuth();
  const [form] = Form.useForm<FormDegerleri>();
  const birim = Form.useWatch("birim", form);
  const musteri = Form.useWatch("musteri", form);
  const tarihler = Form.useWatch("tarihler", form);
  const kalemler = Form.useWatch("kalemler", form);
  const kalemDegisebilir = !kayit || !SEVK_SONRASI.includes(kayit.status);

  const katalog = useQuery({
    queryKey: ["kiralama-katalog", birim],
    queryFn: () => kiralamaApi.katalog(birim, true),
    enabled: !!birim,
  });
  const irtibatlar = useQuery({
    queryKey: ["kiralama-musteri-irtibat", musteri?.musteriId],
    queryFn: () => kiralamaApi.musteriIrtibatlari(musteri!.musteriId!),
    enabled: !!musteri?.musteriId,
  });

  useEffect(() => {
    if (kayit) {
      form.setFieldsValue({
        birim: kayit.birim,
        musteri: { musteriId: kayit.customer_id, musteriAdi: kayit.musteri, lokasyonId: kayit.address_id },
        proje_adi: kayit.proje_adi ?? undefined,
        lokasyon_metni: kayit.lokasyon_metni ?? undefined,
        tarihler: [dayjs(kayit.baslangic), dayjs(kayit.bitis)],
        notes: kayit.notes ?? undefined,
        kalemler: kayit.kalemler.map((k) => ({ id: k.id, product_id: k.product_id, qty: k.qty, note: k.note ?? undefined })),
        irtibatlar: (kayit.irtibatlar ?? []).map((i) => ({ id: i.id, contact_id: i.contact_id, rol: i.rol })),
      });
    } else {
      const varsayilan = kullanici?.birincil_birim;
      form.setFieldsValue({
        birim: varsayilan && KIRALAMA_BIRIMLERI.includes(varsayilan) ? varsayilan : undefined,
        kalemler: [],
        irtibatlar: [],
      });
    }
  }, [kayit, form, kullanici]);

  const kaydet = useMutation({
    mutationFn: async (v: FormDegerleri) => {
      const ortak = {
        customer_id: v.musteri?.musteriId ?? null,
        address_id: v.musteri?.lokasyonId ?? null,
        proje_adi: v.proje_adi?.trim() || null,
        lokasyon_metni: v.lokasyon_metni?.trim() || null,
        baslangic: v.tarihler[0].format("YYYY-MM-DD"),
        bitis: v.tarihler[1].format("YYYY-MM-DD"),
        notes: v.notes?.trim() || null,
        irtibatlar: (v.irtibatlar ?? []).map((i) => ({ id: i.id ?? null, contact_id: i.contact_id, rol: i.rol })),
      };
      const kalemGirdisi = (v.kalemler ?? []).map((k) => ({
        id: k.id ?? null,
        product_id: k.product_id,
        qty: k.qty,
        note: k.note?.trim() || null,
      }));
      if (kayit) {
        return kiralamaApi.guncelle(kayit.id, {
          version: kayit.version,
          ...ortak,
          ...(kalemDegisebilir ? { kalemler: kalemGirdisi } : {}),
        });
      }
      return kiralamaApi.olustur({ birim: v.birim, ...ortak, kalemler: kalemGirdisi });
    },
    onSuccess: (k) => {
      message.success(kayit ? "Kiralama güncellendi" : `${k.rental_no} açıldı`);
      onKaydedildi(k);
    },
    onError: (e) => message.error(hataMesaji(e)),
  });

  const urunSecenekleri = (katalog.data ?? []).map((p) => ({
    value: p.product_id,
    label: `${p.urun_kodu ?? ""} — ${p.urun_adi ?? ""}${p.seri_takipli ? " (seri)" : ""}`,
  }));

  return (
    <Modal
      open
      width={820}
      title={kayit ? `${kayit.rental_no} düzenle` : "Yeni kiralama"}
      onCancel={onKapat}
      onOk={() => form.submit()}
      okText="Kaydet"
      cancelText="Vazgeç"
      confirmLoading={kaydet.isPending}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={(v) => kaydet.mutate(v)}>
        <Row gutter={12}>
          <Col xs={24} md={8}>
            <Form.Item name="birim" label="Birim" rules={[{ required: true, message: "Birim seçin" }]}>
              <Select
                disabled={!!kayit}
                options={KIRALAMA_BIRIMLERI.filter((b) => !kullanici?.birimler?.length || kullanici.birimler.includes(b)).map(
                  (b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }),
                )}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={16}>
            <Form.Item
              name="tarihler"
              label="Başlangıç – iade (bitiş) tarihi"
              rules={[{ required: true, message: "Tarih aralığı seçin" }]}
            >
              <DatePicker.RangePicker format="DD.MM.YYYY" style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="musteri"
          label="Müşteri / lokasyon"
          rules={[
            {
              validator: (_, v?: MusteriLokasyonSecimi) =>
                v?.musteriId ? Promise.resolve() : Promise.reject(new Error("Müşteri seçin")),
            },
          ]}
        >
          <MusteriLokasyonSecici />
        </Form.Item>
        <Row gutter={12}>
          <Col xs={24} md={12}>
            <Form.Item name="proje_adi" label="Proje / etkinlik">
              <Input maxLength={200} />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item name="lokasyon_metni" label="Yer (serbest metin)">
              <Input maxLength={300} placeholder="Ör. Fuar alanı Hol 3" />
            </Form.Item>
          </Col>
        </Row>

        <Typography.Title level={5}>Kalemler</Typography.Title>
        {!kalemDegisebilir && (
          <Alert type="info" showIcon style={{ marginBottom: 8 }} message="Sevk edilmiş kiralamanın kalemleri bu formdan değişmez." />
        )}
        <Form.List name="kalemler">
          {(alanlar, { add, remove }) => (
            <>
              {alanlar.map((a) => (
                <Row key={a.key} gutter={8} align="top">
                  <Col xs={24} md={11}>
                    <Form.Item name={[a.name, "product_id"]} rules={[{ required: true, message: "Ürün seçin" }]}>
                      <Select
                        showSearch
                        optionFilterProp="label"
                        placeholder={birim ? "Katalogdan ürün" : "Önce birim seçin"}
                        disabled={!birim || !kalemDegisebilir}
                        options={urunSecenekleri}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={8} md={3}>
                    <Form.Item name={[a.name, "qty"]} rules={[{ required: true, message: "Adet" }]}>
                      <InputNumber min={1} precision={0} style={{ width: "100%" }} disabled={!kalemDegisebilir} />
                    </Form.Item>
                  </Col>
                  <Col xs={16} md={6}>
                    <Form.Item name={[a.name, "note"]}>
                      <Input maxLength={300} placeholder="Not" disabled={!kalemDegisebilir} />
                    </Form.Item>
                  </Col>
                  <Col xs={20} md={3} style={{ paddingTop: 4 }}>
                    <MusaitlikEtiketi
                      productId={kalemler?.[a.name]?.product_id}
                      tarihler={tarihler}
                      haric={kayit?.id}
                    />
                  </Col>
                  <Col xs={4} md={1}>
                    {kalemDegisebilir && (
                      <Button type="text" danger onClick={() => remove(a.name)} aria-label="Kalemi sil">
                        ✕
                      </Button>
                    )}
                  </Col>
                </Row>
              ))}
              {kalemDegisebilir && (
                <Button type="dashed" onClick={() => add({ qty: 1 })} disabled={!birim} block style={{ marginBottom: 16 }}>
                  Kalem ekle
                </Button>
              )}
            </>
          )}
        </Form.List>

        <Typography.Title level={5}>İrtibat kişileri</Typography.Title>
        <Form.List name="irtibatlar">
          {(alanlar, { add, remove }) => (
            <>
              {alanlar.map((a) => (
                <Row key={a.key} gutter={8}>
                  <Col xs={14} md={14}>
                    <Form.Item name={[a.name, "contact_id"]} rules={[{ required: true, message: "Kişi seçin" }]}>
                      <Select
                        showSearch
                        optionFilterProp="label"
                        placeholder="Müşterinin irtibat kişisi"
                        options={(irtibatlar.data ?? []).map((c) => ({
                          value: c.id,
                          label: c.unvan ? `${c.ad} (${c.unvan})` : c.ad,
                        }))}
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={8} md={8}>
                    <Form.Item name={[a.name, "rol"]} rules={[{ required: true, message: "Rol" }]}>
                      <Select options={Object.entries(IRTIBAT_ROL_ADLARI).map(([k, v]) => ({ value: k, label: v }))} />
                    </Form.Item>
                  </Col>
                  <Col xs={2} md={2}>
                    <Button type="text" danger onClick={() => remove(a.name)} aria-label="İrtibatı sil">
                      ✕
                    </Button>
                  </Col>
                </Row>
              ))}
              <Button
                type="dashed"
                onClick={() => add({ rol: "SAHA_OPERASYON" })}
                disabled={!musteri?.musteriId}
                block
                style={{ marginBottom: 16 }}
              >
                İrtibat ekle
              </Button>
            </>
          )}
        </Form.List>

        <Form.Item name="notes" label="Not">
          <Input.TextArea rows={2} maxLength={4000} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// --- Kart (çekmece) -------------------------------------------------------------------

function KiralamaCekmecesi({
  kiralamaId,
  onKapat,
  onDegisti,
  onDuzenle,
}: {
  kiralamaId: number;
  onKapat: () => void;
  onDegisti: () => void;
  onDuzenle: (k: KiralamaKarti) => void;
}) {
  const { yetkili } = useAuth();
  const { message, modal } = App.useApp();
  const kart = useQuery({
    queryKey: ["kiralama-kart", kiralamaId],
    queryFn: () => kiralamaApi.getir(kiralamaId),
    retry: false,
  });
  const gecmis = useQuery({
    queryKey: ["kiralama-gecmis", kiralamaId],
    queryFn: () => kiralamaApi.gecmis(kiralamaId),
    enabled: kart.isSuccess,
  });
  const [islem, setIslem] = useState<null | "tahsis" | "sevk" | "iade" | "asama" | "geri" | "iptal" | "degisim">(
    null,
  );

  const yaz = yetkili("kiralama.yaz");
  const envanter = yetkili("kiralama.envanter");
  const asamaci = yetkili("kiralama.asama");
  const isAcar = yetkili("kiralama.yaz", "servis.yaz");

  const basit = useMutation({
    mutationFn: (f: () => Promise<unknown>) => f(),
    onSuccess: () => {
      message.success("Kaydedildi");
      onDegisti();
    },
    onError: (e) => message.error(hataMesaji(e)),
  });

  const k = kart.data;
  const kapali = k ? KAPALI.includes(k.status) : true;
  const aktifTahsisler = (k?.tahsisler ?? []).filter((t) => t.durum === "AKTIF");
  const musteride = aktifTahsisler.reduce((s, t) => s + t.musteride, 0);

  const butonlar = !k ? null : (
    <Space wrap>
      {yaz && !kapali && (
        <Button onClick={() => onDuzenle(k)} disabled={k.status === "DEPOYA_ALINDI"}>
          Düzenle
        </Button>
      )}
      {yaz && k.status === "TALEP" && (
        <Button type="primary" loading={basit.isPending} onClick={() => basit.mutate(() => kiralamaApi.planla(k.id))}>
          Planla
        </Button>
      )}
      {envanter && !kapali && k.status !== "TALEP" && k.status !== "DEPOYA_ALINDI" && (
        <Button onClick={() => setIslem("tahsis")}>Tahsis</Button>
      )}
      {asamaci && (k.status === "HAZIRLANIYOR" || SEVK_SONRASI.includes(k.status)) && (
        <Button type={k.status === "HAZIRLANIYOR" ? "primary" : "default"} onClick={() => setIslem("sevk")}>
          {k.status === "HAZIRLANIYOR" ? "Sevk et" : "Ek sevk"}
        </Button>
      )}
      {asamaci && k.sonraki_durumlar.some((d) => (ASAMA_HEDEFLERI as readonly string[]).includes(d)) && (
        <Button onClick={() => setIslem("asama")}>Aşama gir</Button>
      )}
      {asamaci && SEVK_SONRASI.includes(k.status) && musteride > 0 && (
        <Button onClick={() => setIslem("iade")}>İade al</Button>
      )}
      {asamaci &&
        DEGISIM_DURUMLARI.includes(k.status) &&
        aktifTahsisler.some((t) => t.kiralik_id && t.musteride > 0) && (
          <Button onClick={() => setIslem("degisim")}>Sahada değişim</Button>
        )}
      {yaz && k.status === "DEPOYA_ALINDI" && (
        <Button
          type="primary"
          loading={basit.isPending}
          onClick={() =>
            modal.confirm({
              title: "Kiralama kapatılsın mı?",
              content: "Kapanan kiralama geri açılamaz.",
              okText: "Kapat",
              cancelText: "Vazgeç",
              onOk: () => basit.mutateAsync(() => kiralamaApi.kapat(k.id)),
            })
          }
        >
          Kapat
        </Button>
      )}
      {asamaci && k.geri_alinabilir_olay_id && <Button onClick={() => setIslem("geri")}>Son aşamayı geri al</Button>}
      {yaz && ["TALEP", "PLANLANDI", "HAZIRLANIYOR"].includes(k.status) && (
        <Button danger onClick={() => setIslem("iptal")}>
          İptal et
        </Button>
      )}
      <Button onClick={() => window.open(kiralamaApi.tutanakYolu(k.id, "TESLIM"), "_blank")}>Teslim tutanağı</Button>
      {SEVK_SONRASI.concat(["DEPOYA_ALINDI", "KAPANDI"]).includes(k.status) && (
        <Button onClick={() => window.open(kiralamaApi.tutanakYolu(k.id, "IADE"), "_blank")}>İade tutanağı</Button>
      )}
    </Space>
  );

  return (
    <Drawer open onClose={onKapat} width={Math.min(1100, window.innerWidth)} title={k ? `Kiralama ${k.rental_no}` : "Kiralama"}>
      {kart.isError && <Alert type="error" showIcon message={hataMesaji(kart.error)} />}
      {k && (
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Space wrap>
            <KiralamaDurumu durum={k.status} />
            {k.geciken && <Tag color="red">İade gecikti</Tag>}
            {k.onerilen_asama && (
              <Tag color="cyan">Önerilen aşama: {KIRALAMA_DURUM_ADLARI[k.onerilen_asama] ?? k.onerilen_asama}</Tag>
            )}
          </Space>
          {butonlar}
          <Descriptions size="small" bordered column={{ xs: 1, md: 2 }}>
            <Descriptions.Item label="Birim">{BIRIM_ETIKETLERI[k.birim] ?? k.birim}</Descriptions.Item>
            <Descriptions.Item label="Müşteri">{k.musteri ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Tarih">
              {tarih(k.baslangic)} – {tarih(k.bitis)}
            </Descriptions.Item>
            <Descriptions.Item label="Lokasyon">
              {[k.lokasyon, k.lokasyon_metni].filter(Boolean).join(" · ") || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="Proje">{k.proje_adi ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Sorumlu">{k.sorumlu_adi ?? "—"}</Descriptions.Item>
            {k.iptal_gerekcesi && (
              <Descriptions.Item label="İptal gerekçesi" span={2}>
                {k.iptal_gerekcesi}
              </Descriptions.Item>
            )}
            {k.notes && (
              <Descriptions.Item label="Not" span={2}>
                {k.notes}
              </Descriptions.Item>
            )}
          </Descriptions>

          <Tabs
            items={[
              {
                key: "kalem",
                label: "Kalemler ve tahsis",
                children: (
                  <KalemTahsisTablosu
                    k={k}
                    cozebilir={envanter}
                    onCoz={(t) =>
                      modal.confirm({
                        title: "Tahsis çözülsün mü?",
                        content: `${t.urun_kodu ?? ""} ${t.seri ?? `${t.qty} adet`} serbest bırakılır.`,
                        okText: "Çöz",
                        cancelText: "Vazgeç",
                        onOk: () => basit.mutateAsync(() => kiralamaApi.tahsisCoz(k.id, t.id)),
                      })
                    }
                  />
                ),
              },
              {
                key: "irtibat",
                label: "İrtibat",
                children:
                  k.irtibatlar == null ? (
                    <Typography.Text type="secondary">İrtibat bilgisini görme yetkiniz yok.</Typography.Text>
                  ) : (
                    <Table
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={k.irtibatlar}
                      locale={{ emptyText: "İrtibat eklenmemiş" }}
                      columns={[
                        { title: "Kişi", dataIndex: "ad" },
                        { title: "Unvan", dataIndex: "unvan", render: (v) => v ?? "—" },
                        { title: "Rol", dataIndex: "rol", render: (r: string) => IRTIBAT_ROL_ADLARI[r] ?? r },
                      ]}
                    />
                  ),
              },
              {
                key: "servis",
                label: `Servis işleri (${k.servis_isleri.length})`,
                children: (
                  <Space orientation="vertical" style={{ width: "100%" }}>
                    {isAcar && !kapali && (
                      <Space wrap>
                        {Object.entries(SERVIS_ISI_TURLERI).map(([tur, ad]) => (
                          <Button
                            key={tur}
                            size="small"
                            disabled={k.servis_isleri.some((s) => s.tur === tur && !["TAMAMLANDI", "IPTAL", "KAPANDI"].includes(s.status))}
                            onClick={() => basit.mutate(() => kiralamaApi.servisIsi(k.id, tur))}
                          >
                            {ad} işi aç
                          </Button>
                        ))}
                      </Space>
                    )}
                    <Table
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={k.servis_isleri}
                      locale={{ emptyText: "Bağlı servis işi yok" }}
                      columns={[
                        {
                          title: "İş no",
                          dataIndex: "so_no",
                          render: (v: string, r) => <Link to={`/servis-isleri/${r.id}`}>{v}</Link>,
                        },
                        { title: "Tür", dataIndex: "tur", render: (t: string) => SERVIS_ISI_TURLERI[t] ?? t },
                        { title: "Durum", dataIndex: "status" },
                      ]}
                    />
                  </Space>
                ),
              },
              {
                key: "gecmis",
                label: "Geçmiş",
                children: (
                  <Timeline
                    items={(gecmis.data ?? []).map((o) => ({
                      color: o.geri_alindi ? "gray" : o.tur === "DUZELTME" ? "red" : "blue",
                      children: (
                        <Space orientation="vertical" size={0}>
                          <Typography.Text delete={o.geri_alindi}>
                            <strong>{OLAY_ADLARI[o.tur] ?? o.tur}</strong>
                            {o.yeni_durum && ` → ${KIRALAMA_DURUM_ADLARI[o.yeni_durum] ?? o.yeni_durum}`}
                            {o.alan === "asama_onerisi" && o.yeni && ` — öneri: ${String(o.yeni.oneri ?? "")} (${String(o.yeni.so_no ?? "")})`}
                          </Typography.Text>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {zaman(o.at)} · {o.kullanici ?? "sistem"}
                            {o.gerekce ? ` · ${o.gerekce}` : ""}
                          </Typography.Text>
                        </Space>
                      ),
                    }))}
                  />
                ),
              },
            ]}
          />
        </Space>
      )}

      {k && islem === "tahsis" && <TahsisPenceresi k={k} onKapat={() => setIslem(null)} onBitti={onDegisti} />}
      {k && islem === "sevk" && <SevkPenceresi k={k} onKapat={() => setIslem(null)} onBitti={onDegisti} />}
      {k && islem === "iade" && <IadePenceresi k={k} onKapat={() => setIslem(null)} onBitti={onDegisti} />}
      {k && islem === "asama" && <AsamaPenceresi k={k} onKapat={() => setIslem(null)} onBitti={onDegisti} />}
      {k && islem === "degisim" && (
        <KiralamaDegisimPenceresi k={k} onKapat={() => setIslem(null)} onBitti={onDegisti} />
      )}
      {k && (islem === "geri" || islem === "iptal") && (
        <GerekcePenceresi
          baslik={islem === "geri" ? "Son aşamayı geri al" : "Kiralamayı iptal et"}
          aciklama={
            islem === "geri"
              ? "Son aşama ters hareketle geri alınır; kayıt silinmez. Kapanmış/iptal kiralama geri alınamaz."
              : "Sevk edilmemiş kiralama iptal edilir; tahsisler çözülür."
          }
          onKapat={() => setIslem(null)}
          onGonder={async (g) => {
            if (islem === "geri") await kiralamaApi.geriAl(k.id, { gerekce: g, olay_id: k.geri_alinabilir_olay_id });
            else await kiralamaApi.iptal(k.id, g);
            onDegisti();
          }}
        />
      )}
    </Drawer>
  );
}

function KalemTahsisTablosu({ k, cozebilir, onCoz }: { k: KiralamaKarti; cozebilir: boolean; onCoz: (t: TahsisOut) => void }) {
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={k.kalemler}
        columns={[
          {
            title: "Ürün",
            key: "urun",
            render: (_, r) => (
              <Space size={4}>
                <span className="mono">{r.urun_kodu}</span>
                <span>{r.urun_adi}</span>
                {r.seri_takipli && <Tag>seri</Tag>}
              </Space>
            ),
          },
          { title: "Adet", dataIndex: "qty", width: 70, align: "right" },
          {
            title: "Tahsisli",
            dataIndex: "tahsisli",
            width: 80,
            align: "right",
            render: (v: number, r) => <Typography.Text type={v < r.qty ? "warning" : undefined}>{v}</Typography.Text>,
          },
          { title: "Sevk", dataIndex: "sevk", width: 70, align: "right" },
          { title: "İade", dataIndex: "iade", width: 70, align: "right" },
          { title: "Kayıp", dataIndex: "kayip", width: 70, align: "right", render: (v: number) => (v ? <Tag color="red">{v}</Tag> : 0) },
          { title: "Not", dataIndex: "note", ellipsis: true, render: (v) => v ?? "" },
        ]}
      />
      <Typography.Text strong>Tahsisler</Typography.Text>
      <Table<TahsisOut>
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={k.tahsisler.filter((t) => t.durum !== "COZULDU")}
        locale={{ emptyText: "Tahsis yok" }}
        columns={[
          { title: "Ürün", dataIndex: "urun_kodu", render: (v) => <span className="mono">{v}</span> },
          { title: "Seri", dataIndex: "seri", render: (v: string | null, r) => (v ? <span className="mono">{v}</span> : `${r.qty} adet (toplu)`) },
          { title: "Depo", dataIndex: "depo_adi" },
          { title: "Sevk", dataIndex: "sevk_adet", width: 60, align: "right" },
          { title: "İade", dataIndex: "iade_adet", width: 60, align: "right" },
          { title: "Kayıp", dataIndex: "kayip_adet", width: 60, align: "right" },
          { title: "Müşteride", dataIndex: "musteride", width: 90, align: "right" },
          { title: "Durum", dataIndex: "durum", width: 90, render: (d: string) => <Tag color={d === "AKTIF" ? "blue" : "default"}>{d === "AKTIF" ? "Aktif" : "Kapandı"}</Tag> },
          {
            title: "",
            key: "islem",
            width: 70,
            render: (_, t) =>
              cozebilir && t.durum === "AKTIF" && t.sevk_adet === 0 ? (
                <Button size="small" type="link" danger onClick={() => onCoz(t)}>
                  Çöz
                </Button>
              ) : null,
          },
        ]}
      />
    </Space>
  );
}

// --- İşlem pencereleri ----------------------------------------------------------------

function useIslem(onBitti: () => void, onKapat: () => void) {
  const { message } = App.useApp();
  return useMutation({
    mutationFn: (f: () => Promise<unknown>) => f(),
    onSuccess: () => {
      message.success("Kaydedildi");
      onBitti();
      onKapat();
    },
    onError: (e) => message.error(hataMesaji(e)),
  });
}

/** Kalem başına tahsis: seri ürün → HAZIR cihazlar; toplu ürün → depo + adet. */
function TahsisPenceresi({ k, onKapat, onBitti }: { k: KiralamaKarti; onKapat: () => void; onBitti: () => void }) {
  const islem = useIslem(onBitti, onKapat);
  const depolar = useQuery({ queryKey: ["kiralama-depolar"], queryFn: kiralamaApi.depolar });
  const [secim, setSecim] = useState<Record<number, { cihazlar?: number[]; depo_id?: number; adet?: number }>>({});
  const eksikKalemler = k.kalemler.filter((x) => x.tahsisli < x.qty);

  const gonder = () => {
    const satirlar = Object.entries(secim)
      .map(([kalem, s]) => {
        const kalem_id = Number(kalem);
        if (s.cihazlar?.length) return { kalem_id, kiralik_idler: s.cihazlar };
        if (s.depo_id && s.adet) return { kalem_id, depo_id: s.depo_id, adet: s.adet };
        return null;
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
    if (!satirlar.length) return;
    islem.mutate(() => kiralamaApi.tahsis(k.id, satirlar));
  };

  return (
    <Modal open width={760} title="Tahsis" onCancel={onKapat} onOk={gonder} okText="Tahsis et" cancelText="Vazgeç" confirmLoading={islem.isPending} destroyOnHidden>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Kalem adedi aşılamaz; aynı cihaz çakışan tarihli başka kiralamaya tahsis edilemez. Kısmi tahsis yapılabilir,
        sevkten önce her kalem tamamlanmalıdır.
      </Typography.Paragraph>
      {eksikKalemler.length === 0 && <Empty description="Bütün kalemler tahsisli" />}
      <Space orientation="vertical" style={{ width: "100%" }}>
        {eksikKalemler.map((x) => (
          <Card key={x.id} size="small" title={`${x.urun_kodu ?? ""} ${x.urun_adi ?? ""}`} extra={`${x.tahsisli}/${x.qty} tahsisli`}>
            <Row gutter={8}>
              <Col xs={24} md={10}>
                <Select
                  allowClear
                  style={{ width: "100%" }}
                  placeholder="Depo"
                  value={secim[x.id]?.depo_id}
                  onChange={(v) => setSecim((s) => ({ ...s, [x.id]: { ...s[x.id], depo_id: v, cihazlar: [] } }))}
                  options={(depolar.data ?? []).map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
                />
              </Col>
              <Col xs={24} md={14}>
                {x.seri_takipli ? (
                  <CihazSecici
                    productId={x.product_id}
                    depoId={secim[x.id]?.depo_id}
                    sinir={x.qty - x.tahsisli}
                    value={secim[x.id]?.cihazlar ?? []}
                    onChange={(v) => setSecim((s) => ({ ...s, [x.id]: { ...s[x.id], cihazlar: v } }))}
                  />
                ) : (
                  <InputNumber
                    min={1}
                    max={Math.max(1, x.qty - x.tahsisli)}
                    precision={0}
                    style={{ width: "100%" }}
                    placeholder={`Adet (en çok ${x.qty - x.tahsisli})`}
                    value={secim[x.id]?.adet}
                    onChange={(v) => setSecim((s) => ({ ...s, [x.id]: { ...s[x.id], adet: v ?? undefined } }))}
                  />
                )}
              </Col>
            </Row>
          </Card>
        ))}
      </Space>
    </Modal>
  );
}

function CihazSecici({
  productId,
  depoId,
  sinir,
  value,
  onChange,
}: {
  productId: number;
  depoId?: number;
  sinir: number;
  value: number[];
  onChange: (v: number[]) => void;
}) {
  const cihazlar = useQuery({
    queryKey: ["kiralik-hazir", productId, depoId],
    queryFn: () => kiralamaApi.envanter({ product_id: productId, depo_id: depoId, durum: "HAZIR" }, 200, 0),
  });
  return (
    <Select
      mode="multiple"
      style={{ width: "100%" }}
      placeholder={`Hazır cihaz seçin (en çok ${sinir})`}
      value={value}
      maxCount={Math.max(1, sinir)}
      onChange={onChange}
      loading={cihazlar.isLoading}
      optionFilterProp="label"
      options={(cihazlar.data?.kayitlar ?? []).map((c) => ({
        value: c.id,
        label: `${c.serial_no}${c.depo_adi ? ` · ${c.depo_adi}` : ""}`,
        disabled: c.kiralama_id != null,
      }))}
    />
  );
}

function SevkPenceresi({ k, onKapat, onBitti }: { k: KiralamaKarti; onKapat: () => void; onBitti: () => void }) {
  const islem = useIslem(onBitti, onKapat);
  const bekleyen = k.tahsisler.filter((t) => t.durum === "AKTIF" && t.qty > t.sevk_adet);
  const [secili, setSecili] = useState<number[]>(bekleyen.map((t) => t.id));
  const [an, setAn] = useState<Dayjs | null>(dayjs());
  const [not, setNot] = useState("");

  const gonder = () =>
    islem.mutate(() =>
      kiralamaApi.sevk(k.id, {
        at: an?.toISOString() ?? null,
        satirlar: secili.length === bekleyen.length && k.status === "HAZIRLANIYOR" ? null : secili.map((tahsis_id) => ({ tahsis_id })),
        not: not.trim() || undefined,
      }),
    );

  return (
    <Modal open width={720} title={k.status === "HAZIRLANIYOR" ? "Sevk" : "Ek sevk"} onCancel={onKapat} onOk={gonder} okText="Sevk et" cancelText="Vazgeç" okButtonProps={{ disabled: !secili.length }} confirmLoading={islem.isPending} destroyOnHidden>
      <Space orientation="vertical" style={{ width: "100%" }}>
        {k.status === "HAZIRLANIYOR" && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            İlk sevkte her kalem tamamen tahsisli olmalıdır; eksik varsa sunucu eksik listesini döner.
          </Typography.Text>
        )}
        <DatePicker showTime format="DD.MM.YYYY HH:mm" value={an} onChange={setAn} style={{ width: 240 }} />
        <Table<TahsisOut>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={bekleyen}
          rowSelection={{ selectedRowKeys: secili, onChange: (x) => setSecili(x as number[]) }}
          columns={[
            { title: "Ürün", dataIndex: "urun_kodu" },
            { title: "Seri / adet", key: "s", render: (_, t) => t.seri ?? `${t.qty - t.sevk_adet} adet` },
            { title: "Depo", dataIndex: "depo_adi" },
          ]}
        />
        <Input maxLength={300} placeholder="Not (isteğe bağlı)" value={not} onChange={(e) => setNot(e.target.value)} />
      </Space>
    </Modal>
  );
}

function IadePenceresi({ k, onKapat, onBitti }: { k: KiralamaKarti; onKapat: () => void; onBitti: () => void }) {
  const islem = useIslem(onBitti, onKapat);
  const depolar = useQuery({ queryKey: ["kiralama-depolar"], queryFn: kiralamaApi.depolar });
  const disarida = k.tahsisler.filter((t) => t.durum === "AKTIF" && t.musteride > 0);
  const [satirlar, setSatirlar] = useState<Record<number, { sonuc?: string; adet?: number; depo_id?: number; not?: string }>>(
    {},
  );
  const [an, setAn] = useState<Dayjs | null>(dayjs());
  const guncelle = (id: number, p: object) => setSatirlar((s) => ({ ...s, [id]: { ...s[id], ...p } }));

  const gonder = () => {
    const liste = Object.entries(satirlar)
      .filter(([, s]) => s.sonuc)
      .map(([id, s]) => ({
        tahsis_id: Number(id),
        sonuc: s.sonuc!,
        adet: s.adet ?? null,
        depo_id: s.sonuc === "IADE_ALINDI" ? (s.depo_id ?? null) : null,
        not: s.not?.trim() || null,
      }));
    if (!liste.length) return;
    islem.mutate(() => kiralamaApi.iade(k.id, { at: an?.toISOString() ?? null, satirlar: liste }));
  };

  return (
    <Modal open width={900} title="İade al" onCancel={onKapat} onOk={gonder} okText="Kaydet" cancelText="Vazgeç" confirmLoading={islem.isPending} destroyOnHidden>
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Depoya iade edilen cihaz "Kontrolde" olur. Kurulum yapılmış kiralamada son iadeden önce "Toplandı" aşaması
          girilmelidir. Bütün cihazlar dönünce kiralama "Depoya alındı" olur.
        </Typography.Text>
        <DatePicker showTime format="DD.MM.YYYY HH:mm" value={an} onChange={setAn} style={{ width: 240 }} />
        <Table<TahsisOut>
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={disarida}
          columns={[
            { title: "Ürün", dataIndex: "urun_kodu" },
            { title: "Seri / müşteride", key: "s", render: (_, t) => t.seri ?? `${t.musteride} adet` },
            {
              title: "Sonuç",
              key: "sonuc",
              width: 170,
              render: (_, t) => (
                <Select
                  allowClear
                  style={{ width: "100%" }}
                  value={satirlar[t.id]?.sonuc}
                  onChange={(v) => guncelle(t.id, { sonuc: v })}
                  options={Object.entries(IADE_SONUC_ADLARI).map(([v, l]) => ({ value: v, label: l }))}
                />
              ),
            },
            {
              title: "Adet",
              key: "adet",
              width: 90,
              render: (_, t) =>
                t.seri ? (
                  1
                ) : (
                  <InputNumber
                    min={1}
                    max={t.musteride}
                    precision={0}
                    placeholder={String(t.musteride)}
                    value={satirlar[t.id]?.adet}
                    onChange={(v) => guncelle(t.id, { adet: v ?? undefined })}
                  />
                ),
            },
            {
              title: "Depo",
              key: "depo",
              width: 190,
              render: (_, t) => (
                <Select
                  style={{ width: "100%" }}
                  disabled={satirlar[t.id]?.sonuc !== "IADE_ALINDI"}
                  value={satirlar[t.id]?.depo_id}
                  onChange={(v) => guncelle(t.id, { depo_id: v })}
                  options={(depolar.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
                />
              ),
            },
            {
              title: "Not",
              key: "not",
              render: (_, t) => (
                <Input maxLength={300} value={satirlar[t.id]?.not} onChange={(e) => guncelle(t.id, { not: e.target.value })} />
              ),
            },
          ]}
        />
      </Space>
    </Modal>
  );
}

function AsamaPenceresi({ k, onKapat, onBitti }: { k: KiralamaKarti; onKapat: () => void; onBitti: () => void }) {
  const islem = useIslem(onBitti, onKapat);
  const secenekler = k.sonraki_durumlar.filter((d) => (ASAMA_HEDEFLERI as readonly string[]).includes(d));
  const [asama, setAsama] = useState<string | undefined>(
    k.onerilen_asama && secenekler.includes(k.onerilen_asama) ? k.onerilen_asama : secenekler[0],
  );
  const [an, setAn] = useState<Dayjs | null>(dayjs());
  const [isId, setIsId] = useState<number | undefined>();
  const [not, setNot] = useState("");
  return (
    <Modal
      open
      title="Aşama gir"
      onCancel={onKapat}
      okText="Kaydet"
      cancelText="Vazgeç"
      okButtonProps={{ disabled: !asama }}
      confirmLoading={islem.isPending}
      onOk={() =>
        islem.mutate(() =>
          kiralamaApi.asama(k.id, {
            asama: asama!,
            at: an?.toISOString() ?? null,
            service_order_id: isId ?? null,
            not: not.trim() || undefined,
          }),
        )
      }
      destroyOnHidden
    >
      <Space orientation="vertical" style={{ width: "100%" }}>
        <Select
          style={{ width: "100%" }}
          value={asama}
          onChange={setAsama}
          options={secenekler.map((d) => ({ value: d, label: KIRALAMA_DURUM_ADLARI[d] }))}
        />
        <DatePicker showTime format="DD.MM.YYYY HH:mm" value={an} onChange={setAn} style={{ width: 240 }} />
        {k.servis_isleri.length > 0 && (
          <Select
            allowClear
            style={{ width: "100%" }}
            placeholder="İlgili servis işi (isteğe bağlı)"
            value={isId}
            onChange={setIsId}
            options={k.servis_isleri.map((s) => ({ value: s.id, label: `${s.so_no} · ${SERVIS_ISI_TURLERI[s.tur] ?? s.tur}` }))}
          />
        )}
        <Input.TextArea rows={2} maxLength={500} placeholder="Not" value={not} onChange={(e) => setNot(e.target.value)} />
      </Space>
    </Modal>
  );
}

function GerekcePenceresi({
  baslik,
  aciklama,
  onKapat,
  onGonder,
}: {
  baslik: string;
  aciklama: string;
  onKapat: () => void;
  onGonder: (gerekce: string) => Promise<void>;
}) {
  const { message } = App.useApp();
  const [gerekce, setGerekce] = useState("");
  const [bekliyor, setBekliyor] = useState(false);
  return (
    <Modal
      open
      title={baslik}
      onCancel={onKapat}
      okText="Onayla"
      okButtonProps={{ danger: true, disabled: gerekce.trim().length < 3 }}
      cancelText="Vazgeç"
      confirmLoading={bekliyor}
      onOk={async () => {
        setBekliyor(true);
        try {
          await onGonder(gerekce.trim());
          message.success("Kaydedildi");
          onKapat();
        } catch (e) {
          message.error(hataMesaji(e));
        } finally {
          setBekliyor(false);
        }
      }}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">{aciklama}</Typography.Paragraph>
      <Input.TextArea rows={3} maxLength={500} placeholder="Gerekçe (zorunlu)" value={gerekce} onChange={(e) => setGerekce(e.target.value)} />
    </Modal>
  );
}
