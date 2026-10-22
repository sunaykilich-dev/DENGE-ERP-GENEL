/**
 * Planlama — takvim (Gün/Hafta/Ay), plansız havuz, KPI kutuları, kompakt
 * ziyaret kartı, toplu/yeniden plan, plan geçmişi ve servis araç havuzu
 * (TS-042…049, E02-05/06/07/12/13/16/17/19).
 *
 * - Takvim yalnız görünen aralığı yükler (gün / hafta / ay ≤ 42 gün; sunucu
 *   62 gün sınırını ayrıca uygular).
 * - Kart = ziyaret (`kart_anahtari`); kart tıklanınca alt işler AYRI AYRI
 *   listelenir, seçilenler tek işlemde taşınır (yalnız seçilenler).
 * - Havuz gruplaması sunucunun `grup_anahtari`ndan; istemci normalizasyon
 *   yapmaz. Dar ekranda havuz çekmeceye geçer.
 * - KPI kutusu sayısı = açılan liste (`/kpi-liste`), kutu tıklanınca liste
 *   çekmecede açılır (`?kpi=` adresi paylaşılabilir).
 * - Kapalı işin planı soluk ve salt okunur; düğmeler `yetkili()` ile.
 * - P3 (TS-190): Kaynak sekmesi (personel × gün "plan" dakikası, müsaitlik
 *   ve eğitim blokları), Plan Uyumu sekmesi (aynı İstanbul günü; eksik
 *   paydada yok) ve havuzdaki işe aynı ilçe önerisi (seçilen iş AYRI tekli plan).
 */
import {
  CalendarOutlined,
  FileExcelOutlined,
  LeftOutlined,
  RightOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Drawer,
  Empty,
  Form,
  Grid,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Timeline,
  Tooltip,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { ApiError } from "../api/client";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import {
  type Arac,
  type BolgeZiyareti,
  DEGISIM_ETIKETLERI,
  DURUM_ETIKETLERI,
  type HavuzSatiri,
  PLAN_NEDENLERI,
  type Plan,
  type TakvimSatiri,
  planlamaApi,
  planlamaP3Api,
} from "../api/servisPlanlama";
import { useAuth } from "../auth/AuthContext";
import KpiKutusu from "../components/KpiKutusu";
import PlanPenceresi, { type PlanModu, type PlanPenceresiProps } from "../components/PlanPenceresi";
import { KaynakSekmesi, PlanUyumuSekmesi } from "./ServisPlanlamaP3";

type Gorunum = "gun" | "hafta" | "ay";
const GUN_ADLARI = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
const KART_SINIRI: Record<Gorunum, number> = { gun: 999, hafta: 4, ay: 3 };
const ISO = "YYYY-MM-DD";

function pazartesi(d: Dayjs): Dayjs {
  return d.subtract((d.day() + 6) % 7, "day").startOf("day");
}

function aralik(gun: Dayjs, g: Gorunum): [Dayjs, Dayjs] {
  if (g === "gun") return [gun, gun];
  if (g === "hafta") return [pazartesi(gun), pazartesi(gun).add(6, "day")];
  const bas = pazartesi(gun.startOf("month"));
  const son = pazartesi(gun.endOf("month")).add(6, "day");
  return [bas, son];
}

interface Kart {
  anahtar: string;
  gun: string;
  saat: string | null;
  satirlar: TakvimSatiri[];
}

function kartlaraBol(satirlar: TakvimSatiri[]): Map<string, Kart[]> {
  const gunler = new Map<string, Map<string, Kart>>();
  for (const s of satirlar) {
    const gun = gunler.get(s.plan_tarihi) ?? new Map<string, Kart>();
    const kart = gun.get(s.kart_anahtari) ?? {
      anahtar: s.kart_anahtari,
      gun: s.plan_tarihi,
      saat: s.baslangic_saati,
      satirlar: [],
    };
    kart.satirlar.push(s);
    gun.set(s.kart_anahtari, kart);
    gunler.set(s.plan_tarihi, gun);
  }
  const sonuc = new Map<string, Kart[]>();
  for (const [gun, kartlar] of gunler) {
    sonuc.set(
      gun,
      [...kartlar.values()].sort((a, b) => (a.saat ?? "99").localeCompare(b.saat ?? "99")),
    );
  }
  return sonuc;
}

function kartTuru(k: Kart): string {
  const pb = k.satirlar.filter((s) => s.tur === "PB").length;
  if (pb === 0) return "Servis";
  return pb === k.satirlar.length ? "Bakım" : "Karma";
}

function ZiyaretKarti({ kart, onAc }: { kart: Kart; onAc: () => void }) {
  const ilk = kart.satirlar[0];
  const kapali = kart.satirlar.every((s) => s.kapali);
  const cakisma = kart.satirlar.some((s) => s.cakisma);
  const ekip = [...new Map(kart.satirlar.flatMap((s) => s.ekip).map((u) => [u.user_id, u])).values()];
  return (
    <Card
      size="small"
      hoverable
      onClick={onAc}
      style={{
        marginBottom: 6,
        opacity: kapali ? 0.5 : 1,
        borderColor: cakisma ? "#de3a11" : undefined,
        cursor: "pointer",
      }}
      styles={{ body: { padding: 6 } }}
    >
      <Space size={4} wrap style={{ fontSize: 12 }}>
        <Typography.Text strong>{kart.saat ?? "Saat belirsiz"}</Typography.Text>
        <Tag style={{ marginInlineEnd: 0 }}>{kartTuru(kart)}</Tag>
        {kart.satirlar.length > 1 && <Badge count={kart.satirlar.length} color="#1677ff" />}
        {cakisma && (
          <Tooltip title="Çakışma var">
            <Tag color="red" style={{ marginInlineEnd: 0 }}>
              Çakışma
            </Tag>
          </Tooltip>
        )}
      </Space>
      <div style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {ilk.musteri}
        {ilk.lokasyon ? ` · ${ilk.lokasyon}` : ""}
      </div>
      <div
        style={{ fontSize: 11, color: "#888", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
      >
        {ekip.map((u) => u.ad).join(", ") || "Ekip yok"}
        {ilk.arac_plaka ? ` · ${ilk.arac_plaka}` : ""}
      </div>
    </Card>
  );
}

interface PencereDurumu {
  mod: PlanModu;
  isIdler: number[];
  birim: string;
  mevcut?: Plan | null;
  gun?: string;
  varsayilan?: PlanPenceresiProps["varsayilan"];
}

export default function ServisPlanlamaPage() {
  const { yetkili, kullanici } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const ekran = Grid.useBreakpoint();
  const [params, setParams] = useSearchParams();
  const planlayabilir = yetkili("servis.planla");

  const [gun, setGun] = useState<Dayjs>(() => {
    const p = params.get("gun");
    return p && dayjs(p, ISO).isValid() ? dayjs(p, ISO) : dayjs().startOf("day");
  });
  const [gorunum, setGorunum] = useState<Gorunum>("hafta");
  const [birim, setBirim] = useState<string | undefined>(
    kullanici?.birimler?.length === 1 ? kullanici.birimler[0] : undefined,
  );
  const [tur, setTur] = useState<string>("TUMU");
  const [gruplama, setGruplama] = useState<"lokasyon" | "sehir">("lokasyon");
  const [arama, setArama] = useState("");
  const [havuzSecili, setHavuzSecili] = useState<number[]>([]);
  const [havuzAcik, setHavuzAcik] = useState(false);
  const [kart, setKart] = useState<Kart | null>(null);
  const [kartSecili, setKartSecili] = useState<number[]>([]);
  const [pencere, setPencere] = useState<PencereDurumu | null>(null);
  const [geriAl, setGeriAl] = useState<TakvimSatiri | null>(null);
  const [gecmisIs, setGecmisIs] = useState<TakvimSatiri | null>(null);
  const [bolgeIs, setBolgeIs] = useState<HavuzSatiri | null>(null);
  const [geriAlForm] = Form.useForm<{ neden: string; not?: string }>();

  const suzgec = { birim, tur: tur === "TUMU" ? undefined : tur };
  const [bas, bit] = aralik(gun, gorunum);
  const basStr = bas.format(ISO);
  const bitStr = bit.format(ISO);
  const kpiKodu = params.get("kpi");

  const takvim = useQuery({
    queryKey: ["servis-takvim", basStr, bitStr, birim, tur],
    queryFn: () => planlamaApi.takvim(basStr, bitStr, suzgec),
  });
  const havuz = useQuery({
    queryKey: ["servis-havuz", birim, tur, gruplama, arama],
    queryFn: () => planlamaApi.havuz({ ...suzgec, gruplama, q: arama || undefined }),
  });
  const kpi = useQuery({
    queryKey: ["servis-plan-kpi", gun.format(ISO), birim, tur],
    queryFn: () => planlamaApi.kpi(gun.format(ISO), suzgec),
  });
  const kpiListe = useQuery({
    queryKey: ["servis-plan-kpi-liste", kpiKodu, gun.format(ISO), birim, tur],
    queryFn: () => planlamaApi.kpiListe(kpiKodu!, gun.format(ISO), suzgec),
    enabled: !!kpiKodu,
  });
  const bolge = useQuery({
    queryKey: ["servis-bolge-onerisi", bolgeIs?.is_id, gun.format(ISO)],
    queryFn: () => planlamaP3Api.bolgeOnerisi(bolgeIs!.is_id, gun.format(ISO)),
    enabled: bolgeIs != null,
  });
  const gecmis = useQuery({
    queryKey: ["servis-plan-gecmisi", gecmisIs?.is_id],
    queryFn: () => planlamaApi.gecmis(gecmisIs!.is_id),
    enabled: gecmisIs != null,
  });

  const tazele = () => {
    for (const k of ["servis-takvim", "servis-havuz", "servis-plan-kpi", "servis-plan-kpi-liste"]) {
      void qc.invalidateQueries({ queryKey: [k] });
    }
  };

  const geriAlMut = useMutation({
    mutationFn: (v: { neden: string; not?: string }) =>
      planlamaApi.geriAl(geriAl!.is_id, v.neden, v.not),
    onSuccess: () => {
      message.success("Plan geri alındı; iş havuza döndü");
      setGeriAl(null);
      setKart(null);
      tazele();
    },
    onError: (e: ApiError) =>
      message.error(e.cakisma ? `${e.message} Gerekirse sayfayı yenileyin.` : e.message),
  });

  const kartlar = useMemo(() => kartlaraBol(takvim.data ?? []), [takvim.data]);
  // Açık kart, takvim tazelenince güncel satırlarla yeniden kurulur.
  const acikKart = useMemo(() => {
    if (!kart) return null;
    return kartlar.get(kart.gun)?.find((k) => k.anahtar === kart.anahtar) ?? kart;
  }, [kart, kartlar]);

  const havuzGruplari = useMemo(() => {
    const m = new Map<string, { etiket: string; satirlar: HavuzSatiri[] }>();
    for (const s of havuz.data?.kayitlar ?? []) {
      const g = m.get(s.grup_anahtari) ?? { etiket: s.grup_etiketi, satirlar: [] };
      g.satirlar.push(s);
      m.set(s.grup_anahtari, g);
    }
    return [...m.entries()];
  }, [havuz.data]);
  const seciliHavuz = (havuz.data?.kayitlar ?? []).filter((s) => havuzSecili.includes(s.is_id));
  const topluUygun =
    seciliHavuz.length > 0 &&
    new Set(seciliHavuz.map((s) => s.birim)).size === 1 &&
    (gruplama === "sehir" || new Set(seciliHavuz.map((s) => s.grup_anahtari)).size === 1);

  const kaydirma = (yon: 1 | -1) =>
    setGun((g) => g.add(yon, gorunum === "gun" ? "day" : gorunum === "hafta" ? "week" : "month"));

  const kartAc = (k: Kart) => {
    setKart(k);
    setKartSecili([]);
  };

  // --- Takvim gövdesi -----------------------------------------------------------

  const gunHucresi = (g: Dayjs, sinir: number) => {
    const liste = kartlar.get(g.format(ISO)) ?? [];
    return (
      <>
        {liste.slice(0, sinir).map((k) => (
          <ZiyaretKarti key={k.anahtar} kart={k} onAc={() => kartAc(k)} />
        ))}
        {liste.length > sinir && (
          <Button
            size="small"
            type="link"
            onClick={() => {
              setGun(g);
              setGorunum("gun");
            }}
          >
            +{liste.length - sinir} daha
          </Button>
        )}
      </>
    );
  };

  const takvimGovdesi = () => {
    if (gorunum === "gun") {
      return (kartlar.get(gun.format(ISO)) ?? []).length ? (
        gunHucresi(gun, KART_SINIRI.gun)
      ) : (
        <Empty description="Bu gün plan yok" />
      );
    }
    const gunler = Array.from({ length: bit.diff(bas, "day") + 1 }, (_, i) => bas.add(i, "day"));
    if (gorunum === "hafta") {
      return (
        <Row gutter={[8, 8]}>
          {gunler.map((g) => (
            <Col
              key={g.format(ISO)}
              {...(ekran.xl ? { flex: "1 1 0", style: { minWidth: 0 } } : { xs: 24, sm: 12, md: 8 })}
            >
              <Typography.Text strong type={g.isSame(dayjs(), "day") ? "success" : undefined}>
                {GUN_ADLARI[(g.day() + 6) % 7]} {g.format("DD.MM")}
              </Typography.Text>
              <div style={{ minHeight: 40 }}>{gunHucresi(g, KART_SINIRI.hafta)}</div>
            </Col>
          ))}
        </Row>
      );
    }
    // Ay: haftalar × 7 gün; dar ekranda tek sütun liste.
    const haftalar: Dayjs[][] = [];
    for (let i = 0; i < gunler.length; i += 7) haftalar.push(gunler.slice(i, i + 7));
    return (
      <div style={{ overflowX: "auto" }}>
        {haftalar.map((h) => (
          <Row key={h[0].format(ISO)} gutter={[4, 4]} wrap={!ekran.md}>
            {h.map((g) => (
              <Col
                key={g.format(ISO)}
                flex={ekran.md ? "1 1 0" : undefined}
                xs={ekran.md ? undefined : 24}
                style={{
                  minHeight: 70,
                  borderTop: "1px solid #f0f0f0",
                  opacity: g.month() === gun.month() ? 1 : 0.55,
                }}
              >
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {ekran.md ? g.format("D") : `${GUN_ADLARI[(g.day() + 6) % 7]} ${g.format("DD.MM")}`}
                </Typography.Text>
                {gunHucresi(g, KART_SINIRI.ay)}
              </Col>
            ))}
          </Row>
        ))}
      </div>
    );
  };

  // --- Havuz ---------------------------------------------------------------------

  const havuzIcerik = (
    <>
      <Space wrap style={{ marginBottom: 8 }}>
        <Segmented
          size="small"
          value={gruplama}
          onChange={(v) => setGruplama(v as "lokasyon" | "sehir")}
          options={[
            { value: "lokasyon", label: "Lokasyon" },
            { value: "sehir", label: "Şehir / İlçe" },
          ]}
        />
        <Input.Search
          size="small"
          allowClear
          placeholder="İş no, müşteri, tesis, seri"
          onSearch={setArama}
          style={{ width: 200 }}
        />
      </Space>
      {planlayabilir && (
        <Space style={{ marginBottom: 8 }} wrap>
          <Button
            size="small"
            type="primary"
            disabled={!topluUygun}
            onClick={() =>
              setPencere({
                mod: "toplu",
                isIdler: havuzSecili,
                birim: seciliHavuz[0].birim,
                gun: gun.format(ISO),
              })
            }
          >
            Toplu Planla ({havuzSecili.length})
          </Button>
          {havuzSecili.length > 0 && (
            <Button size="small" onClick={() => setHavuzSecili([])}>
              Seçimi temizle
            </Button>
          )}
        </Space>
      )}
      <Typography.Text type="secondary" style={{ fontSize: 12, display: "block" }}>
        {havuz.data ? `${havuz.data.toplam} plansız iş` : ""}
        {havuz.data && havuz.data.toplam > havuz.data.kayitlar.length
          ? ` (ilk ${havuz.data.kayitlar.length} gösteriliyor; aramayla daraltın)`
          : ""}
      </Typography.Text>
      {havuz.isLoading ? (
        <Card loading size="small" />
      ) : havuzGruplari.length === 0 ? (
        <Empty description="Plansız iş yok" />
      ) : (
        havuzGruplari.map(([anahtar, g]) => {
          const idler = g.satirlar.map((s) => s.is_id);
          const hepsi = idler.every((i) => havuzSecili.includes(i));
          return (
            <Card
              key={anahtar}
              size="small"
              style={{ marginTop: 8 }}
              title={
                <Space>
                  {planlayabilir && (
                    <Checkbox
                      checked={hepsi}
                      indeterminate={!hepsi && idler.some((i) => havuzSecili.includes(i))}
                      onChange={(e) =>
                        setHavuzSecili((s) =>
                          e.target.checked
                            ? [...new Set([...s, ...idler])]
                            : s.filter((i) => !idler.includes(i)),
                        )
                      }
                    />
                  )}
                  <span style={{ whiteSpace: "normal" }}>{g.etiket}</span>
                  <Tag>{g.satirlar.length}</Tag>
                </Space>
              }
            >
              {g.satirlar.map((s) => (
                <div key={s.is_id} style={{ display: "flex", gap: 6, alignItems: "center", padding: "2px 0" }}>
                  {planlayabilir && (
                    <Checkbox
                      checked={havuzSecili.includes(s.is_id)}
                      onChange={(e) =>
                        setHavuzSecili((x) =>
                          e.target.checked ? [...x, s.is_id] : x.filter((i) => i !== s.is_id),
                        )
                      }
                    />
                  )}
                  <div style={{ flex: 1, minWidth: 0, fontSize: 12 }}>
                    <Typography.Text strong>{s.so_no}</Typography.Text>{" "}
                    {s.tur === "PB" && <Tag color="blue">Bakım</Tag>}
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.konu}
                    </div>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {DURUM_ETIKETLERI[s.durum] ?? s.durum} · {s.yas_gun ?? "?"} gün
                    </Typography.Text>
                  </div>
                  {planlayabilir && (
                    <Space.Compact size="small">
                      <Button
                        size="small"
                        onClick={() =>
                          setPencere({ mod: "tekli", isIdler: [s.is_id], birim: s.birim, gun: gun.format(ISO) })
                        }
                      >
                        Planla
                      </Button>
                      <Tooltip title="Aynı ilçedeki plansız işler ve yakın ziyaretler">
                        <Button size="small" onClick={() => setBolgeIs(s)}>
                          Bölge
                        </Button>
                      </Tooltip>
                    </Space.Compact>
                  )}
                </div>
              ))}
            </Card>
          );
        })
      )}
    </>
  );

  // --- Ziyaret kartı çekmecesi -----------------------------------------------------

  const planiDuzenle = async (s: TakvimSatiri) => {
    try {
      const p = await planlamaApi.isPlani(s.is_id);
      setPencere({ mod: "tekli", isIdler: [s.is_id], birim: s.birim, mevcut: p.plan });
    } catch (e) {
      message.error((e as ApiError).message);
    }
  };

  const kartCekmecesi = acikKart && (
    <Drawer
      open
      onClose={() => setKart(null)}
      width={ekran.md ? 560 : "100%"}
      title={
        acikKart.satirlar[0].ziyaret_no
          ? `Ziyaret ${acikKart.satirlar[0].ziyaret_no}`
          : acikKart.satirlar[0].so_no
      }
      extra={
        planlayabilir &&
        kartSecili.length > 0 && (
          <Button
            type="primary"
            onClick={() => {
              const ilk = acikKart.satirlar.find((s) => kartSecili.includes(s.is_id))!;
              setPencere({ mod: "yeniden", isIdler: kartSecili, birim: ilk.birim });
            }}
          >
            Seçilenleri Taşı ({kartSecili.length})
          </Button>
        )
      }
    >
      <Typography.Paragraph type="secondary">
        {dayjs(acikKart.gun).format("DD.MM.YYYY")} · {acikKart.saat ?? "saat belirsiz"} ·{" "}
        {acikKart.satirlar[0].musteri}
        {acikKart.satirlar[0].lokasyon ? ` · ${acikKart.satirlar[0].lokasyon}` : ""}
        {acikKart.satirlar[0].il ? ` (${acikKart.satirlar[0].il})` : ""}
      </Typography.Paragraph>
      {acikKart.satirlar.map((s) => (
        <Card
          key={s.is_id}
          size="small"
          style={{ marginBottom: 8, opacity: s.kapali ? 0.6 : 1 }}
          title={
            <Space wrap>
              {planlayabilir && !s.kapali && (
                <Checkbox
                  checked={kartSecili.includes(s.is_id)}
                  onChange={(e) =>
                    setKartSecili((x) =>
                      e.target.checked ? [...x, s.is_id] : x.filter((i) => i !== s.is_id),
                    )
                  }
                />
              )}
              <span>{s.so_no}</span>
              <Tag>{DURUM_ETIKETLERI[s.durum] ?? s.durum}</Tag>
              {s.cakisma && <Tag color="red">Çakışma{s.cakisma_gecildi ? " (gerekçeli)" : ""}</Tag>}
            </Space>
          }
        >
          <div>{s.konu}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {s.sure_dk} dk planlı · {s.ekip.map((u) => `${u.ad}${u.rol === "SEF" ? " (şef)" : ""}`).join(", ") || "ekip yok"}
            {s.arac_plaka ? ` · ${s.arac_plaka}` : ""}
          </Typography.Text>
          {(s.irtibat_adi || s.irtibat_telefon) && (
            <div style={{ fontSize: 12 }}>
              {s.irtibat_adi}{" "}
              {s.irtibat_telefon && <a href={`tel:${s.irtibat_telefon}`}>{s.irtibat_telefon}</a>}
            </div>
          )}
          {(s.saha_bolgesi || s.saha_notu) && (
            <div style={{ fontSize: 12 }}>
              {[s.saha_bolgesi, s.saha_notu].filter(Boolean).join(" · ")}
            </div>
          )}
          <Space wrap style={{ marginTop: 6 }}>
            {planlayabilir && !s.kapali && (
              <>
                <Button size="small" onClick={() => void planiDuzenle(s)}>
                  Planı Düzenle
                </Button>
                <Button
                  size="small"
                  danger
                  onClick={() => {
                    geriAlForm.resetFields();
                    setGeriAl(s);
                  }}
                >
                  Geri Al
                </Button>
              </>
            )}
            <Button size="small" type="link" onClick={() => setGecmisIs(s)}>
              Plan geçmişi{s.erteleme_sayisi ? ` (${s.erteleme_sayisi} erteleme)` : ""}
            </Button>
          </Space>
        </Card>
      ))}
    </Drawer>
  );

  // --- KPI listesi çekmecesi ------------------------------------------------------

  const kpiBasligi = kpi.data?.find((k) => k.kod === kpiKodu)?.baslik ?? kpiKodu;
  const kpiCekmecesi = kpiKodu && (
    <Drawer
      open
      width={ekran.md ? 720 : "100%"}
      title={`${kpiBasligi} (${kpiListe.data?.toplam ?? "…"})`}
      onClose={() => {
        params.delete("kpi");
        setParams(params, { replace: true });
      }}
    >
      <Table
        size="small"
        rowKey={(r) => ("plan_id" in r ? `p${r.plan_id}` : `i${r.is_id}`)}
        loading={kpiListe.isLoading}
        dataSource={kpiListe.data?.kayitlar ?? []}
        pagination={{ pageSize: 50 }}
        scroll={{ x: 560 }}
        columns={[
          { title: "İş No", dataIndex: "so_no" },
          { title: "Müşteri", dataIndex: "musteri", ellipsis: true },
          { title: "Lokasyon", dataIndex: "lokasyon", ellipsis: true },
          {
            title: "Plan",
            render: (_, r) =>
              "plan_tarihi" in r
                ? `${dayjs(r.plan_tarihi).format("DD.MM")} ${r.baslangic_saati ?? "—"}`
                : "Plansız",
          },
          { title: "Durum", dataIndex: "durum", render: (d: string) => DURUM_ETIKETLERI[d] ?? d },
        ]}
      />
    </Drawer>
  );

  // --- Sayfa -------------------------------------------------------------------------

  const birimSecenekleri = [
    { value: "", label: "Tüm birimler" },
    ...BIRIM_KODLARI.filter(
      (b) => !kullanici?.birimler?.length || kullanici.role.scope === "TUMU" || kullanici.birimler.includes(b),
    ).map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] })),
  ];

  const takvimSekmesi = (
    <>
      <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
        {(kpi.data ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} xl={4}>
            <KpiKutusu
              kod={k.kod}
              baslik={k.baslik}
              tanim={k.tanim}
              deger={k.deger}
              vurgu={k.kod === "cakismali" && k.deger > 0 ? "kritik" : "normal"}
              yol={`/servis-planlama?kpi=${k.kod}&gun=${gun.format(ISO)}`}
            />
          </Col>
        ))}
      </Row>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button icon={<LeftOutlined />} onClick={() => kaydirma(-1)} aria-label="Önceki" />
        <Button onClick={() => setGun(dayjs().startOf("day"))}>Bugün</Button>
        <Button icon={<RightOutlined />} onClick={() => kaydirma(1)} aria-label="Sonraki" />
        <DatePicker value={gun} allowClear={false} format="DD.MM.YYYY" onChange={(d) => d && setGun(d)} />
        <Segmented
          value={gorunum}
          onChange={(v) => setGorunum(v as Gorunum)}
          options={[
            { value: "gun", label: "Gün" },
            { value: "hafta", label: "Hafta" },
            { value: "ay", label: "Ay" },
          ]}
        />
        <Select style={{ width: 170 }} value={birim ?? ""} options={birimSecenekleri} onChange={(v) => setBirim(v || undefined)} />
        <Segmented
          value={tur}
          onChange={(v) => setTur(String(v))}
          options={[
            { value: "TUMU", label: "Tümü" },
            { value: "SERVIS", label: "Servis" },
            { value: "BAKIM", label: "Bakım" },
          ]}
        />
        {yetkili("servis_rapor.disaaktar") && (
          <Button
            icon={<FileExcelOutlined />}
            onClick={() => window.open(planlamaApi.excelYolu(basStr, bitStr, suzgec), "_blank")}
          >
            Excel
          </Button>
        )}
        {!ekran.lg && (
          <Button icon={<UnorderedListOutlined />} onClick={() => setHavuzAcik(true)}>
            Havuz ({havuz.data?.toplam ?? 0})
          </Button>
        )}
      </Space>
      <Row gutter={12}>
        <Col xs={24} lg={17}>
          <Card
            size="small"
            loading={takvim.isLoading}
            title={
              <Space>
                <CalendarOutlined />
                {gorunum === "gun"
                  ? gun.format("DD.MM.YYYY dddd")
                  : `${bas.format("DD.MM.YYYY")} – ${bit.format("DD.MM.YYYY")}`}
              </Space>
            }
          >
            {takvim.isError ? (
              <Empty description={(takvim.error as ApiError).message} />
            ) : (
              takvimGovdesi()
            )}
          </Card>
        </Col>
        {ekran.lg && (
          <Col lg={7}>
            <Card size="small" title="Plansız havuz">
              {havuzIcerik}
            </Card>
          </Col>
        )}
      </Row>
      {!ekran.lg && (
        <Drawer open={havuzAcik} onClose={() => setHavuzAcik(false)} width="100%" title="Plansız havuz">
          {havuzIcerik}
        </Drawer>
      )}
    </>
  );

  return (
    <Card title="Planlama" styles={{ body: { paddingTop: 8 } }}>
      <Tabs
        items={[
          { key: "takvim", label: "Takvim", children: takvimSekmesi },
          { key: "kaynak", label: "Kaynak", children: <KaynakSekmesi birim={birim} /> },
          ...(yetkili("servis_rapor.gor")
            ? [{ key: "uyum", label: "Plan Uyumu", children: <PlanUyumuSekmesi birim={birim} /> }]
            : []),
          { key: "araclar", label: "Servis Araçları", children: <AracSekmesi /> },
        ]}
      />
      {kartCekmecesi}
      {kpiCekmecesi}
      <Drawer
        open={bolgeIs !== null}
        onClose={() => setBolgeIs(null)}
        width={ekran.md ? 560 : "100%"}
        title={`Bölge önerisi — ${bolgeIs?.so_no ?? ""}`}
      >
        {bolge.isLoading ? (
          <Card loading size="small" />
        ) : bolge.isError ? (
          <Empty description={(bolge.error as ApiError).message} />
        ) : bolge.data?.mesaj ? (
          <Empty description={bolge.data.mesaj} />
        ) : (
          bolge.data && (
            <>
              <Typography.Paragraph type="secondary">
                {bolge.data.il}
                {bolge.data.ilce ? ` / ${bolge.data.ilce}` : " (ilçe girilmemiş; il düzeyinde)"} · ±
                {bolge.data.gun_araligi} gün. Seçilen iş ziyarete eklenmez, ayrı plan olarak kaydedilir.
              </Typography.Paragraph>
              <Typography.Title level={5}>Yakın ziyaretler</Typography.Title>
              {bolge.data.ziyaretler.length === 0 ? (
                <Empty description="Bu bölgede yakın ziyaret yok" />
              ) : (
                bolge.data.ziyaretler.map((z: BolgeZiyareti) => (
                  <Card key={z.kart_anahtari} size="small" style={{ marginBottom: 6 }}>
                    <Space wrap style={{ fontSize: 12 }}>
                      <Typography.Text strong>{dayjs(z.plan_tarihi).format("DD.MM.YYYY")}</Typography.Text>
                      <span>
                        {z.baslangic_saati ?? "saat belirsiz"}
                        {z.bitis_saati ? `–${z.bitis_saati}` : ""}
                      </span>
                      <span>{z.ziyaret_no ?? z.is_nolari.join(", ")}</span>
                    </Space>
                    <div style={{ fontSize: 12 }}>
                      {z.musteri}
                      {z.lokasyon ? ` · ${z.lokasyon}` : ""}
                    </div>
                    <div style={{ fontSize: 11, color: "#888" }}>
                      {z.ekip.map((u) => u.ad).join(", ") || "Ekip yok"}
                      {z.arac_plaka ? ` · ${z.arac_plaka}` : ""}
                    </div>
                    <Button
                      size="small"
                      style={{ marginTop: 4 }}
                      onClick={() => {
                        const hedef = bolgeIs!;
                        setBolgeIs(null);
                        setPencere({
                          mod: "tekli",
                          isIdler: [hedef.is_id],
                          birim: hedef.birim,
                          gun: z.plan_tarihi,
                          varsayilan: {
                            baslangic_saati: z.onerilen_baslangic,
                            teknisyen_idler: z.ekip.filter((u) => u.rol === "TEKNISYEN").map((u) => u.user_id),
                            arac_id: z.arac_id,
                          },
                        });
                      }}
                    >
                      Bu ziyaretten sonra ayrı planla{z.onerilen_baslangic ? ` (${z.onerilen_baslangic})` : ""}
                    </Button>
                  </Card>
                ))
              )}
              <Typography.Title level={5} style={{ marginTop: 12 }}>
                Aynı bölgedeki plansız işler
              </Typography.Title>
              {bolge.data.plansiz_isler.length === 0 ? (
                <Empty description="Plansız iş yok" />
              ) : (
                bolge.data.plansiz_isler.map((s) => (
                  <div key={s.is_id} style={{ display: "flex", gap: 6, alignItems: "center", padding: "2px 0" }}>
                    <div style={{ flex: 1, minWidth: 0, fontSize: 12 }}>
                      <Typography.Text strong>{s.so_no}</Typography.Text> {s.musteri}
                      {s.lokasyon ? ` · ${s.lokasyon}` : ""}
                      <div style={{ color: "#888" }}>{s.yas_gun ?? "?"} gün bekliyor</div>
                    </div>
                    <Button
                      size="small"
                      onClick={() => {
                        setBolgeIs(null);
                        setPencere({ mod: "tekli", isIdler: [s.is_id], birim: s.birim, gun: gun.format(ISO) });
                      }}
                    >
                      Planla
                    </Button>
                  </div>
                ))
              )}
            </>
          )
        )}
      </Drawer>
      {pencere && (
        <PlanPenceresi
          acik
          mod={pencere.mod}
          isIdler={pencere.isIdler}
          birim={pencere.birim}
          mevcut={pencere.mevcut}
          varsayilanGun={pencere.gun ?? acikKart?.gun}
          varsayilan={pencere.varsayilan}
          onKapat={() => setPencere(null)}
          onKaydedildi={() => {
            setPencere(null);
            setHavuzSecili([]);
            setKartSecili([]);
            tazele();
          }}
        />
      )}
      <Modal
        open={geriAl !== null}
        title={`Planı geri al — ${geriAl?.so_no ?? ""}`}
        okText="Geri Al"
        okButtonProps={{ danger: true, loading: geriAlMut.isPending }}
        cancelText="Vazgeç"
        onCancel={() => setGeriAl(null)}
        onOk={() => void geriAlForm.validateFields().then((v) => geriAlMut.mutate(v))}
      >
        <Form form={geriAlForm} layout="vertical">
          <Form.Item name="neden" label="Neden" rules={[{ required: true, message: "Neden zorunlu" }]}>
            <Select options={Object.entries(PLAN_NEDENLERI).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item
            name="not"
            label="Açıklama"
            dependencies={["neden"]}
            rules={[
              ({ getFieldValue }) => ({
                validator: (_, v: string | undefined) =>
                  getFieldValue("neden") === "DIGER" && !v?.trim()
                    ? Promise.reject(new Error("'Diğer' nedeninde açıklama zorunlu"))
                    : Promise.resolve(),
              }),
            ]}
          >
            <Input maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer
        open={gecmisIs !== null}
        onClose={() => setGecmisIs(null)}
        width={ekran.md ? 480 : "100%"}
        title={`Plan geçmişi — ${gecmisIs?.so_no ?? ""}`}
      >
        {gecmis.isLoading ? (
          <Card loading size="small" />
        ) : (
          <Timeline
            items={(gecmis.data ?? []).map((p) => ({
              color: p.aktif ? "green" : p.iptal_nedeni ? "red" : "gray",
              children: (
                <>
                  <Typography.Text strong>
                    {DEGISIM_ETIKETLERI[p.degisim] ?? p.degisim}: {dayjs(p.plan_tarihi).format("DD.MM.YYYY")}{" "}
                    {p.baslangic_saati ?? "saat belirsiz"} ({p.sure_dk} dk)
                  </Typography.Text>
                  <div style={{ fontSize: 12 }}>
                    {p.planlayan ?? "sistem"} · {p.olusturma ? dayjs(p.olusturma).format("DD.MM.YYYY HH:mm") : ""}
                  </div>
                  {p.degisim_nedeni && (
                    <div style={{ fontSize: 12 }}>
                      Neden: {PLAN_NEDENLERI[p.degisim_nedeni] ?? p.degisim_nedeni}
                      {p.degisim_notu ? ` — ${p.degisim_notu}` : ""}
                    </div>
                  )}
                  {p.iptal_nedeni && (
                    <div style={{ fontSize: 12 }}>
                      Geri alındı: {PLAN_NEDENLERI[p.iptal_nedeni] ?? p.iptal_nedeni}
                      {p.iptal_notu ? ` — ${p.iptal_notu}` : ""}
                    </div>
                  )}
                  {p.cakisma_gerekcesi && (
                    <div style={{ fontSize: 12 }}>Çakışma gerekçesi: {p.cakisma_gerekcesi}</div>
                  )}
                  <div style={{ fontSize: 12, color: "#888" }}>
                    {p.ekip.map((u) => u.ad).join(", ") || "ekip yok"}
                  </div>
                </>
              ),
            }))}
          />
        )}
      </Drawer>
    </Card>
  );
}

// --- Servis araç havuzu (TS-048) ------------------------------------------------------

function AracSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const yazabilir = yetkili("servis.arac_yaz");
  const [duzenlenen, setDuzenlenen] = useState<Arac | "yeni" | null>(null);
  const [form] = Form.useForm<{ plaka: string; birim?: string; notlar?: string; is_active?: boolean }>();
  const liste = useQuery({ queryKey: ["servis-araclar-tumu"], queryFn: () => planlamaApi.araclar() });

  const kaydet = useMutation({
    mutationFn: async (v: { plaka: string; birim?: string; notlar?: string; is_active?: boolean }) => {
      if (duzenlenen === "yeni") {
        return planlamaApi.aracEkle({ plaka: v.plaka, birim: v.birim || null, notlar: v.notlar || null });
      }
      const a = duzenlenen as Arac;
      return planlamaApi.aracGuncelle({
        id: a.id,
        version: a.version,
        plaka: v.plaka,
        birim: v.birim || null,
        ortak_havuz: !v.birim,
        notlar: v.notlar ?? "",
        is_active: v.is_active,
      });
    },
    onSuccess: () => {
      message.success("Araç kaydedildi");
      setDuzenlenen(null);
      void qc.invalidateQueries({ queryKey: ["servis-araclar-tumu"] });
      void qc.invalidateQueries({ queryKey: ["servis-araclar"] });
    },
    onError: (e: ApiError) =>
      message.error(e.cakisma ? `${e.message} Gerekirse sayfayı yenileyin.` : e.message),
  });

  const ac = (a: Arac | "yeni") => {
    form.resetFields();
    if (a !== "yeni") {
      form.setFieldsValue({ plaka: a.plaka, birim: a.birim ?? "", notlar: a.notlar ?? "", is_active: a.is_active });
    } else {
      form.setFieldsValue({ birim: "", is_active: true });
    }
    setDuzenlenen(a);
  };

  return (
    <>
      {yazabilir && (
        <Button type="primary" style={{ marginBottom: 8 }} onClick={() => ac("yeni")}>
          Araç Ekle
        </Button>
      )}
      <Table
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data ?? []}
        pagination={false}
        scroll={{ x: 480 }}
        columns={[
          { title: "Plaka", dataIndex: "plaka" },
          {
            title: "Birim",
            dataIndex: "birim",
            render: (b: string | null) => (b ? BIRIM_ETIKETLERI[b] ?? b : <Tag>Ortak havuz</Tag>),
          },
          { title: "Zimmet", dataIndex: "zimmetli", render: (z: string | null) => z ?? "—" },
          {
            title: "Durum",
            dataIndex: "is_active",
            render: (a: boolean) => (a ? <Tag color="green">Aktif</Tag> : <Tag>Pasif</Tag>),
          },
          { title: "Not", dataIndex: "notlar", ellipsis: true },
          ...(yazabilir
            ? [
                {
                  title: "",
                  key: "islem",
                  render: (_: unknown, a: Arac) => (
                    <Button size="small" onClick={() => ac(a)}>
                      Düzenle
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        open={duzenlenen !== null}
        title={duzenlenen === "yeni" ? "Araç Ekle" : "Aracı Düzenle"}
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={kaydet.isPending}
        onCancel={() => setDuzenlenen(null)}
        onOk={() => void form.validateFields().then((v) => kaydet.mutate(v))}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="plaka" label="Plaka" rules={[{ required: true, min: 4, max: 20 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="birim" label="Birim">
            <Select
              options={[
                { value: "", label: "Ortak havuz" },
                ...BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] })),
              ]}
            />
          </Form.Item>
          <Form.Item name="notlar" label="Not">
            <Input.TextArea maxLength={1000} autoSize={{ minRows: 1, maxRows: 3 }} />
          </Form.Item>
          {duzenlenen !== "yeni" && (
            <Form.Item name="is_active" label="Aktif" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );
}
