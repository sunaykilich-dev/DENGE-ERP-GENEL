/**
 * İrsaliye listesi (KARARLAR 2026-11-09 S4.3/S4.4): PDF indir, iptal,
 * muhasebeye devir ve Logo Excel/CSV dökümü.
 *
 * Stok ekranında (Transfer > İrsaliyeler) tam hâliyle, sipariş ayrıntısında
 * `siparisId` ile sade hâliyle kullanılır. Yetkiler sunucuda zorlanır; burada
 * yalnız düğmeler gizlenir: iptal `siparis.yaz`/`cihaz.transfer`, devir
 * `tahsilat.yaz`, döküm `rapor.disaaktar`. Fiyatlı PDF yalnız sipariş/teklif
 * fiyatını görebilene sunulur.
 */
import { DownloadOutlined, FilePdfOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Dropdown, Empty, Input, Select, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import type { ApiError } from "../api/client";
import { HEDEF_ADLARI, type Irsaliye, irsaliyeApi } from "../api/irsaliye";
import { useAuth } from "../auth/AuthContext";

interface Props {
  siparisId?: number;
}

export default function IrsaliyeListesi({ siparisId }: Props) {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const sade = siparisId != null;
  const [devir, setDevir] = useState<"bekleyen" | "devredildi" | undefined>();
  const [ara, setAra] = useState("");
  const [secili, setSecili] = useState<number[]>([]);

  const fiyatGorur = yetkili("siparis.gor") || yetkili("teklif.gor");
  const iptalEder = yetkili("siparis.yaz") || yetkili("cihaz.transfer");
  const devreder = yetkili("tahsilat.yaz");
  const aktarir = yetkili("rapor.disaaktar");

  const liste = useQuery({
    queryKey: ["irsaliyeler", siparisId, devir, ara],
    queryFn: () =>
      irsaliyeApi.liste({ order_id: siparisId, devir, ara: ara.trim() || undefined }),
  });

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["irsaliyeler"] });
    setSecili([]);
  };
  const hata = (e: ApiError) => message.error(e.message);

  const iptal = useMutation({
    mutationFn: (v: { id: number; neden: string; version: number }) =>
      irsaliyeApi.iptal(v.id, v.neden, v.version),
    onSuccess: (i) => {
      message.success(`${i.irsaliye_no} iptal edildi`);
      yenile();
    },
    onError: hata,
  });
  const devret = useMutation({
    mutationFn: (v: { idler: number[]; not?: string }) => irsaliyeApi.devret(v.idler, v.not),
    onSuccess: (r) => {
      message.success(`${r.devredilen.length} irsaliye muhasebeye devredildi`);
      yenile();
    },
    onError: hata,
  });
  const geriAl = useMutation({
    mutationFn: (v: { id: number; gerekce: string }) => irsaliyeApi.devriGeriAl(v.id, v.gerekce),
    onSuccess: () => {
      message.success("Muhasebe devri geri alındı");
      yenile();
    },
    onError: hata,
  });

  function metinSor(baslik: string, aciklama: string, zorunlu: boolean, tamam: (m: string) => unknown) {
    let metin = "";
    modal.confirm({
      title: baslik,
      content: (
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">{aciklama}</Typography.Text>
          <Input.TextArea rows={2} maxLength={300} onChange={(e) => (metin = e.target.value)} />
        </Space>
      ),
      okText: "Tamam",
      cancelText: "Vazgeç",
      onOk: () => {
        if (zorunlu && metin.trim().length < 3) {
          message.error("Açıklama zorunludur");
          return Promise.reject();
        }
        return tamam(metin.trim());
      },
    });
  }

  const veri = liste.data ?? [];

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {!sade && (
        <Space wrap>
          <Select
            allowClear
            placeholder="Muhasebe devri"
            style={{ width: 190 }}
            value={devir}
            onChange={(v) => {
              setDevir(v);
              setSecili([]);
            }}
            options={[
              { value: "bekleyen", label: "Devir bekleyen" },
              { value: "devredildi", label: "Muhasebeye devredilen" },
            ]}
          />
          <Input.Search
            allowClear
            placeholder="İrsaliye no / alıcı"
            style={{ width: 220 }}
            onSearch={setAra}
            onChange={(e) => !e.target.value && setAra("")}
          />
          {devreder && (
            <Button
              type="primary"
              disabled={!secili.length}
              onClick={() =>
                metinSor(
                  `${secili.length} irsaliye muhasebeye devredilsin mi?`,
                  "İsteğe bağlı not (dönem, fatura no…). Seçilenlerden biri uygun değilse hiçbiri işaretlenmez.",
                  false,
                  (not) => devret.mutateAsync({ idler: secili, not: not || undefined }),
                )
              }
            >
              Muhasebeye devret{secili.length ? ` (${secili.length})` : ""}
            </Button>
          )}
          {aktarir && (
            <Dropdown
              menu={{
                items: [
                  { key: "xlsx", label: "Logo aktarım (Excel)" },
                  { key: "csv", label: "Logo aktarım (CSV)" },
                ],
                onClick: ({ key }) =>
                  window.open(irsaliyeApi.logoYolu(devir, key as "xlsx" | "csv"), "_blank"),
              }}
            >
              <Button icon={<DownloadOutlined />}>Logo dökümü</Button>
            </Dropdown>
          )}
        </Space>
      )}
      <Table<Irsaliye>
        rowKey="id"
        size="small"
        loading={liste.isLoading}
        dataSource={veri}
        pagination={sade ? false : { pageSize: 15, showSizeChanger: false }}
        scroll={{ x: sade ? undefined : 900 }}
        locale={{ emptyText: <Empty description="İrsaliye yok" /> }}
        rowSelection={
          !sade && devreder
            ? {
                selectedRowKeys: secili,
                onChange: (k) => setSecili(k as number[]),
                getCheckboxProps: (i) => ({
                  disabled: i.durum === "IPTAL" || i.muhasebe_devri_at != null,
                }),
              }
            : undefined
        }
        columns={[
          { title: "İrsaliye no", dataIndex: "irsaliye_no", width: 150, className: "mono" },
          {
            title: "Tarih",
            dataIndex: "duzenleme_tarihi",
            width: 100,
            className: "mono",
            render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
          },
          ...(sade
            ? []
            : [
                {
                  title: "Alıcı",
                  ellipsis: true,
                  render: (_: unknown, i: Irsaliye) => (
                    <span>
                      {i.alici_unvan}{" "}
                      <Typography.Text type="secondary">
                        ({HEDEF_ADLARI[i.hedef_konum] ?? i.hedef_konum})
                      </Typography.Text>
                    </span>
                  ),
                },
              ]),
          {
            title: "Miktar",
            width: 80,
            className: "mono",
            render: (_: unknown, i: Irsaliye) => Number(i.toplam_miktar),
          },
          {
            title: "Durum",
            width: 170,
            render: (_: unknown, i: Irsaliye) => (
              <Space size={4} wrap>
                {i.durum === "IPTAL" ? <Tag color="red">iptal</Tag> : <Tag color="blue">düzenlendi</Tag>}
                {i.muhasebe_devri_at && (
                  <Tag color="green" title={i.muhasebe_devreden ?? undefined}>
                    muhasebede
                  </Tag>
                )}
              </Space>
            ),
          },
          {
            title: "",
            width: sade ? 120 : 230,
            render: (_: unknown, i: Irsaliye) => (
              <Space size={4} wrap>
                {fiyatGorur && i.fiyatli ? (
                  <Dropdown
                    menu={{
                      items: [
                        { key: "f", label: "Fiyatsız" },
                        { key: "p", label: "Fiyatlı" },
                      ],
                      onClick: ({ key }) =>
                        window.open(irsaliyeApi.pdfYolu(i.id, key === "p"), "_blank"),
                    }}
                  >
                    <Button size="small" icon={<FilePdfOutlined />}>
                      PDF indir
                    </Button>
                  </Dropdown>
                ) : (
                  <Button
                    size="small"
                    icon={<FilePdfOutlined />}
                    href={irsaliyeApi.pdfYolu(i.id)}
                    target="_blank"
                  >
                    PDF indir
                  </Button>
                )}
                {!sade && iptalEder && i.durum !== "IPTAL" && !i.muhasebe_devri_at && (
                  <Button
                    size="small"
                    danger
                    type="text"
                    onClick={() =>
                      metinSor(
                        `${i.irsaliye_no} iptal edilsin mi?`,
                        "Numara iptal olarak kalır; stok geri alınmaz (geri gelen mal iade transferiyle girilir).",
                        true,
                        (neden) => iptal.mutateAsync({ id: i.id, neden, version: i.version }),
                      )
                    }
                  >
                    İptal
                  </Button>
                )}
                {!sade && devreder && i.muhasebe_devri_at && (
                  <Button
                    size="small"
                    type="text"
                    onClick={() =>
                      metinSor(
                        "Muhasebe devri geri alınsın mı?",
                        "Gerekçe zorunludur; denetim izine yazılır.",
                        true,
                        (gerekce) => geriAl.mutateAsync({ id: i.id, gerekce }),
                      )
                    }
                  >
                    Devri geri al
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
    </Space>
  );
}
