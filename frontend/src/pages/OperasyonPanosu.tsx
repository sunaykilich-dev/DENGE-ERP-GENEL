/**
 * Operasyon Merkezi panosu (2026-11-18, kullanıcı kararları).
 *
 * Servis şefinin gün boyu açık tuttuğu "şu an neye müdahale etmeliyim"
 * ekranı. Sabah planı Servis Planlama'da yapılır; burada planın gün içindeki
 * sapması ve araya giren işin hızla verilmesi izlenir:
 *
 * - **Tayin bekleyenler:** en çok kaçan iş. Bekleme MESAİ dakikasıyla
 *   sayılır, eşik Parametreler'dedir (kritik / diğer). Sıra sunucudan:
 *   önce süresi geçenler, sonra öncelik, sonra en uzun bekleyen.
 * - **Plandan sapanlar:** planlı saati geçip yola çıkılmayan, beklemesi
 *   uzayan, bakım vadesi geçen işler.
 * - **Ekip durumu:** yolda / sahada / boşta (teknisyenin zaman sayacından).
 *
 * Hesapların tamamı sunucuda (`GET /operasyon/pano`); bu ekran süre türetmez.
 */
import { UserAddOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Empty, Modal, Skeleton, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { BIRIM_ETIKETLERI } from "../api/personel";
import {
  operasyonApi,
  type EkipDurumu,
  type EkipUyesi,
  type PanoSatiri,
  type Sapma,
  type SapmaTuru,
  type TayinBekleyen,
} from "../api/servisOperasyon";
import { teknikServisApi } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import { IsDetayCekmecesi } from "./ServisIsleriPage";

const YENILEME_MS = 60_000;

const DURUM_ADI: Record<EkipDurumu, string> = { BOSTA: "Boşta", YOLDA: "Yolda", SAHADA: "Sahada" };
const DURUM_SIRASI: Record<EkipDurumu, number> = { BOSTA: 0, YOLDA: 1, SAHADA: 2 };
const FAALIYET_ADI: Record<string, string> = {
  YOL: "yolda",
  SAHA: "sahada",
  UZAKTAN: "uzaktan",
  ATOLYE: "atölyede",
  TEST: "testte",
  BEKLEME: "beklemede",
  DIGER: "çalışıyor",
};
const SAPMA_ADI: Record<SapmaTuru, string> = {
  PLAN_SAATI: "Planlı saati geçti",
  BEKLEME: "Bekleme süresi geçti",
  BAKIM_VADESI: "Bakım vadesi geçti",
};
/** Toplamı satır sınırını aşan türde "tümü" bağlantısı (aynı KPI süzgeci). */
const SAPMA_KPI: Partial<Record<SapmaTuru, string>> = {
  BEKLEME: "bekleme_bitis_gecti",
  BAKIM_VADESI: "vadesi_gecen_bakim",
};

/** Mesai dakikası: kısa sürede dakika/saat; uzun beklemede "N gündür" (açılıştan). */
function sure(dk: number, acilis?: string): string {
  if (dk < 60) return `${dk} dk`;
  if (dk < 600 || !acilis) return `${Math.floor(dk / 60)} sa ${dk % 60} dk`;
  return `${Math.max(1, dayjs().diff(dayjs(acilis), "day"))} gündür`;
}

function mahal(r: PanoSatiri): string {
  return r.musteri?.title ?? r.customer_name_raw ?? "—";
}

function NoRozeti({ r, onClick }: { r: PanoSatiri; onClick: () => void }) {
  const oncelik = r.oncelik === "KRITIK" ? " kritik" : r.oncelik === "YUKSEK" ? " yuksek" : "";
  return (
    <button type="button" className={`fl-no-rozet op-no${oncelik}`} onClick={onClick}>
      {r.so_no}
    </button>
  );
}

function IsHucresi({ r, onClick }: { r: PanoSatiri; onClick: () => void }) {
  return (
    <div>
      <button type="button" className="op-konu" onClick={onClick}>
        {r.konu}
      </button>
      <div className="op-mahal">{mahal(r)}</div>
    </div>
  );
}

/** Tek tıkla tayin: işin biriminin ekibi, boşta olanlar ve az işi olanlar üstte. */
function HizliTayin({
  is,
  ekip,
  kapat,
  ekipKur,
}: {
  is: TayinBekleyen;
  ekip: EkipUyesi[];
  kapat: () => void;
  ekipKur: (is: TayinBekleyen) => void;
}) {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const adaylar = ekip
    .filter((k) => k.birimler.includes(is.birim))
    .sort(
      (a, b) =>
        DURUM_SIRASI[a.durum] - DURUM_SIRASI[b.durum] ||
        a.bugun_planli + a.acik_atanmis - (b.bugun_planli + b.acik_atanmis) ||
        a.ad.localeCompare(b.ad, "tr"),
    );
  const ver = useMutation({
    mutationFn: (k: EkipUyesi) =>
      teknikServisApi.topluAta(
        [is.id],
        [{ user_id: k.user_id, rol: k.saha_rolu === "SEF" ? "SEF" : "TEKNISYEN", is_lead: true }],
        "EKLE",
      ),
    onSuccess: (_, k) => {
      message.success(`${is.so_no} → ${k.ad}`);
      void qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("operasyon") });
      kapat();
    },
    onError: (e: Error) => message.error(e.message),
  });
  return (
    <Modal
      open
      title={`Tayin et — ${is.so_no}`}
      onCancel={kapat}
      footer={[
        <Button key="ekip" onClick={() => ekipKur(is)}>
          Birden çok kişi…
        </Button>,
        <Button key="vazgec" onClick={kapat}>
          Vazgeç
        </Button>,
      ]}
      destroyOnHidden
    >
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {BIRIM_ETIKETLERI[is.birim] ?? is.birim} ekibi. Boşta olanlar ve bugün az işi olanlar üstte; seçilen kişi
        sorumlu olur.
      </Typography.Text>
      {adaylar.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Bu birimde tayin edilebilir personel yok" />
      ) : (
        <ul className="op-aday-listesi">
          {adaylar.map((k) => (
            <li key={k.user_id}>
              <button type="button" className="op-aday" disabled={ver.isPending} onClick={() => ver.mutate(k)}>
                <span className="op-avatar">{basHarfler(k.ad)}</span>
                <span className="op-aday-ad">
                  <b>{k.ad}</b>
                  <span>
                    Bugün {k.bugun_planli} planlı · {k.acik_atanmis} açık iş
                  </span>
                </span>
                <span className={`op-durum ${k.durum.toLowerCase()}`}>{DURUM_ADI[k.durum]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

function basHarfler(ad: string): string {
  return ad
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toLocaleUpperCase("tr"))
    .join("");
}

function Bolum({
  baslik,
  sayi,
  kirmizi,
  not,
  children,
}: {
  baslik: string;
  sayi?: number;
  kirmizi?: boolean;
  not?: string;
  children: ReactNode;
}) {
  return (
    <section className="op-bolum">
      <div className="op-bolum-bas">
        <h2>{baslik}</h2>
        {sayi !== undefined && <span className={`op-sayi${kirmizi ? " kirmizi" : ""}`}>{sayi}</span>}
        {not && <span className="op-not">{not}</span>}
      </div>
      {children}
    </section>
  );
}

export default function OperasyonPanosu({
  birim,
  tumIsler,
  ekipKur,
}: {
  birim?: string;
  /** "Tüm açık işler" sekmesine geçiş. */
  tumIsler: () => void;
  /** Birden çok kişilik ekip tayini (mevcut toplu tayin penceresi). */
  ekipKur: (isId: number, birim: string) => void;
}) {
  const { yetkili } = useAuth();
  const git = useNavigate();
  const [tayinIs, setTayinIs] = useState<TayinBekleyen | null>(null);
  const [detayId, setDetayId] = useState<number | null>(null);
  const planlayabilir = yetkili("servis.planla");
  const pano = useQuery({
    queryKey: ["operasyon-pano", birim],
    queryFn: () => operasyonApi.pano(birim),
    refetchInterval: YENILEME_MS,
  });
  const sozluk = useQuery({
    queryKey: ["servis-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    staleTime: 5 * 60_000,
    enabled: detayId != null,
  });

  if (pano.error) return <Alert type="error" showIcon message={(pano.error as Error).message} />;
  if (!pano.data) return <Skeleton active paragraph={{ rows: 8 }} />;
  const d = pano.data;
  const ac = (r: PanoSatiri) => setDetayId(r.id);

  const tayinSutunlari: ColumnsType<TayinBekleyen> = [
    { title: "İş No", key: "no", width: 170, render: (_, r) => <NoRozeti r={r} onClick={() => ac(r)} /> },
    { title: "Açıklama / Mahal", key: "is", render: (_, r) => <IsHucresi r={r} onClick={() => ac(r)} /> },
    {
      title: "Birim",
      dataIndex: "birim",
      width: 150,
      responsive: ["md"],
      render: (b: string) => BIRIM_ETIKETLERI[b] ?? b,
    },
    {
      title: "Bekliyor",
      key: "sure",
      width: 220,
      render: (_, r) => {
        const kalan = r.esik_dk - r.bekleme_dk;
        return (
          <Tooltip title={`Açılış ${dayjs(r.created_at).format("DD.MM.YYYY HH:mm")} · süre yalnız mesaide sayılır`}>
            <span className={`op-sure${r.gecikti ? " gecikti" : ""}`}>
              {sure(r.bekleme_dk, r.created_at)}
              {r.gecikti ? (
                <span className="op-etiket kirmizi">
                  {r.bekleme_dk < 600 ? `${sure(r.bekleme_dk - r.esik_dk)} gecikti` : "gecikti"}
                </span>
              ) : kalan <= r.esik_dk * 0.3 ? (
                <span className="op-etiket turuncu">{kalan} dk kaldı</span>
              ) : null}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: "",
      key: "eylem",
      width: 110,
      align: "right",
      render: (_, r) =>
        planlayabilir ? (
          <Button type="primary" size="small" icon={<UserAddOutlined />} onClick={() => setTayinIs(r)}>
            Tayin et
          </Button>
        ) : null,
    },
  ];

  const sapmaSutunlari: ColumnsType<Sapma> = [
    { title: "İş No", key: "no", width: 170, render: (_, r) => <NoRozeti r={r} onClick={() => ac(r)} /> },
    { title: "Açıklama / Mahal", key: "is", render: (_, r) => <IsHucresi r={r} onClick={() => ac(r)} /> },
    {
      title: "Neden",
      key: "neden",
      width: 240,
      render: (_, r) => (
        <div>
          <Tag color={r.sapma === "BAKIM_VADESI" ? "blue" : "orange"} style={{ marginInlineEnd: 0 }}>
            {SAPMA_ADI[r.sapma]}
          </Tag>
          <div className="op-mahal" style={{ textTransform: "none" }}>
            {r.sapma === "PLAN_SAATI" && r.plan_baslangic
              ? `Plan ${dayjs(r.plan_baslangic).format("HH:mm")} · yola çıkılmadı`
              : r.sapma === "BEKLEME" && r.aktif_bekleme
                ? r.aktif_bekleme
                : null}
          </div>
        </div>
      ),
    },
    { title: "Sorumlu", key: "sorumlu", width: 170, responsive: ["md"], render: (_, r) => r.sorumlu?.ad ?? "—" },
    {
      title: "",
      key: "eylem",
      width: 110,
      align: "right",
      render: (_, r) =>
        r.sapma === "BAKIM_VADESI" && planlayabilir ? (
          <Button size="small" onClick={() => git(`/servis-planlama?is=${r.id}`)}>
            Planla
          </Button>
        ) : (
          <Button size="small" onClick={() => ac(r)}>
            Aç
          </Button>
        ),
    },
  ];
  const fazlasi = (Object.keys(d.sapma_toplamlari) as SapmaTuru[])
    .map((t) => ({ t, fazla: d.sapma_toplamlari[t] - d.sapmalar.filter((s) => s.sapma === t).length }))
    .filter((x) => x.fazla > 0);

  const ekip = [...d.ekip].sort(
    (a, b) => DURUM_SIRASI[a.durum] - DURUM_SIRASI[b.durum] || a.ad.localeCompare(b.ad, "tr"),
  );
  const o = d.ozet;

  return (
    <div className="op-pano">
      <div className="op-ozet">
        <span className="op-ozet-bas">Bugün</span>
        <Link to="/servis-isleri?kpi=bugun_planli">
          <strong>{o.bugun_planli}</strong> planlı
        </Link>
        <span>
          <strong>{o.bugun_tamamlanan}</strong> tamamlandı
        </span>
        <span>
          <strong>{o.sahada}</strong> sahada
        </span>
        <span>
          <strong>{o.yolda}</strong> yolda
        </span>
        <a href="#op-tayin" className={o.tayin_bekleyen ? "kirmizi" : undefined}>
          <strong>{o.tayin_bekleyen}</strong> tayin bekliyor
        </a>
        <a href="#op-sapma" className={o.sapma ? "kirmizi" : undefined}>
          <strong>{o.sapma}</strong> plandan saptı
        </a>
        <Button type="link" size="small" className="op-ozet-tum" onClick={tumIsler}>
          Tüm açık işler →
        </Button>
      </div>

      <div id="op-tayin">
        <Bolum
          baslik="Tayin bekleyenler"
          sayi={o.tayin_bekleyen}
          kirmizi={o.tayin_geciken > 0}
          not={`Süre mesaide sayılır · eşik: kritik ${d.esikler.kritik_dk} dk, diğer ${d.esikler.diger_dk} dk`}
        >
          <Table<TayinBekleyen>
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={d.tayin_bekleyenler}
            columns={tayinSutunlari}
            rowClassName={(r) => (r.gecikti ? "op-satir-gecikti" : "")}
            locale={{ emptyText: <div className="op-bos">✓ Tayin bekleyen iş yok</div> }}
          />
        </Bolum>
      </div>

      <div id="op-sapma">
        <Bolum baslik="Plandan sapanlar" sayi={o.sapma} not="Sabah planının gerisinde kalanlar">
          <Table<Sapma>
            rowKey={(r) => `${r.sapma}-${r.id}`}
            size="small"
            pagination={false}
            dataSource={d.sapmalar}
            columns={sapmaSutunlari}
            locale={{ emptyText: <div className="op-bos">✓ Plandan sapan iş yok</div> }}
          />
          {fazlasi.map(({ t, fazla }) => (
            <div key={t} className="op-fazla">
              {SAPMA_KPI[t] ? (
                <Link to={`/servis-isleri?kpi=${SAPMA_KPI[t]}`}>
                  {SAPMA_ADI[t]}: {fazla} iş daha → Servis İşleri
                </Link>
              ) : (
                `${SAPMA_ADI[t]}: ${fazla} iş daha`
              )}
            </div>
          ))}
        </Bolum>
      </div>

      <Bolum baslik="Ekip durumu" not={`${o.bosta} boşta · ${o.yolda} yolda · ${o.sahada} sahada`}>
        {ekip.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Tayin edilebilir saha personeli yok" />
        ) : (
          <div className="op-ekip">
            {ekip.map((k) => (
              <div key={k.user_id} className={`op-kisi ${k.durum.toLowerCase()}`}>
                <span className="op-avatar">{basHarfler(k.ad)}</span>
                <div className="op-kisi-ad">
                  <b>{k.ad}</b>
                  <span>
                    {k.acik_sayac
                      ? `${k.acik_sayac.so_no} · ${FAALIYET_ADI[k.acik_sayac.faaliyet] ?? ""}`
                      : `Bugün ${k.bugun_planli} planlı iş`}
                  </span>
                </div>
                <span className={`op-durum ${k.durum.toLowerCase()}`}>{DURUM_ADI[k.durum]}</span>
              </div>
            ))}
          </div>
        )}
      </Bolum>

      <div className="op-guncel">
        Güncelleme {dayjs(d.sunucu_zamani).format("HH:mm")} · dakikada bir kendiliğinden yenilenir
      </div>

      {tayinIs && (
        <HizliTayin
          is={tayinIs}
          ekip={d.ekip}
          kapat={() => setTayinIs(null)}
          ekipKur={(r) => {
            setTayinIs(null);
            ekipKur(r.id, r.birim);
          }}
        />
      )}
      {detayId != null && (
        <IsDetayCekmecesi
          key={detayId}
          id={detayId}
          sozluk={sozluk.data}
          isAc={setDetayId}
          kapat={() => {
            setDetayId(null);
            void pano.refetch();
          }}
        />
      )}
    </div>
  );
}
