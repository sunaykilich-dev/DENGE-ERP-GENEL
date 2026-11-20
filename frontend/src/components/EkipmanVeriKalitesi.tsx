/**
 * Ekipman Kütüğü › Veri Kalitesi (TS-188 / TS-191, E03-13/14).
 *
 * Kutular sunucunun sayısını gösterir (sayı = liste). "liste" türündeki kutu
 * kütük listesini `?kalite=<kod>` süzgeciyle açar; mükerrer grup ve saha farkı
 * kutuları bu panelde kendi sayfalı listesini açar. Birleştirme ve "kütüğe
 * uygula" yalnız `ekipman.yaz` sahibine görünür; ikisi de sunucuda kural
 * ihlalinde (açık bağ, seri çakışması) 409 + liste döner ve hiçbir şey değişmez.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Modal,
  Radio,
  Row,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  DURUM_ETIKETLERI,
  ekipmanApi,
  EkipmanHatasi,
  TIP_ETIKETLERI,
  type MukerrerGrup,
  type SahaFarki,
} from "../api/servisEkipman";
import { useAuth } from "../auth/AuthContext";
import Statistic from "./Statistic";

const SAYFA = 20;

export interface EkipmanVeriKalitesiProps {
  /** Açık liste: "mukerrer" | "saha" | null. */
  liste: string | null;
  onListe: (liste: string | null) => void;
  /** "liste" türü kutu tıklanınca kütük süzgeci uygulanır. */
  onKalite: (kod: string) => void;
}

function engelMetni(e: unknown): string | null {
  if (!(e instanceof EkipmanHatasi) || !e.detay) return null;
  const d = e.detay as Record<string, { so_no?: string; sozlesme_no?: string; atolye_no?: string }[]>;
  const parcalar = [
    ...(d.sozlesme_kalemleri ?? []).map((x) => `Sözleşme ${x.sozlesme_no}`),
    ...(d.servis_isleri ?? []).map((x) => `İş ${x.so_no}`),
    ...(d.atolye_kayitlari ?? []).map((x) => `Atölye ${x.atolye_no}`),
  ];
  return parcalar.length ? parcalar.join(", ") : null;
}

export default function EkipmanVeriKalitesi({ liste, onListe, onKalite }: EkipmanVeriKalitesiProps) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const git = useNavigate();
  const yazabilir = yetkili("ekipman.yaz");
  const [sayfa, setSayfa] = useState(1);
  const [grup, setGrup] = useState<MukerrerGrup | null>(null);
  const [ana, setAna] = useState<number | null>(null);
  const [gerekce, setGerekce] = useState("");
  const [yoksay, setYoksay] = useState<SahaFarki | null>(null);
  const [hata, setHata] = useState<string | null>(null);

  const ozet = useQuery({ queryKey: ["ekipman-kalite"], queryFn: ekipmanApi.veriKalitesi });
  const gruplar = useQuery({
    queryKey: ["ekipman-mukerrer", sayfa],
    queryFn: () => ekipmanApi.mukerrerGruplar(SAYFA, (sayfa - 1) * SAYFA),
    enabled: liste === "mukerrer",
  });
  const farklar = useQuery({
    queryKey: ["ekipman-saha", sayfa],
    queryFn: () => ekipmanApi.sahaFarklari(SAYFA, (sayfa - 1) * SAYFA),
    enabled: liste === "saha",
  });

  const tazele = () => {
    for (const k of ["ekipman-kalite", "ekipman-mukerrer", "ekipman-saha", "servis-ekipman"]) {
      void qc.invalidateQueries({ queryKey: [k] });
    }
  };

  const birlestir = useMutation({
    mutationFn: async () => {
      if (!grup || ana == null) return;
      // Ana dışındaki her kayıt sırayla birleştirilir; ilk engelde durur.
      for (const k of grup.kayitlar) {
        if (k.id !== ana) await ekipmanApi.birlestir(k.id, ana, gerekce);
      }
    },
    onSuccess: () => {
      message.success("Kayıtlar birleştirildi");
      setGrup(null);
      tazele();
    },
    onError: (e: Error) => {
      const engel = engelMetni(e);
      setHata(engel ? `${e.message} (${engel})` : e.message);
      tazele();
    },
  });

  const uygula = useMutation({
    mutationFn: (f: SahaFarki) => ekipmanApi.sahaUygula(f.so_id),
    onSuccess: () => {
      message.success("Kütüğe uygulandı");
      tazele();
    },
    onError: (e: Error) => void message.error(e.message),
  });

  const yoksayMut = useMutation({
    mutationFn: () => ekipmanApi.sahaYoksay(yoksay!.so_id, gerekce),
    onSuccess: () => {
      message.success("Fark yok sayıldı");
      setYoksay(null);
      tazele();
    },
    onError: (e: Error) => void message.error(e.message),
  });

  return (
    <Card size="small" title="Veri Kalitesi">
      <Row gutter={[12, 12]}>
        {(ozet.data ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={6} xl={3}>
            <Card
              size="small"
              hoverable
              role="link"
              tabIndex={0}
              data-kalite={k.kod}
              onClick={() => {
                setSayfa(1);
                if (k.liste === "liste") onKalite(k.kod);
                else onListe(k.liste);
              }}
              style={{ height: "100%", borderColor: liste === k.liste && k.liste !== "liste" ? "#b7791f" : undefined }}
            >
              <Statistic
                title={<span title={k.tanim}>{k.baslik}</span>}
                value={k.deger}
                valueStyle={{ color: k.deger ? "#b7791f" : undefined }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {liste === "mukerrer" && (
        <Table<MukerrerGrup>
          style={{ marginTop: 12 }}
          size="small"
          rowKey={(g) => `${g.tip}|${g.seri_anahtari}|${g.kayitlar.map((k) => k.id).join(",")}`}
          loading={gruplar.isLoading}
          dataSource={gruplar.data?.kayitlar ?? []}
          locale={{ emptyText: <Empty description="Mükerrer seri grubu yok" /> }}
          scroll={{ x: 640 }}
          pagination={{
            current: sayfa,
            pageSize: SAYFA,
            total: gruplar.data?.toplam ?? 0,
            onChange: setSayfa,
            showSizeChanger: false,
            showTotal: (t) => `${t} grup`,
          }}
          columns={[
            { title: "Tip", dataIndex: "tip", width: 140, render: (t: string) => TIP_ETIKETLERI[t] ?? t },
            { title: "Seri", dataIndex: "seri_anahtari", width: 140, render: (s) => <span className="mono">{s}</span> },
            {
              title: "Kayıtlar",
              key: "k",
              render: (_, g) => (
                <Space orientation="vertical" size={2}>
                  {g.kayitlar.map((k) => (
                    <Typography.Link key={k.id} onClick={() => git(`/servis-ekipman/${k.id}`)}>
                      #{k.id} · {k.hesap_unvan ?? "müşteri yok"}
                      {k.lokasyon_adi ? ` · ${k.lokasyon_adi}` : ""} ·{" "}
                      {DURUM_ETIKETLERI[k.lifecycle_status] ?? k.lifecycle_status}
                    </Typography.Link>
                  ))}
                </Space>
              ),
            },
            ...(yazabilir
              ? [
                  {
                    title: "",
                    key: "islem",
                    width: 110,
                    render: (_: unknown, g: MukerrerGrup) => (
                      <Button
                        size="small"
                        onClick={() => {
                          setGrup(g);
                          setAna(g.kayitlar[0]?.id ?? null);
                          setGerekce("");
                          setHata(null);
                        }}
                      >
                        Birleştir
                      </Button>
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}

      {liste === "saha" && (
        <Table<SahaFarki>
          style={{ marginTop: 12 }}
          size="small"
          rowKey="sonuc_id"
          loading={farklar.isLoading}
          dataSource={farklar.data?.kayitlar ?? []}
          locale={{ emptyText: <Empty description="Karar bekleyen saha farkı yok" /> }}
          scroll={{ x: 760 }}
          pagination={{
            current: sayfa,
            pageSize: SAYFA,
            total: farklar.data?.toplam ?? 0,
            onChange: setSayfa,
            showSizeChanger: false,
          }}
          columns={[
            {
              title: "İş",
              dataIndex: "so_no",
              width: 150,
              render: (n: string, f) => (
                <Typography.Link onClick={() => git(`/servis-isleri/${f.so_id}`)}>{n}</Typography.Link>
              ),
            },
            {
              title: "Kütük",
              key: "kutuk",
              render: (_, f) =>
                f.ekipman_id ? (
                  <Typography.Link onClick={() => git(`/servis-ekipman/${f.ekipman_id}`)}>
                    {f.kutuk_seri ?? "seri yok"}
                    {f.kutuk_bolge ? ` · ${f.kutuk_bolge}` : ""}
                  </Typography.Link>
                ) : (
                  <Tag>ekipman bağlı değil</Tag>
                ),
            },
            {
              title: "Saha",
              key: "saha",
              render: (_, f) => [f.saha_seri, f.saha_bolge].filter(Boolean).join(" · ") || "—",
            },
            { title: "Teknisyen", dataIndex: "teknisyen", render: (v) => v ?? "—" },
            { title: "Tarih", dataIndex: "tarih", width: 100, render: (d: string) => dayjs(d).format("DD.MM.YYYY") },
            ...(yazabilir
              ? [
                  {
                    title: "",
                    key: "islem",
                    width: 190,
                    render: (_: unknown, f: SahaFarki) => (
                      <Space size={4}>
                        <Button
                          size="small"
                          type="primary"
                          disabled={!f.ekipman_id}
                          loading={uygula.isPending && uygula.variables?.so_id === f.so_id}
                          onClick={() => uygula.mutate(f)}
                        >
                          Kütüğe uygula
                        </Button>
                        <Button
                          size="small"
                          onClick={() => {
                            setYoksay(f);
                            setGerekce("");
                          }}
                        >
                          Yok say
                        </Button>
                      </Space>
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}

      <Modal
        title="Mükerrer kayıtları birleştir"
        open={grup != null}
        onCancel={() => setGrup(null)}
        onOk={() => birlestir.mutate()}
        okText="Birleştir"
        cancelText="Vazgeç"
        okButtonProps={{ disabled: ana == null || gerekce.trim().length < 5 }}
        confirmLoading={birlestir.isPending}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          Kalacak (ana) kaydı seçin. Diğerleri pasife alınır ve "birleştirildi" bağı taşır; geçmiş,
          ekler ve kapanmış işler onlarda kalır. Açık sözleşme kalemi, servis işi ya da atölye kaydı
          olan kayıt birleştirilemez.
        </Typography.Paragraph>
        <Radio.Group value={ana} onChange={(e) => setAna(e.target.value)}>
          <Space orientation="vertical">
            {grup?.kayitlar.map((k) => (
              <Radio key={k.id} value={k.id}>
                #{k.id} · {k.hesap_unvan ?? "müşteri yok"} · {k.serial_no ?? "—"} ·{" "}
                {dayjs(k.created_at).format("DD.MM.YYYY")}
              </Radio>
            ))}
          </Space>
        </Radio.Group>
        <Input.TextArea
          style={{ marginTop: 12 }}
          rows={2}
          maxLength={500}
          placeholder="Gerekçe (en az 5 karakter)"
          value={gerekce}
          onChange={(e) => setGerekce(e.target.value)}
        />
        {hata && <Alert style={{ marginTop: 12 }} type="error" showIcon title={hata} />}
      </Modal>

      <Modal
        title={`Saha farkını yok say — ${yoksay?.so_no ?? ""}`}
        open={yoksay != null}
        onCancel={() => setYoksay(null)}
        onOk={() => yoksayMut.mutate()}
        okText="Yok say"
        cancelText="Vazgeç"
        okButtonProps={{ disabled: gerekce.trim().length < 5 }}
        confirmLoading={yoksayMut.isPending}
        destroyOnHidden
      >
        <Input.TextArea
          rows={2}
          maxLength={500}
          placeholder="Gerekçe (en az 5 karakter) — ekipman geçmişine yazılır"
          value={gerekce}
          onChange={(e) => setGerekce(e.target.value)}
        />
      </Modal>
    </Card>
  );
}
