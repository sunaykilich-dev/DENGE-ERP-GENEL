/**
 * Atölye KPI raporu (TS-194, E05-09/24) — çevrim, dış servis ve işçilik.
 *
 * Sayılabilir göstergeler `KpiKutusu`dur: tıklanınca sunucunun verdiği
 * süzgeçle (`sorgu`) atölye listesi açılır ve listenin toplamı kutudaki sayıyla
 * aynıdır. Ortalama/medyan göstergeleri sayı değil ölçüdür; ölçülemediğinde
 * "—" gösterilir, 0 yazılmaz. Dönem Türkiye günüdür, en çok 24 ay.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, DatePicker, Row, Space, Table, Tooltip, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { atolyeApi, atolyeListeYolu, type AtolyeRaporKutusu } from "../api/atolye";
import { useAuth } from "../auth/AuthContext";
import KpiKutusu from "./KpiKutusu";
import Statistic from "./Statistic";

const sayi = (v: number | string | null | undefined) =>
  v === null || v === undefined ? null : Number(v);

function Olcu({ k }: { k: AtolyeRaporKutusu }) {
  const deger = sayi(k.deger);
  return (
    <Card size="small" style={{ height: "100%" }}>
      <Tooltip title={k.tanim}>
        <div>
          <Statistic
            title={k.baslik}
            value={deger === null ? "—" : deger}
            precision={deger === null || k.birim === "dk" ? undefined : 1}
            suffix={deger === null ? undefined : k.birim}
          />
        </div>
      </Tooltip>
    </Card>
  );
}

export default function AtolyeKpiRaporu() {
  const { yetkili } = useAuth();
  const [aralik, setAralik] = useState<[Dayjs, Dayjs]>([dayjs().subtract(30, "day"), dayjs()]);
  const q = { bas: aralik[0].format("YYYY-MM-DD"), bit: aralik[1].format("YYYY-MM-DD") };
  const rapor = useQuery({
    queryKey: ["atolye-kpi-raporu", q],
    queryFn: () => atolyeApi.kpiRaporu(q),
  });

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Space wrap>
        <DatePicker.RangePicker
          allowClear={false}
          format="DD.MM.YYYY"
          value={aralik}
          onChange={(v) => v && v[0] && v[1] && setAralik([v[0], v[1]])}
        />
        {yetkili("servis_rapor.disaaktar") && (
          <Button onClick={() => window.open(atolyeApi.kpiExcelYolu(q), "_blank")}>Excel</Button>
        )}
      </Space>
      {rapor.isError && <Alert type="error" showIcon title={(rapor.error as Error).message} />}
      <Typography.Text type="secondary">
        Dönem, kaydın ilk kez teslime hazır olduğu güne göre seçilir. Çevrim süresi kabulden
        teslime hazıra geçen süredir; tahmini bitiş kullanılmaz. Süre kaydı eksik kayıt işçilik
        ortalamasına girmez.
      </Typography.Text>
      <Row gutter={[12, 12]}>
        {(rapor.data?.kutular ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={6}>
            {k.sorgu ? (
              <KpiKutusu
                kod={k.kod}
                baslik={k.baslik}
                tanim={k.tanim}
                deger={sayi(k.deger)}
                yol={atolyeListeYolu(k.sorgu)}
                vurgu={k.kod === "TESLIM_ALINMADI" && Number(k.deger) > 0 ? "uyari" : "normal"}
              />
            ) : (
              <Olcu k={k} />
            )}
          </Col>
        ))}
      </Row>
      <Table
        size="small"
        rowKey="servis_turu"
        loading={rapor.isLoading}
        pagination={false}
        scroll={{ x: true }}
        dataSource={rapor.data?.servis_turu_kirilimi ?? []}
        columns={[
          { title: "Servis türü", dataIndex: "ad" },
          {
            title: "Tamamlanan",
            dataIndex: "adet",
            render: (v: number, r) => <Link to={atolyeListeYolu(r.sorgu)}>{v}</Link>,
          },
          { title: "Ort. çevrim (gün)", dataIndex: "cevrim_ort_gun", render: (v) => v ?? "—" },
          { title: "Medyan (gün)", dataIndex: "cevrim_medyan_gun", render: (v) => v ?? "—" },
          {
            title: "Dış servis hariç (gün)",
            dataIndex: "cevrim_dis_haric_ort_gun",
            render: (v) => v ?? "—",
          },
          { title: "Dış servise giden", dataIndex: "dis_servis_adet" },
          { title: "Ort. dış servis (gün)", dataIndex: "dis_servis_ort_gun", render: (v) => v ?? "—" },
          { title: "Süre kaydı eksik", dataIndex: "sure_eksik" },
          { title: "Ort. işçilik (dk)", dataIndex: "iscilik_ort_dk", render: (v) => v ?? "—" },
        ]}
      />
    </Space>
  );
}
