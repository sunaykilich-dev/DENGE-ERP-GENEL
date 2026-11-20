import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Timeline,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, type ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/** Cihazın MOBILITE/ARAC_TAKIP servis işleri (TS-193): IMEI/seri ile okuma
 * anında eşleşir; `devices`'a yazılmaz. Yalnız `servis.gor` sahibine görünür. */
interface CihazServisIsi {
  id: number;
  so_no: string;
  birim: string;
  status: string;
  konu: string;
  created_at: string;
}

function CihazServisIsleri({ cihazId }: { cihazId: number }) {
  const navigate = useNavigate();
  const isler = useQuery({
    queryKey: ["cihaz-servis-isleri", cihazId],
    queryFn: () =>
      api.getSayfa<CihazServisIsi>(`/api/teknik-servis/cihaz-servis-isleri?cihaz_id=${cihazId}&limit=20`),
  });
  return (
    <Card size="small" title={`Servis işleri${isler.data ? ` (${isler.data.toplam})` : ""}`}>
      {isler.data && isler.data.kayitlar.length === 0 ? (
        <Typography.Text type="secondary">Bu cihaz için servis işi yok</Typography.Text>
      ) : (
        <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          {(isler.data?.kayitlar ?? []).map((s) => (
            <Space key={s.id} size={6} wrap>
              <Typography.Link className="mono" onClick={() => navigate(`/servis-isleri/${s.id}`)}>
                {s.so_no}
              </Typography.Link>
              <Tag>{s.status.replaceAll("_", " ")}</Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {dayjs(s.created_at).format("DD.MM.YYYY")} · {s.konu}
              </Typography.Text>
            </Space>
          ))}
        </Space>
      )}
    </Card>
  );
}

interface Cihaz {
  id: number;
  imei: string | null;
  serial_no: string | null;
  identity_kind: string;
  kimlik: string;
  is_identity_provisional: boolean;
  product_code: string | null;
  product_name: string | null;
  product_family: string | null;
  parent_kimlik: string | null;
  channel_no: number | null;
  device_role: string | null;
  status: string;
  sonraki_durumlar: string[];
  btk_status: string;
  first_activation_date: string | null;
  warranty_end_date: string | null;
  hat_msisdn: string | null;
  hat_iccid: string | null;
  arac_plaka: string | null;
  musteri_unvan: string | null;
}

interface AracDonemi {
  id: number;
  vehicle_plate: string | null;
  valid_from: string;
  valid_to: string | null;
  removal_reason: string | null;
  is_inferred: boolean;
}

interface Kart extends Cihaz {
  hat: {
    id: number;
    iccid: string;
    msisdn: string | null;
    operator: string;
    status: string;
    plan_name: string | null;
    data_allowance_mb: number | null;
    data_used_mb: number | null;
    commitment_end_date: string | null;
  } | null;
  alt_cihazlar: Cihaz[];
  durum_gecmisi: {
    from_status: string | null;
    to_status: string;
    reason: string | null;
    changed_at: string;
  }[];
  hat_baslangici_bilinmiyor: boolean;
  hat_gecmisi_adedi: number;
  ek_adedi: number;
}

const DURUM_RENGI: Record<string, string> = {
  AKTIF: "green",
  STOKTA: "blue",
  YENIDEN_STOKTA: "blue",
  TEST_EDILDI: "cyan",
  REZERVE: "gold",
  SEVK_EDILDI: "gold",
  MONTAJ_BEKLIYOR: "gold",
  SOKULDU: "orange",
  ARIZALI: "red",
  RMA: "red",
  TAMIRDE: "magenta",
  HURDA: "default",
  KAYIP_CALINTI: "volcano",
  ITHALATTA: "purple",
};

/** Cihaz durumları, iş akışındaki sıraya göre gruplanmış (durum makinesiyle
    aynı sıra) — alfabetik liste ekranda anlam taşımıyordu. */
const DURUM_GRUPLARI: { grup: string; durumlar: string[] }[] = [
  { grup: "Stokta", durumlar: ["ITHALATTA", "STOKTA", "TEST_EDILDI", "YENIDEN_STOKTA"] },
  { grup: "Yolda / söz verilmiş", durumlar: ["REZERVE", "SEVK_EDILDI", "MONTAJ_BEKLIYOR"] },
  { grup: "Sahada", durumlar: ["AKTIF", "SOKULDU"] },
  { grup: "Serviste", durumlar: ["ARIZALI", "RMA", "TAMIRDE"] },
  { grup: "Kapanmış", durumlar: ["HURDA", "KAYIP_CALINTI"] },
];

function DurumEtiketi({ durum }: { durum: string }) {
  return <Tag color={DURUM_RENGI[durum] ?? "default"}>{durum.replaceAll("_", " ")}</Tag>;
}

export default function CihazlarPage() {
  const { kimlik } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const [arama, setArama] = useState("");
  const [durum, setDurum] = useState("HEPSI");
  const [gecici, setGecici] = useState(false);
  // Sayfalama SUNUCUDA: 17.000 cihazı tarayıcıya indirip orada bölmek
  // hem yavaş hem yanıltıcıydı (gelen 100 kayıt "hepsi" sanılıyordu).
  const [sayfa, setSayfa] = useState(1);
  const SAYFA_BOYU = 25;

  const cihazlar = useQuery({
    queryKey: ["cihazlar", arama, durum, gecici, sayfa],
    queryFn: () => {
      const p = new URLSearchParams();
      if (arama) p.set("q", arama);
      if (durum !== "HEPSI") p.set("durum", durum);
      if (gecici) p.set("kimligi_gecici", "true");
      p.set("limit", String(SAYFA_BOYU));
      p.set("offset", String((sayfa - 1) * SAYFA_BOYU));
      return api.getSayfa<Cihaz>(`/api/cihazlar?${p}`);
    },
    placeholderData: (onceki) => onceki,
  });

  const kart = useQuery({
    queryKey: ["cihaz", kimlik],
    queryFn: () => api.get<Kart>(`/api/cihazlar/${encodeURIComponent(kimlik!)}`),
    enabled: !!kimlik,
  });

  // Ömür boyu araç geçmişi — brief §4.5 "cihaz kartında zaman çizelgesi".
  const aracGecmisi = useQuery({
    queryKey: ["cihaz-arac-gecmis", kart.data?.id],
    queryFn: () =>
      api.get<AracDonemi[]>(`/api/is-emirleri/cihaz/${kart.data!.id}/gecmis`),
    enabled: !!kart.data?.id,
  });

  const durumDegistir = useMutation({
    mutationFn: ({ id, to_status }: { id: number; to_status: string }) =>
      api.post(`/api/cihazlar/${id}/durum`, { to_status }),
    onSuccess: () => {
      message.success("Durum güncellendi");
      void qc.invalidateQueries({ queryKey: ["cihaz"] });
      void qc.invalidateQueries({ queryKey: ["cihazlar"] });
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const k = kart.data;

  return (
    <Card
      title="Cihazlar"
      extra={
        <Space>
          <Input.Search
            placeholder="IMEI, seri no veya ürün"
            allowClear
            onSearch={(v) => {
              setArama(v);
              setSayfa(1);
            }}
            style={{ width: 260 }}
          />
        </Space>
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          value={durum}
          onChange={(v) => {
            setDurum(v);
            setSayfa(1);
          }}
          style={{ width: 240 }}
          options={[
            { value: "HEPSI", label: "Tüm durumlar" },
            ...DURUM_GRUPLARI.map((g) => ({
              label: g.grup,
              options: g.durumlar.map((d) => ({ value: d, label: d.replaceAll("_", " ") })),
            })),
          ]}
        />
        <Button
          type={gecici ? "primary" : "default"}
          onClick={() => {
            setGecici((v) => !v);
            setSayfa(1);
          }}
          size="small"
        >
          Kimliği geçici olanlar
        </Button>
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={cihazlar.isLoading}
        dataSource={cihazlar.data?.kayitlar ?? []}
        pagination={{
          current: sayfa,
          pageSize: SAYFA_BOYU,
          total: cihazlar.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} cihaz`,
        }}
        onRow={(c) => ({
          onClick: () => navigate(`/cihazlar/${encodeURIComponent(c.kimlik)}`),
          style: { cursor: "pointer" },
        })}
        columns={[
          {
            title: "Kimlik",
            width: 190,
            render: (_, c: Cihaz) => (
              <Space size={4}>
                <span className="mono">{c.kimlik}</span>
                {c.identity_kind === "SERI_NO" && (
                  <Tooltip title="Bu üründe IMEI fiziksel olarak yok (analog kamera)">
                    <Tag color="orange">seri</Tag>
                  </Tooltip>
                )}
                {c.is_identity_provisional && <Tag color="red">geçici</Tag>}
              </Space>
            ),
          },
          { title: "Ürün", dataIndex: "product_name", width: 200, ellipsis: true },
          {
            title: "Hat (SIM)",
            width: 150,
            className: "mono",
            render: (_, c: Cihaz) =>
              c.hat_msisdn ? (
                <Tooltip title={c.hat_iccid ? `ICCID ${c.hat_iccid}` : "ICCID girilmemiş"}>
                  <span>{c.hat_msisdn}</span>
                </Tooltip>
              ) : (
                <Typography.Text type="secondary">—</Typography.Text>
              ),
          },
          {
            title: "Araç",
            width: 120,
            className: "mono",
            render: (_, c: Cihaz) =>
              c.arac_plaka ?? <Typography.Text type="secondary">—</Typography.Text>,
          },
          {
            title: "Firma",
            width: 200,
            ellipsis: true,
            render: (_, c: Cihaz) =>
              c.musteri_unvan ?? <Typography.Text type="secondary">—</Typography.Text>,
          },
          {
            title: "Durum",
            width: 160,
            render: (_, c: Cihaz) => <DurumEtiketi durum={c.status} />,
          },
        ]}
        scroll={{ x: 1060 }}
      />

      <Drawer
        title={k ? `Cihaz ${k.kimlik}` : "Cihaz"}
        open={!!kimlik}
        size={640}
        onClose={() => navigate("/cihazlar")}
        loading={kart.isLoading}
      >
        {kart.isError && <Empty description="Cihaz bulunamadı" />}
        {k && (
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            {k.is_identity_provisional && (
              <Alert
                type="warning"
                showIcon
                title="Kimlik geçici"
                description="Bu cihazın IMEI'si veri göçünde bulunamadı. Sahadan doğrulanıp düzeltilmeli."
              />
            )}

            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Kimlik" span={2}>
                <span className="mono">{k.kimlik}</span>{" "}
                <Tag>{k.identity_kind === "IMEI" ? "IMEI" : "Seri no"}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Ürün" span={2}>
                {k.product_name} <Typography.Text type="secondary">({k.product_code})</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="Durum">
                <DurumEtiketi durum={k.status} />
              </Descriptions.Item>
              <Descriptions.Item label="BTK">{k.btk_status}</Descriptions.Item>
              <Descriptions.Item label="İlk aktivasyon">
                {k.first_activation_date
                  ? dayjs(k.first_activation_date).format("DD.MM.YYYY")
                  : "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Garanti bitişi">
                {k.warranty_end_date ? dayjs(k.warranty_end_date).format("DD.MM.YYYY") : "—"}
              </Descriptions.Item>
              {k.parent_kimlik && (
                <Descriptions.Item label="Ana cihaz" span={2}>
                  <span className="mono">{k.parent_kimlik}</span>
                  {k.channel_no && <Tag style={{ marginInlineStart: 8 }}>kanal {k.channel_no}</Tag>}
                </Descriptions.Item>
              )}
            </Descriptions>

            {yetkili("cihaz.yaz") && k.sonraki_durumlar.length > 0 && (
              <Space>
                <Typography.Text type="secondary">Durumu değiştir:</Typography.Text>
                <Select
                  placeholder="Yeni durum"
                  style={{ width: 220 }}
                  loading={durumDegistir.isPending}
                  // Eylem tetikleyici olarak kullanılıyor: seçim yapıldıktan
                  // sonra boş kalsın ki "şu an şu durumdayım" izlenimi vermesin.
                  value={undefined}
                  onChange={(v: string) => durumDegistir.mutate({ id: k.id, to_status: v })}
                  options={k.sonraki_durumlar.map((d) => ({
                    value: d,
                    label: d.replaceAll("_", " "),
                  }))}
                />
              </Space>
            )}

            <Card size="small" title="Takılı hat">
              {k.hat ? (
                <Descriptions size="small" column={2}>
                  <Descriptions.Item label="ICCID">
                    <span className="mono">{k.hat.iccid}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="Numara">
                    <span className="mono">{k.hat.msisdn ?? "—"}</span>
                  </Descriptions.Item>
                  <Descriptions.Item label="Operatör">{k.hat.operator}</Descriptions.Item>
                  <Descriptions.Item label="Paket">{k.hat.plan_name ?? "—"}</Descriptions.Item>
                </Descriptions>
              ) : (
                <Typography.Text type="secondary">Takılı hat yok</Typography.Text>
              )}
              {k.hat_baslangici_bilinmiyor && (
                <Tooltip title="Eşleşme kaynak dosyadaki ICCID'den kuruldu; aktivasyon anı dosyada yoktu. Uydurulmuş bir tarih yazılmadı — gerçek tarihi girebilirsiniz.">
                  <Tag color="gold">başlangıç tarihi bilinmiyor</Tag>
                </Tooltip>
              )}
              {k.hat_gecmisi_adedi > 0 && (
                <Typography.Text type="secondary">
                  Geçmişte {k.hat_gecmisi_adedi} hat eşleşmesi
                </Typography.Text>
              )}
            </Card>

            {k.alt_cihazlar.length > 0 && (
              <Card size="small" title={`Bağlı kameralar (${k.alt_cihazlar.length})`}>
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={k.alt_cihazlar}
                  columns={[
                    { title: "Kanal", dataIndex: "channel_no", width: 70, className: "mono" },
                    {
                      title: "Kimlik",
                      dataIndex: "kimlik",
                      className: "mono",
                      render: (v: string) => (
                        <a onClick={() => navigate(`/cihazlar/${encodeURIComponent(v)}`)}>{v}</a>
                      ),
                    },
                    { title: "Ürün", dataIndex: "product_name" },
                    {
                      title: "Durum",
                      width: 130,
                      render: (_, c: Cihaz) => <DurumEtiketi durum={c.status} />,
                    },
                  ]}
                />
              </Card>
            )}

            <Card
              size="small"
              title={`Araç geçmişi (${(aracGecmisi.data ?? []).length})`}
            >
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                Bu cihaz ömrü boyunca hangi araçlarda, hangi tarihlerde takılıydı. Garanti
                cihaza bağlıdır; araç değişse de süre değişmez.
              </Typography.Paragraph>
              {(aracGecmisi.data ?? []).length === 0 ? (
                <Typography.Text type="secondary">Henüz araca takılmamış</Typography.Text>
              ) : (
                <Timeline
                  items={(aracGecmisi.data ?? []).map((g) => ({
                    color: g.valid_to ? "gray" : "green",
                    children: (
                      <Space orientation="vertical" size={0}>
                        <Space size={6}>
                          <span className="mono">{g.vehicle_plate}</span>
                          {!g.valid_to && <Tag color="green">takılı</Tag>}
                          {g.is_inferred && (
                            <Tooltip title="Kaynakta söküm kaydı yoktu; söküm tarihi sonraki montajdan çıkarıldı. Doğruysa onaylayın, değilse düzeltin.">
                              <Tag color="gold">tarih tahmini</Tag>
                            </Tooltip>
                          )}
                        </Space>
                        <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>
                          {dayjs(g.valid_from).format("DD.MM.YYYY")} →{" "}
                          {g.valid_to ? dayjs(g.valid_to).format("DD.MM.YYYY") : "—"}
                          {g.removal_reason ? ` · ${g.removal_reason}` : ""}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              )}
            </Card>

            <Card size="small" title="Durum geçmişi">
              {k.durum_gecmisi.length === 0 ? (
                <Typography.Text type="secondary">Henüz durum değişikliği yok</Typography.Text>
              ) : (
                <Timeline
                  items={k.durum_gecmisi.map((g) => ({
                    children: (
                      <Space orientation="vertical" size={0}>
                        <span>
                          {g.from_status && (
                            <Typography.Text type="secondary">
                              {g.from_status.replaceAll("_", " ")} →{" "}
                            </Typography.Text>
                          )}
                          <strong>{g.to_status.replaceAll("_", " ")}</strong>
                        </span>
                        <Typography.Text type="secondary" className="mono" style={{ fontSize: 12 }}>
                          {dayjs(g.changed_at).format("DD.MM.YYYY HH:mm")}
                          {g.reason ? ` · ${g.reason}` : ""}
                        </Typography.Text>
                      </Space>
                    ),
                  }))}
                />
              )}
            </Card>

            {yetkili("servis.gor") && <CihazServisIsleri cihazId={k.id} />}
          </Space>
        )}
      </Drawer>
    </Card>
  );
}
