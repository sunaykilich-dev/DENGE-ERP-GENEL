/**
 * Planlama P3 sekmeleri (TS-190): Kaynak görünümü (E02-21/20, E08-D03) ve
 * Plan Uyumu raporu (E02-22). `ServisPlanlamaPage` sekmeleri olarak çizilir;
 * dosya yalnız sayfa dosyası büyümesin diye ayrıdır.
 *
 * - Kaynak hücresi **"plan" dakikasıdır** (gerçek süre değil); müsaitlik ve
 *   eğitim oturumu blokları salt okunur etiket. Blok girişi `servis.planla`;
 *   not ≤200 ve sağlık bilgisi yazılmaz (sunucu da reddeder).
 * - Plan uyumu: aynı İstanbul günü = uyumlu; süre kaydı eksik ayrı sayılır,
 *   orana girmez. Kutu sayısı = ayrıntı listesinin `X-Toplam-Kayit`'ı.
 */
import { DeleteOutlined, FileExcelOutlined, LeftOutlined, PlusOutlined, RightOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { ApiError } from "../api/client";
import { BIRIM_ETIKETLERI } from "../api/personel";
import {
  type KaynakHucresi,
  type KaynakSatiri,
  MUSAITLIK_TURLERI,
  SAGLIK_UYARISI,
  type UyumKirilimi,
  type UyumSatiri,
  planlamaP3Api,
} from "../api/servisPlanlama";
import { useAuth } from "../auth/AuthContext";
import KpiKutusu from "../components/KpiKutusu";

const ISO = "YYYY-MM-DD";
const GUN_ADLARI = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

function pazartesi(d: Dayjs): Dayjs {
  return d.subtract((d.day() + 6) % 7, "day").startOf("day");
}

// --- Kaynak görünümü -----------------------------------------------------------------

interface BlokFormu {
  kisi_id: number;
  aralik: [Dayjs, Dayjs];
  tur: string;
  not?: string;
}

export function KaynakSekmesi({ birim }: { birim?: string }) {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const planlayabilir = yetkili("servis.planla");
  const [hafta, setHafta] = useState<Dayjs>(() => pazartesi(dayjs()));
  const [blokAcik, setBlokAcik] = useState(false);
  const [form] = Form.useForm<BlokFormu>();

  const veri = useQuery({
    queryKey: ["servis-kaynak", hafta.format(ISO), birim],
    queryFn: () => planlamaP3Api.kaynak(hafta.format(ISO), birim),
  });

  const tazele = () => {
    for (const k of ["servis-kaynak", "servis-takvim", "servis-plan-kpi", "servis-plan-kpi-liste"]) {
      void qc.invalidateQueries({ queryKey: [k] });
    }
  };

  const ekle = useMutation({
    mutationFn: (v: BlokFormu) =>
      planlamaP3Api.musaitlikEkle({
        kisi_id: v.kisi_id,
        baslangic: v.aralik[0].toISOString(),
        bitis: v.aralik[1].toISOString(),
        tur: v.tur,
        not: v.not?.trim() || null,
      }),
    onSuccess: (r) => {
      if (r.plan_uyarilari.length) {
        message.warning(
          `Blok kaydedildi; bu aralıkta kişinin ${r.plan_uyarilari.length} planı var (çakışmalı işaretlendi).`,
        );
      } else {
        message.success("Müsaitlik bloğu kaydedildi");
      }
      setBlokAcik(false);
      tazele();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const sil = useMutation({
    mutationFn: (v: { kisi: number; blok: number }) => planlamaP3Api.musaitlikSil(v.kisi, v.blok),
    onSuccess: () => {
      message.success("Blok silindi");
      tazele();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const hucre = (satir: KaynakSatiri, h: KaynakHucresi) => (
    <Space direction="vertical" size={2} style={{ fontSize: 12 }}>
      {h.plan_dk > 0 && (
        <Tooltip title={`${h.ziyaret_sayisi} ziyaret, ${h.is_sayisi} iş (planlanan süre, gerçek süre değil)`}>
          <Tag color={h.cakisma ? "red" : "blue"} style={{ marginInlineEnd: 0 }}>
            plan {h.plan_dk} dk
          </Tag>
        </Tooltip>
      )}
      {h.musaitlik.map((b) => (
        <Tooltip
          key={b.id}
          title={`${dayjs(b.baslangic).format("DD.MM HH:mm")} – ${dayjs(b.bitis).format("DD.MM HH:mm")}${b.not ? ` · ${b.not}` : ""}`}
        >
          <Tag color="orange" style={{ marginInlineEnd: 0 }}>
            {MUSAITLIK_TURLERI[b.tur] ?? b.tur}
            {planlayabilir && (
              <Popconfirm
                title="Blok silinsin mi?"
                okText="Sil"
                cancelText="Vazgeç"
                onConfirm={() => sil.mutate({ kisi: satir.user_id, blok: b.id })}
              >
                <DeleteOutlined style={{ marginInlineStart: 4 }} aria-label="Bloğu sil" />
              </Popconfirm>
            )}
          </Tag>
        </Tooltip>
      ))}
      {h.egitim.map((e, i) => (
        <Tooltip key={i} title={`Eğitim oturumu · ${e.sure_saat} saat (salt okunur)`}>
          <Tag color="purple" style={{ marginInlineEnd: 0, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis" }}>
            {e.kurs}
          </Tag>
        </Tooltip>
      ))}
    </Space>
  );

  const gunler = veri.data?.gunler ?? [];
  const sutunlar = [
    {
      title: "Personel",
      dataIndex: "ad",
      fixed: "left" as const,
      width: 140,
      render: (ad: string, s: KaynakSatiri) => (
        <span>
          {ad}
          <div style={{ fontSize: 11, color: "#888" }}>
            {s.toplam_plan_dk ? `plan ${s.toplam_plan_dk} dk` : "plan yok"}
          </div>
        </span>
      ),
    },
    ...gunler.map((g, i) => ({
      title: `${GUN_ADLARI[i]} ${dayjs(g).format("DD.MM")}`,
      key: g,
      width: 120,
      render: (_: unknown, s: KaynakSatiri) => hucre(s, s.hucreler[i]),
    })),
  ];

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Button icon={<LeftOutlined />} aria-label="Önceki hafta" onClick={() => setHafta((h) => h.subtract(1, "week"))} />
        <DatePicker
          picker="week"
          value={hafta}
          allowClear={false}
          format={(d) => `${pazartesi(d).format("DD.MM")} – ${pazartesi(d).add(6, "day").format("DD.MM.YYYY")}`}
          onChange={(d) => d && setHafta(pazartesi(d))}
        />
        <Button icon={<RightOutlined />} aria-label="Sonraki hafta" onClick={() => setHafta((h) => h.add(1, "week"))} />
        {planlayabilir && (
          <Button
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              form.setFieldsValue({ tur: "IZIN" });
              setBlokAcik(true);
            }}
          >
            Müsaitlik bloğu
          </Button>
        )}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Hücrede planlanan dakika ("plan") gösterilir; gerçek çalışma süresi Zaman Takibi'ndedir.
        </Typography.Text>
      </Space>
      {veri.isError ? (
        <Empty description={(veri.error as ApiError).message} />
      ) : (
        <Table<KaynakSatiri>
          size="small"
          rowKey="user_id"
          loading={veri.isLoading}
          dataSource={veri.data?.satirlar ?? []}
          columns={sutunlar}
          pagination={false}
          scroll={{ x: 980 }}
          locale={{ emptyText: <Empty description="Bu birimde saha personeli yok" /> }}
        />
      )}
      <Modal
        open={blokAcik}
        title="Müsaitlik bloğu"
        okText="Kaydet"
        cancelText="Vazgeç"
        confirmLoading={ekle.isPending}
        onCancel={() => setBlokAcik(false)}
        onOk={() => void form.validateFields().then((v) => ekle.mutate(v))}
      >
        <Alert type="warning" showIcon message={SAGLIK_UYARISI} style={{ marginBottom: 12 }} />
        <Form form={form} layout="vertical">
          <Form.Item name="kisi_id" label="Personel" rules={[{ required: true, message: "Personel seçin" }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={(veri.data?.satirlar ?? []).map((s) => ({ value: s.user_id, label: s.ad }))}
            />
          </Form.Item>
          <Form.Item name="aralik" label="Aralık" rules={[{ required: true, message: "Aralık seçin" }]}>
            <DatePicker.RangePicker showTime={{ format: "HH:mm" }} format="DD.MM.YYYY HH:mm" style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="tur" label="Tür" rules={[{ required: true }]}>
            <Select options={Object.entries(MUSAITLIK_TURLERI).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="not" label="Not (isteğe bağlı)" extra="En çok 200 karakter; sağlık bilgisi yazmayın.">
            <Input maxLength={200} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// --- Plan uyumu ------------------------------------------------------------------------

const SINIF_ADLARI: Record<string, string> = {
  UYUMLU: "Plana uyumlu",
  KAYDI: "Başka güne kaydı",
  EKSIK: "Süre kaydı eksik",
};
const KIRILIM_ADLARI: Record<string, string> = {
  birim: "Birim",
  tur: "Servis / Bakım",
  il: "İl",
  sef: "Şef",
  teknisyen: "Teknisyen",
};

function oran(o: number | null) {
  return o == null ? "—" : `%${o.toLocaleString("tr-TR")}`;
}

export function PlanUyumuSekmesi({ birim }: { birim?: string }) {
  const { yetkili } = useAuth();
  const [params, setParams] = useSearchParams();
  const [aralik, setAralik] = useState<[Dayjs, Dayjs]>(() => [dayjs().subtract(29, "day"), dayjs()]);
  const [tur, setTur] = useState("TUMU");
  const sinif = params.get("uyum") ?? undefined;
  const suzgec = {
    baslangic: aralik[0].format(ISO),
    bitis: aralik[1].format(ISO),
    birim,
    tur: tur === "TUMU" ? undefined : tur,
  };

  const rapor = useQuery({
    queryKey: ["servis-plan-uyumu", suzgec.baslangic, suzgec.bitis, birim, tur],
    queryFn: () => planlamaP3Api.planUyumu(suzgec),
  });
  const ayrinti = useQuery({
    queryKey: ["servis-plan-uyumu-ayrinti", suzgec.baslangic, suzgec.bitis, birim, tur, sinif],
    queryFn: () => planlamaP3Api.planUyumuAyrinti({ ...suzgec, sinif }),
  });

  const o = rapor.data?.ozet;
  const kutu = (kod: string, baslik: string, deger: number | null | undefined, tanim: string, liste = true) => (
    <Col xs={12} sm={8} md={6} xl={3} key={kod}>
      <KpiKutusu
        kod={kod}
        baslik={baslik}
        tanim={tanim}
        deger={deger ?? null}
        yol={liste ? `/servis-planlama?uyum=${kod}` : "/servis-planlama"}
        yukleniyor={rapor.isLoading}
      />
    </Col>
  );
  const kirilimSutunlari = [
    { title: "Değer", dataIndex: "etiket" },
    { title: "Uyumlu", dataIndex: "uyumlu" },
    { title: "Kaydı", dataIndex: "kaydi" },
    { title: "Eksik", dataIndex: "eksik" },
    { title: "Oran", dataIndex: "oran", render: oran },
  ];
  const personelGorur = yetkili("servis_rapor.personel");

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <DatePicker.RangePicker
          format="DD.MM.YYYY"
          allowClear={false}
          value={aralik}
          onChange={(v) => v && v[0] && v[1] && setAralik([v[0], v[1]])}
        />
        <Segmented
          value={tur}
          onChange={(v) => setTur(String(v))}
          options={[
            { value: "TUMU", label: "Tümü" },
            { value: "SERVIS", label: "Servis" },
            { value: "BAKIM", label: "Bakım" },
          ]}
        />
        {yetkili("servis_rapor.disaaktar") && (
          <Button
            icon={<FileExcelOutlined />}
            onClick={() => window.open(planlamaP3Api.planUyumuExcelYolu(suzgec), "_blank")}
          >
            Excel
          </Button>
        )}
        {birim && <Tag>{BIRIM_ETIKETLERI[birim] ?? birim}</Tag>}
      </Space>
      {rapor.isError ? (
        <Empty description={(rapor.error as ApiError).message} />
      ) : (
        <>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            Ziyaretin ilk YOL/SAHA kaydının İstanbul günü plan günüyle aynıysa "uyumlu". Süre kaydı
            olmayan ziyaretler ayrı sayılır ve orana girmez. Gelecek günlerin planı değerlendirilmez
            {rapor.data ? ` (son gün ${dayjs(rapor.data.suzgec.degerlendirilen_son_gun).format("DD.MM.YYYY")})` : ""}.
          </Typography.Paragraph>
          <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
            {kutu("UYUMLU", "Plana uyumlu", o?.uyumlu, "İlk kayıt plan günüyle aynı İstanbul gününde")}
            {kutu("KAYDI", "Başka güne kaydı", o?.kaydi, "İlk kayıt plan gününden farklı bir günde")}
            {kutu("EKSIK", "Süre kaydı eksik", o?.eksik, "Ziyaretin hiç YOL/SAHA kaydı yok; orana girmez")}
            {kutu("oran", "Uyum oranı (%)", o?.oran, "Uyumlu ÷ (uyumlu + kaydı)", false)}
            {kutu("ziyaret_basina_is", "Ziyaret başına iş", o?.ziyaret_basina_is, "İş sayısı ÷ ziyaret sayısı", false)}
            {kutu("tekrar", "30 günde tekrar ziyaret", o?.tekrar_ziyaret_30, "Aynı müşteri + lokasyona 30 gün içinde ayrı ziyaret", false)}
            {kutu("erteleme", "Erteleme", rapor.data?.erteleme.toplam, "Yeni plan günü aralıkta olan ertelemeler", false)}
          </Row>
          <Row gutter={[12, 12]}>
            <Col xs={24} lg={14}>
              <Card size="small" title="Kırılımlar">
                <Tabs
                  size="small"
                  items={Object.entries(rapor.data?.kirilimlar ?? {}).map(([ad, satirlar]) => ({
                    key: ad,
                    label: KIRILIM_ADLARI[ad] ?? ad,
                    children: (
                      <Table<UyumKirilimi>
                        size="small"
                        rowKey="anahtar"
                        dataSource={satirlar}
                        columns={kirilimSutunlari}
                        pagination={false}
                        scroll={{ x: 420 }}
                      />
                    ),
                  }))}
                />
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card size="small" title="Erteleme nedenleri" style={{ marginBottom: 12 }}>
                <Table
                  size="small"
                  rowKey={(r) => r.neden ?? "-"}
                  dataSource={rapor.data?.erteleme.nedenler ?? []}
                  pagination={false}
                  columns={[
                    { title: "Neden", dataIndex: "ad" },
                    { title: "Adet", dataIndex: "adet" },
                  ]}
                />
              </Card>
              <Card size="small" title="Plan bekleyen yaşı (bugün)">
                <Table
                  size="small"
                  rowKey="aralik"
                  dataSource={rapor.data?.bekleyen_yasi ?? []}
                  pagination={false}
                  columns={[
                    { title: "Aralık", dataIndex: "aralik" },
                    { title: "İş", dataIndex: "adet" },
                  ]}
                />
              </Card>
            </Col>
          </Row>
          <Card
            size="small"
            style={{ marginTop: 12 }}
            title={
              <Space wrap>
                <span>Ziyaretler</span>
                {sinif && (
                  <Tag
                    closable
                    color="blue"
                    onClose={() => {
                      params.delete("uyum");
                      setParams(params, { replace: true });
                    }}
                  >
                    {SINIF_ADLARI[sinif] ?? sinif}
                  </Tag>
                )}
                <Typography.Text type="secondary">{ayrinti.data ? `${ayrinti.data.toplam} ziyaret` : ""}</Typography.Text>
              </Space>
            }
          >
            <Table<UyumSatiri>
              size="small"
              rowKey="anahtar"
              loading={ayrinti.isLoading}
              dataSource={ayrinti.data?.kayitlar ?? []}
              scroll={{ x: 720 }}
              pagination={{ pageSize: 50, showSizeChanger: false }}
              columns={[
                { title: "Ziyaret / İş", dataIndex: "ziyaret", className: "mono" },
                {
                  title: "Plan günü",
                  dataIndex: "plan_tarihi",
                  render: (d: string) => dayjs(d).format("DD.MM.YYYY"),
                },
                {
                  title: "İlk kayıt günü",
                  dataIndex: "ilk_kayit_gunu",
                  render: (d: string | null) => (d ? dayjs(d).format("DD.MM.YYYY") : <Tag color="orange">Kayıt eksik</Tag>),
                },
                {
                  title: "Sonuç",
                  dataIndex: "sinif",
                  render: (s: string) => (
                    <Tag color={s === "UYUMLU" ? "green" : s === "KAYDI" ? "gold" : "orange"}>{SINIF_ADLARI[s]}</Tag>
                  ),
                },
                { title: "Tür", dataIndex: "tur", render: (t: string) => (t === "BAKIM" ? "Bakım" : "Servis") },
                { title: "İl", dataIndex: "il", render: (i: string | null) => i ?? "—" },
                ...(personelGorur
                  ? [
                      {
                        title: "Ekip",
                        key: "ekip",
                        render: (_: unknown, r: UyumSatiri) => [...(r.sefler ?? []), ...(r.teknisyenler ?? [])].join(", ") || "—",
                      },
                    ]
                  : []),
              ]}
            />
          </Card>
        </>
      )}
    </>
  );
}
