/**
 * Servis Paneli — tıklanabilir KPI kutuları (TS-035, E01-14).
 *
 * Kural "sayı = liste": kutudaki sayı sunucunun `KPI_TANIMLARI` süzgecinden
 * gelir ve tıklanınca AYNI süzgeçle `/servis-isleri?kpi=<kod>` açılır; ekran
 * kendi sayısını hesaplamaz. Kutular kullanıcının birim/iş kapsamıyla sayılır.
 * Dönem seçimi (bugün / bu hafta / bu ay / son 30 gün) yalnız dönemsel
 * kutuları etkiler ve tarayıcıda hatırlanır. Mobilite `PanelPage` ayrı ve
 * değişmedi (K17).
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Row, Segmented, Space, Statistic, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import { DONEMLER, teknikServisApi, type PanelKutusu } from "../api/teknikServis";
import KpiKutusu from "../components/KpiKutusu";

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
  { kod: "SERVIS", baslik: "Servis işleri (anlık)", aciklama: "Planlı bakım (PB) işleri bu kutularda sayılmaz." },
  { kod: "DONEM", baslik: "Dönem" },
  { kod: "BAKIM", baslik: "Planlı bakım" },
];

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
      <Card
        size="small"
        title="Servis Paneli"
        extra={
          <Segmented
            size="small"
            value={donem}
            onChange={(v) => donemSec(String(v))}
            options={DONEMLER.map((d) => ({ value: d.kod, label: d.ad }))}
          />
        }
      >
        {panel.data && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Dönem: {panel.data.donem_adi} (
            {dayjs(panel.data.donem_baslangic).format("DD.MM.YYYY")} –{" "}
            {dayjs(panel.data.donem_bitis).format("DD.MM.YYYY")}). Kutuya tıklayınca aynı süzgeçle
            liste açılır.
          </Typography.Text>
        )}
      </Card>

      {panel.isError && <Alert type="error" showIcon message={(panel.error as Error).message} />}

      {GRUPLAR.map((g) => {
        const grupKutulari = kutular.filter((k) => k.grup === g.kod);
        if (!panel.isLoading && grupKutulari.length === 0) return null;
        return (
          <Card key={g.kod} size="small" title={g.baslik}>
            {g.aciklama && (
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 0 }}>
                {g.aciklama}
              </Typography.Paragraph>
            )}
            <Row gutter={[12, 12]}>
              {(panel.isLoading ? Array.from({ length: 4 }, () => null) : grupKutulari).map(
                (k, i) => (
                  <Col key={k?.kod ?? i} xs={12} sm={8} md={6} xl={4}>
                    {k ? (
                      <KpiKutusu
                        kod={k.kod}
                        baslik={k.baslik}
                        tanim={k.tanim}
                        deger={k.deger}
                        yol={k.yol}
                        vurgu={k.deger > 0 ? k.vurgu : "normal"}
                      />
                    ) : (
                      <KpiKutusu kod="" baslik="" deger={0} yol="/servis-isleri" yukleniyor />
                    )}
                  </Col>
                ),
              )}
              {g.kod === "DONEM" && olcum && (
                <>
                  <Col xs={12} sm={8} md={6} xl={4}>
                    <Card size="small" style={{ height: "100%" }}>
                      <Tooltip title="Dönemde tamamlananlar içinde telefonla/uzaktan çözülenlerin oranı (pay ve payda yandaki kutular).">
                        <Statistic
                          title="Telefon/uzaktan oranı"
                          value={olcum.uzaktan_oran_yuzde ?? "—"}
                          suffix={olcum.uzaktan_oran_yuzde != null ? "%" : undefined}
                        />
                      </Tooltip>
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6} xl={4}>
                    <Card size="small" style={{ height: "100%" }}>
                      <Tooltip title="Bildirim (yoksa açılış) anından tamamlanmaya kadar geçen ortalama süre.">
                        <Statistic
                          title="Ortalama çözüm süresi"
                          value={olcum.ortalama_cozum_saat ?? "—"}
                          suffix={olcum.ortalama_cozum_saat != null ? "saat" : undefined}
                        />
                      </Tooltip>
                      {olcum.cozum_tahmini > 0 && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {olcum.cozum_tahmini} işte bildirim anı yok (açılış anı kullanıldı)
                        </Typography.Text>
                      )}
                    </Card>
                  </Col>
                </>
              )}
            </Row>
          </Card>
        );
      })}
    </Space>
  );
}
