import { InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Radio,
  Segmented,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import { useState } from "react";

import { api, type ApiError } from "../api/client";
import Statistic from "../components/Statistic";

interface ProfilSutunu {
  alan: string;
  baslik: string;
  zorunlu: boolean;
  aciklama: string;
}

interface Profil {
  kod: string;
  ad: string;
  aciklama: string;
  izin: string;
  sutunlar: ProfilSutunu[];
}

interface Satir {
  satir_no: number;
  veri: Record<string, string | null>;
  hatalar: string[];
  uyarilar: string[];
  cakisma: { tip: string; kayit_id: number; aciklama: string } | null;
  ham: Record<string, string>;
}

interface Parti {
  id: number;
  profile: string;
  filename: string;
  status: string;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  conflict_rows: number;
  created_rows: number;
  updated_rows: number;
  skipped_rows: number;
}

const DURUM_RENGI: Record<string, string> = {
  HAZIR: "gold",
  AKTARILDI: "green",
  IPTAL: "default",
};

/** Satırın önizlemedeki durumu — sıralama ve rozet bunu kullanır. */
function satirDurumu(s: Satir): "hata" | "cakisma" | "uyari" | "gecerli" {
  if (s.hatalar.length) return "hata";
  if (s.cakisma) return "cakisma";
  if (s.uyarilar.length) return "uyari";
  return "gecerli";
}

export default function IceAktarmaPage() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const [kod, setKod] = useState<string | null>(null);
  const [parti, setParti] = useState<Parti | null>(null);
  const [satirlar, setSatirlar] = useState<Satir[]>([]);
  const [kararlar, setKararlar] = useState<Record<number, string>>({});
  const [suzgec, setSuzgec] = useState<string>("hepsi");

  const profiller = useQuery({
    queryKey: ["ice-profiller"],
    queryFn: () => api.get<Profil[]>("/api/ice-aktarma/profiller"),
  });

  const partiler = useQuery({
    queryKey: ["ice-partiler"],
    queryFn: () => api.get<Parti[]>("/api/ice-aktarma/partiler"),
  });

  const secili = (profiller.data ?? []).find((p) => p.kod === kod) ?? null;

  const hata = (e: ApiError) => void message.error(e.message);

  const uygula = useMutation({
    mutationFn: (id: number) =>
      api.post<{ parti: Parti; sonuc: Record<string, number> }>(
        `/api/ice-aktarma/partiler/${id}/uygula`,
        { kararlar },
      ),
    onSuccess: (r) => {
      message.success(
        `${r.sonuc.eklendi} eklendi, ${r.sonuc.guncellendi} güncellendi, ` +
          `${r.sonuc.atlandi} atlandı`,
      );
      setParti(r.parti);
      setSatirlar([]);
      setKararlar({});
      void qc.invalidateQueries({ queryKey: ["ice-partiler"] });
    },
    onError: hata,
  });

  const iptal = useMutation({
    mutationFn: (id: number) => api.post(`/api/ice-aktarma/partiler/${id}/iptal`),
    onSuccess: () => {
      message.success("Parti iptal edildi");
      setParti(null);
      setSatirlar([]);
      void qc.invalidateQueries({ queryKey: ["ice-partiler"] });
    },
    onError: hata,
  });

  async function dosyaYukle(file: File) {
    if (!kod) return false;
    const gövde = new FormData();
    gövde.append("file", file);
    try {
      // FormData gönderirken Content-Type'ı tarayıcı sınır (boundary) ile
      // birlikte kendisi koymalı; elle koymak isteği bozar.
      const res = await fetch(`/api/ice-aktarma/${kod}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        body: gövde,
      });
      const veri = await res.json();
      if (!res.ok) {
        message.error(typeof veri?.detail === "string" ? veri.detail : "Dosya okunamadı");
        return false;
      }
      setParti(veri.parti);
      setSatirlar(veri.satirlar);
      setKararlar({});
      setSuzgec(veri.parti.error_rows || veri.parti.conflict_rows ? "sorunlu" : "hepsi");
      message.success(`${veri.parti.total_rows} satır okundu — henüz hiçbir şey yazılmadı`);
      void qc.invalidateQueries({ queryKey: ["ice-partiler"] });
    } catch {
      message.error("Dosya yüklenemedi");
    }
    return false;
  }

  function uygulaSor() {
    if (!parti) return;
    const cakismali = satirlar.filter((s) => s.cakisma && !s.hatalar.length);
    const guncellenecek = cakismali.filter((s) => kararlar[s.satir_no] === "guncelle").length;
    const yazilacak = satirlar.filter(
      (s) => !s.hatalar.length && (!s.cakisma || kararlar[s.satir_no] === "guncelle"),
    ).length;

    modal.confirm({
      title: "İçe aktarmayı uygula",
      content: (
        <Space orientation="vertical">
          <Typography.Text>
            <strong>{yazilacak}</strong> satır yazılacak ({guncellenecek} tanesi mevcut kaydı
            güncelleyecek).
          </Typography.Text>
          <Typography.Text type="secondary">
            Hatalı satırlar ve karar verilmeyen çakışmalar atlanır. İşlem tek transaction'da
            yürür — yarım kalmış parti oluşmaz.
          </Typography.Text>
        </Space>
      ),
      okText: "Uygula",
      cancelText: "Vazgeç",
      onOk: () => uygula.mutateAsync(parti.id),
    });
  }

  const gorunen = satirlar.filter((s) => {
    if (suzgec === "hepsi") return true;
    if (suzgec === "sorunlu") return s.hatalar.length > 0 || s.cakisma != null;
    return satirDurumu(s) === suzgec;
  });

  // Önizlemede ham verinin ilk birkaç sütunu gösterilir; kullanıcı satırı
  // tanısın yeter, tamamı karantina raporunda zaten var.
  const ozetKolonlari = secili
    ? secili.sutunlar.slice(0, 3).map((c) => ({
        title: c.baslik,
        width: 160,
        ellipsis: true,
        render: (_: unknown, s: Satir) => s.ham[c.alan] ?? "—",
      }))
    : [];

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card title="Toplu içe aktarma">
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Alert
            type="info"
            title="Yüklemek yazmak değildir"
            description="Dosya önce okunur ve doğrulanır; ne gireceğini, neyin hata verdiğini ve neyin zaten kayıtlı olduğunu gördükten sonra onaylarsınız."
          />

          {profiller.data?.length === 0 ? (
            <Empty description="Yetkili olduğunuz bir içe aktarma profili yok" />
          ) : (
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              <Space wrap>
                {(profiller.data ?? []).map((p) => (
                  <Button
                    key={p.kod}
                    type={kod === p.kod ? "primary" : "default"}
                    onClick={() => {
                      setKod(p.kod);
                      setParti(null);
                      setSatirlar([]);
                    }}
                  >
                    {p.ad}
                  </Button>
                ))}
              </Space>

              {secili && (
                <>
                  <Typography.Text type="secondary">{secili.aciklama}</Typography.Text>
                  <Space wrap>
                    <Button
                      onClick={() =>
                        window.open(
                          `/api/ice-aktarma/profiller/${secili.kod}/sablon.xlsx`,
                          "_blank",
                        )
                      }
                    >
                      Boş şablon indir
                    </Button>
                    <Typography.Text type="secondary">
                      Zorunlu sütunlar:{" "}
                      {secili.sutunlar
                        .filter((c) => c.zorunlu)
                        .map((c) => c.baslik)
                        .join(", ") || "yok"}
                    </Typography.Text>
                  </Space>

                  <Upload.Dragger
                    accept=".xlsx,.xlsm,.csv"
                    maxCount={1}
                    showUploadList={false}
                    beforeUpload={dosyaYukle}
                  >
                    <p className="ant-upload-drag-icon">
                      <InboxOutlined />
                    </p>
                    <p className="ant-upload-text">
                      Dosyayı sürükleyin ya da seçmek için tıklayın
                    </p>
                    <p className="ant-upload-hint">
                      .xlsx veya .csv · başlık satırı sayfanın herhangi bir yerinde olabilir
                    </p>
                  </Upload.Dragger>
                </>
              )}
            </Space>
          )}
        </Space>
      </Card>

      {parti && satirlar.length > 0 && (
        <Card
          title={`Önizleme · ${parti.filename}`}
          extra={
            <Space>
              <Button
                onClick={() =>
                  window.open(`/api/ice-aktarma/partiler/${parti.id}/karantina.xlsx`, "_blank")
                }
              >
                Karantina indir
              </Button>
              <Button danger onClick={() => iptal.mutate(parti.id)}>
                Vazgeç
              </Button>
              <Button
                type="primary"
                loading={uygula.isPending}
                disabled={parti.valid_rows === 0 && parti.conflict_rows === 0}
                onClick={uygulaSor}
              >
                Uygula
              </Button>
            </Space>
          }
        >
          <Space orientation="vertical" size={16} style={{ width: "100%" }}>
            <Space size={40} wrap>
              <Statistic title="Toplam satır" value={parti.total_rows} />
              <Statistic
                title="Sorunsuz"
                value={parti.valid_rows}
                valueStyle={{ color: "#1f6b4d" }}
              />
              <Statistic
                title="Çakışma"
                value={parti.conflict_rows}
                valueStyle={parti.conflict_rows ? { color: "#b58105" } : undefined}
              />
              <Statistic
                title="Hatalı"
                value={parti.error_rows}
                valueStyle={parti.error_rows ? { color: "#b42318" } : undefined}
              />
            </Space>

            {parti.conflict_rows > 0 && (
              <Alert
                type="warning"
                title={`${parti.conflict_rows} satır zaten sistemde kayıtlı`}
                description="Karar verilmeyen çakışmalı satır ATLANIR. Mevcut kaydın üzerine yazılmasını istiyorsanız satırda 'Güncelle' seçin."
              />
            )}

            <Segmented
              value={suzgec}
              onChange={(v) => setSuzgec(String(v))}
              options={[
                { label: `Hepsi (${satirlar.length})`, value: "hepsi" },
                {
                  label: `Sorunlu (${parti.error_rows + parti.conflict_rows})`,
                  value: "sorunlu",
                },
                { label: `Hatalı (${parti.error_rows})`, value: "hata" },
                { label: `Çakışma (${parti.conflict_rows})`, value: "cakisma" },
                { label: `Sorunsuz (${parti.valid_rows})`, value: "gecerli" },
              ]}
            />

            <Table
              rowKey="satir_no"
              size="small"
              dataSource={gorunen}
              scroll={{ x: 1180 }}
              pagination={{ pageSize: 25, showSizeChanger: false }}
              locale={{ emptyText: <Empty description="Bu süzgeçte satır yok" /> }}
              columns={[
                { title: "Satır", dataIndex: "satir_no", width: 70, className: "mono" },
                {
                  title: "Durum",
                  width: 110,
                  render: (_: unknown, s: Satir) => {
                    const d = satirDurumu(s);
                    const etiket = {
                      hata: ["red", "hata"],
                      cakisma: ["gold", "çakışma"],
                      uyari: ["blue", "uyarı"],
                      gecerli: ["green", "hazır"],
                    }[d];
                    return <Tag color={etiket[0]}>{etiket[1]}</Tag>;
                  },
                },
                ...ozetKolonlari,
                {
                  title: "Açıklama",
                  width: 420,
                  render: (_: unknown, s: Satir) => (
                    <Space orientation="vertical" size={2}>
                      {s.hatalar.map((h, i) => (
                        <Typography.Text key={`h${i}`} type="danger">
                          {h}
                        </Typography.Text>
                      ))}
                      {s.cakisma && (
                        <Typography.Text type="warning">{s.cakisma.aciklama}</Typography.Text>
                      )}
                      {s.uyarilar.map((u, i) => (
                        <Typography.Text key={`u${i}`} type="secondary">
                          {u}
                        </Typography.Text>
                      ))}
                    </Space>
                  ),
                },
                {
                  title: "Karar",
                  width: 180,
                  render: (_: unknown, s: Satir) =>
                    s.hatalar.length ? (
                      <Tooltip title="Hatalı satır hiçbir koşulda yazılmaz">
                        <Typography.Text type="secondary">yazılmayacak</Typography.Text>
                      </Tooltip>
                    ) : s.cakisma ? (
                      <Radio.Group
                        size="small"
                        value={kararlar[s.satir_no] ?? "atla"}
                        onChange={(e) =>
                          setKararlar((k) => ({ ...k, [s.satir_no]: e.target.value }))
                        }
                        options={[
                          { label: "Atla", value: "atla" },
                          { label: "Güncelle", value: "guncelle" },
                        ]}
                        optionType="button"
                      />
                    ) : (
                      <Typography.Text type="secondary">eklenecek</Typography.Text>
                    ),
                },
              ]}
            />
          </Space>
        </Card>
      )}

      <Card title="Geçmiş partiler">
        <Table
          rowKey="id"
          size="small"
          loading={partiler.isLoading}
          dataSource={partiler.data ?? []}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="Henüz içe aktarma yapılmadı" /> }}
          columns={[
            { title: "Dosya", dataIndex: "filename" },
            {
              title: "Profil",
              dataIndex: "profile",
              width: 120,
              render: (x: string) =>
                (profiller.data ?? []).find((p) => p.kod === x)?.ad ?? x,
            },
            {
              title: "Durum",
              dataIndex: "status",
              width: 120,
              render: (x: string) => <Tag color={DURUM_RENGI[x]}>{x.toLowerCase()}</Tag>,
            },
            { title: "Satır", dataIndex: "total_rows", width: 80, className: "mono" },
            {
              title: "Sonuç",
              width: 220,
              className: "mono",
              render: (_: unknown, p: Parti) =>
                p.status === "AKTARILDI"
                  ? `+${p.created_rows} yeni · ${p.updated_rows} güncel · ${p.skipped_rows} atlandı`
                  : "—",
            },
            {
              title: "",
              width: 120,
              render: (_: unknown, p: Parti) => (
                <Button
                  size="small"
                  type="link"
                  onClick={() =>
                    window.open(`/api/ice-aktarma/partiler/${p.id}/karantina.xlsx`, "_blank")
                  }
                >
                  Karantina
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
