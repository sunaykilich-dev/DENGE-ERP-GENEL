import { DownloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Kullanici } from "../api/client";
import { useAuth } from "../auth/AuthContext";

interface ErisimKaydi {
  id: number;
  user_id: number | null;
  entity: string;
  entity_id: string | null;
  action: string;
  amac: string | null;
  ip: string | null;
  created_at: string;
}

interface VeriBulSonucu {
  arama: string;
  hesaplar: {
    id: number;
    unvan: string;
    telefon: string | null;
    eposta: string | null;
    vkn: string | null;
    anonim: boolean;
  }[];
  kisiler: {
    id: number;
    account_id: number | null;
    ad: string;
    telefon: string | null;
    eposta: string | null;
    anonim: boolean;
  }[];
  araclar: { id: number; plaka: string; sase: string | null; musteri_id: number | null }[];
  cihazlar: { device_id: number; kimlik: string | null; status: string }[];
  ozet: Record<string, number>;
}

interface Saklama {
  adet: number;
  kayitlar: {
    account_id: number;
    unvan: string;
    telefon: string | null;
    eposta: string | null;
    anonim: boolean;
    esik_yil: number;
  }[];
}

const OZET_ADI: Record<string, string> = {
  hesaplar: "hesap",
  kisiler: "kişi",
  araclar: "araç",
  cihazlar: "cihaz",
};

export default function KvkkPage() {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const qc = useQueryClient();

  const [arama, setArama] = useState("");
  const [sorgu, setSorgu] = useState("");
  const [yil, setYil] = useState<number | null>(null);
  const [anonimHedef, setAnonimHedef] = useState<{ id: number; unvan: string } | null>(null);
  const [gerekce, setGerekce] = useState("");
  const [onay, setOnay] = useState(false);

  const log = useQuery({
    queryKey: ["kvkk-log"],
    queryFn: () => api.get<ErisimKaydi[]>("/api/kvkk/erisim-logu?limit=300"),
  });

  // Log yalnız kullanıcı id'si tutuyor; adı göstermek için kullanıcı listesi
  // çekilir. Yetki yoksa id olduğu gibi kalır.
  const kullanicilar = useQuery({
    queryKey: ["kullanicilar"],
    queryFn: () => api.get<Kullanici[]>("/api/kullanicilar"),
    enabled: yetkili("sistem.kullanici"),
  });
  const adi = (id: number | null) =>
    id == null
      ? "sistem"
      : ((kullanicilar.data ?? []).find((k) => k.id === id)?.full_name ?? `#${id}`);

  const veri = useQuery({
    queryKey: ["kvkk-veri", sorgu],
    queryFn: () => api.get<VeriBulSonucu>(`/api/kvkk/veri-bul?arama=${encodeURIComponent(sorgu)}`),
    enabled: sorgu.length >= 3,
  });

  const saklama = useQuery({
    queryKey: ["kvkk-saklama", yil],
    queryFn: () => api.get<Saklama>(`/api/kvkk/saklama-suresi-dolanlar${yil ? `?yil=${yil}` : ""}`),
  });

  const anonimlestir = useMutation({
    mutationFn: (id: number) =>
      api.post<{ account_id: number; kisi: number; arac: number }>(
        `/api/kvkk/hesaplar/${id}/anonimlestir`,
        { gerekce, onay },
      ),
    onSuccess: (s) => {
      message.success(`Anonimleştirildi: ${s.kisi} kişi, ${s.arac} araç kaydı maskelendi.`);
      setAnonimHedef(null);
      setGerekce("");
      setOnay(false);
      void qc.invalidateQueries({ queryKey: ["kvkk-saklama"] });
      void qc.invalidateQueries({ queryKey: ["kvkk-veri"] });
      void qc.invalidateQueries({ queryKey: ["kvkk-log"] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  return (
    <>
      <Tabs
        defaultActiveKey="veri-bul"
        items={[
          {
            key: "veri-bul",
            label: "Veri bulma",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Alert
                  type="info"
                  title="Erişim ve silme taleplerinde kullanılır"
                  description="Bir kişiye ait tüm kayıtları unvan, kişi adı, telefon, e-posta ya da plakadan bulur. Bu aramanın kendisi de kişisel veri erişimidir ve loglanır."
                />
                <Card
                  title="Kişiye ait kayıtlar"
                  extra={
                    sorgu.length >= 3 && (
                      <Button
                        icon={<DownloadOutlined />}
                        onClick={() =>
                          window.open(
                            `/api/kvkk/veri-bul.xlsx?arama=${encodeURIComponent(sorgu)}`,
                            "_blank",
                          )
                        }
                      >
                        Döküm (Excel)
                      </Button>
                    )
                  }
                >
                  <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                    <Input.Search
                      value={arama}
                      onChange={(e) => setArama(e.target.value)}
                      onSearch={(v) => setSorgu(v.trim())}
                      placeholder="Unvan, ad soyad, telefon, e-posta veya plaka (en az 3 karakter)"
                      enterButton="Ara"
                      allowClear
                      style={{ maxWidth: 520 }}
                    />

                    {veri.isError && <Alert type="error" title={(veri.error as Error).message} />}

                    {veri.data && (
                      <>
                        <Space wrap size={[8, 8]}>
                          {Object.entries(veri.data.ozet).map(([k, v]) => (
                            <Tag key={k} color={v ? "blue" : "default"}>
                              {v} {OZET_ADI[k] ?? k}
                            </Tag>
                          ))}
                        </Space>

                        <Table
                          title={() => "Hesaplar"}
                          rowKey="id"
                          size="small"
                          pagination={false}
                          dataSource={veri.data.hesaplar}
                          scroll={{ x: 720 }}
                          locale={{ emptyText: <Empty description="Hesap bulunamadı" /> }}
                          columns={[
                            {
                              title: "Unvan",
                              dataIndex: "unvan",
                              width: 260,
                              ellipsis: true,
                              render: (x: string, r) => <Link to={`/hesaplar/${r.id}`}>{x}</Link>,
                            },
                            {
                              title: "Telefon",
                              dataIndex: "telefon",
                              width: 150,
                              className: "mono",
                              render: (x: string | null) => x ?? "—",
                            },
                            {
                              title: "E-posta",
                              dataIndex: "eposta",
                              width: 220,
                              ellipsis: true,
                              render: (x: string | null) => x ?? "—",
                            },
                            {
                              title: "",
                              width: 160,
                              render: (_: unknown, r) =>
                                r.anonim ? (
                                  <Tag>anonimleştirilmiş</Tag>
                                ) : (
                                  <Button
                                    size="small"
                                    danger
                                    onClick={() => setAnonimHedef({ id: r.id, unvan: r.unvan })}
                                  >
                                    Anonimleştir
                                  </Button>
                                ),
                            },
                          ]}
                        />

                        <Table
                          title={() => "Kişiler"}
                          rowKey="id"
                          size="small"
                          pagination={false}
                          dataSource={veri.data.kisiler}
                          scroll={{ x: 620 }}
                          locale={{ emptyText: <Empty description="Kişi kaydı yok" /> }}
                          columns={[
                            { title: "Ad soyad", dataIndex: "ad", width: 240, ellipsis: true },
                            {
                              title: "Telefon",
                              dataIndex: "telefon",
                              width: 150,
                              className: "mono",
                              render: (x: string | null) => x ?? "—",
                            },
                            {
                              title: "E-posta",
                              dataIndex: "eposta",
                              width: 220,
                              ellipsis: true,
                              render: (x: string | null) => x ?? "—",
                            },
                          ]}
                        />

                        <Table
                          title={() => "Araçlar"}
                          rowKey="id"
                          size="small"
                          pagination={{ pageSize: 10, hideOnSinglePage: true }}
                          dataSource={veri.data.araclar}
                          scroll={{ x: 520 }}
                          locale={{ emptyText: <Empty description="Araç kaydı yok" /> }}
                          columns={[
                            {
                              title: "Plaka",
                              dataIndex: "plaka",
                              width: 160,
                              className: "mono",
                              render: (x: string, r) => <Link to={`/araclar/${r.id}`}>{x}</Link>,
                            },
                            {
                              title: "Şase",
                              dataIndex: "sase",
                              width: 220,
                              className: "mono",
                              render: (x: string | null) => x ?? "—",
                            },
                          ]}
                        />

                        <Table
                          title={() => "Cihazlar"}
                          rowKey="device_id"
                          size="small"
                          pagination={{ pageSize: 10, hideOnSinglePage: true }}
                          dataSource={veri.data.cihazlar}
                          scroll={{ x: 420 }}
                          locale={{ emptyText: <Empty description="Cihaz kaydı yok" /> }}
                          columns={[
                            {
                              title: "Kimlik",
                              dataIndex: "kimlik",
                              width: 200,
                              className: "mono",
                              render: (x: string | null) =>
                                x ? <Link to={`/cihazlar/${x}`}>{x}</Link> : "—",
                            },
                            {
                              title: "Durum",
                              dataIndex: "status",
                              width: 160,
                              render: (x: string) => <Tag>{x.replaceAll("_", " ")}</Tag>,
                            },
                          ]}
                        />
                      </>
                    )}
                  </Space>
                </Card>
              </Space>
            ),
          },
          {
            key: "saklama",
            label: "Saklama süresi",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Alert
                  type="warning"
                  title="Bu liste otomatik hiçbir şey silmez"
                  description="Ölçüt: aktif aboneliği, üzerinde cihazı ve eşik süre içinde iş emri olmayan müşteriler. Karar insana bırakılır — yanlış bir ölçütün müşteri kaydını sessizce silmesi geri alınamazdı."
                />
                <Card
                  title="Saklama süresi dolmuş hesaplar"
                  extra={
                    <InputNumber
                      value={yil}
                      onChange={(v) => setYil(v == null ? null : Number(v))}
                      min={1}
                      max={30}
                      placeholder="ayardan"
                      addonAfter="yıl"
                      style={{ width: 150 }}
                    />
                  }
                >
                  <Table
                    rowKey="account_id"
                    size="small"
                    loading={saklama.isLoading}
                    dataSource={saklama.data?.kayitlar ?? []}
                    scroll={{ x: 760 }}
                    pagination={{ pageSize: 20, hideOnSinglePage: true }}
                    locale={{
                      emptyText: <Empty description="Saklama süresi dolan hesap yok" />,
                    }}
                    columns={[
                      {
                        title: "Unvan",
                        dataIndex: "unvan",
                        width: 280,
                        ellipsis: true,
                        render: (x: string, r) => <Link to={`/hesaplar/${r.account_id}`}>{x}</Link>,
                      },
                      {
                        title: "Telefon",
                        dataIndex: "telefon",
                        width: 150,
                        className: "mono",
                        render: (x: string | null) => x ?? "—",
                      },
                      {
                        title: "E-posta",
                        dataIndex: "eposta",
                        width: 220,
                        ellipsis: true,
                        render: (x: string | null) => x ?? "—",
                      },
                      {
                        title: "Eşik",
                        dataIndex: "esik_yil",
                        width: 90,
                        render: (x: number) => `${x} yıl`,
                      },
                      {
                        title: "",
                        width: 150,
                        render: (_: unknown, r) => (
                          <Button
                            size="small"
                            danger
                            onClick={() => setAnonimHedef({ id: r.account_id, unvan: r.unvan })}
                          >
                            Anonimleştir
                          </Button>
                        ),
                      },
                    ]}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: "log",
            label: "Erişim logu",
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Alert
                  type="info"
                  title="Kişisel veriyi kimin gördüğü"
                  description="Yazma işlemleri denetim izinde; burası KVKK'nın ayrıca istediği OKUMA kaydıdır. Liste ekranları değil, tek bir kişinin kartının açılması loglanır — aksi halde log gürültüden okunamazdı."
                />
                <Card title="Kişisel veri erişim logu">
                  <Table
                    rowKey="id"
                    size="small"
                    loading={log.isLoading}
                    dataSource={log.data ?? []}
                    scroll={{ x: 900 }}
                    pagination={{ pageSize: 25, hideOnSinglePage: true }}
                    locale={{ emptyText: <Empty description="Henüz erişim kaydı yok" /> }}
                    columns={[
                      {
                        title: "Zaman",
                        dataIndex: "created_at",
                        width: 160,
                        className: "mono",
                        render: (x: string) => dayjs(x).format("DD.MM.YYYY HH:mm"),
                      },
                      {
                        title: "Kullanıcı",
                        dataIndex: "user_id",
                        width: 180,
                        ellipsis: true,
                        render: (x: number | null) => adi(x),
                      },
                      {
                        title: "Kayıt",
                        width: 200,
                        render: (_: unknown, r: ErisimKaydi) => (
                          <Space size={4}>
                            <Tag>{r.entity}</Tag>
                            {r.entity_id && <span className="mono">#{r.entity_id}</span>}
                          </Space>
                        ),
                      },
                      { title: "İşlem", dataIndex: "action", width: 130 },
                      {
                        title: "Amaç",
                        dataIndex: "amac",
                        ellipsis: true,
                        render: (x: string | null) => x ?? "—",
                      },
                      {
                        title: "IP",
                        dataIndex: "ip",
                        width: 130,
                        className: "mono",
                        render: (x: string | null) => x ?? "—",
                      },
                    ]}
                  />
                </Card>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        open={anonimHedef != null}
        title="Hesabı anonimleştir"
        okText="Anonimleştir"
        okButtonProps={{ danger: true, disabled: !onay || gerekce.trim().length < 5 }}
        confirmLoading={anonimlestir.isPending}
        onOk={() => anonimHedef && anonimlestir.mutate(anonimHedef.id)}
        onCancel={() => {
          setAnonimHedef(null);
          setGerekce("");
          setOnay(false);
        }}
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="Hesap">{anonimHedef?.unvan}</Descriptions.Item>
          </Descriptions>
          <Alert
            type="error"
            title="Bu işlem geri alınamaz"
            description="Unvan, telefon, e-posta, VKN, IBAN, kişi adları ve plakalar maskelenir. Cihaz geçmişi, iş emirleri ve hak ediş kayıtları — ticari kayıt oldukları için — olduğu gibi kalır."
          />
          <Input.TextArea
            value={gerekce}
            onChange={(e) => setGerekce(e.target.value)}
            placeholder="Gerekçe: silme talebi referansı (en az 5 karakter)"
            rows={3}
            maxLength={300}
            showCount
          />
          <Checkbox checked={onay} onChange={(e) => setOnay(e.target.checked)}>
            İşlemin geri alınamaz olduğunu anlıyorum.
          </Checkbox>
          <Typography.Text type="secondary">
            İşlemi yapan kullanıcı ve gerekçe denetim izine yazılır.
          </Typography.Text>
        </Space>
      </Modal>
    </>
  );
}
