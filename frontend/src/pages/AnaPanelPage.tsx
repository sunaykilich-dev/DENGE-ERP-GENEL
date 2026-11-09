import {
  AppstoreAddOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  ColumnWidthOutlined,
  EditOutlined,
  EyeInvisibleOutlined,
  FilterOutlined,
  HolderOutlined,
  ReloadOutlined,
  TeamOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, DatePicker, Drawer, Empty, Select, Skeleton, Tag, Tooltip } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState, type DragEvent, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { anaPanelApi, anaPanelParametreleri, type AnaPanelSuzgeci, type AnaPanelYaniti } from "../api/anaPanel";
import {
  anaPanelDuzeniApi,
  DUZEN_SORGU_ANAHTARI,
  ekle,
  tasi,
  type DuzenOgesi,
  type DuzenYaniti,
  type KatalogOgesi,
} from "../api/anaPanelDuzeni";
import { useAuth } from "../auth/AuthContext";
import { useSirket } from "../auth/SirketContext";
import { BILESEN_CIZIMLERI, type BilesenBaglami } from "./anaPanel/kayit";
import RolDuzenleriPenceresi from "./anaPanel/RolDuzenleriPenceresi";
import { Kart, listeSuzgeci, suzgecOku, YENILEME_MS } from "./anaPanel/servisParcalari";
import "./anaPanel.css";

/**
 * Ana Panel — kişiye özel düzenlenebilir pano (KARARLAR 2026-11-04 §4;
 * KARARLAR 2026-11-09 S8; G7.2/G7.3/G8.1).
 *
 * Düzen SUNUCUDADIR (`GET /api/ana-panel/duzen`): kullanıcının kendi düzeni →
 * rol varsayılanı → sistem varsayılanı (bugünkü panel). Bileşen kataloğu
 * sunucuda izinle süzülür; kişi göremeyeceği veriyi ekleyemez. Ön yüz yalnız
 * çizer (`anaPanel/kayit.tsx`).
 *
 * Düzenleme (G1.9 — tek düğme): "Düzenle" → bileşenleri sürükle ya da ↑/↓ ile
 * taşı, Dar/Geniş seç, gizle; "Bileşen Ekle" katalog çekmecesini açar;
 * "Varsayılana Dön" rol/sistem düzenini getirir. Değişiklikler yalnız
 * "Kaydet"te sunucuya gider (iyimser kilit `version`; 409 → yenile).
 *
 * Teknik servis verisi (`GET /api/teknik-servis/ana-panel`, `servis.gor`) yalnız
 * panelde servis bileşeni görünürken istenir; süzgeç çubuğu da yalnız o zaman
 * çizilir. Süzgeçler adres çubuğunda tutulur; sekme görünürken 60 sn'de bir yenilenir.
 */

type Secenek = { value: string | number; label: string };

function ServisSuzgeci({
  suzgec,
  veri,
  yukleniyor,
  yenile,
  degistir,
}: {
  suzgec: AnaPanelSuzgeci;
  veri?: AnaPanelYaniti;
  yukleniyor: boolean;
  yenile: () => void;
  degistir: (yeni: Partial<AnaPanelSuzgeci>) => void;
}) {
  const yonlendir = useNavigate();
  const { menuBirimleri } = useSirket();
  const sec = veri?.secenekler;
  const aralik: [Dayjs, Dayjs] | null = veri ? [dayjs(veri.donem.bas), dayjs(veri.donem.bit)] : null;
  const secim = (deger: string | number | undefined, secenekler: Secenek[]) => ({
    value: deger,
    options: secenekler,
    allowClear: true,
    placeholder: "Tümü",
    size: "small" as const,
    showSearch: { optionFilterProp: "label" as const },
    popupMatchSelectWidth: false,
  });
  return (
    <div className="ap-suzgec" role="search" aria-label="Ana panel süzgeçleri">
      <div className="ap-suzgec-alan">
        <span>Bölüm</span>
        <Select
          aria-label="Bölüm"
          {...secim(
            suzgec.birim,
            (sec?.birimler ?? [])
              .filter((b) => !menuBirimleri || menuBirimleri.has(b.kod))
              .map((b) => ({ value: b.kod, label: b.ad })),
          )}
          onChange={(v) => degistir({ birim: v as string | undefined })}
        />
      </div>
      <div className="ap-suzgec-alan">
        <span>Durum</span>
        <Select
          aria-label="Durum"
          {...secim(suzgec.durum_grubu, (sec?.durum_gruplari ?? []).map((d) => ({ value: d.kod, label: d.ad })))}
          onChange={(v) => degistir({ durum_grubu: v as string | undefined })}
        />
      </div>
      <div className="ap-suzgec-alan">
        <span>Şef</span>
        <Select
          aria-label="Şef"
          {...secim(suzgec.sef_id, (sec?.sefler ?? []).map((k) => ({ value: k.id, label: k.ad ?? `#${k.id}` })))}
          onChange={(v) => degistir({ sef_id: v as number | undefined })}
        />
      </div>
      <div className="ap-suzgec-alan">
        <span>Personel</span>
        <Select
          aria-label="Personel"
          {...secim(suzgec.personel_id, (sec?.personel ?? []).map((k) => ({ value: k.id, label: k.ad ?? `#${k.id}` })))}
          onChange={(v) => degistir({ personel_id: v as number | undefined })}
        />
      </div>
      <div className="ap-suzgec-alan">
        <span>Lokasyon</span>
        <Select
          aria-label="Lokasyon"
          {...secim(suzgec.lokasyon_id, (sec?.lokasyonlar ?? []).map((l) => ({ value: l.id, label: l.ad ?? `#${l.id}` })))}
          notFoundContent="Açık işi olan lokasyon yok"
          onChange={(v) => degistir({ lokasyon_id: v as number | undefined })}
        />
      </div>
      <div className="ap-suzgec-alan">
        {/* B-14: dönemin neyi etkilediği ekranda yazsın. */}
        <Tooltip title="Açık iş, askıdaki ve SLA sayıları anlıktır; dönem yalnız tamamlanan işleri ve önceki döneme göre karşılaştırmayı etkiler.">
          <span style={{ cursor: "help", textDecoration: "underline dotted" }}>Dönem</span>
        </Tooltip>
        <DatePicker.RangePicker
          size="small"
          format="DD.MM.YYYY"
          value={aralik}
          allowClear
          style={{ width: 210 }}
          onChange={(d) =>
            degistir({
              bas: d?.[0] ? d[0].format("YYYY-MM-DD") : undefined,
              bit: d?.[1] ? d[1].format("YYYY-MM-DD") : undefined,
            })
          }
        />
      </div>
      <Tooltip title="İş listesinde bütün süzgeçler (tür, öncelik, müşteri, arama) kullanılabilir">
        <Button size="small" type="text" icon={<FilterOutlined />} onClick={() => yonlendir(listeSuzgeci(suzgec))}>
          Daha Fazla Filtre
        </Button>
      </Tooltip>
      <span className="ap-suzgec-sag">
        {veri && (
          <span className="ap-son-guncelleme" aria-live="polite">
            Son güncelleme: {dayjs(veri.guncelleme_zamani).format("DD.MM.YYYY HH:mm")}
          </span>
        )}
        <Button size="small" type="primary" icon={<ReloadOutlined />} loading={yukleniyor} onClick={yenile}>
          Yenile
        </Button>
      </span>
    </div>
  );
}

const KAYNAK_ADI: Record<string, string> = {
  KULLANICI: "Kişisel düzeniniz",
  ROL: "Rolünüzün varsayılan düzeni",
  SISTEM: "Standart düzen",
};

/** Katalog çekmecesi: izinli bileşenler, gruplu; panelde olan "Panelde" görünür. */
function KatalogCekmecesi({
  acik,
  kapat,
  katalog,
  taslak,
  ekleBilesen,
}: {
  acik: boolean;
  kapat: () => void;
  katalog: KatalogOgesi[];
  taslak: DuzenOgesi[];
  ekleBilesen: (k: KatalogOgesi) => void;
}) {
  const gruplar = useMemo(() => {
    const m = new Map<string, KatalogOgesi[]>();
    for (const k of katalog) m.set(k.grup, [...(m.get(k.grup) ?? []), k]);
    return [...m.entries()];
  }, [katalog]);
  return (
    <Drawer title="Bileşen Ekle" open={acik} onClose={kapat} size={380}>
      {katalog.length === 0 ? (
        <Empty description="Panelinize ekleyebileceğiniz bileşen yok" />
      ) : (
        gruplar.map(([grup, ogeler]) => (
          <div key={grup} className="ap-katalog-grup">
            <h3>{grup}</h3>
            {ogeler.map((k) => {
              const panelde = taslak.some((o) => o.kod === k.kod && o.gorunur);
              return (
                <div key={k.kod} className="ap-katalog-oge">
                  <div>
                    <b>{k.ad}</b>
                    <small>{k.aciklama}</small>
                  </div>
                  {panelde ? (
                    <Tag>Panelde</Tag>
                  ) : (
                    <Button size="small" type="primary" ghost onClick={() => ekleBilesen(k)}>
                      Ekle
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        ))
      )}
    </Drawer>
  );
}

export default function AnaPanelPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const { kullanici } = useAuth();
  const { menuBirimleri } = useSirket();
  const [arama, setArama] = useSearchParams();
  const suzgec = useMemo(() => suzgecOku(arama), [arama]);

  const duzen = useQuery({ queryKey: DUZEN_SORGU_ANAHTARI, queryFn: anaPanelDuzeniApi.getir });
  const [taslak, setTaslak] = useState<DuzenOgesi[] | null>(null);
  // "Varsayılana Dön" sonrası değişiklik yapılmadan Kaydet → kişisel düzen silinir.
  const [sifirlanacak, setSifirlanacak] = useState(false);
  const [katalogAcik, setKatalogAcik] = useState(false);
  const [rolPenceresi, setRolPenceresi] = useState(false);
  const [suruklenen, setSuruklenen] = useState<number | null>(null);
  const duzenleniyor = taslak !== null;

  const katalog = useMemo(() => new Map((duzen.data?.katalog ?? []).map((k) => [k.kod, k])), [duzen.data]);
  const liste = (taslak ?? duzen.data?.bilesenler ?? []).filter((o) => katalog.has(o.kod));
  const gorunenler = liste.filter((o) => o.gorunur);
  const servisGerekli = gorunenler.some((o) => BILESEN_CIZIMLERI[o.kod]?.servis);

  const panel = useQuery({
    queryKey: ["ana-panel", suzgec],
    queryFn: () => anaPanelApi.getir(suzgec),
    enabled: servisGerekli,
    refetchInterval: YENILEME_MS,
    refetchIntervalInBackground: false,
    placeholderData: (onceki) => onceki,
  });

  const degistirSuzgec = (yeni: Partial<AnaPanelSuzgeci>) => {
    setArama(anaPanelParametreleri({ ...suzgec, ...yeni }), { replace: true });
  };

  const taslakDegistir = (f: (t: DuzenOgesi[]) => DuzenOgesi[]) => {
    setSifirlanacak(false);
    setTaslak((t) => f(t ?? []));
  };

  const bitir = (y: DuzenYaniti, mesaj: string) => {
    qc.setQueryData(DUZEN_SORGU_ANAHTARI, y);
    setTaslak(null);
    setSifirlanacak(false);
    setKatalogAcik(false);
    message.success(mesaj);
  };
  const kaydet = useMutation({
    mutationFn: () =>
      sifirlanacak
        ? anaPanelDuzeniApi.sifirla(duzen.data?.version ?? null)
        : anaPanelDuzeniApi.kaydet(taslak ?? [], duzen.data?.version ?? null),
    onSuccess: (y) => bitir(y, sifirlanacak ? "Panel varsayılan düzene döndü" : "Panel düzeniniz kaydedildi"),
    onError: (e: Error) => {
      message.error(e.message);
      qc.invalidateQueries({ queryKey: DUZEN_SORGU_ANAHTARI });
    },
  });

  const baslat = () => {
    if (!duzen.data) return;
    setTaslak(duzen.data.bilesenler.filter((o) => katalog.has(o.kod)));
    setSifirlanacak(false);
  };
  const vazgec = () => {
    setTaslak(null);
    setSifirlanacak(false);
    setKatalogAcik(false);
  };
  const varsayilanaDon = () => {
    if (!duzen.data) return;
    setTaslak(duzen.data.varsayilan.bilesenler);
    setSifirlanacak(true);
  };

  // Liste indeksleri (gizliler dahil) üzerinden taşıma: görünen komşuyla yer değiştirir.
  const komsu = (i: number, yon: -1 | 1) => {
    let j = i + yon;
    while (j >= 0 && j < liste.length && !liste[j].gorunur) j += yon;
    return j >= 0 && j < liste.length ? j : null;
  };
  const tasiOge = (i: number, j: number | null) => {
    if (j == null) return;
    taslakDegistir(() => tasi(liste, i, j));
  };
  const surukleBirak = (hedef: number) => (e: DragEvent) => {
    e.preventDefault();
    if (suruklenen != null) tasiOge(suruklenen, hedef);
    setSuruklenen(null);
  };

  const baglam: BilesenBaglami = { servis: panel.data, kullaniciId: kullanici?.id, menuBirimleri };

  const hucre = (o: DuzenOgesi) => {
    const i = liste.indexOf(o);
    const k = katalog.get(o.kod);
    const cizim = BILESEN_CIZIMLERI[o.kod];
    if (!k || !cizim) return null;
    let icerik: ReactNode;
    if (cizim.servis && !panel.data) {
      icerik = panel.isError ? null : (
        <Kart baslik={k.ad}>
          <Skeleton active paragraph={{ rows: k.tur === "gosterge" ? 1 : 3 }} title={false} />
        </Kart>
      );
    } else {
      icerik = cizim.cizim(baglam);
    }
    if (!duzenleniyor && icerik == null) return null;
    const sinif = `ap-hucre ap-hucre--${k.tur} ap-hucre--${o.boyut === "GENIS" ? "genis" : "dar"}${
      suruklenen === i ? " ap-hucre--suruklenen" : ""
    }`;
    if (!duzenleniyor) {
      return (
        <div key={o.kod} className={sinif} data-bilesen={o.kod}>
          {icerik}
        </div>
      );
    }
    return (
      <div
        key={o.kod}
        className={`${sinif} ap-hucre--duzen`}
        data-bilesen={o.kod}
        draggable
        onDragStart={() => setSuruklenen(i)}
        onDragEnd={() => setSuruklenen(null)}
        onDragOver={(e) => e.preventDefault()}
        onDrop={surukleBirak(i)}
      >
        <div className="ap-duzen-arac" role="toolbar" aria-label={`${k.ad} düzeni`}>
          <HolderOutlined className="ap-tutamak" aria-hidden />
          <span className="ad" title={k.ad}>
            {k.ad}
          </span>
          <Tooltip title="Yukarı / sola taşı">
            <Button size="small" type="text" icon={<ArrowUpOutlined />} aria-label="Yukarı taşı" disabled={komsu(i, -1) == null} onClick={() => tasiOge(i, komsu(i, -1))} />
          </Tooltip>
          <Tooltip title="Aşağı / sağa taşı">
            <Button size="small" type="text" icon={<ArrowDownOutlined />} aria-label="Aşağı taşı" disabled={komsu(i, 1) == null} onClick={() => tasiOge(i, komsu(i, 1))} />
          </Tooltip>
          <Tooltip title={o.boyut === "GENIS" ? "Daralt" : "Genişlet"}>
            <Button
              size="small"
              type={o.boyut === "GENIS" ? "primary" : "text"}
              ghost={o.boyut === "GENIS"}
              icon={<ColumnWidthOutlined />}
              aria-label={o.boyut === "GENIS" ? "Daralt" : "Genişlet"}
              aria-pressed={o.boyut === "GENIS"}
              onClick={() =>
                taslakDegistir(() =>
                  liste.map((x) => (x.kod === o.kod ? { ...x, boyut: x.boyut === "GENIS" ? "DAR" : "GENIS" } : x)),
                )
              }
            />
          </Tooltip>
          <Tooltip title="Panelden kaldır (Bileşen Ekle'den geri eklenir)">
            <Button
              size="small"
              type="text"
              danger
              icon={<EyeInvisibleOutlined />}
              aria-label="Panelden kaldır"
              onClick={() => taslakDegistir(() => liste.map((x) => (x.kod === o.kod ? { ...x, gorunur: false } : x)))}
            />
          </Tooltip>
        </div>
        <div className="ap-duzen-icerik">
          {icerik ?? <div className="ap-bos">{k.ad}: bu süzgeçle gösterilecek veri yok.</div>}
        </div>
      </div>
    );
  };

  const veri = duzen.data;

  return (
    <div className="ap">
      <div className="ap-ust">
        <div>
          <h1 className="ap-baslik">Ana Panel</h1>
          <div className="ap-alt-baslik">
            {servisGerekli ? "Tüm operasyonların anlık özeti ve ekiplerin güncel durumu" : "Size özel özet"}
            {veri && (
              <Tag style={{ marginInlineStart: 8 }}>
                {KAYNAK_ADI[sifirlanacak ? veri.varsayilan.kaynak : duzenleniyor ? "KULLANICI" : veri.kaynak]}
              </Tag>
            )}
          </div>
        </div>
        {veri && (
          <div className="ap-duzen-dugmeleri">
            {duzenleniyor ? (
              <>
                <Button icon={<AppstoreAddOutlined />} onClick={() => setKatalogAcik(true)}>
                  Bileşen Ekle
                </Button>
                <Button icon={<UndoOutlined />} onClick={varsayilanaDon}>
                  Varsayılana Dön
                </Button>
                <Button onClick={vazgec}>Vazgeç</Button>
                <Button type="primary" loading={kaydet.isPending} onClick={() => kaydet.mutate()}>
                  Kaydet
                </Button>
              </>
            ) : (
              <>
                {veri.rol_duzenleyebilir && (
                  <Button icon={<TeamOutlined />} onClick={() => setRolPenceresi(true)}>
                    Rol Varsayılanları
                  </Button>
                )}
                <Button icon={<EditOutlined />} onClick={baslat} disabled={veri.katalog.length === 0}>
                  Düzenle
                </Button>
              </>
            )}
          </div>
        )}
      </div>

      {duzenleniyor && (
        <Alert
          type="info"
          showIcon
          title="Düzenleme kipi: bileşenleri sürükleyin ya da oklarla taşıyın, genişliğini değiştirin, kaldırın. Değişiklikler Kaydet'e basınca saklanır."
        />
      )}

      {servisGerekli && (
        <ServisSuzgeci
          suzgec={suzgec}
          veri={panel.data}
          yukleniyor={panel.isFetching}
          yenile={() => panel.refetch()}
          degistir={degistirSuzgec}
        />
      )}

      {duzen.isError && (
        <Alert
          type="error"
          showIcon
          title="Panel düzeni yüklenemedi"
          description={(duzen.error as Error)?.message}
          action={
            <Button size="small" onClick={() => duzen.refetch()}>
              Tekrar dene
            </Button>
          }
        />
      )}
      {servisGerekli && panel.isError && (
        <Alert
          type="error"
          showIcon
          title="Ana panel yüklenemedi"
          description={(panel.error as Error)?.message}
          action={
            <Button size="small" onClick={() => panel.refetch()}>
              Tekrar dene
            </Button>
          }
        />
      )}

      {!veri ? (
        duzen.isError ? null : <Skeleton active paragraph={{ rows: 10 }} />
      ) : gorunenler.length === 0 ? (
        <Empty
          description={
            veri.katalog.length === 0
              ? "Rolünüzün görebileceği bir panel bileşeni yok. Menüden çalışacağınız ekranı seçin."
              : "Panelinizde bileşen yok. Düzenle → Bileşen Ekle ile ekleyebilirsiniz."
          }
        />
      ) : (
        <div className={`ap-izgara${duzenleniyor ? " ap-izgara--duzen" : ""}`}>{gorunenler.map(hucre)}</div>
      )}

      {veri && (
        <KatalogCekmecesi
          acik={katalogAcik}
          kapat={() => setKatalogAcik(false)}
          katalog={veri.katalog}
          taslak={liste}
          ekleBilesen={(k) => taslakDegistir(() => ekle(liste, k))}
        />
      )}
      {veri?.rol_duzenleyebilir && (
        <RolDuzenleriPenceresi acik={rolPenceresi} kapat={() => setRolPenceresi(false)} />
      )}
    </div>
  );
}
