/**
 * Hesap kartının "Servis" sekmesi (TS-192, E14-07).
 *
 * Canlı `/api/hesaplar/{id}/kart` DEĞİŞMEZ; bu sekme ayrı uçtan
 * (`/api/teknik-servis/ana-veri/musteriler/{id}/servis-karti`) beslenir. Açık
 * iş sayısı servis işi listesinin `X-Toplam-Kayit`'ıyla aynı süzgeçtir; sayıya
 * tıklamak o listeyi açar. Bloklar kullanıcının izni ve birim kapsamıyla
 * gelir; tutar yalnız `maliyet.gor` sahibinde vardır.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Card, Col, Empty, Row, Select, Space, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useNavigate } from "react-router-dom";

import { anaVeriApi, SLA_TAKVIM_SECENEKLERI, type SlaTakvimTuru } from "../api/anaVeri";
import { TIP_ETIKETLERI } from "../api/servisEkipman";
import { useAuth } from "../auth/AuthContext";
import Statistic from "./Statistic";

const tarih = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : "—");
const takvimEtiketi = (t: SlaTakvimTuru | null) =>
  SLA_TAKVIM_SECENEKLERI.find((s) => s.value === t)?.label ?? null;

export default function HesapServisKarti({ hesapId }: { hesapId: number }) {
  const git = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const kart = useQuery({
    queryKey: ["hesap-servis-karti", hesapId],
    queryFn: () => anaVeriApi.servisKarti(hesapId),
  });
  // Müşteri sözleşmesinin SLA takvimi (Faz A, TS-200); `version` ile iyimser kilit.
  const takvimYaz = useMutation({
    mutationFn: (tur: SlaTakvimTuru | null) =>
      anaVeriApi.musteriSlaTakvimi(hesapId, tur, kart.data!.version),
    onSuccess: () => message.success("SLA takvimi kaydedildi; yeni açılan işlere uygulanır"),
    onError: (e: Error) => message.error(e.message),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["hesap-servis-karti", hesapId] }),
  });
  const k = kart.data;
  if (kart.isError) return <Alert type="error" showIcon title={(kart.error as Error).message} />;
  if (!k) return <Card loading size="small" />;

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      {k.aciklama && <Alert type="info" showIcon title={k.aciklama} />}
      <Space wrap align="center">
        <Typography.Text strong>SLA takvimi</Typography.Text>
        <Select<SlaTakvimTuru>
          style={{ minWidth: 260 }}
          size="small"
          allowClear
          placeholder="SLA politikasından devral"
          value={k.sla_takvim_turu ?? undefined}
          options={SLA_TAKVIM_SECENEKLERI}
          disabled={!yetkili("lokasyon.yaz")}
          loading={takvimYaz.isPending}
          onChange={(v) => takvimYaz.mutate(v ?? null)}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Lokasyonun kendi takvimi bunu ezer; açık işlerin hedefi değişmez.
        </Typography.Text>
      </Space>
      <Row gutter={[8, 8]}>
        <Col xs={12} sm={8}>
          <Card
            size="small"
            hoverable
            role="link"
            onClick={() => git(`/servis-isleri?musteri_id=${hesapId}&durum_grubu=ACIK`)}
          >
            <Statistic title="Açık servis işi" value={k.acik_is_sayisi} />
          </Card>
        </Col>
        {k.ekipman_sayisi != null && (
          <Col xs={12} sm={8}>
            <Card size="small" hoverable role="link" onClick={() => git(`/servis-ekipman?hesap_id=${hesapId}`)}>
              <Statistic title="Ekipman" value={k.ekipman_sayisi} />
            </Card>
          </Col>
        )}
        {k.sozlesmeler && (
          <Col xs={12} sm={8}>
            <Card size="small">
              <Statistic title="Bakım sözleşmesi" value={k.sozlesmeler.length} />
            </Card>
          </Col>
        )}
      </Row>

      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={k.lokasyonlar}
        scroll={{ x: 420 }}
        locale={{ emptyText: <Empty description="Tesis yok" /> }}
        columns={[
          {
            title: "Tesis",
            key: "t",
            render: (_, l) => (
              <Space size={4}>
                {l.tesis_adi ?? "—"}
                {!l.aktif && <Tag>pasif</Tag>}
              </Space>
            ),
          },
          { title: "İl", dataIndex: "il", width: 110, render: (v) => v ?? "—" },
          {
            title: "SLA takvimi",
            dataIndex: "sla_takvim_turu",
            width: 150,
            render: (t: SlaTakvimTuru | null) => takvimEtiketi(t) ?? <Typography.Text type="secondary">Müşteriden</Typography.Text>,
          },
          {
            title: "Açık iş",
            dataIndex: "acik_is",
            width: 90,
            align: "right",
            // Sayı = Servis İşleri `?musteri_id=&adres_id=&durum_grubu=ACIK` toplamı.
            render: (v: number, l) =>
              v ? (
                <a
                  onClick={() =>
                    git(`/servis-isleri?musteri_id=${hesapId}&adres_id=${l.id}&durum_grubu=ACIK`)
                  }
                >
                  {v}
                </a>
              ) : (
                v
              ),
          },
        ]}
      />

      <Typography.Text strong>Son servis işleri</Typography.Text>
      <Table
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={k.servis_isleri}
        scroll={{ x: 560 }}
        onRow={(s) => ({ onClick: () => git(`/servis-isleri/${s.id}`), style: { cursor: "pointer" } })}
        locale={{ emptyText: <Empty description="Servis işi yok" /> }}
        columns={[
          { title: "İş no", dataIndex: "so_no", width: 150, className: "mono" },
          { title: "Konu", dataIndex: "konu", ellipsis: true },
          { title: "Durum", dataIndex: "durum", width: 130, render: (d: string) => <Tag>{d}</Tag> },
          { title: "Tarih", dataIndex: "tarih", width: 100, render: tarih },
        ]}
      />

      {k.sozlesmeler && k.sozlesmeler.length > 0 && (
        <>
          <Typography.Text strong>Bakım sözleşmeleri</Typography.Text>
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={k.sozlesmeler}
            scroll={{ x: 520 }}
            columns={[
              { title: "No", dataIndex: "no", width: 120, className: "mono" },
              { title: "Tesis", dataIndex: "tesis", ellipsis: true, render: (v) => v ?? "—" },
              { title: "Dönem", dataIndex: "donem", width: 190 },
              { title: "Durum", dataIndex: "durum", width: 120, render: (d: string) => <Tag>{d}</Tag> },
            ]}
          />
        </>
      )}

      {k.ekipman_turleri && k.ekipman_turleri.length > 0 && (
        <Space wrap>
          {k.ekipman_turleri.map((t) => (
            <Tag key={t.tip}>
              {TIP_ETIKETLERI[t.tip] ?? t.tip}: {t.adet}
            </Tag>
          ))}
        </Space>
      )}

      {k.kiralamalar && k.kiralamalar.length > 0 && (
        <>
          <Typography.Text strong>Açık kiralamalar</Typography.Text>
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={k.kiralamalar}
            scroll={{ x: 460 }}
            columns={[
              { title: "No", dataIndex: "no", width: 160, className: "mono" },
              { title: "Durum", dataIndex: "durum", render: (d: string) => <Tag>{d}</Tag> },
              { title: "Başlangıç", dataIndex: "baslangic", width: 100, render: tarih },
              { title: "Bitiş", dataIndex: "bitis", width: 100, render: tarih },
            ]}
          />
        </>
      )}

      {k.teklifler && k.teklifler.length > 0 && (
        <>
          <Typography.Text strong>Servis teklifleri</Typography.Text>
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={k.teklifler}
            scroll={{ x: 420 }}
            columns={[
              { title: "No", dataIndex: "no", width: 160, className: "mono" },
              { title: "Durum", dataIndex: "durum", render: (d: string) => <Tag>{d}</Tag> },
              { title: "Tarih", dataIndex: "tarih", width: 100, render: tarih },
            ]}
          />
        </>
      )}
    </Space>
  );
}
