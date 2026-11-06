import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import Statistic from "../components/Statistic";
import { useAuth } from "../auth/AuthContext";

/** Sunucu tarafında `Decimal` olan alanlar JSON'a string olarak düşer. */
interface Dashboard {
  tarih: string;
  donem: string;
  sahadaki_cihaz: number;
  stoktaki_cihaz: number;
  cihaz_durumlari: Record<string, number>;
  stok_degeri_try: string | null;
  maliyeti_girilmemis_cihaz: number;
  aylik_montaj: number;
  aktif_abonelik: number;
  mrr: string;
  arr: string;
  churn_yuzde: string | null;
  bekleyen_teklif: number;
  bekleyen_hakedis_adet: number;
  bekleyen_hakedis_tutar: string;
}

interface Geciken {
  account_id: number;
  title: string;
  musteri_bakiye: string;
  gecen_gun: number | null;
}

interface Yenilenecek {
  subscription_id: number;
  subscription_no: string;
  customer_title: string;
  end_date: string;
  kalan_gun: number;
}

const tl = (v: number | string | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

/** Cihaz durumlarının hangi kovaya düştüğü — panelde kovalar gösterilir. */
const KOVALAR: { ad: string; durumlar: string[]; renk: string }[] = [
  { ad: "Sahada", durumlar: ["AKTIF", "MONTAJ_BEKLIYOR"], renk: "#1f6b4d" },
  {
    ad: "Stokta",
    durumlar: ["STOKTA", "TEST_EDILDI", "YENIDEN_STOKTA", "ITHALATTA"],
    renk: "#11417f",
  },
  { ad: "Yolda / rezerve", durumlar: ["REZERVE", "SEVK_EDILDI"], renk: "#b58105" },
  { ad: "Serviste", durumlar: ["ARIZALI", "RMA", "TAMIRDE"], renk: "#8250df" },
  { ad: "Sökülü", durumlar: ["SOKULDU"], renk: "#7a8394" },
  { ad: "Kayıp / hurda", durumlar: ["HURDA", "KAYIP_CALINTI"], renk: "#b42318" },
];

export default function PanelPage() {
  const { kullanici, yetkili } = useAuth();

  const ozet = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<Dashboard>("/api/raporlar/dashboard"),
    enabled: yetkili("rapor.gor"),
  });

  const gecikenler = useQuery({
    queryKey: ["panel-gecikenler"],
    queryFn: () => api.get<Geciken[]>("/api/tahsilat/gecikenler"),
    enabled: yetkili("tahsilat.gor"),
  });

  const yenilenecekler = useQuery({
    queryKey: ["panel-yenilenecek"],
    queryFn: () => api.get<Yenilenecek[]>("/api/abonelikler/yenilenecekler"),
    enabled: yetkili("abonelik.gor"),
  });

  if (!yetkili("rapor.gor")) {
    return (
      <Card>
        <Empty description="Panel için rapor görme yetkiniz yok. Soldaki menüden çalışmaya devam edebilirsiniz." />
      </Card>
    );
  }

  const d = ozet.data;
  const toplamCihaz = d ? Object.values(d.cihaz_durumlari).reduce((a, b) => a + b, 0) : 0;

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card loading={ozet.isLoading}>
        <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Merhaba{kullanici ? `, ${kullanici.full_name.split(" ")[0]}` : ""}
          </Typography.Title>
          <Typography.Text type="secondary">
            {d ? dayjs(d.tarih).format("D MMMM YYYY") : ""} · {d?.donem} dönemi
          </Typography.Text>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic
              title="Sahadaki cihaz"
              value={d?.sahadaki_cihaz ?? 0}
              valueStyle={{ color: "#1f6b4d" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic title="Stoktaki cihaz" value={d?.stoktaki_cihaz ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic title={`${d?.donem ?? ""} montajı`} value={d?.aylik_montaj ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic
              title="Stok değeri"
              value={d?.stok_degeri_try ?? 0}
              formatter={() =>
                d?.stok_degeri_try == null ? (
                  <Tooltip title="Maliyet görme yetkiniz yok">
                    <Typography.Text type="secondary">gizli</Typography.Text>
                  </Tooltip>
                ) : (
                  tl(d.stok_degeri_try)
                )
              }
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic
              title="MRR"
              value={d?.mrr ?? 0}
              formatter={(v) => tl(Number(v))}
              valueStyle={{ color: "#11417f" }}
            />
            <Typography.Text type="secondary">ARR {tl(d?.arr)}</Typography.Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic
              title="Churn (bu ay)"
              value={d?.churn_yuzde ?? 0}
              formatter={() =>
                d?.churn_yuzde == null
                  ? "—"
                  : `%${Number(d.churn_yuzde).toLocaleString("tr-TR", {
                      minimumFractionDigits: 2,
                    })}`
              }
              valueStyle={Number(d?.churn_yuzde ?? 0) > 0 ? { color: "#b42318" } : undefined}
            />
            <Typography.Text type="secondary">
              {d?.aktif_abonelik ?? 0} aktif abonelik
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic title="Bekleyen teklif" value={d?.bekleyen_teklif ?? 0} />
            <Link to="/teklifler">
              <Typography.Text type="secondary">Tekliflere git →</Typography.Text>
            </Link>
          </Card>
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <Card loading={ozet.isLoading}>
            <Statistic
              title="Bekleyen hak ediş"
              value={d?.bekleyen_hakedis_tutar ?? 0}
              formatter={(v) => tl(Number(v))}
              valueStyle={{ color: "#b58105" }}
            />
            <Typography.Text type="secondary">
              {d?.bekleyen_hakedis_adet ?? 0} döküm
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      {d && d.maliyeti_girilmemis_cihaz > 0 && (
        <Alert
          type="info"
          title={`${d.maliyeti_girilmemis_cihaz} stok cihazının maliyeti girilmemiş`}
          description="Stok değeri yalnız maliyeti bilinen cihazları kapsıyor; 'stok değeri düşük' ile 'maliyet girilmemiş' aynı şey değil."
        />
      )}

      <Card title="Cihaz dağılımı" loading={ozet.isLoading}>
        <Space orientation="vertical" size={10} style={{ width: "100%" }}>
          {KOVALAR.map((k) => {
            const adet = k.durumlar.reduce((t, s) => t + (d?.cihaz_durumlari[s] ?? 0), 0);
            if (!adet) return null;
            return (
              <div key={k.ad}>
                <Space style={{ width: "100%", justifyContent: "space-between" }}>
                  <Typography.Text>{k.ad}</Typography.Text>
                  <Typography.Text className="mono">
                    {adet.toLocaleString("tr-TR")}
                  </Typography.Text>
                </Space>
                <Progress
                  percent={toplamCihaz ? Math.round((adet / toplamCihaz) * 100) : 0}
                  strokeColor={k.renk}
                  showInfo={false}
                  size="small"
                />
              </div>
            );
          })}
          {toplamCihaz === 0 && <Empty description="Henüz cihaz kaydı yok" />}
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        {yetkili("tahsilat.gor") && (
          <Col xs={24} xl={12}>
            <Card
              title="Ödemesi geciken müşteriler"
              extra={<Link to="/tahsilat">Tümü →</Link>}
              loading={gecikenler.isLoading}
            >
              <Table
                rowKey="account_id"
                size="small"
                pagination={false}
                dataSource={(gecikenler.data ?? []).slice(0, 6)}
                locale={{ emptyText: <Empty description="Geciken ödeme yok" /> }}
                columns={[
                  { title: "Müşteri", dataIndex: "title", ellipsis: true },
                  {
                    title: "Bakiye",
                    dataIndex: "musteri_bakiye",
                    width: 140,
                    className: "tutar",
                    render: (x: number) => <strong style={{ color: "#b42318" }}>{tl(x)}</strong>,
                  },
                  {
                    title: "Geciken",
                    width: 120,
                    render: (_: unknown, r: Geciken) => (
                      <Tag color="red">
                        {r.gecen_gun == null ? "hiç ödeme yok" : `${r.gecen_gun} gün`}
                      </Tag>
                    ),
                  },
                ]}
              />
            </Card>
          </Col>
        )}

        {yetkili("abonelik.gor") && (
          <Col xs={24} xl={12}>
            <Card
              title="Yenileme yaklaşan sözleşmeler"
              extra={<Link to="/abonelikler">Tümü →</Link>}
              loading={yenilenecekler.isLoading}
            >
              <Table
                rowKey="subscription_id"
                size="small"
                pagination={false}
                dataSource={(yenilenecekler.data ?? []).slice(0, 6)}
                locale={{ emptyText: <Empty description="Yaklaşan yenileme yok" /> }}
                columns={[
                  { title: "Müşteri", dataIndex: "customer_title", ellipsis: true },
                  {
                    title: "Bitiş",
                    dataIndex: "end_date",
                    width: 120,
                    className: "mono",
                    render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
                  },
                  {
                    title: "Kalan",
                    dataIndex: "kalan_gun",
                    width: 110,
                    render: (x: number) => (
                      <Tag color={x < 0 ? "red" : x <= 7 ? "orange" : "gold"}>
                        {x < 0 ? `${-x} gün geçti` : `${x} gün`}
                      </Tag>
                    ),
                  },
                ]}
              />
            </Card>
          </Col>
        )}
      </Row>
    </Space>
  );
}
