import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Input,
  Progress,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, type ApiError } from "../api/client";
import Statistic from "../components/Statistic";
import { useAuth } from "../auth/AuthContext";

interface Hat {
  id: number;
  iccid: string;
  msisdn: string | null;
  operator: string;
  status: string;
  plan_name: string | null;
  data_allowance_mb: number | null;
  data_used_mb: number | null;
  tariff_cost: number | null;
  package_cost: number | null;
  apn_cost: number | null;
  aylik_maliyet: number;
  monthly_charge: number | null;
  discount_rate: number | null;
  commitment_end_date: string | null;
  taahhut_kalan_gun: number | null;
  iccid_saglamasi: boolean;
  iccid_eksik: boolean;
}

const tl = (v: number | null | undefined) =>
  v == null ? "—" : `${Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2 })} ₺`;

interface KotaSatiri {
  sim_id: number;
  iccid: string;
  msisdn: string | null;
  yuzde: number;
  seviye: string;
}

interface RiskSatiri {
  tur: string;
  id: number;
  kimlik: string;
  urun: string | null;
  destekledigi: string[] | null;
}

interface AtilSatiri {
  sim_id: number;
  msisdn: string | null;
  iccid: string;
  aylik_maliyet: number;
  neden: string;
}

export default function HatlarPage() {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  // Genel aramadan gelen `?q=` doğrudan filtreye düşer: arama sonucuna
  // tıklayan kullanıcı filtresiz listeye değil aradığı kayda varır.
  const [aramaParam] = useSearchParams();
  const [arama, setArama] = useState(aramaParam.get("q") ?? "");
  const [taahhut, setTaahhut] = useState(false);

  const kota = useQuery({
    queryKey: ["hat-kota"],
    queryFn: () => api.get<KotaSatiri[]>("/api/hatlar/rapor/kota"),
  });
  const risk = useQuery({
    queryKey: ["hat-2g"],
    queryFn: () => api.get<RiskSatiri[]>("/api/hatlar/rapor/2g-riski"),
  });
  const atil = useQuery({
    queryKey: ["hat-atil"],
    queryFn: () => api.get<AtilSatiri[]>("/api/hatlar/rapor/atil"),
  });
  const karlilik = useQuery({
    queryKey: ["hat-karlilik"],
    queryFn: () => api.get<Record<string, number>>("/api/hatlar/rapor/karlilik"),
    enabled: yetkili("maliyet.gor"),
    retry: false,
  });

  const senkron = useMutation({
    mutationFn: () => api.post<Record<string, unknown>>("/api/hatlar/senkron"),
    onSuccess: (s) => {
      message.success(
        `${s.adaptor} · ${s.sorgulanan} hat sorgulandı, ${s.guncellenen} güncellendi`,
      );
      void qc.invalidateQueries({ queryKey: ["hatlar"] });
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  // Sayfalama SUNUCUDA; gelen liste "hepsi" değil, istenen sayfadır.
  const [sayfa, setSayfa] = useState(1);
  const SAYFA_BOYU = 25;

  const hatlar = useQuery({
    queryKey: ["hatlar", arama, taahhut, sayfa],
    queryFn: () => {
      const p = new URLSearchParams();
      if (arama) p.set("q", arama);
      if (taahhut) p.set("taahhudu_bitenler", "true");
      p.set("limit", String(SAYFA_BOYU));
      p.set("offset", String((sayfa - 1) * SAYFA_BOYU));
      return api.getSayfa<Hat>(`/api/hatlar?${p}`);
    },
  });

  // Uyarı TÜM veri hakkında; açık sayfadaki 25 kayıttan sayılamaz.
  const iccidEksikSorgu = useQuery({
    queryKey: ["hatlar-iccid-eksik"],
    queryFn: () => api.getSayfa<Hat>("/api/hatlar?iccid_eksik=true&limit=1"),
  });
  const iccidEksik = iccidEksikSorgu.data?.toplam ?? 0;

  return (
    <Card
      title="Hatlar (SIM)"
      extra={
        <Space>
          {yetkili("hat.senkron") && (
            <Button onClick={() => senkron.mutate()} loading={senkron.isPending}>
              Operatörden senkronize et
            </Button>
          )}
          <Button type={taahhut ? "primary" : "default"} onClick={() => {
            setTaahhut((v) => !v);
            setSayfa(1);
          }}>
            Taahhüdü yaklaşanlar
          </Button>
          <Input.Search
            placeholder="ICCID, numara veya paket"
          defaultValue={arama}
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
      {iccidEksik > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          title={`${iccidEksik.toLocaleString("tr-TR")} hattın ICCID'si eksik`}
          description="Bu hatlar veri göçünde yalnızca numarasıyla açıldı (kaynakta ICCID yoktu). Operatörden alınıp tamamlanmalı; hat kartı o zamana kadar numarayla çalışır."
        />
      )}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="Maliyet üç kalemden oluşur"
        description="Tarife + veri paketi + APN. İndirim taahhüde bağlıdır: taahhüt biterse aylık maliyet kat kat artar, bu yüzden taahhüt bitiş tarihi izlenir."
      />

      <Table
        rowKey="id"
        size="small"
        loading={hatlar.isLoading}
        dataSource={hatlar.data?.kayitlar ?? []}
        pagination={{
          current: sayfa,
          pageSize: SAYFA_BOYU,
          total: hatlar.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} hat`,
        }}
        columns={[
          {
            title: "Numara",
            width: 150,
            render: (_, h: Hat) => <span className="mono">{h.msisdn ?? "—"}</span>,
          },
          {
            title: "ICCID",
            width: 210,
            render: (_, h: Hat) =>
              // Yer tutucunun biçimini (MSISDN:…) arayüz bilmemeli; sunucu
              // "eksik mi" sorusunu kendisi cevaplıyor.
              h.iccid_eksik ? (
                <Tooltip title="ICCID kaynakta yoktu — operatörden alınıp girilecek">
                  <Tag color="orange">eksik</Tag>
                </Tooltip>
              ) : (
                <Space size={4}>
                  <span className="mono">{h.iccid}</span>
                  {!h.iccid_saglamasi && (
                    <Tooltip title="20 haneli ICCID'nin sağlama hanesi tutmuyor — kontrol edin">
                      <Tag color="gold">?</Tag>
                    </Tooltip>
                  )}
                </Space>
              ),
          },
          { title: "Operatör", dataIndex: "operator", width: 130 },
          {
            title: "Durum",
            dataIndex: "status",
            width: 90,
            render: (v: string) => (
              <Tag color={v === "AKTIF" ? "green" : v === "IPTAL" ? "default" : "gold"}>{v}</Tag>
            ),
          },
          { title: "Paket", dataIndex: "plan_name", width: 130 },
          {
            title: "Kullanım",
            width: 150,
            render: (_, h: Hat) => {
              if (!h.data_allowance_mb) return <Typography.Text type="secondary">—</Typography.Text>;
              const oran = Math.round(((h.data_used_mb ?? 0) / h.data_allowance_mb) * 100);
              return (
                <Progress
                  percent={Math.min(oran, 100)}
                  size="small"
                  status={oran >= 100 ? "exception" : oran >= 80 ? "active" : "normal"}
                />
              );
            },
          },
          {
            title: "Aylık maliyet",
            width: 130,
            className: "tutar",
            render: (_, h: Hat) => (
              <Tooltip
                title={`Tarife ${tl(h.tariff_cost)} + Paket ${tl(h.package_cost)} + APN ${tl(h.apn_cost)}`}
              >
                {tl(h.aylik_maliyet || null)}
              </Tooltip>
            ),
          },
          {
            title: "Taahhüt",
            width: 150,
            render: (_, h: Hat) => {
              if (!h.commitment_end_date)
                return <Typography.Text type="secondary">—</Typography.Text>;
              const kalan = h.taahhut_kalan_gun ?? 0;
              return (
                <Space size={4}>
                  <span className="mono">{dayjs(h.commitment_end_date).format("DD.MM.YYYY")}</span>
                  {kalan <= 60 && <Tag color={kalan <= 0 ? "red" : "orange"}>{kalan} gün</Tag>}
                </Space>
              );
            },
          },
        ]}
      />

      <Tabs
        style={{ marginTop: 24 }}
        items={[
          {
            key: "kota",
            label: `Kota uyarıları${kota.data?.length ? ` (${kota.data.length})` : ""}`,
            children: (
              <Table
                rowKey="sim_id"
                size="small"
                loading={kota.isLoading}
                dataSource={kota.data ?? []}
                pagination={{ pageSize: 10, showSizeChanger: false }}
                columns={[
                  { title: "Numara", dataIndex: "msisdn", className: "mono", width: 150 },
                  { title: "ICCID", dataIndex: "iccid", className: "mono" },
                  {
                    title: "Kullanım",
                    width: 160,
                    render: (_, k: KotaSatiri) => (
                      <Space size={6}>
                        <Tag color={k.seviye === "ASILDI" ? "red" : "orange"}>%{k.yuzde}</Tag>
                        {k.seviye === "ASILDI" && <span>kota aşıldı</span>}
                      </Space>
                    ),
                  },
                ]}
              />
            ),
          },
          {
            key: "2g",
            label: `2G riski${risk.data?.length ? ` (${risk.data.length})` : ""}`,
            children: (
              <>
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  title="2G/3G yetkilendirmeleri 30 Nisan 2029'da bitiyor"
                  description="Bu liste hem bir risk hem de cihaz değişimi için satış fırsatı listesidir: yalnız 2G/3G destekleyen cihazlar ve yalnız 2G açık hatlar."
                />
                <Table
                  rowKey={(r) => `${r.tur}-${r.id}`}
                  size="small"
                  loading={risk.isLoading}
                  dataSource={risk.data ?? []}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  columns={[
                    {
                      title: "Tür",
                      dataIndex: "tur",
                      width: 90,
                      render: (v: string) => <Tag>{v}</Tag>,
                    },
                    { title: "Kimlik", dataIndex: "kimlik", className: "mono", width: 180 },
                    { title: "Ürün / Paket", dataIndex: "urun" },
                    {
                      title: "Desteklediği",
                      width: 160,
                      render: (_, r: RiskSatiri) => (
                        <Space size={2} wrap>
                          {(r.destekledigi ?? []).map((t) => (
                            <Tag key={t} style={{ marginInlineEnd: 0 }}>
                              {t}
                            </Tag>
                          ))}
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
          {
            key: "atil",
            label: `Atıl hatlar${atil.data?.length ? ` (${atil.data.length})` : ""}`,
            children: (
              <>
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                  title="Aktif ama veri göndermeyen hatlar"
                  description="Hiç senkron edilmemiş hatlar da listelenir — gereksiz maliyetin görünmemesi bu raporun varlık sebebini ortadan kaldırırdı."
                />
                <Table
                  rowKey="sim_id"
                  size="small"
                  loading={atil.isLoading}
                  dataSource={atil.data ?? []}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  columns={[
                    { title: "Numara", dataIndex: "msisdn", className: "mono", width: 150 },
                    { title: "ICCID", dataIndex: "iccid", className: "mono" },
                    {
                      title: "Aylık maliyet",
                      dataIndex: "aylik_maliyet",
                      width: 130,
                      className: "tutar",
                      render: tl,
                    },
                    { title: "Neden", dataIndex: "neden", width: 180 },
                  ]}
                />
              </>
            ),
          },
          ...(yetkili("maliyet.gor") && karlilik.data
            ? [
                {
                  key: "karlilik",
                  label: "Kârlılık",
                  children: (
                    <Space size={40} wrap>
                      <Statistic title="Aktif hat" value={karlilik.data.aktif_hat} />
                      <Statistic
                        title="Aylık gelir"
                        value={karlilik.data.aylik_gelir}
                        formatter={(v) => tl(Number(v))}
                      />
                      <Statistic
                        title="Aylık maliyet"
                        value={karlilik.data.aylik_maliyet}
                        formatter={(v) => tl(Number(v))}
                      />
                      <Statistic
                        title="Aylık marj"
                        value={karlilik.data.aylik_marj}
                        formatter={(v) => tl(Number(v))}
                        valueStyle={{ color: "#1f6b4d" }}
                      />
                      <Statistic
                        title="Cihaza takılı olmayan"
                        value={karlilik.data.cihaza_takili_olmayan}
                      />
                    </Space>
                  ),
                },
              ]
            : []),
        ]}
      />
    </Card>
  );
}
