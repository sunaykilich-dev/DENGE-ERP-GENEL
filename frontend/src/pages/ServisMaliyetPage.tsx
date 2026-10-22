import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import { api, type ApiError } from "../api/client";
import {
  ANALIZ_KPI,
  DURUM_ADLARI,
  DURUM_RENKLERI,
  GELIR_KAYNAK_ADLARI,
  servisMaliyetApi,
  tl,
  type AnalizOzeti,
  type AnalizSatiri,
  type IsFinansi,
  type Tarife,
} from "../api/servisMaliyet";
import { teknikServisApi } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";
import Statistic from "../components/Statistic";

/**
 * Servis Maliyet (TS-145, TS-146, TS-149).
 *
 * - **Analiz**: dönemde çözülmüş işler; dönem/birim/tür/müşteri süzgeci,
 *   eksik-veri KPI kutuları (tıklanınca liste o duruma süzülür), birim × tür
 *   özeti. Toplamlar yalnız TAM satırlardan (sunucu hesaplar); eksik tutar
 *   "—" basılır, 0 yazılmaz.
 * - **İş finansı** (satıra tıklayınca): gelir ve diğer maliyet kaydı,
 *   değişiklik geçmişi. Fatura devrinden sonra sunucu 409 verir.
 * - **İşçilik tarifeleri**: birim bazlı saatlik maliyet; geçmiş tarihli tarife
 *   `sistem.ayar` + gerekçe ister (sunucu denetler).
 *
 * Menü `maliyet.gor`; analiz ayrıca `servis_rapor.gor`, yazma `maliyet.yaz`.
 */
export default function ServisMaliyetPage() {
  const { yetkili } = useAuth();
  const analizYetkisi = yetkili("maliyet.gor", "servis_rapor.gor");
  const [sekme, setSekme] = useState(analizYetkisi ? "analiz" : "tarifeler");

  return (
    <Tabs
      activeKey={sekme}
      onChange={setSekme}
      items={[
        ...(analizYetkisi
          ? [{ key: "analiz", label: "Maliyet analizi", children: <AnalizSekmesi /> }]
          : []),
        { key: "tarifeler", label: "İşçilik tarifeleri", children: <TarifeSekmesi /> },
      ]}
    />
  );
}

interface Hesap {
  id: number;
  title: string;
}

function AnalizSekmesi() {
  const { yetkili } = useAuth();
  const [donem, setDonem] = useState<Dayjs | null>(dayjs().startOf("month"));
  const [aralik, setAralik] = useState<[Dayjs, Dayjs] | null>(null);
  const [birim, setBirim] = useState<string>();
  const [tur, setTur] = useState<string>();
  const [musteriId, setMusteriId] = useState<number>();
  const [musteriArama, setMusteriArama] = useState("");
  const [durum, setDurum] = useState<string>();
  const [seciliIs, setSeciliIs] = useState<number | null>(null);

  const formVerileri = useQuery({
    queryKey: ["ts-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    staleTime: 5 * 60_000,
  });
  const musteriler = useQuery({
    queryKey: ["maliyet-musteri", musteriArama],
    queryFn: () =>
      api.get<Hesap[]>(
        `/api/hesaplar?rol=MUSTERI&limit=50${
          musteriArama ? `&q=${encodeURIComponent(musteriArama)}` : ""
        }`,
      ),
  });

  const suzgec = {
    ...(aralik
      ? { baslangic: aralik[0].format("YYYY-MM-DD"), bitis: aralik[1].format("YYYY-MM-DD") }
      : { donem: (donem ?? dayjs()).format("YYYY-MM") }),
    birim,
    tur,
    musteri_id: musteriId,
  };
  // KPI sayıları süzgeçsiz (durum hariç) analizden; liste `durum` ile süzülür.
  const genel = useQuery({
    queryKey: ["maliyet-analiz", suzgec],
    queryFn: () => servisMaliyetApi.analiz(suzgec),
  });
  const liste = useQuery({
    queryKey: ["maliyet-analiz", suzgec, durum],
    queryFn: () => servisMaliyetApi.analiz({ ...suzgec, durum }),
    enabled: durum !== undefined,
  });
  const satirlar = durum ? liste.data?.satirlar : genel.data?.satirlar;
  const g = genel.data?.genel;

  const birimAdi = useMemo(() => {
    const m: Record<string, string> = {};
    for (const b of formVerileri.data?.birimler ?? []) m[b.kod] = b.ad;
    return m;
  }, [formVerileri.data]);
  const turAdi = useMemo(() => {
    const m: Record<string, string> = {};
    for (const t of formVerileri.data?.turler ?? []) m[t.kod] = t.ad;
    return m;
  }, [formVerileri.data]);

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small">
        <Space wrap>
          <DatePicker
            picker="month"
            format="MM.YYYY"
            value={aralik ? null : donem}
            onChange={(d) => {
              setAralik(null);
              setDonem(d);
            }}
            placeholder="Dönem"
          />
          <DatePicker.RangePicker
            format="DD.MM.YYYY"
            value={aralik}
            onChange={(r) => setAralik(r && r[0] && r[1] ? [r[0], r[1]] : null)}
            placeholder={["Başlangıç", "Bitiş"]}
          />
          <Select
            allowClear
            placeholder="Birim"
            style={{ width: 160 }}
            value={birim}
            onChange={setBirim}
            options={(formVerileri.data?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
          />
          <Select
            allowClear
            placeholder="İş türü"
            style={{ width: 180 }}
            value={tur}
            onChange={setTur}
            options={(formVerileri.data?.turler ?? []).map((t) => ({ value: t.kod, label: t.ad }))}
          />
          <Select
            allowClear
            showSearch
            filterOption={false}
            onSearch={setMusteriArama}
            placeholder="Müşteri"
            style={{ width: 240 }}
            value={musteriId}
            onChange={setMusteriId}
            options={(musteriler.data ?? []).map((h) => ({ value: h.id, label: h.title }))}
          />
          {yetkili("servis_rapor.disaaktar") && (
            <>
              <Button
                onClick={() =>
                  window.open(servisMaliyetApi.analizExcelAdresi(suzgec, "is"), "_blank")
                }
              >
                Excel (iş)
              </Button>
              <Button
                onClick={() =>
                  window.open(servisMaliyetApi.analizExcelAdresi(suzgec, "musteri"), "_blank")
                }
              >
                Excel (müşteri)
              </Button>
            </>
          )}
        </Space>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: "8px 0 0" }}>
          Dönemde tamamlanan/kapatılan işler. Dönem en çok 12 ay. Toplamlar yalnız verisi tam
          işlerden; eksik tutar "—" gösterilir.
        </Typography.Paragraph>
      </Card>

      {genel.isError && <Alert type="error" showIcon title={(genel.error as ApiError).message} />}

      <Row gutter={[12, 12]}>
        {ANALIZ_KPI.map((k) => (
          <Col key={k.kod} xs={12} sm={8} lg={4}>
            <Card
              size="small"
              hoverable
              loading={genel.isLoading}
              data-kpi={k.kod}
              onClick={() => setDurum(durum === k.kod ? undefined : k.kod)}
              style={{
                height: "100%",
                borderColor: durum === k.kod ? "#de3a11" : undefined,
              }}
            >
              <Statistic title={k.baslik} value={g ? (g[k.alan as keyof AnalizOzeti] as number) : 0} />
            </Card>
          </Col>
        ))}
      </Row>

      {g && (
        <Card size="small" title={`Genel toplam · ${g.tam_adet} / ${g.adet} iş tam veri`}>
          <Space size={32} wrap>
            <Statistic title="Gelir" value={tl(g.gelir)} />
            <Statistic title="Parça" value={tl(g.malzeme)} />
            <Statistic title="İşçilik" value={tl(g.iscilik)} />
            <Statistic title="Diğer" value={tl(g.diger)} />
            <Statistic title="Fark" value={tl(g.fark)} />
          </Space>
        </Card>
      )}

      <Card size="small" title="Birim × tür özeti">
        <Table<AnalizOzeti>
          rowKey={(r) => `${r.birim}-${r.tur}`}
          size="small"
          loading={genel.isLoading}
          dataSource={genel.data?.ozet ?? []}
          pagination={false}
          scroll={{ x: true }}
          columns={[
            { title: "Birim", dataIndex: "birim", render: (x: string) => birimAdi[x] ?? x },
            { title: "Tür", dataIndex: "tur", render: (x: string) => turAdi[x] ?? x },
            { title: "İş", dataIndex: "adet", className: "mono", width: 60 },
            { title: "Tam", dataIndex: "tam_adet", className: "mono", width: 60 },
            { title: "Gelir", dataIndex: "gelir", className: "tutar", render: tl },
            { title: "Parça", dataIndex: "malzeme", className: "tutar", render: tl },
            { title: "İşçilik", dataIndex: "iscilik", className: "tutar", render: tl },
            { title: "Diğer", dataIndex: "diger", className: "tutar", render: tl },
            { title: "Fark", dataIndex: "fark", className: "tutar", render: (x) => <strong>{tl(x)}</strong> },
            {
              title: "Eksik",
              render: (_: unknown, r: AnalizOzeti) => {
                const n = r.sure_eksik + r.tarife_eksik + r.maliyet_eksik + r.gelir_yok;
                return n ? <Tag color="orange">{n}</Tag> : "—";
              },
            },
          ]}
        />
      </Card>

      <Card
        size="small"
        title={
          durum ? (
            <Space>
              İşler
              <Tag closable color={DURUM_RENKLERI[durum]} onClose={() => setDurum(undefined)}>
                {DURUM_ADLARI[durum] ?? durum}
              </Tag>
            </Space>
          ) : (
            "İşler"
          )
        }
      >
        <Table<AnalizSatiri>
          rowKey="so_id"
          size="small"
          loading={durum ? liste.isLoading : genel.isLoading}
          dataSource={satirlar ?? []}
          pagination={{ pageSize: 50, showSizeChanger: false }}
          scroll={{ x: true }}
          onRow={(r) => ({ onClick: () => setSeciliIs(r.so_id), style: { cursor: "pointer" } })}
          locale={{ emptyText: <Empty description="Bu süzgeçte iş yok" /> }}
          columns={[
            { title: "İş no", dataIndex: "so_no", className: "mono", width: 130 },
            { title: "Müşteri", dataIndex: "musteri", render: (x: string | null) => x ?? "—" },
            { title: "Birim", dataIndex: "birim", render: (x: string) => birimAdi[x] ?? x },
            { title: "Tür", dataIndex: "tur", render: (x: string) => turAdi[x] ?? x },
            {
              title: "Kapanış",
              dataIndex: "kapanis_tarihi",
              className: "mono",
              render: (x: string | null) => (x ? dayjs(x).format("DD.MM.YYYY") : "—"),
            },
            {
              title: "Süre",
              dataIndex: "sure_dk",
              className: "mono",
              render: (x: number | null) => (x == null ? "—" : `${(x / 60).toFixed(1)} sa`),
            },
            { title: "Gelir", dataIndex: "gelir", className: "tutar", render: tl },
            { title: "Parça", dataIndex: "malzeme", className: "tutar", render: tl },
            { title: "İşçilik", dataIndex: "iscilik", className: "tutar", render: tl },
            { title: "Diğer", dataIndex: "diger", className: "tutar", render: tl },
            { title: "Fark", dataIndex: "fark", className: "tutar", render: (x) => <strong>{tl(x)}</strong> },
            {
              title: "Durum",
              dataIndex: "durum",
              render: (x: string) => <Tag color={DURUM_RENKLERI[x]}>{DURUM_ADLARI[x] ?? x}</Tag>,
            },
          ]}
        />
      </Card>

      <IsFinansiCekmecesi soId={seciliIs} onClose={() => setSeciliIs(null)} />
    </Space>
  );
}

/** Tek işin finansı: gelir / diğer maliyet kaydı ve geçmişi (TS-145). */
export function IsFinansiCekmecesi({ soId, onClose }: { soId: number | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const yazabilir = yetkili("maliyet.gor", "maliyet.yaz");
  const [gelirForm] = Form.useForm();
  const [digerForm] = Form.useForm();

  const finans = useQuery({
    queryKey: ["is-finansi", soId],
    queryFn: () => servisMaliyetApi.isFinansi(soId as number),
    enabled: soId != null,
  });
  const gecmis = useQuery({
    queryKey: ["is-finansi-gecmis", soId],
    queryFn: () => servisMaliyetApi.gecmis(soId as number),
    enabled: soId != null,
  });

  const tazele = (f: IsFinansi) => {
    qc.setQueryData(["is-finansi", soId], f);
    void qc.invalidateQueries({ queryKey: ["is-finansi-gecmis", soId] });
    void qc.invalidateQueries({ queryKey: ["maliyet-analiz"] });
  };
  const hata = (e: ApiError) => message.error(e.message);

  const gelir = useMutation({
    mutationFn: (v: { kaynak: string; tutar: number | null; not?: string | null }) =>
      servisMaliyetApi.gelirYaz(soId as number, { ...v, version: finans.data?.finans_version ?? null }),
    onSuccess: (f) => {
      message.success("Gelir kaydedildi");
      gelirForm.resetFields();
      tazele(f);
    },
    onError: hata,
  });
  const diger = useMutation({
    mutationFn: (v: { tutar: number | null; not?: string | null }) =>
      servisMaliyetApi.digerMaliyetYaz(soId as number, {
        ...v,
        version: finans.data?.finans_version ?? null,
      }),
    onSuccess: (f) => {
      message.success("Diğer maliyet kaydedildi");
      digerForm.resetFields();
      tazele(f);
    },
    onError: hata,
  });

  const f = finans.data;
  const kilitli = !!f?.fatura_iletildi_at;
  const kaynak = Form.useWatch("kaynak", gelirForm);

  return (
    <Drawer
      title={f ? `${f.so_no} · iş finansı` : "İş finansı"}
      open={soId != null}
      onClose={onClose}
      size={640}
      loading={finans.isLoading}
    >
      {finans.isError && <Alert type="error" showIcon title={(finans.error as ApiError).message} />}
      {f && (
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          {kilitli && (
            <Alert
              type="info"
              showIcon
              title="Fatura devri yapıldı"
              description={`${dayjs(f.fatura_iletildi_at).format("DD.MM.YYYY HH:mm")} itibarıyla gelir ve maliyet kilitli.`}
            />
          )}
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="Süre">
              {f.sure_dk == null ? "—" : `${f.sure_dk} dk`}
            </Descriptions.Item>
            <Descriptions.Item label="Durum">
              <Tag color={DURUM_RENKLERI[f.durum]}>{DURUM_ADLARI[f.durum] ?? f.durum}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="İşçilik">
              {tl(f.iscilik)}{" "}
              {f.iscilik_durumu !== "TAM" && <Tag color="orange">{DURUM_ADLARI[f.iscilik_durumu]}</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Parça">
              {tl(f.malzeme)}{" "}
              {f.malzeme_durumu !== "TAM" && (
                <Tag color="orange">{DURUM_ADLARI[f.malzeme_durumu] ?? f.malzeme_durumu}</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="Diğer maliyet">
              {tl(f.diger_maliyet)}
              {f.diger_maliyet_notu ? ` · ${f.diger_maliyet_notu}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="Gelir">
              {tl(f.gelir)}
              {f.gelir_kaynagi ? ` · ${GELIR_KAYNAK_ADLARI[f.gelir_kaynagi] ?? f.gelir_kaynagi}` : ""}
              {f.gelir_notu ? ` · ${f.gelir_notu}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="Fark" span={2}>
              <strong>{tl(f.fark)}</strong>
              {f.fark == null && (
                <Typography.Text type="secondary"> (eksik veri — hesaplanamadı)</Typography.Text>
              )}
            </Descriptions.Item>
          </Descriptions>

          {yazabilir && !kilitli && (
            <>
              <Card size="small" title="Gelir kaydı">
                <Form
                  form={gelirForm}
                  layout="inline"
                  initialValues={{ kaynak: "ELLE" }}
                  onFinish={(v) =>
                    gelir.mutate({
                      kaynak: v.kaynak,
                      tutar:
                        v.kaynak === "ELLE" || v.kaynak === "SOZLESME"
                          ? (v.tutar ?? null)
                          : v.kaynak === "UCRETSIZ_GARANTI"
                            ? 0
                            : null,
                      not: v.not || null,
                    })
                  }
                >
                  <Form.Item name="kaynak">
                    <Select
                      style={{ width: 180 }}
                      options={["ELLE", "UCRETSIZ_GARANTI", "SOZLESME", "TEKLIF", "YOK"].map(
                        (k) => ({
                          value: k,
                          label:
                            k === "TEKLIF" ? "Kabul edilen teklife dön" : GELIR_KAYNAK_ADLARI[k],
                        }),
                      )}
                    />
                  </Form.Item>
                  {(kaynak === "ELLE" || kaynak === "SOZLESME") && (
                    <Form.Item name="tutar" rules={[{ required: true, message: "Tutar girin" }]}>
                      <InputNumber min={0} placeholder="KDV hariç TL" style={{ width: 150 }} />
                    </Form.Item>
                  )}
                  <Form.Item
                    name="not"
                    rules={
                      kaynak === "ELLE" || kaynak === "UCRETSIZ_GARANTI"
                        ? [{ required: true, message: "Not zorunlu" }]
                        : []
                    }
                  >
                    <Input placeholder="Not" style={{ width: 180 }} maxLength={1000} />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" loading={gelir.isPending}>
                    Kaydet
                  </Button>
                </Form>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Teklif kaynaklı gelir, bağlı teklif kabul edilince otomatik yazılır.
                </Typography.Text>
              </Card>
              <Card size="small" title="Diğer maliyet (konaklama, yol, taşeron…)">
                <Form
                  form={digerForm}
                  layout="inline"
                  onFinish={(v) => diger.mutate({ tutar: v.tutar ?? null, not: v.not || null })}
                >
                  <Form.Item name="tutar">
                    <InputNumber min={0} placeholder="Boş = kaydı sil" style={{ width: 150 }} />
                  </Form.Item>
                  <Form.Item name="not">
                    <Input placeholder="Not" style={{ width: 220 }} maxLength={1000} />
                  </Form.Item>
                  <Button htmlType="submit" loading={diger.isPending}>
                    Kaydet
                  </Button>
                </Form>
              </Card>
            </>
          )}

          <Card size="small" title="Değişiklik geçmişi">
            {(gecmis.data ?? []).length === 0 ? (
              <Typography.Text type="secondary">Kayıt yok</Typography.Text>
            ) : (
              <Timeline
                items={(gecmis.data ?? []).map((s) => ({
                  content: (
                    <Space orientation="vertical" size={0}>
                      <Typography.Text strong>
                        {dayjs(s.zaman).format("DD.MM.YYYY HH:mm")} · {s.kullanici ?? "Sistem"}
                      </Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {s.eylem} ·{" "}
                        {Object.entries(s.yeni)
                          .map(([k, v]) => `${k}: ${String(s.eski[k] ?? "—")} → ${String(v ?? "—")}`)
                          .join(", ")}
                      </Typography.Text>
                    </Space>
                  ),
                }))}
              />
            )}
          </Card>
        </Space>
      )}
    </Drawer>
  );
}

function TarifeSekmesi() {
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const yazabilir = yetkili("maliyet.gor", "maliyet.yaz");
  const geriTarihli = yetkili("sistem.ayar");
  const [birim, setBirim] = useState<string>();
  const [acik, setAcik] = useState(false);
  const [form] = Form.useForm();

  const formVerileri = useQuery({
    queryKey: ["ts-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    staleTime: 5 * 60_000,
  });
  const tarifeler = useQuery({
    queryKey: ["iscilik-tarifeleri", birim],
    queryFn: () => servisMaliyetApi.tarifeler(birim),
  });
  const yenile = () => void qc.invalidateQueries({ queryKey: ["iscilik-tarifeleri"] });

  const ekle = useMutation({
    mutationFn: servisMaliyetApi.tarifeEkle,
    onSuccess: () => {
      message.success("Tarife eklendi; önceki tarife bu tarihte kapandı");
      setAcik(false);
      form.resetFields();
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });
  const kapat = useMutation({
    mutationFn: servisMaliyetApi.tarifeKapat,
    onSuccess: () => {
      message.success("Tarife geri alındı");
      yenile();
    },
    onError: (e: ApiError) => message.error(e.message),
  });

  function kapatSor(t: Tarife) {
    let gerekce = "";
    modal.confirm({
      title: "Henüz başlamamış tarifeyi geri al",
      content: (
        <Input.TextArea
          rows={3}
          placeholder="Gerekçe (zorunlu)"
          onChange={(e) => (gerekce = e.target.value)}
        />
      ),
      okText: "Geri al",
      cancelText: "Vazgeç",
      onOk: () => {
        if (gerekce.trim().length < 5) {
          message.error("Gerekçe en az 5 karakter olmalı");
          return Promise.reject();
        }
        return kapat.mutateAsync({ tarife_id: t.id, version: t.version, gerekce });
      },
    });
  }

  const bugun = dayjs().format("YYYY-MM-DD");
  const secilenTarih: Dayjs | undefined = Form.useWatch("valid_from", form);
  const gecmisTarih = secilenTarih ? secilenTarih.isBefore(dayjs(), "day") : false;

  return (
    <Card
      title="İşçilik tarifeleri"
      extra={
        <Space>
          <Select
            allowClear
            placeholder="Birim"
            style={{ width: 160 }}
            value={birim}
            onChange={setBirim}
            options={(formVerileri.data?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
          />
          {yazabilir && (
            <Button type="primary" onClick={() => setAcik(true)}>
              Yeni tarife
            </Button>
          )}
        </Space>
      }
    >
      <Table<Tarife>
        rowKey="id"
        size="small"
        loading={tarifeler.isLoading}
        dataSource={tarifeler.data ?? []}
        pagination={false}
        columns={[
          { title: "Birim", dataIndex: "birim" },
          {
            title: "Başlangıç",
            dataIndex: "valid_from",
            className: "mono",
            render: (x: string) => dayjs(x).format("DD.MM.YYYY"),
          },
          {
            title: "Bitiş",
            dataIndex: "valid_to",
            className: "mono",
            render: (x: string | null, r) =>
              r.kapatildi ? <Tag>geri alındı</Tag> : x ? dayjs(x).format("DD.MM.YYYY") : "açık",
          },
          { title: "Saatlik maliyet", dataIndex: "hourly_cost", className: "tutar", render: tl },
          { title: "Gerekçe", dataIndex: "gerekce", render: (x: string | null) => x ?? "—" },
          { title: "Giren", dataIndex: "giren", render: (x: string | null) => x ?? "—" },
          {
            title: "",
            width: 90,
            render: (_: unknown, r) =>
              yazabilir && !r.kapatildi && r.valid_from > bugun ? (
                <Button size="small" danger onClick={() => kapatSor(r)}>
                  Geri al
                </Button>
              ) : null,
          },
        ]}
      />
      <Modal
        title="Yeni işçilik tarifesi"
        open={acik}
        onCancel={() => setAcik(false)}
        onOk={() => form.submit()}
        confirmLoading={ekle.isPending}
        okText="Ekle"
        cancelText="Vazgeç"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v) =>
            ekle.mutate({
              birim: v.birim,
              valid_from: (v.valid_from as Dayjs).format("YYYY-MM-DD"),
              hourly_cost: v.hourly_cost,
              gerekce: v.gerekce || null,
            })
          }
        >
          <Form.Item name="birim" label="Birim" rules={[{ required: true, message: "Birim seçin" }]}>
            <Select
              options={(formVerileri.data?.birimler ?? []).map((b) => ({ value: b.kod, label: b.ad }))}
            />
          </Form.Item>
          <Form.Item
            name="valid_from"
            label="Geçerlilik başlangıcı"
            rules={[{ required: true, message: "Tarih seçin" }]}
          >
            <DatePicker format="DD.MM.YYYY" />
          </Form.Item>
          <Form.Item
            name="hourly_cost"
            label="Saatlik maliyet (TL)"
            rules={[{ required: true, message: "Tutar girin" }]}
          >
            <InputNumber min={0.01} style={{ width: 180 }} />
          </Form.Item>
          {gecmisTarih && (
            <Alert
              type={geriTarihli ? "warning" : "error"}
              showIcon
              style={{ marginBottom: 12 }}
              title={
                geriTarihli
                  ? "Geçmiş tarihli tarife kapanmış işlerin maliyetini değiştirir; gerekçe zorunlu."
                  : "Geçmiş tarihli tarife yalnız sistem ayarı yetkisiyle girilebilir."
              }
            />
          )}
          <Form.Item
            name="gerekce"
            label="Gerekçe"
            rules={gecmisTarih ? [{ required: true, message: "Gerekçe zorunlu" }] : []}
          >
            <Input.TextArea rows={2} maxLength={300} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
