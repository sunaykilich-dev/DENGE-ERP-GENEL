/**
 * Eğitim → Etkinlik raporu, Yeniden değerlendir, Yetkinlik eşlemeleri (TS-198).
 *
 * - Etkinlik (E08-12): kurs × birim; 0/30/60/90 başarı ve ortalama, 0→90 farkı,
 *   sınav farkı, kritik faaliyet, takip uyumu. Veri yoksa "veri yok" (0 değil).
 *   Excel `servis_rapor.disaaktar` ile; not/aksiyon kolonları yalnız
 *   `egitim.detay` sahibinin dosyasında (sunucu karar verir).
 * - Yeniden değerlendir (E08-16 P3): başarılı 90. gün gözleminden sonra bağlı
 *   yetkinliği değerlendirilmemiş kişiler; seviye kendiliğinden değişmez.
 * - Eşlemeler: kurs ↔ yetkinlik bağı ve servis işi türü → asgari yetkinlik
 *   (E08-22). Eşleme tayini ENGELLEMEZ, yalnız uyarı üretir. Yazma `egitim.yaz`.
 */
import { DownloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useEffect, useState } from "react";

import {
  ASAMALAR,
  asamaEtiketi,
  egitimApi,
  type EtkinlikSatiri,
  type YenidenDegerlendirSatiri,
} from "../api/egitim";
import { BIRIM_ETIKETLERI, BIRIM_KODLARI } from "../api/personel";
import { teknikServisApi } from "../api/teknikServis";
import { useAuth } from "../auth/AuthContext";

const yuzde = (v: number | null) => (v === null ? "veri yok" : `%${v.toLocaleString("tr-TR")}`);
const sayi = (v: number | null) => (v === null ? "veri yok" : v.toLocaleString("tr-TR"));

function hata(e: unknown) {
  return (e as Error).message;
}

export function EtkinlikSekmesi() {
  const { yetkili } = useAuth();
  const [yil, setYil] = useState(dayjs().year());
  const [birim, setBirim] = useState<string | undefined>();
  const [kursId, setKursId] = useState<number | undefined>();
  const kurslar = useQuery({ queryKey: ["egitim", "kurslar"], queryFn: () => egitimApi.kurslar() });
  const p = { yil, birim, kurs_id: kursId };
  const rapor = useQuery({ queryKey: ["egitim", "etkinlik", p], queryFn: () => egitimApi.etkinlik(p) });

  const kolonlar: ColumnsType<EtkinlikSatiri> = [
    {
      title: "Eğitim",
      fixed: "left",
      render: (_, r) => (
        <>
          <Typography.Text className="mono">{r.kurs_kod}</Typography.Text> {r.kurs}
        </>
      ),
    },
    { title: "Birim", dataIndex: "birim", render: (v: string | null) => (v ? BIRIM_ETIKETLERI[v] ?? v : "—") },
    ...ASAMALAR.map((a) => ({
      title: asamaEtiketi(a),
      key: `a${a}`,
      render: (_: unknown, r: EtkinlikSatiri) => {
        const h = r.asamalar[String(a)];
        return h.adet ? (
          <span>
            {yuzde(h.basari_orani)} · ort. {sayi(h.ortalama)}{" "}
            <Typography.Text type="secondary">({h.adet})</Typography.Text>
          </span>
        ) : (
          <Typography.Text type="secondary">veri yok</Typography.Text>
        );
      },
    })),
    {
      title: "0→90",
      dataIndex: "fark_metni",
      render: (v: string | null) => v ?? <Typography.Text type="secondary">veri yok</Typography.Text>,
    },
    {
      title: "Sınav (ön → son)",
      render: (_, r) =>
        r.sinav_on_ort === null && r.sinav_son_ort === null
          ? "veri yok"
          : `${sayi(r.sinav_on_ort)} → ${sayi(r.sinav_son_ort)}`,
    },
    {
      title: "Kritik (açık/kapalı)",
      render: (_, r) => (
        <>
          {r.kritik_acik > 0 ? <Tag color="red">{r.kritik_acik}</Tag> : "0"} / {r.kritik_kapali}
        </>
      ),
    },
    {
      title: "Takip uyumu",
      render: (_, r) =>
        r.takip_zamani_gelen ? `${r.takip_yapilan}/${r.takip_zamani_gelen} (${yuzde(r.takip_uyum_yuzde)})` : "—",
    },
    {
      title: "Eğitim kişi-saat",
      dataIndex: "egitim_kisi_saat",
      render: (v: number | null) => (v === null ? "—" : v.toLocaleString("tr-TR")),
    },
  ];

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <InputNumber min={2020} max={2100} value={yil} onChange={(v) => v && setYil(v)} />
        <Select
          allowClear
          placeholder="Birim"
          style={{ width: 170 }}
          value={birim}
          onChange={setBirim}
          options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="Eğitim"
          style={{ width: 240 }}
          value={kursId}
          onChange={setKursId}
          options={(kurslar.data ?? []).map((k) => ({ value: k.id, label: `${k.kod} ${k.baslik}` }))}
        />
        {yetkili("servis_rapor.disaaktar") && (
          <Button icon={<DownloadOutlined />} href={egitimApi.etkinlikExcelYolu(p)}>
            Excel
          </Button>
        )}
      </Space>
      {rapor.isError && <Alert type="error" message={hata(rapor.error)} />}
      <Table<EtkinlikSatiri>
        rowKey={(r) => `${r.course_id}-${r.birim ?? ""}`}
        size="small"
        loading={rapor.isLoading}
        dataSource={rapor.data?.satirlar}
        scroll={{ x: 1300 }}
        pagination={false}
        columns={kolonlar}
      />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Kritik maddeli gözlem başarısız sayılır. Gözlemi olmayan aşama "veri yok"tur. Eğitim
        saati yalnız bilgi amaçlıdır.
      </Typography.Text>
    </Space>
  );
}

export function YenidenDegerlendirSekmesi() {
  const [sayfa, setSayfa] = useState(1);
  const [birim, setBirim] = useState<string | undefined>();
  const liste = useQuery({
    queryKey: ["egitim", "yeniden-degerlendir", birim, sayfa],
    queryFn: () => egitimApi.yenidenDegerlendir({ birim }, 50, (sayfa - 1) * 50),
  });
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Space wrap>
        <Select
          allowClear
          placeholder="Birim"
          style={{ width: 170 }}
          value={birim}
          onChange={(v) => {
            setBirim(v);
            setSayfa(1);
          }}
          options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))}
        />
        <Typography.Text type="secondary">
          Başarılı 90. gün gözleminden sonra bağlı yetkinliği değerlendirilmemiş kişiler. Seviye
          kendiliğinden değişmez; değerlendirme girilince satır düşer.
        </Typography.Text>
      </Space>
      {liste.isError && <Alert type="error" message={hata(liste.error)} />}
      <Table<YenidenDegerlendirSatiri>
        rowKey={(r) => `${r.user_id}-${r.competency_id}`}
        size="small"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar}
        scroll={{ x: 700 }}
        pagination={{
          current: sayfa,
          pageSize: 50,
          total: liste.data?.toplam,
          onChange: setSayfa,
          showTotal: (t) => `${t} kayıt`,
        }}
        columns={[
          { title: "Personel", dataIndex: "ad" },
          {
            title: "Yetkinlik",
            render: (_, r) => (
              <>
                {r.yetkinlik} {r.kritik && <Tag color="red">Kritik</Tag>}
              </>
            ),
          },
          { title: "Bağlı eğitim", dataIndex: "kurslar", render: (v) => v ?? "—" },
          {
            title: "90. gün gözlemi",
            dataIndex: "gozlem_tarihi",
            render: (v: string) => dayjs(v).format("DD.MM.YYYY"),
          },
        ]}
      />
    </Space>
  );
}

interface GereksinimSatiriForm {
  competency_id: number | null;
  min_seviye: number;
  course_id: number | null;
}

export function EslemeSekmesi() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const yazabilir = yetkili("egitim.yaz");
  const kurslar = useQuery({ queryKey: ["egitim", "kurslar"], queryFn: () => egitimApi.kurslar() });
  const yetkinlikler = useQuery({
    queryKey: ["egitim", "yetkinlikler", true],
    queryFn: () => egitimApi.yetkinlikler(true),
  });
  const formVerileri = useQuery({
    queryKey: ["ts-form-verileri"],
    queryFn: teknikServisApi.formVerileri,
    staleTime: 5 * 60_000,
  });

  // --- Kurs ↔ yetkinlik ---------------------------------------------------------
  const [kursId, setKursId] = useState<number | undefined>();
  const [bagli, setBagli] = useState<number[]>([]);
  const bag = useQuery({
    queryKey: ["egitim", "kurs-yetkinlik", kursId],
    queryFn: () => egitimApi.kursYetkinlikleri(kursId!),
    enabled: kursId !== undefined,
  });
  useEffect(() => {
    setBagli((bag.data ?? []).map((y) => y.id));
  }, [bag.data]);
  const bagKaydet = useMutation({
    mutationFn: () => egitimApi.kursYetkinlikBagla(kursId!, bagli),
    onSuccess: () => {
      message.success("Kursun yetkinlik bağları kaydedildi");
      qc.invalidateQueries({ queryKey: ["egitim", "kurs-yetkinlik"] });
    },
    onError: (e) => void message.error(hata(e)),
  });

  // --- Servis işi türü → asgari yetkinlik --------------------------------------------
  const [birim, setBirim] = useState<string | undefined>();
  const [tur, setTur] = useState<string | undefined>();
  const [satirlar, setSatirlar] = useState<GereksinimSatiriForm[]>([]);
  const gereksinim = useQuery({
    queryKey: ["egitim", "gereksinim", birim, tur],
    queryFn: () => egitimApi.gereksinimler({ birim, tur }),
    enabled: !!birim && !!tur,
  });
  useEffect(() => {
    setSatirlar(
      (gereksinim.data ?? []).map((g) => ({
        competency_id: g.competency_id,
        min_seviye: g.min_seviye,
        course_id: g.course_id,
      })),
    );
  }, [gereksinim.data]);
  const gereksinimKaydet = useMutation({
    mutationFn: () =>
      egitimApi.gereksinimKaydet({
        birim: birim!,
        tur: tur!,
        satirlar: satirlar
          .filter((s) => s.competency_id !== null)
          .map((s) => ({
            competency_id: s.competency_id as number,
            min_seviye: s.min_seviye,
            course_id: s.course_id,
          })),
      }),
    onSuccess: () => {
      message.success("Eşleme kaydedildi");
      qc.invalidateQueries({ queryKey: ["egitim", "gereksinim"] });
    },
    onError: (e) => void message.error(hata(e)),
  });

  const yetkinlikSecenekleri = (yetkinlikler.data ?? []).map((y) => ({
    value: y.id,
    label: `${y.kod} — ${y.ad}`,
  }));
  const kursSecenekleri = (kurslar.data ?? []).map((k) => ({
    value: k.id,
    label: `${k.kod} ${k.baslik}`,
  }));

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="Kurs ↔ yetkinlik bağı">
        <Space wrap style={{ width: "100%" }}>
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="Eğitim seçin"
            style={{ width: 280, maxWidth: "100%" }}
            value={kursId}
            onChange={setKursId}
            options={kursSecenekleri}
          />
          <Select
            mode="multiple"
            optionFilterProp="label"
            placeholder="Bağlı yetkinlikler"
            style={{ width: 360, maxWidth: "100%" }}
            disabled={!kursId || !yazabilir}
            value={bagli}
            onChange={setBagli}
            options={yetkinlikSecenekleri}
          />
          {yazabilir && (
            <Button
              type="primary"
              disabled={!kursId}
              loading={bagKaydet.isPending}
              onClick={() => bagKaydet.mutate()}
            >
              Kaydet
            </Button>
          )}
        </Space>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: "8px 0 0" }}>
          Bağ yalnız "yeniden değerlendir" listesini besler; yetkinlik seviyesi kendiliğinden
          değişmez.
        </Typography.Paragraph>
      </Card>

      <Card size="small" title="Servis işi türü → asgari yetkinlik">
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            placeholder="Birim"
            style={{ width: 170 }}
            value={birim}
            onChange={setBirim}
            options={BIRIM_KODLARI.map((b) => ({ value: b, label: BIRIM_ETIKETLERI[b] ?? b }))}
          />
          <Select
            placeholder="İş türü"
            style={{ width: 200 }}
            value={tur}
            onChange={setTur}
            options={(formVerileri.data?.turler ?? []).map((t) => ({ value: t.kod, label: t.ad }))}
          />
        </Space>
        {birim && tur ? (
          <>
            <Table<GereksinimSatiriForm>
              rowKey={(_, i) => String(i)}
              size="small"
              pagination={false}
              dataSource={satirlar}
              scroll={{ x: 640 }}
              columns={[
                {
                  title: "Yetkinlik",
                  render: (_, s, i) => (
                    <Select
                      showSearch
                      optionFilterProp="label"
                      style={{ width: 260 }}
                      disabled={!yazabilir}
                      value={s.competency_id ?? undefined}
                      onChange={(v) =>
                        setSatirlar(satirlar.map((x, j) => (j === i ? { ...x, competency_id: v } : x)))
                      }
                      options={yetkinlikSecenekleri}
                    />
                  ),
                },
                {
                  title: "Asgari seviye",
                  render: (_, s, i) => (
                    <InputNumber
                      min={1}
                      max={4}
                      disabled={!yazabilir}
                      value={s.min_seviye}
                      onChange={(v) =>
                        setSatirlar(
                          satirlar.map((x, j) => (j === i ? { ...x, min_seviye: v ?? 1 } : x)),
                        )
                      }
                    />
                  ),
                },
                {
                  title: "Zorunlu eğitim",
                  render: (_, s, i) => (
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      style={{ width: 220 }}
                      disabled={!yazabilir}
                      value={s.course_id ?? undefined}
                      onChange={(v) =>
                        setSatirlar(
                          satirlar.map((x, j) => (j === i ? { ...x, course_id: v ?? null } : x)),
                        )
                      }
                      options={kursSecenekleri}
                    />
                  ),
                },
                ...(yazabilir
                  ? [
                      {
                        title: "",
                        key: "sil",
                        render: (_: unknown, __: GereksinimSatiriForm, i: number) => (
                          <Button
                            size="small"
                            danger
                            onClick={() => setSatirlar(satirlar.filter((_x, j) => j !== i))}
                          >
                            Kaldır
                          </Button>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
            {yazabilir && (
              <Space style={{ marginTop: 12 }}>
                <Button
                  onClick={() =>
                    setSatirlar([...satirlar, { competency_id: null, min_seviye: 3, course_id: null }])
                  }
                >
                  Satır ekle
                </Button>
                <Button
                  type="primary"
                  loading={gereksinimKaydet.isPending}
                  onClick={() => gereksinimKaydet.mutate()}
                >
                  Kaydet
                </Button>
              </Space>
            )}
          </>
        ) : (
          <Typography.Text type="secondary">Birim ve iş türü seçin.</Typography.Text>
        )}
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: "8px 0 0" }}>
          Eşleme tayini engellemez: eşik altındaki teknisyen yine tayin edilir, tayin yanıtında ve
          olay geçmişinde uyarı görünür.
        </Typography.Paragraph>
      </Card>
    </Space>
  );
}
