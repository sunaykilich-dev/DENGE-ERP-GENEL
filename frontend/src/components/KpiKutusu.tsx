import { InfoCircleOutlined } from "@ant-design/icons";
import { Card, Tooltip, Typography } from "antd";
import { useNavigate } from "react-router-dom";

import Statistic from "./Statistic";

/**
 * Tıklanabilir KPI kutusu — teknik servisin bütün panolarında TEK bileşen
 * (plan TS-012, E01-14 / E12-08).
 *
 * Kural "sayı = liste": kutudaki sayı, tıklanınca açılan listenin
 * `X-Toplam-Kayit` başlığıyla aynı sorgudan gelir; kutu kendi sayısını
 * HESAPLAMAZ, sunucunun verdiği `deger`i gösterir. Her modül kendi `Card
 * hoverable` kodunu yazsaydı (E04/E06/E08/E09 kontrollerindeki çakışma)
 * biri tooltip'i, biri "ölçülemedi" durumunu unuturdu.
 *
 * `deger === null` "ölçülemedi" demektir (ör. süre kaydı eksik): "0"
 * GÖSTERİLMEZ — eksik veriyi sıfır gibi sunmak yanlış karar aldırır. Varsa
 * `eksik` sayısı alt yazıda belirtilir.
 */
export interface KpiKutusuProps {
  /** Sunucudaki KPI kodu (liste süzgeci `?kpi=<kod>` ile aynı). */
  kod: string;
  baslik: string;
  /** Ölçümün tanımı — ⓘ ipucunda gösterilir (sunucunun `/tanimlar` metni). */
  tanim?: string;
  deger: number | null;
  /** Tıklanınca gidilecek liste adresi (aynı süzgeçle). */
  yol: string;
  /** `deger` null iken ölçülemeyen kayıt sayısı. */
  eksik?: number | null;
  /** Kritik eşik aşıldığında sayı uyarı renginde gösterilir. */
  vurgu?: "normal" | "uyari" | "kritik";
  yukleniyor?: boolean;
}

const VURGU_RENGI: Record<NonNullable<KpiKutusuProps["vurgu"]>, string | undefined> = {
  normal: undefined,
  uyari: "#b7791f",
  kritik: "#de3a11",
};

export default function KpiKutusu({
  kod,
  baslik,
  tanim,
  deger,
  yol,
  eksik,
  vurgu = "normal",
  yukleniyor,
}: KpiKutusuProps) {
  const git = useNavigate();
  const olculemedi = deger === null;

  return (
    <Card
      size="small"
      hoverable
      loading={yukleniyor}
      data-kpi={kod}
      role="link"
      tabIndex={0}
      aria-label={`${baslik}: ${olculemedi ? "ölçülemedi" : deger}`}
      onClick={() => git(yol)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          git(yol);
        }
      }}
      style={{ height: "100%", minWidth: 0 }}
    >
      <Statistic
        title={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{baslik}</span>
            {tanim && (
              <Tooltip title={tanim}>
                {/* İpucu tıklaması listeye gitmesin. */}
                <InfoCircleOutlined
                  onClick={(e) => e.stopPropagation()}
                  aria-label={`${baslik} tanımı`}
                />
              </Tooltip>
            )}
          </span>
        }
        value={olculemedi ? "—" : deger}
        valueStyle={{ color: olculemedi ? undefined : VURGU_RENGI[vurgu] }}
      />
      {olculemedi && eksik != null && eksik > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {eksik.toLocaleString("tr-TR")} iş eksik veri
        </Typography.Text>
      )}
    </Card>
  );
}
