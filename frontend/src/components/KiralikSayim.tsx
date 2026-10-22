/**
 * Kiralama deposu fiziksel sayımı (TS-195, E06-22 b).
 *
 * Akış: depo seç → sayım aç → sayılan seri/adetleri gir (satırların tamamı
 * kaydedilir) → farkı gör → yalnız onayladığın fark satırlarını uygula.
 * Onaysız fark HİÇBİR şeyi değiştirmez. "Sayıldı, sistemde yok" ve "başka
 * yerde" satırları bilgidir: giriş/transfer kendi ekranından yapılır.
 * Sayım sonrası depoda hareket olduysa sunucu 409 döner; "değişimi kabul et"
 * ile fark güncel bakiyeyle uygulanır. Okuma `kiralama.gor`, yazma
 * `kiralama.envanter`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Col,
  Drawer,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";

import type { ApiError } from "../api/client";
import {
  type FarkSatiri,
  kiralamaApi,
  SAYIM_DURUM_ADLARI,
  type SayimSatirGirdisi,
} from "../api/kiralama";
import { useAuth } from "../auth/AuthContext";

const zaman = (d?: string | null) => (d ? dayjs(d).format("DD.MM.YYYY HH:mm") : "—");
const DURUM_RENGI: Record<string, string> = { ACIK: "blue", ONAYLANDI: "green", IPTAL: "default" };
const FARK_RENGI: Record<string, string> = {
  SAYILMADI: "red",
  EKSIK: "red",
  FAZLA: "gold",
  SISTEMDE_YOK: "purple",
  BASKA_YERDE: "purple",
};

interface TaslakSatir extends SayimSatirGirdisi {
  anahtar: string;
}

function SayimDetayi({ sayimId, kapat, onDegisti }: { sayimId: number; kapat: () => void; onDegisti: () => void }) {
  const { message, modal } = App.useApp();
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const envanterci = yetkili("kiralama.envanter");
  const detay = useQuery({ queryKey: ["kiralik-sayim", sayimId], queryFn: () => kiralamaApi.sayim(sayimId) });
  const fark = useQuery({ queryKey: ["kiralik-sayim-fark", sayimId], queryFn: () => kiralamaApi.sayimFarki(sayimId) });
  const katalog = useQuery({ queryKey: ["kiralama-katalog-tum"], queryFn: () => kiralamaApi.katalog(undefined, true) });
  const [taslak, setTaslak] = useState<TaslakSatir[]>([]);
  const [secili, setSecili] = useState<string[]>([]);
  const [gerekce, setGerekce] = useState("");
  const [seriMetni, setSeriMetni] = useState("");
  const [urun, setUrun] = useState<number | undefined>();
  const acik = detay.data?.durum === "ACIK";

  useEffect(() => {
    if (!detay.data) return;
    setTaslak(
      detay.data.satirlar.map((s) => ({
        anahtar: `s${s.id}`,
        product_id: s.product_id,
        seri: s.seri,
        adet: s.sayilan_adet,
        notes: s.notes,
      })),
    );
  }, [detay.data]);

  const urunler = useMemo(() => new Map((katalog.data ?? []).map((k) => [k.product_id, k])), [katalog.data]);
  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["kiralik-sayim", sayimId] });
    void qc.invalidateQueries({ queryKey: ["kiralik-sayim-fark", sayimId] });
    void qc.invalidateQueries({ queryKey: ["kiralik-sayimlar"] });
    onDegisti();
  };

  const kaydet = useMutation({
    mutationFn: () =>
      kiralamaApi.sayimSatirlari(
        sayimId,
        taslak.map(({ product_id, seri, adet, notes }) => ({ product_id, seri, adet, notes })),
      ),
    onSuccess: () => {
      message.success("Sayım satırları kaydedildi");
      tazele();
    },
    onError: (e) => message.error((e as Error).message),
  });

  const onayla = useMutation({
    mutationFn: (kabul: boolean) =>
      kiralamaApi.sayimOnayla(sayimId, { kararlar: secili, gerekce: gerekce || undefined, degisimi_kabul: kabul }),
    onSuccess: (r) => {
      message.success(`Sayım onaylandı (${r.hareketler.length} hareket)`);
      setSecili([]);
      tazele();
    },
    onError: (e, kabul) => {
      const govde = (e as ApiError).govde as { detail?: { mesaj?: string } } | undefined;
      if ((e as ApiError).status === 409 && !kabul && govde?.detail?.mesaj) {
        modal.confirm({
          title: "Sayım sonrası hareket var",
          content: govde.detail.mesaj,
          okText: "Değişimi kabul et ve onayla",
          cancelText: "Vazgeç",
          onOk: () => onayla.mutate(true),
        });
        return;
      }
      message.error(govde?.detail?.mesaj ?? (e as Error).message);
      tazele();
    },
  });

  const iptal = useMutation({
    mutationFn: (g: string) => kiralamaApi.sayimIptal(sayimId, g),
    onSuccess: () => {
      message.success("Sayım iptal edildi");
      tazele();
      kapat();
    },
    onError: (e) => message.error((e as Error).message),
  });

  const ekle = () => {
    if (!urun) return;
    const k = urunler.get(urun);
    if (k?.seri_takipli) {
      const seriler = seriMetni
        .split(/[\s,;]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (!seriler.length) return;
      setTaslak((t) => [
        ...t,
        ...seriler.map((s, i) => ({ anahtar: `y${Date.now()}-${i}`, product_id: urun, seri: s, adet: 1 })),
      ]);
    } else {
      setTaslak((t) => [...t, { anahtar: `y${Date.now()}`, product_id: urun, adet: 0 }]);
    }
    setSeriMetni("");
  };

  const farkSutunlari = [
    { title: "Fark", dataIndex: "tur_adi", render: (v: string, r: FarkSatiri) => <Tag color={FARK_RENGI[r.tur]}>{v}</Tag> },
    { title: "Ürün", key: "urun", render: (_: unknown, r: FarkSatiri) => `${r.urun_kodu ?? ""} ${r.urun_adi ?? ""}` },
    { title: "Seri", dataIndex: "seri", render: (v: string | null) => v ?? "—" },
    { title: "Sistem", dataIndex: "sistem_adet", align: "right" as const },
    { title: "Sayılan", dataIndex: "sayilan_adet", align: "right" as const },
    { title: "Fark", dataIndex: "fark", align: "right" as const },
  ];

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      {detay.data && (
        <Space wrap>
          <Tag color={DURUM_RENGI[detay.data.durum]}>{SAYIM_DURUM_ADLARI[detay.data.durum]}</Tag>
          <Typography.Text>{detay.data.depo_adi}</Typography.Text>
          <Typography.Text type="secondary">Başlangıç: {zaman(detay.data.baslangic_at)}</Typography.Text>
          {detay.data.onay_at && <Typography.Text type="secondary">Onay: {zaman(detay.data.onay_at)}</Typography.Text>}
        </Space>
      )}

      <Typography.Title level={5}>Sayılanlar</Typography.Title>
      {acik && envanterci && (
        <Row gutter={[8, 8]}>
          <Col xs={24} md={9}>
            <Select
              showSearch
              optionFilterProp="label"
              style={{ width: "100%" }}
              placeholder="Ürün"
              value={urun}
              onChange={setUrun}
              options={(katalog.data ?? []).map((k) => ({
                value: k.product_id,
                label: `${k.urun_kodu ?? ""} ${k.urun_adi ?? ""}${k.seri_takipli ? " (seri)" : ""}`,
              }))}
            />
          </Col>
          {urun && urunler.get(urun)?.seri_takipli && (
            <Col xs={24} md={11}>
              <Input
                placeholder="Seri numaraları (boşluk/virgül ile)"
                value={seriMetni}
                onChange={(e) => setSeriMetni(e.target.value)}
                onPressEnter={ekle}
              />
            </Col>
          )}
          <Col xs={24} md={4}>
            <Button onClick={ekle} disabled={!urun}>
              Ekle
            </Button>
          </Col>
        </Row>
      )}
      <Table
        size="small"
        rowKey="anahtar"
        dataSource={taslak}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: true }}
        columns={[
          {
            title: "Ürün",
            key: "urun",
            render: (_, r) => {
              const k = urunler.get(r.product_id);
              return k ? `${k.urun_kodu ?? ""} ${k.urun_adi ?? ""}` : `#${r.product_id}`;
            },
          },
          { title: "Seri", dataIndex: "seri", render: (v?: string | null) => v ?? "—" },
          {
            title: "Sayılan",
            key: "adet",
            render: (_, r) =>
              r.seri ? (
                1
              ) : (
                <InputNumber
                  min={0}
                  disabled={!acik || !envanterci}
                  value={r.adet ?? 0}
                  onChange={(v) =>
                    setTaslak((t) => t.map((x) => (x.anahtar === r.anahtar ? { ...x, adet: Number(v ?? 0) } : x)))
                  }
                />
              ),
          },
          ...(acik && envanterci
            ? [
                {
                  title: "",
                  key: "sil",
                  render: (_: unknown, r: TaslakSatir) => (
                    <Button size="small" type="link" danger onClick={() => setTaslak((t) => t.filter((x) => x.anahtar !== r.anahtar))}>
                      Çıkar
                    </Button>
                  ),
                },
              ]
            : []),
        ]}
      />
      {acik && envanterci && (
        <Button type="primary" loading={kaydet.isPending} onClick={() => kaydet.mutate()}>
          Satırları kaydet
        </Button>
      )}

      <Typography.Title level={5}>Fark</Typography.Title>
      {(fark.data?.sayim_sonrasi_hareket ?? 0) > 0 && acik && (
        <Alert
          type="warning"
          showIcon
          title={`Sayım başladıktan sonra bu depoda ${fark.data?.sayim_sonrasi_hareket} hareket oldu; fark güncel bakiyeye göre gösteriliyor.`}
        />
      )}
      <Typography.Text type="secondary">
        Onaylanmayan fark hiçbir şeyi değiştirmez. Seçilen "sayılmadı" seri KAYIP olur, toplu eksik/fazla
        adet düzeltilir (fazla çıkan adet kontrole girer).
      </Typography.Text>
      <Table
        size="small"
        rowKey="anahtar"
        loading={fark.isLoading}
        dataSource={fark.data?.satirlar ?? []}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        scroll={{ x: true }}
        rowSelection={
          acik && envanterci
            ? {
                selectedRowKeys: secili,
                onChange: (k) => setSecili(k as string[]),
                getCheckboxProps: (r: FarkSatiri) => ({ disabled: !r.uygulanabilir }),
              }
            : undefined
        }
        columns={farkSutunlari}
      />
      {acik && envanterci && (
        <Space wrap>
          <Input
            style={{ width: 280 }}
            maxLength={300}
            placeholder="Gerekçe (isteğe bağlı)"
            value={gerekce}
            onChange={(e) => setGerekce(e.target.value)}
          />
          <Button type="primary" loading={onayla.isPending} onClick={() => onayla.mutate(false)}>
            {secili.length ? `${secili.length} farkı uygula ve onayla` : "Farksız onayla"}
          </Button>
          <Button
            danger
            onClick={() => {
              let metin = "";
              modal.confirm({
                title: "Sayımı iptal et",
                content: <Input.TextArea maxLength={500} placeholder="Gerekçe" onChange={(e) => (metin = e.target.value)} />,
                okText: "İptal et",
                cancelText: "Vazgeç",
                onOk: () => iptal.mutateAsync(metin),
              });
            }}
          >
            Sayımı iptal et
          </Button>
        </Space>
      )}
    </Space>
  );
}

export default function KiralikSayim({ onDegisti }: { onDegisti: () => void }) {
  const { message } = App.useApp();
  const { yetkili } = useAuth();
  const qc = useQueryClient();
  const envanterci = yetkili("kiralama.envanter");
  const [durum, setDurum] = useState<string | undefined>("ACIK");
  const [secili, setSecili] = useState<number | null>(null);
  const [yeniAcik, setYeniAcik] = useState(false);
  const [depo, setDepo] = useState<number | undefined>();
  const [notlar, setNotlar] = useState("");
  const liste = useQuery({ queryKey: ["kiralik-sayimlar", durum], queryFn: () => kiralamaApi.sayimlar(durum) });
  const depolar = useQuery({ queryKey: ["kiralama-depolar"], queryFn: kiralamaApi.depolar });

  const ac = useMutation({
    mutationFn: () => kiralamaApi.sayimAc(depo!, notlar || undefined),
    onSuccess: (s) => {
      message.success("Sayım açıldı");
      setYeniAcik(false);
      setSecili(s.id);
      void qc.invalidateQueries({ queryKey: ["kiralik-sayimlar"] });
    },
    onError: (e) => message.error((e as Error).message),
  });

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Space wrap>
        <Select
          allowClear
          style={{ width: 180 }}
          placeholder="Durum"
          value={durum}
          onChange={setDurum}
          options={Object.entries(SAYIM_DURUM_ADLARI).map(([k, v]) => ({ value: k, label: v }))}
        />
        {envanterci && (
          <Button type="primary" onClick={() => setYeniAcik(true)}>
            Sayım başlat
          </Button>
        )}
      </Space>
      <Table
        size="small"
        rowKey="id"
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar ?? []}
        pagination={{ pageSize: 50, hideOnSinglePage: true, total: liste.data?.toplam }}
        scroll={{ x: true }}
        onRow={(r) => ({ onClick: () => setSecili(r.id), style: { cursor: "pointer" } })}
        columns={[
          { title: "No", dataIndex: "id" },
          { title: "Depo", dataIndex: "depo_adi" },
          {
            title: "Durum",
            dataIndex: "durum",
            render: (d: string) => <Tag color={DURUM_RENGI[d]}>{SAYIM_DURUM_ADLARI[d] ?? d}</Tag>,
          },
          { title: "Başlangıç", dataIndex: "baslangic_at", render: zaman },
          { title: "Onay", dataIndex: "onay_at", render: zaman },
          { title: "Not", dataIndex: "notes", ellipsis: true },
        ]}
      />

      <Modal
        title="Depo sayımı başlat"
        open={yeniAcik}
        onCancel={() => setYeniAcik(false)}
        onOk={() => ac.mutate()}
        okButtonProps={{ disabled: !depo, loading: ac.isPending }}
        okText="Başlat"
        cancelText="Vazgeç"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Select
            style={{ width: "100%" }}
            placeholder="Kiralama deposu"
            value={depo}
            onChange={setDepo}
            options={(depolar.data ?? []).map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))}
          />
          <Input.TextArea maxLength={2000} placeholder="Not" value={notlar} onChange={(e) => setNotlar(e.target.value)} />
          <Checkbox checked disabled>
            Sayım açılınca hiçbir bakiye değişmez; fark yalnız onayda uygulanır
          </Checkbox>
        </Space>
      </Modal>

      <Drawer
        title={secili ? `Sayım #${secili}` : "Sayım"}
        open={secili !== null}
        size={900}
        onClose={() => setSecili(null)}
        destroyOnHidden
      >
        {secili !== null && <SayimDetayi sayimId={secili} kapat={() => setSecili(null)} onDegisti={onDegisti} />}
      </Drawer>
    </Space>
  );
}
