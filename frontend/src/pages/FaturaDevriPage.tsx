/**
 * Fatura devri (TS-197, E07-26) — "Faturaya iletildi" işareti (Logo entegrasyonu değil).
 *
 * - Menü izni `tahsilat.gor`; işaret ve geri alma `tahsilat.yaz`; "Dışa aktar"
 *   (Excel / CSV Logo) `rapor.disaaktar` VEYA `servis_rapor.disaaktar` — Finans
 *   Uzmanı da teknik servis rolleri de alır (sunucu kapısıyla aynı kural).
 *   Düğmeler `yetkili()` ile gizlenir.
 * - İş No, `servis.gor` sahibinde işin kartını açan bağlantıdır.
 * - Bekleyen: kabul edilmiş birimli teklifi ya da elle/sözleşme/teklif geliri
 *   olan kapanmış servis işleri. Çoklu seçimle toplu işaret; bir iş bile uygun
 *   değilse sunucu TAMAMINI reddeder (409) ve sorunlu işler gösterilir.
 * - İletilenler: kim ve ne zaman; gerekçeyle geri alınabilir. İşaretten sonra
 *   işin geliri değiştirilemez (sunucu kilidi).
 * - Tutar kolonu yalnız sunucu `tutar` anahtarını döndürdüğünde görünür.
 * - 375 px'te tablo yatay kayar; 409'da yenileme mesajı.
 */
import { DownOutlined, DownloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Dropdown,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import {
  type DevirSatiri,
  type DevirSuzgeci,
  servisMaliyetApi,
  tl,
} from "../api/servisMaliyet";
import { useAuth } from "../auth/AuthContext";

const SAYFA = 50;
const tarih = (v: string | null | undefined) => (v ? dayjs(v).format("DD.MM.YYYY") : "—");
const zaman = (v: string | null | undefined) => (v ? dayjs(v).format("DD.MM.YYYY HH:mm") : "—");

function hataMetni(e: unknown): string {
  if (e instanceof ApiError) {
    const govde = e.govde as { detail?: { mesaj?: string; sorunlu_isler?: number[] } } | undefined;
    const d = govde?.detail;
    if (d && typeof d === "object" && d.mesaj) {
      return d.sorunlu_isler?.length
        ? `${d.mesaj} (sorunlu iş kimlikleri: ${d.sorunlu_isler.join(", ")}). Listeyi yenileyin.`
        : d.mesaj;
    }
    if (e.status === 409) return `${e.message} — kayıt değişmiş olabilir, listeyi yenileyin.`;
    return e.message;
  }
  return (e as Error).message;
}

export default function FaturaDevriPage() {
  const [sekme, setSekme] = useState<"bekleyen" | "iletildi">("bekleyen");
  return (
    <Card>
      <Typography.Title level={4}>Fatura Devri</Typography.Title>
      <Typography.Paragraph type="secondary">
        Kabul edilmiş teklifi ya da girilmiş geliri olan kapanmış servis işleri. "Faturaya
        iletildi" işareti muhasebe devrini kaydeder; işaretten sonra işin geliri değiştirilemez.
      </Typography.Paragraph>
      <Tabs
        activeKey={sekme}
        onChange={(k) => setSekme(k as "bekleyen" | "iletildi")}
        items={[
          { key: "bekleyen", label: "Bekleyenler", children: <DevirListesi durum="bekleyen" /> },
          { key: "iletildi", label: "İletilenler", children: <DevirListesi durum="iletildi" /> },
        ]}
      />
    </Card>
  );
}

function DevirListesi({ durum }: { durum: "bekleyen" | "iletildi" }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [sayfa, setSayfa] = useState(1);
  const [donem, setDonem] = useState<string | null>(null);
  const [birim, setBirim] = useState<string | null>(null);
  const [secili, setSecili] = useState<number[]>([]);
  const [notPenceresi, setNotPenceresi] = useState(false);
  const [not, setNot] = useState("");
  const [geriAl, setGeriAl] = useState<DevirSatiri | null>(null);
  const [gerekce, setGerekce] = useState("");
  const [hata, setHata] = useState<string | null>(null);

  const suzgec: DevirSuzgeci = { durum, donem, birim };
  const liste = useQuery({
    queryKey: ["fatura-devri", suzgec, sayfa],
    queryFn: () =>
      servisMaliyetApi.faturaDevri({ ...suzgec, limit: SAYFA, offset: (sayfa - 1) * SAYFA }),
  });
  const yenile = () => qc.invalidateQueries({ queryKey: ["fatura-devri"] });

  const isaretle = useMutation({
    mutationFn: () => servisMaliyetApi.faturaIsaretle(secili, not),
    onSuccess: (r) => {
      message.success(`${r.isaretlenen.length} iş faturaya iletildi olarak işaretlendi`);
      setSecili([]);
      setNot("");
      setNotPenceresi(false);
      setHata(null);
      yenile();
    },
    onError: (e) => {
      setHata(hataMetni(e));
      setNotPenceresi(false);
    },
  });
  const geriAlMut = useMutation({
    mutationFn: () => servisMaliyetApi.faturaGeriAl(geriAl!.so_id, gerekce),
    onSuccess: () => {
      message.success("Devir geri alındı");
      setGeriAl(null);
      setGerekce("");
      yenile();
    },
    onError: (e) => void message.error(hataMetni(e)),
  });

  const tutarVar = (liste.data?.kayitlar ?? []).some((r) => "tutar" in r);
  // Sunucu kapısı: tahsilat.gor VE (rapor.disaaktar VEYA servis_rapor.disaaktar).
  const disaAktarabilir = yetkili("rapor.disaaktar") || yetkili("servis_rapor.disaaktar");
  const isGorebilir = yetkili("servis.gor");
  const kolonlar: ColumnsType<DevirSatiri> = [
    {
      title: "İş No",
      dataIndex: "so_no",
      className: "mono",
      width: 160,
      render: (v: string, r) =>
        isGorebilir ? <Link to={`/servis-isleri/${r.so_id}`}>{v}</Link> : v,
    },
    { title: "Birim", dataIndex: "birim", render: (v: string) => BIRIM_ETIKETLERI[v] ?? v },
    { title: "Müşteri", dataIndex: "musteri", render: (v) => v ?? "—" },
    { title: "Kapanış", dataIndex: "kapanis_tarihi", render: tarih, width: 110 },
    {
      title: "Dayanak",
      render: (_, r) => (
        <Space size={4} wrap>
          {r.teklifler.map((t) => (
            <Tag key={t}>{t}</Tag>
          ))}
          {r.gelir_kaynagi && r.gelir_kaynagi !== "TEKLIF" && <Tag>{r.gelir_kaynagi}</Tag>}
        </Space>
      ),
    },
    ...(tutarVar
      ? ([
          {
            title: "Tutar (KDV hariç)",
            dataIndex: "tutar",
            render: (v: DevirSatiri["tutar"]) => tl(v),
          },
        ] as ColumnsType<DevirSatiri>)
      : []),
    ...(durum === "iletildi"
      ? ([
          { title: "İletildi", dataIndex: "fatura_iletildi_at", render: zaman },
          { title: "İleten", dataIndex: "iletti", render: (v) => v ?? "—" },
          { title: "Not", dataIndex: "fatura_notu", render: (v) => v ?? "—" },
          ...(yetkili("tahsilat.yaz")
            ? [
                {
                  title: "",
                  key: "eylem",
                  render: (_: unknown, r: DevirSatiri) => (
                    <Button size="small" onClick={() => setGeriAl(r)}>
                      Geri al
                    </Button>
                  ),
                },
              ]
            : []),
        ] as ColumnsType<DevirSatiri>)
      : []),
  ];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <DatePicker
          picker="month"
          format="MM.YYYY"
          placeholder={durum === "bekleyen" ? "Kapanış ayı" : "Devir ayı"}
          onChange={(d) => {
            setDonem(d ? d.format("YYYY-MM") : null);
            setSayfa(1);
          }}
        />
        <Select
          allowClear
          placeholder="Birim"
          style={{ width: 170 }}
          value={birim ?? undefined}
          onChange={(v) => {
            setBirim(v ?? null);
            setSayfa(1);
          }}
          options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))}
        />
        {durum === "bekleyen" && yetkili("tahsilat.yaz") && (
          <Button
            type="primary"
            disabled={!secili.length}
            onClick={() => setNotPenceresi(true)}
          >
            Faturaya iletildi olarak işaretle ({secili.length})
          </Button>
        )}
        {disaAktarabilir && (
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                { key: "xlsx", label: "Excel" },
                { key: "csv", label: "CSV (Logo)" },
              ],
              onClick: ({ key }) => {
                const adres = servisMaliyetApi.faturaDevriExcelAdresi(suzgec);
                window.open(key === "csv" ? `${adres}&bicim=csv` : adres, "_blank");
              },
            }}
          >
            <Button icon={<DownloadOutlined />}>
              Dışa aktar <DownOutlined />
            </Button>
          </Dropdown>
        )}
      </Space>
      {hata && <Alert type="error" showIcon closable message={hata} onClose={() => setHata(null)} />}
      {liste.isError && <Alert type="error" message={(liste.error as Error).message} />}
      <Table<DevirSatiri>
        rowKey="so_id"
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 900 }}
        rowSelection={
          durum === "bekleyen" && yetkili("tahsilat.yaz")
            ? {
                selectedRowKeys: secili,
                onChange: (k) => setSecili(k as number[]),
                preserveSelectedRowKeys: true,
              }
            : undefined
        }
        pagination={{
          current: sayfa,
          pageSize: SAYFA,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} iş`,
        }}
        columns={kolonlar}
      />
      <Modal
        open={notPenceresi}
        title={`${secili.length} işi faturaya iletildi olarak işaretle`}
        okText="İşaretle"
        cancelText="Vazgeç"
        confirmLoading={isaretle.isPending}
        onOk={() => isaretle.mutate()}
        onCancel={() => setNotPenceresi(false)}
      >
        <Typography.Paragraph type="secondary">
          İşaretten sonra bu işlerin geliri değiştirilemez; gerekirse devir gerekçeyle geri alınır.
        </Typography.Paragraph>
        <Input.TextArea
          rows={3}
          maxLength={300}
          placeholder="Not (ör. fatura dönemi) — isteğe bağlı"
          value={not}
          onChange={(e) => setNot(e.target.value)}
        />
      </Modal>
      <Modal
        open={geriAl !== null}
        title={`Devri geri al: ${geriAl?.so_no ?? ""}`}
        okText="Geri al"
        cancelText="Vazgeç"
        okButtonProps={{ disabled: !gerekce.trim(), danger: true }}
        confirmLoading={geriAlMut.isPending}
        onOk={() => geriAlMut.mutate()}
        onCancel={() => setGeriAl(null)}
      >
        <Input.TextArea
          rows={3}
          maxLength={300}
          placeholder="Gerekçe (zorunlu)"
          value={gerekce}
          onChange={(e) => setGerekce(e.target.value)}
        />
      </Modal>
    </Space>
  );
}
