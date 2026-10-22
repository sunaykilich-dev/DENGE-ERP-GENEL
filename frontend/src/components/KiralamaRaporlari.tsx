/**
 * Kiralama raporları (TS-195, E06-21): depo durumu, geciken iade, kontrolde
 * bekleme. Sunucu: `/api/kiralama/raporlar/*` (`kiralama.gor + servis_rapor.gor`;
 * Excel ek olarak `servis_rapor.disaaktar`). Fiyat kolonu YOKTUR.
 *
 * Geciken iade satır sayısı, kiralama listesinin "Geciken" KPI'sıyla aynı
 * sorgudan gelir (sayı = liste). Aşama süresi zaman kaydından; kayıt yoksa
 * "Eksik" yazılır, tahmini süre gösterilmez.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Segmented, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { type AsamaSuresi, kiralamaApi, KIRALAMA_DURUM_ADLARI } from "../api/kiralama";
import { BIRIM_ETIKETLERI } from "../api/personel";
import { useAuth } from "../auth/AuthContext";

type Rapor = "depo-durumu" | "geciken-iade" | "kontrolde-bekleme";

const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");
const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");

function AsamaHucresi({ a }: { a?: AsamaSuresi }) {
  if (!a || a.durum === "IS_YOK") return <Typography.Text type="secondary">İş yok</Typography.Text>;
  if (a.dk === null) return <Tag color="orange">Eksik</Tag>;
  return (
    <span>
      {Math.floor(a.dk / 60)} sa {a.dk % 60} dk
    </span>
  );
}

function DepoDurumu() {
  const q = useQuery({ queryKey: ["kiralama-rapor-depo"], queryFn: kiralamaApi.raporDepoDurumu });
  const sayi = (v: number) => (v ? v.toLocaleString("tr-TR") : "");
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      {q.isError && <Alert type="error" showIcon title={(q.error as Error).message} />}
      <Typography.Text type="secondary">
        Rezerve: tahsis edilmiş ama sevk edilmemiş adet (hazırın içindedir). Serbest = hazır −
        rezerve. Kirada: o depodan çıkıp müşteride olan adet.
      </Typography.Text>
      <Table
        size="small"
        loading={q.isLoading}
        rowKey={(r) => `${r.depo_id ?? "x"}-${r.product_id}`}
        dataSource={q.data?.satirlar ?? []}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: true }}
        columns={[
          { title: "Depo", dataIndex: "depo_adi" },
          {
            title: "Ürün",
            key: "urun",
            render: (_, r) => `${r.urun_kodu ?? ""} ${r.urun_adi ?? ""}`,
          },
          { title: "Hazır", dataIndex: "hazir", align: "right", render: sayi },
          { title: "Rezerve", dataIndex: "rezerve", align: "right", render: sayi },
          { title: "Serbest", dataIndex: "serbest", align: "right", render: sayi },
          { title: "Kirada", dataIndex: "kirada", align: "right", render: sayi },
          { title: "Kontrolde", dataIndex: "kontrolde", align: "right", render: sayi },
          { title: "Hazır değil", dataIndex: "hazir_degil", align: "right", render: sayi },
          { title: "Kayıp", dataIndex: "kayip", align: "right", render: sayi },
          { title: "Atölyede", dataIndex: "atolyede", align: "right", render: sayi },
        ]}
      />
    </Space>
  );
}

function GecikenIade() {
  const q = useQuery({ queryKey: ["kiralama-rapor-geciken"], queryFn: kiralamaApi.raporGecikenIade });
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      {q.isError && <Alert type="error" showIcon title={(q.error as Error).message} />}
      <Typography.Text type="secondary">
        İade günü geçmiş ve cihazı hâlâ müşteride olan kiralamalar.{" "}
        <Link to="/kiralamalar?kpi=geciken">Listede aç</Link>
      </Typography.Text>
      <Table
        size="small"
        loading={q.isLoading}
        rowKey="id"
        dataSource={q.data ?? []}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: true }}
        columns={[
          {
            title: "Kiralama",
            dataIndex: "rental_no",
            render: (v: string, r) => <Link to={`/kiralamalar/${r.id}`}>{v}</Link>,
          },
          { title: "Birim", dataIndex: "birim", render: (b: string) => BIRIM_ETIKETLERI[b] ?? b },
          { title: "Müşteri", dataIndex: "musteri", ellipsis: true },
          { title: "Durum", dataIndex: "status", render: (s: string) => KIRALAMA_DURUM_ADLARI[s] ?? s },
          { title: "İade günü", dataIndex: "bitis", render: tarih },
          {
            title: "Gecikme",
            dataIndex: "gecikme_gun",
            align: "right",
            render: (g: number) => <Tag color={g > 7 ? "red" : "orange"}>{g} gün</Tag>,
          },
          { title: "Müşterideki", dataIndex: "musteride_adet", align: "right" },
          {
            title: "Seriler",
            dataIndex: "seriler",
            ellipsis: true,
            render: (s: string[]) => s.join(", ") || "—",
          },
          {
            title: "Kurulum süresi",
            key: "kurulum",
            render: (_, r) => <AsamaHucresi a={r.asama_sureleri.KURULUM} />,
          },
          {
            title: "Toplama süresi",
            key: "toplama",
            render: (_, r) => <AsamaHucresi a={r.asama_sureleri.TOPLAMA} />,
          },
        ]}
      />
    </Space>
  );
}

function KontroldeBekleme() {
  const q = useQuery({ queryKey: ["kiralama-rapor-kontrol"], queryFn: kiralamaApi.raporKontroldeBekleme });
  const gun = (g: number | null, uzun: boolean) =>
    g === null ? "—" : <Tag color={uzun ? "red" : "default"}>{g} gün</Tag>;
  return (
    <Space orientation="vertical" style={{ width: "100%" }}>
      {q.isError && <Alert type="error" showIcon title={(q.error as Error).message} />}
      <Typography.Text type="secondary">
        Dönüş kontrolü bekleyen cihazlar; {q.data?.esik_gun ?? 7} günü aşanlar kırmızı.{" "}
        <Link to="/kiralik-envanter?durum=KONTROLDE">Seri cihaz listesinde aç</Link>
      </Typography.Text>
      <Table
        size="small"
        loading={q.isLoading}
        rowKey="kiralik_id"
        dataSource={q.data?.seri ?? []}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: true }}
        columns={[
          {
            title: "Ürün",
            key: "urun",
            render: (_, r) => `${r.urun_kodu ?? ""} ${r.urun_adi ?? ""}`,
          },
          { title: "Seri no", dataIndex: "serial_no" },
          { title: "Depo", dataIndex: "depo_adi" },
          { title: "Kontrole giriş", dataIndex: "giris_at", render: zaman },
          { title: "Bekleme", key: "gun", render: (_, r) => gun(r.bekleme_gun, r.uzun) },
        ]}
      />
      {(q.data?.toplu.length ?? 0) > 0 && (
        <Table
          size="small"
          rowKey={(r) => `${r.depo_id}-${r.product_id}`}
          dataSource={q.data?.toplu ?? []}
          pagination={false}
          scroll={{ x: true }}
          title={() => "Seri takipsiz ürünler"}
          columns={[
            {
              title: "Ürün",
              key: "urun",
              render: (_, r) => `${r.urun_kodu ?? ""} ${r.urun_adi ?? ""}`,
            },
            { title: "Depo", dataIndex: "depo_adi" },
            { title: "Adet", dataIndex: "adet", align: "right" },
            { title: "Son giriş", dataIndex: "son_giris_at", render: zaman },
            { title: "Bekleme", key: "gun", render: (_, r) => gun(r.bekleme_gun, r.uzun) },
          ]}
        />
      )}
    </Space>
  );
}

export default function KiralamaRaporlari() {
  const { yetkili } = useAuth();
  const [rapor, setRapor] = useState<Rapor>("depo-durumu");
  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Space wrap>
        <Segmented<Rapor>
          value={rapor}
          onChange={setRapor}
          options={[
            { value: "depo-durumu", label: "Depo durumu" },
            { value: "geciken-iade", label: "Geciken iade" },
            { value: "kontrolde-bekleme", label: "Kontrolde bekleme" },
          ]}
        />
        {yetkili("servis_rapor.disaaktar") && (
          <Button onClick={() => window.open(kiralamaApi.raporExcelYolu(rapor), "_blank")}>Excel</Button>
        )}
      </Space>
      {rapor === "depo-durumu" && <DepoDurumu />}
      {rapor === "geciken-iade" && <GecikenIade />}
      {rapor === "kontrolde-bekleme" && <KontroldeBekleme />}
    </Space>
  );
}
