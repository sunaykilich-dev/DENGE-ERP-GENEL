/**
 * Parça tüketim raporu (TS-196, E11-18).
 *
 * Net çıkış = servis işlerine yazılmış defter satırlarının −Σadet'i (iade ve
 * ters kayıt düşer). PB ve diğer servis işleri her kırılımda ayrı satırdır.
 * Tutar sütunu yalnız sunucu `tutar` anahtarını gönderdiğinde (maliyet.gor)
 * çizilir; maliyeti bilinmeyen satır "maliyet eksik"tir, 0 gösterilmez.
 */
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Col, DatePicker, Row, Select, Space, Table, Tag, Typography } from "antd";
import type { TableColumnsType as ColumnsType } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { Link } from "react-router-dom";

import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { parcaApi, TUKETIM_KIRILIMLARI, type TuketimSatiri } from "../api/yedekParca";
import { useAuth } from "../auth/AuthContext";

const para = (v?: string | null) =>
  v == null ? "—" : Number(v).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function ParcaTuketimRaporu() {
  const { yetkili, kullanici } = useAuth();
  const [aralik, setAralik] = useState<[Dayjs, Dayjs]>([dayjs().subtract(30, "day"), dayjs()]);
  const [kirilim, setKirilim] = useState("parca_ay");
  const [birim, setBirim] = useState<string | undefined>();
  const [isGrubu, setIsGrubu] = useState<string | undefined>();
  const s = {
    bas: aralik[0].format("YYYY-MM-DD"),
    bit: aralik[1].format("YYYY-MM-DD"),
    kirilim,
    birim,
    is_grubu: isGrubu,
  };
  const rapor = useQuery({ queryKey: ["parca", "tuketim", s], queryFn: () => parcaApi.tuketim(s) });
  const tutarVar = !!kullanici?.sees_cost && rapor.data?.toplam.tutar !== undefined;

  const boyut: ColumnsType<TuketimSatiri> = {
    parca_ay: [
      { title: "Ay", dataIndex: "ay" },
      { title: "Parça", key: "p", render: (_: unknown, r: TuketimSatiri) => `${r.urun_kodu ?? ""} — ${r.urun_adi ?? ""}` },
    ],
    birim: [{ title: "Birim", dataIndex: "birim", render: (b: string) => BIRIM_ETIKETLERI[b] ?? b }],
    musteri: [{ title: "Müşteri", dataIndex: "musteri", render: (m?: string | null) => m ?? "—" }],
    is_turu: [{ title: "İş türü", dataIndex: "is_turu" }],
    is: [
      {
        title: "Servis işi",
        key: "so",
        render: (_: unknown, r: TuketimSatiri) => <Link to={`/servis-isleri/${r.so_id}`}>{r.so_no}</Link>,
      },
      { title: "Parça", key: "p", render: (_: unknown, r: TuketimSatiri) => `${r.urun_kodu ?? ""} — ${r.urun_adi ?? ""}` },
    ],
    ekipman: [
      {
        title: "Ekipman",
        key: "e",
        render: (_: unknown, r: TuketimSatiri) => (r.ekipman ? `${r.ekipman.tip} · ${r.ekipman.seri ?? r.ekipman.id}` : "—"),
      },
      { title: "Parça", key: "p", render: (_: unknown, r: TuketimSatiri) => `${r.urun_kodu ?? ""} — ${r.urun_adi ?? ""}` },
    ],
  }[kirilim] as ColumnsType<TuketimSatiri>;

  const sutunlar: ColumnsType<TuketimSatiri> = [
    ...boyut,
    {
      title: "İş grubu",
      dataIndex: "is_grubu",
      render: (g: string, r) => <Tag color={g === "PLANLI_BAKIM" ? "cyan" : "default"}>{r.is_grubu_adi}</Tag>,
    },
    { title: "Net çıkış", dataIndex: "net_cikis", align: "right" },
    { title: "Hareket", dataIndex: "hareket", align: "right" },
    ...(tutarVar
      ? [
          {
            title: "Tutar (TL)",
            key: "tutar",
            align: "right" as const,
            render: (_: unknown, r: TuketimSatiri) =>
              r.maliyet_eksik ? <Tag color="orange">Maliyet eksik</Tag> : para(r.tutar),
          },
        ]
      : []),
  ];

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Row gutter={[8, 8]}>
        <Col xs={24} md={8}>
          <DatePicker.RangePicker
            allowClear={false}
            format="DD.MM.YYYY"
            style={{ width: "100%" }}
            value={aralik}
            onChange={(v) => v && v[0] && v[1] && setAralik([v[0], v[1]])}
          />
        </Col>
        <Col xs={12} md={5}>
          <Select
            style={{ width: "100%" }}
            value={kirilim}
            onChange={setKirilim}
            options={Object.entries(TUKETIM_KIRILIMLARI).map(([k, v]) => ({ value: k, label: v }))}
          />
        </Col>
        <Col xs={12} md={4}>
          <Select
            allowClear
            style={{ width: "100%" }}
            placeholder="Birim"
            value={birim}
            onChange={setBirim}
            options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] }))}
          />
        </Col>
        <Col xs={12} md={4}>
          <Select
            allowClear
            style={{ width: "100%" }}
            placeholder="İş grubu"
            value={isGrubu}
            onChange={setIsGrubu}
            options={[
              { value: "PLANLI_BAKIM", label: "Planlı bakım (PB)" },
              { value: "SERVIS", label: "Diğer servis işleri" },
            ]}
          />
        </Col>
        <Col xs={12} md={3}>
          {yetkili("servis_rapor.disaaktar") && (
            <Button onClick={() => window.open(parcaApi.tuketimExcelYolu(s), "_blank")}>Excel</Button>
          )}
        </Col>
      </Row>
      {rapor.isError && <Alert type="error" showIcon title={(rapor.error as Error).message} />}
      <Typography.Text>
        Toplam net çıkış: <strong>{rapor.data?.toplam.net_cikis ?? "—"}</strong>
        {tutarVar && (
          <>
            {" "}
            · Tutar: <strong>{para(rapor.data?.toplam.tutar)}</strong> TL
            {(rapor.data?.toplam.maliyet_eksik_hareket ?? 0) > 0 &&
              ` (${rapor.data?.toplam.maliyet_eksik_hareket} hareketin maliyeti bilinmiyor; tutara girmedi)`}
          </>
        )}
      </Typography.Text>
      <Table
        size="small"
        loading={rapor.isLoading}
        rowKey={(r) =>
          [r.ay, r.product_id, r.birim, r.musteri_id, r.is_turu, r.so_id, r.ekipman_id, r.is_grubu].join("|")
        }
        dataSource={rapor.data?.satirlar ?? []}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: true }}
        columns={sutunlar}
      />
    </Space>
  );
}
