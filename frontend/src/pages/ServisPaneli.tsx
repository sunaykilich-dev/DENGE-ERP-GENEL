/**
 * Servis Paneli — tıklanabilir KPI kutucukları (TS-035, E01-14), SAP Fiori
 * launchpad görünümünde (rehber §2: 176×176 kutucuk, kalın başlık, sol altta
 * çizgi ikon + büyük KPI sayısı, grup başlıkları 20 px).
 *
 * Kural "sayı = liste": kutudaki sayı sunucunun `KPI_TANIMLARI` süzgecinden
 * gelir ve tıklanınca AYNI süzgeçle `/servis-isleri?kpi=<kod>` açılır; ekran
 * kendi sayısını hesaplamaz. Kutular kullanıcının birim/iş kapsamıyla sayılır.
 * Dönem seçimi (bugün / bu hafta / bu ay / son 30 gün) yalnız dönemsel
 * kutuları etkiler ve tarayıcıda hatırlanır. Mobilite `PanelPage` ayrı ve
 * değişmedi (K17).
 */
import {
  AlertOutlined,
  CalendarOutlined,
  CarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  FieldTimeOutlined,
  PauseCircleOutlined,
  PhoneOutlined,
  PieChartOutlined,
  ReloadOutlined,
  ToolOutlined,
  UserAddOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Segmented, Space, Typography } from "antd";
import dayjs from "dayjs";
import type { ReactNode } from "react";
import { useState } from "react";

import { DONEMLER, teknikServisApi, type PanelKutusu } from "../api/teknikServis";
import { TAYIN } from "../fiori/etiketler";
import { KpiKutucugu } from "../fiori/ListeRaporu";

const DONEM_ANAHTARI = "servisPaneli.donem";

function kayitliDonem(): string {
  try {
    const d = localStorage.getItem(DONEM_ANAHTARI);
    if (d && DONEMLER.some((x) => x.kod === d)) return d;
  } catch {
    /* gizli pencere / engelli depolama: varsayılan */
  }
  return "ay";
}

const GRUPLAR: { kod: PanelKutusu["grup"]; baslik: string; aciklama?: string }[] = [
  { kod: "SERVIS", baslik: "Servis İşleri", aciklama: "Anlık. Planlı bakım (PB) işleri bu kutucuklarda sayılmaz." },
  { kod: "DONEM", baslik: "Dönem" },
  { kod: "BAKIM", baslik: "Planlı Bakım" },
];

/** Sunucunun başlıklarındaki "atanmamış" dilini görünümde "tayin"e çevirir (kod aynı). */
const tayinDili = (s: string) =>
  s
    .replace(/Atanmamış/g, TAYIN.tayinEdilmemis)
    .replace(/atanmamış/g, TAYIN.tayinEdilmemis.toLocaleLowerCase("tr"))
    .replace(/Atanan/g, "Tayin edilen")
    .replace(/atanan/g, "tayin edilen")
    .replace(/Atandı/g, TAYIN.tayinEdildi)
    .replace(/atandı/g, "tayin edildi")
    .replace(/Atama/g, TAYIN.tayin)
    .replace(/atama/g, "tayin");

/** KPI koduna göre çizgi ikon (yalnız görünüm). */
function ikonu(kod: string): ReactNode {
  if (kod.includes("atanmamis")) return <UserAddOutlined />;
  if (kod.includes("kritik")) return <AlertOutlined />;
  if (kod.includes("bekle")) return <PauseCircleOutlined />;
  if (kod.includes("sahada")) return <CarOutlined />;
  if (kod.includes("gecik") || kod.includes("sure")) return <FieldTimeOutlined />;
  if (kod.includes("tamam") || kod.includes("kapanis")) return <CheckCircleOutlined />;
  if (kod.includes("uzaktan")) return <PhoneOutlined />;
  if (kod.includes("tekrar")) return <ReloadOutlined />;
  if (kod.includes("plan") || kod.includes("bugun")) return <CalendarOutlined />;
  if (kod.startsWith("bakim")) return <ToolOutlined />;
  return <ClockCircleOutlined />;
}

export default function ServisPaneli() {
  const [donem, setDonem] = useState(kayitliDonem);
  const panel = useQuery({
    queryKey: ["servis-paneli", donem],
    queryFn: () => teknikServisApi.panel(donem),
  });

  const donemSec = (d: string) => {
    setDonem(d);
    try {
      localStorage.setItem(DONEM_ANAHTARI, d);
    } catch {
      /* depolama yoksa yalnız bu oturumda geçerli */
    }
  };

  const kutular = panel.data?.kutular ?? [];
  const olcum = panel.data?.olcumler;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <div>
          <h2 className="fl-kutucuk-grubu-baslik" style={{ margin: 0 }}>
            Servis Paneli
          </h2>
          {panel.data && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Dönem: {panel.data.donem_adi} ({dayjs(panel.data.donem_baslangic).format("DD.MM.YYYY")} –{" "}
              {dayjs(panel.data.donem_bitis).format("DD.MM.YYYY")}). Kutucuğa tıklayınca aynı süzgeçle liste
              açılır.
            </Typography.Text>
          )}
        </div>
        <div style={{ maxWidth: "100%", overflowX: "auto" }}>
          <Segmented
            size="small"
            value={donem}
            onChange={(v) => donemSec(String(v))}
            options={DONEMLER.map((d) => ({ value: d.kod, label: d.ad }))}
          />
        </div>
      </div>

      {panel.isError && <Alert type="error" showIcon title={(panel.error as Error).message} />}

      {GRUPLAR.map((g) => {
        const grupKutulari = kutular.filter((k) => k.grup === g.kod);
        if (!panel.isLoading && grupKutulari.length === 0) return null;
        return (
          <section key={g.kod} aria-label={g.baslik}>
            <h3 className="fl-kutucuk-grubu-baslik">{g.baslik}</h3>
            {g.aciklama && (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: -6 }}>
                {g.aciklama}
              </Typography.Paragraph>
            )}
            <div className="fl-kutucuklar">
              {panel.isLoading
                ? Array.from({ length: 4 }, (_, i) => <KpiKutucugu key={i} baslik="" yukleniyor />)
                : grupKutulari.map((k) => (
                    <KpiKutucugu
                      key={k.kod}
                      kod={k.kod}
                      baslik={tayinDili(k.baslik)}
                      tanim={tayinDili(k.tanim)}
                      deger={k.deger}
                      ikon={ikonu(k.kod)}
                      yol={k.yol}
                      vurgu={k.deger > 0 ? k.vurgu : "normal"}
                    />
                  ))}
              {g.kod === "DONEM" && olcum && (
                <>
                  <KpiKutucugu
                    baslik="Telefon/uzaktan oranı"
                    tanim="Dönemde tamamlananlar içinde telefonla/uzaktan çözülenlerin oranı (pay ve payda yandaki kutucuklar)."
                    deger={olcum.uzaktan_oran_yuzde}
                    birim="%"
                    ikon={<PieChartOutlined />}
                  />
                  <KpiKutucugu
                    baslik="Ortalama çözüm süresi"
                    altBaslik={
                      olcum.cozum_tahmini > 0
                        ? `${olcum.cozum_tahmini} işte bildirim anı yok (açılış anı kullanıldı)`
                        : undefined
                    }
                    tanim="Bildirim (yoksa açılış) anından tamamlanmaya kadar geçen ortalama süre."
                    deger={olcum.ortalama_cozum_saat}
                    birim="saat"
                    ikon={<ClockCircleOutlined />}
                  />
                </>
              )}
            </div>
          </section>
        );
      })}
    </Space>
  );
}
