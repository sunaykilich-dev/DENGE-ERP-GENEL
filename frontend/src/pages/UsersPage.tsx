import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError, type Kullanici, type Rol } from "../api/client";
import { personelApi } from "../api/personel";
import { kapsamEtiketi, kapsamKataloguSorgusu, useAuth } from "../auth/AuthContext";
import IzinIstisnalari from "../components/IzinIstisnalari";
import RolDuzenle from "../components/RolDuzenle";
import RolYetkileri from "../components/RolYetkileri";
import Statistic from "../components/Statistic";

/**
 * Liste satırı: kullanıcı + giriş/birim bilgisi + rolünden sapma (E13-10).
 * Liste yanıtında `sirketler` ham üyelik KODLARIDIR (oturumdaki nesne değil).
 */
type KullaniciSatiri = Omit<Kullanici, "sirketler"> & {
  sirketler?: string[];
  giris_acik?: boolean;
  birimler?: string[];
  birincil_birim?: string | null;
  sapma_sayisi?: number;
  /** Yürürlükteki süreli vekâlet (TS-213); kalıcı sapmadan ayrı sayılır. */
  vekalet_sayisi?: number;
};

/** `PATCH /api/kullanicilar/{id}` yanıtı: geçici parola YALNIZ burada, bir kez. */
type GuncellemeSonucu = Kullanici & {
  gecici_parola?: string | null;
  gecici_parola_bitis?: string | null;
};

// --- Erişim gözden geçirme (TS-214; sunucu: `api/erisim_gozden.py`) --------------

interface ErisimKpi {
  kod: string;
  baslik: string;
  aciklama: string;
  adet: number;
}

interface ErisimSatiri {
  id: number;
  full_name: string;
  username: string;
  rol_adi: string;
  is_active: boolean;
  giris_acik: boolean;
  son_giris_at: string | null;
  ayrilis_tarihi: string | null;
  kilitli: boolean;
  mfa_enabled: boolean;
  hassas_izinler: string[];
  sapma_sayisi: number;
  vekalet_sayisi: number;
  son_gozden_gecirme_at: string | null;
  son_gozden_geciren: string | null;
}

const ERISIM_SAYFA = 25;

function zamanMetni(v: string | null): string {
  return v ? dayjs(v).format("DD.MM.YYYY HH:mm") : "—";
}

/**
 * Erişim gözden geçirme sekmesi. Kutular süzgeçtir: kutudaki sayı, tıklanınca
 * açılan listenin toplamıyla aynıdır (sunucu iki yerde aynı koşulu kullanır).
 * "Gözden geçirildi" işareti yalnız denetim kaydıdır.
 */
function ErisimGozden() {
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [kpi, setKpi] = useState<string | undefined>();
  const [sayfa, setSayfa] = useState(1);
  const [isaretlenen, setIsaretlenen] = useState<ErisimSatiri | null>(null);
  const [not, setNot] = useState("");

  const ozet = useQuery({
    queryKey: ["erisim-gozden-ozet"],
    queryFn: () =>
      api.get<{ girissiz_gun: number; kpiler: ErisimKpi[] }>("/api/erisim-gozden/ozet"),
  });
  const liste = useQuery({
    queryKey: ["erisim-gozden", kpi, sayfa],
    queryFn: () => {
      const p = new URLSearchParams({
        limit: String(ERISIM_SAYFA),
        offset: String((sayfa - 1) * ERISIM_SAYFA),
      });
      if (kpi) p.set("kpi", kpi);
      return api.getSayfa<ErisimSatiri>(`/api/erisim-gozden?${p}`);
    },
  });
  const isaretle = useMutation({
    mutationFn: (s: ErisimSatiri) =>
      api.post(`/api/erisim-gozden/${s.id}/gozden-gecirildi`, { not: not.trim() || null }),
    onSuccess: () => {
      message.success("Gözden geçirildi olarak işaretlendi (denetim kaydına yazıldı)");
      setIsaretlenen(null);
      setNot("");
      void qc.invalidateQueries({ queryKey: ["erisim-gozden"] });
    },
    onError: (e: ApiError) => void message.error(e.message),
  });
  const kpiSec = (k: string | undefined) => {
    setKpi(k);
    setSayfa(1);
  };

  return (
    <Space orientation="vertical" style={{ width: "100%" }} size="middle">
      <Row gutter={[12, 12]}>
        {(ozet.data?.kpiler ?? []).map((k) => (
          <Col key={k.kod} xs={12} sm={8} md={6} lg={4}>
            <Tooltip title={k.aciklama}>
              <Card
                size="small"
                hoverable
                onClick={() => kpiSec(kpi === k.kod ? undefined : k.kod)}
                style={{ height: "100%", borderColor: kpi === k.kod ? "#1677ff" : undefined }}
              >
                <Statistic
                  title={k.kod === "uzun_girissiz" ? `${k.baslik} (${ozet.data?.girissiz_gun}+ gün)` : k.baslik}
                  value={k.adet}
                  valueStyle={k.adet > 0 && k.kod !== "hassas_izin" ? { color: "#b42318" } : undefined}
                />
              </Card>
            </Tooltip>
          </Col>
        ))}
      </Row>
      <Space wrap>
        {kpi && (
          <Button onClick={() => kpiSec(undefined)}>
            Süzgeci kaldır ({ozet.data?.kpiler.find((k) => k.kod === kpi)?.baslik})
          </Button>
        )}
        {yetkili("rapor.disaaktar") && (
          <Button
            onClick={() =>
              window.open(`/api/erisim-gozden/excel${kpi ? `?kpi=${kpi}` : ""}`, "_blank")
            }
          >
            Excel
          </Button>
        )}
      </Space>
      <Table
        rowKey="id"
        size="small"
        scroll={{ x: 900 }}
        loading={liste.isLoading}
        dataSource={liste.data?.kayitlar ?? []}
        pagination={{
          current: sayfa,
          pageSize: ERISIM_SAYFA,
          total: liste.data?.toplam ?? 0,
          showSizeChanger: false,
          onChange: setSayfa,
          showTotal: (t) => `${t.toLocaleString("tr-TR")} hesap`,
        }}
        columns={[
          { title: "Ad soyad", dataIndex: "full_name", ellipsis: true },
          { title: "Kullanıcı adı", dataIndex: "username", className: "mono", width: 130 },
          { title: "Rol", dataIndex: "rol_adi", ellipsis: true },
          {
            title: "Durum",
            width: 190,
            render: (_, s: ErisimSatiri) => (
              <Space size={4} wrap>
                {!s.is_active && <Tag>pasif</Tag>}
                {s.giris_acik ? <Tag color="green">giriş açık</Tag> : <Tag>giriş kapalı</Tag>}
                {s.ayrilis_tarihi && <Tag color="red">ayrıldı</Tag>}
                {s.kilitli && <Tag color="red">kilitli</Tag>}
                {!s.mfa_enabled && <Tag>MFA yok</Tag>}
              </Space>
            ),
          },
          {
            title: "Hassas / sapma",
            width: 220,
            render: (_, s: ErisimSatiri) => (
              <Space size={4} wrap>
                {s.hassas_izinler.map((i) => (
                  <Tag key={i} color="gold" className="mono">
                    {i}
                  </Tag>
                ))}
                {s.sapma_sayisi > 0 && <Tag color="orange">istisna {s.sapma_sayisi}</Tag>}
                {s.vekalet_sayisi > 0 && <Tag color="purple">vekâlet {s.vekalet_sayisi}</Tag>}
              </Space>
            ),
          },
          { title: "Son giriş", width: 140, render: (_, s: ErisimSatiri) => zamanMetni(s.son_giris_at) },
          {
            title: "Son gözden geçirme",
            width: 190,
            render: (_, s: ErisimSatiri) =>
              s.son_gozden_gecirme_at ? (
                <span>
                  {zamanMetni(s.son_gozden_gecirme_at)}
                  {s.son_gozden_geciren && (
                    <Typography.Text type="secondary"> · {s.son_gozden_geciren}</Typography.Text>
                  )}
                </span>
              ) : (
                <Tag>hiç</Tag>
              ),
          },
          {
            title: "",
            width: 120,
            render: (_, s: ErisimSatiri) => (
              <Button size="small" onClick={() => setIsaretlenen(s)}>
                Gözden geçirildi
              </Button>
            ),
          },
        ]}
      />
      <Modal
        title={isaretlenen ? `${isaretlenen.full_name} — erişim gözden geçirildi` : ""}
        open={isaretlenen !== null}
        onCancel={() => setIsaretlenen(null)}
        onOk={() => isaretlenen && isaretle.mutate(isaretlenen)}
        okText="İşaretle"
        cancelText="Vazgeç"
        confirmLoading={isaretle.isPending}
        destroyOnHidden
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Kişinin o anki rolü ve hassas izinleri denetim kaydına işaretle birlikte yazılır.
            Yetki değişmez; değiştirmek için kullanıcıyı düzenleyin.
          </Typography.Text>
          <Input.TextArea
            rows={2}
            maxLength={300}
            placeholder="Not (isteğe bağlı), ör. 2026 Q1 erişim gözden geçirmesi"
            value={not}
            onChange={(e) => setNot(e.target.value)}
          />
        </Space>
      </Modal>
    </Space>
  );
}

/** Rol seçeneğinin etiketi: kısıtlı kapsam adın yanında yazılır. */
function rolEtiketi(r: Rol): string {
  const etiket = kapsamEtiketi(r.scope);
  return etiket ? `${r.name} — ${etiket}` : r.name;
}

export default function UsersPage() {
  // Seçili rol, iki penceredeki yetki panelini besler: yönetici rolü
  // seçerken ne verdiğini aynı ekranda görsün.
  const { kullanici: kendisi, yetkili } = useAuth();
  const [sekme, setSekme] = useState("kullanicilar");
  const [rolDuzenle, setRolDuzenle] = useState<{
    acik: boolean;
    kod?: string;
    sayi?: number;
  }>({ acik: false });
  const [yeniRol, setYeniRol] = useState<string>();
  const [duzenlenenRol, setDuzenlenenRol] = useState<string>();
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const [acik, setAcik] = useState(false);
  const [form] = Form.useForm();
  // Düzenlenen kullanıcı; null ise düzenleme penceresi kapalı.
  const [duzenlenen, setDuzenlenen] = useState<KullaniciSatiri | null>(null);
  const [duzenleForm] = Form.useForm();

  const kullanicilar = useQuery({
    queryKey: ["kullanicilar"],
    queryFn: () => api.get<KullaniciSatiri[]>("/api/kullanicilar"),
  });
  const roller = useQuery({ queryKey: ["roller"], queryFn: () => api.get<Rol[]>("/api/roller") });
  const katalog = useQuery(kapsamKataloguSorgusu);
  // Birim kapsamlı rolde birimsiz hesap sunucuda 400; alan bu rolde zorunlu.
  const yeniRolBirimIster =
    katalog.data?.kapsamlar.find(
      (k) => k.kod === roller.data?.find((r) => r.code === yeniRol)?.scope,
    )?.birim_zorunlu ?? false;
  const birimSecenekleri = (katalog.data?.birimler ?? []).map((b) => ({
    value: b.kod,
    label: b.ad,
  }));
  // Rol testi B-03 (KARARLAR 2026-11-04 §1, §5.1): admin kullanıcıyı şirkete üye yapar.
  const sirketSecenekleri = (katalog.data?.sirketler ?? []).map((s) => ({ value: s.kod, label: s.ad }));
  const sirketAdi = (kod: string) => katalog.data?.sirketler?.find((s) => s.kod === kod)?.ad ?? kod;
  // Birim üyeliği personel kartı ucundan yazılır (`personel.yaz`); kişi kendi birimini değiştiremez.
  const birimYazabilir = yetkili("personel.yaz");
  const [kaydediliyor, setKaydediliyor] = useState(false);

  const yenile = () => {
    void qc.invalidateQueries({ queryKey: ["kullanicilar"] });
    void qc.invalidateQueries({ queryKey: ["kilitli-kullanicilar"] });
  };

  // Giriş kilidi kendiliğinden açılmıyor; açılmazsa kullanıcı bir daha giremez,
  // bu yüzden kimin kilitli olduğu bu ekranda görünmek zorunda.
  const kilitliler = useQuery({
    queryKey: ["kilitli-kullanicilar"],
    queryFn: () => api.get<string[]>("/api/kullanicilar/kilitli"),
  });

  const kilitAc = useMutation({
    mutationFn: (username: string) => api.post(`/api/kullanicilar/${username}/kilidi-ac`, {}),
    onSuccess: () => {
      message.success("Kilit açıldı");
      yenile();
    },
  });

  useEffect(() => {
    if (duzenlenen) {
      duzenleForm.setFieldsValue({
        full_name: duzenlenen.full_name,
        email: duzenlenen.email ?? undefined,
        role_code: duzenlenen.role.code,
        sirketler: duzenlenen.sirketler ?? [],
        birimler: duzenlenen.birimler ?? [],
        birincil_birim: duzenlenen.birincil_birim ?? undefined,
        giris_acik: duzenlenen.giris_acik ?? true,
        password: undefined,
        parola_sifirla: false,
        reset_mfa: false,
      });
    }
  }, [duzenlenen, duzenleForm]);

  const olustur = useMutation({
    mutationFn: (v: unknown) => api.post<Kullanici>("/api/kullanicilar", v),
    onSuccess: () => {
      message.success("Kullanıcı açıldı");
      setAcik(false);
      form.resetFields();
      void yenile();
    },
    onError: (e: ApiError) => void message.error(e.message),
  });

  const guncelle = useMutation({
    mutationFn: ({ id, ...v }: { id: number } & Record<string, unknown>) =>
      api.patch<GuncellemeSonucu>(`/api/kullanicilar/${id}`, v),
    onSuccess: (sonuc) => {
      void yenile();
      // Geçici parola YALNIZ bu yanıtta ve bir kez gelir (TS-212); kapatılınca
      // bir daha gösterilemez — yönetici kullanıcıya şimdi iletmeli.
      if (sonuc?.gecici_parola) {
        modal.info({
          title: `${sonuc.full_name} — geçici parola`,
          width: 460,
          content: (
            <Space orientation="vertical">
              <Typography.Text copyable={{ text: sonuc.gecici_parola }} className="mono" strong>
                {sonuc.gecici_parola}
              </Typography.Text>
              <Typography.Text type="secondary">
                Bu parola bir daha gösterilmez. Tek girişte ve{" "}
                {sonuc.gecici_parola_bitis
                  ? dayjs(sonuc.gecici_parola_bitis).format("DD.MM.YYYY HH:mm")
                  : "72 saat"}{" "}
                tarihine kadar geçerlidir; kullanıcı ilk girişte kendi parolasını belirler.
              </Typography.Text>
            </Space>
          ),
        });
      }
    },
    onError: (e: ApiError) => {
      // 409 = iyimser kilitleme çakışması; kullanıcıya sessiz kayıp yerine
      // net mesaj gider ve liste tazelenir.
      message.error(e.message);
      if (e.cakisma) void yenile();
    },
  });

  // Silme (2026-11-24): yalnız iz bırakmamış hesap kalıcı silinir; izi olan
  // için sunucu 409 KAYITLI_KULLANICI döner → pasifleştirme önerilir.
  const sil = useMutation({
    mutationFn: (k: KullaniciSatiri) => api.delete<void>(`/api/kullanicilar/${k.id}`),
    onSuccess: () => {
      message.success("Kullanıcı silindi");
      void yenile();
    },
    onError: (e: ApiError, k) => {
      const detay = (e.govde as { detail?: { kod?: string; mesaj?: string } } | undefined)?.detail;
      if (e.status === 409 && detay?.kod === "KAYITLI_KULLANICI") {
        modal.confirm({
          title: "Bu kullanıcı silinemez",
          content: detay.mesaj,
          okText: k.is_active ? "Pasifleştir" : "Tamam",
          cancelText: "Vazgeç",
          onOk: () =>
            k.is_active
              ? guncelle.mutate({ id: k.id, is_active: false, version: k.version })
              : undefined,
        });
        return;
      }
      message.error(e.message);
    },
  });
  const [pasifleriGoster, setPasifleriGoster] = useState(false);

  return (
    <Card
      title="Kullanıcılar ve roller"
      extra={
        sekme === "kullanicilar" ? (
          <Space>
            <Switch
              size="small"
              checked={pasifleriGoster}
              onChange={setPasifleriGoster}
              checkedChildren="Pasifler görünür"
              unCheckedChildren="Pasifler gizli"
            />
            <Button type="primary" onClick={() => setAcik(true)}>
              Yeni kullanıcı
            </Button>
          </Space>
        ) : sekme === "roller" ? (
          <Button type="primary" onClick={() => setRolDuzenle({ acik: true })}>
            Yeni rol
          </Button>
        ) : null
      }
    >
      <Tabs
        activeKey={sekme}
        onChange={setSekme}
        items={[
          { key: "kullanicilar", label: "Kullanıcılar" },
          { key: "roller", label: `Roller (${roller.data?.length ?? 0})` },
          { key: "erisim", label: "Erişim gözden geçirme" },
        ]}
      />
      {sekme === "erisim" ? (
        <ErisimGozden />
      ) : sekme === "roller" ? (
        <Table
          rowKey="code"
          size="small"
          pagination={false}
          dataSource={roller.data ?? []}
          columns={[
            { title: "Rol", dataIndex: "name" },
            { title: "Kod", dataIndex: "code", className: "mono" },
            {
              title: "Kapsam",
              render: (_: unknown, r: Rol) =>
                kapsamEtiketi(r.scope) ? (
                  <Tag>{kapsamEtiketi(r.scope)}</Tag>
                ) : (
                  <Tag color="blue">tüm kayıtlar</Tag>
                ),
            },
            {
              title: "Kullanıcı",
              render: (_: unknown, r: Rol) =>
                (kullanicilar.data ?? []).filter((k) => k.role.code === r.code).length,
            },
            {
              title: "",
              align: "right" as const,
              render: (_: unknown, r: Rol) => (
                <Button
                  size="small"
                  onClick={() =>
                    setRolDuzenle({
                      acik: true,
                      kod: r.code,
                      sayi: (kullanicilar.data ?? []).filter((k) => k.role.code === r.code)
                        .length,
                    })
                  }
                >
                  Düzenle
                </Button>
              ),
            },
          ]}
        />
      ) : (
      <Table
        rowKey="id"
        loading={kullanicilar.isLoading}
        dataSource={(kullanicilar.data ?? []).filter((k) => pasifleriGoster || k.is_active)}
        pagination={false}
        columns={[
          {
            title: "Ad Soyad",
            // Personel kartı = kullanıcı (TS-008); kart izni olan kartı buradan açar.
            render: (_, k: KullaniciSatiri) =>
              yetkili("personel.gor") ? (
                <Link to={`/personel/${k.id}`}>{k.full_name}</Link>
              ) : (
                k.full_name
              ),
          },
          { title: "Kullanıcı adı", dataIndex: "username", className: "mono" },
          {
            title: "Rol",
            render: (_, k: KullaniciSatiri) => (
              <Space size={4} wrap>
                <Tag color="blue">{k.role.name}</Tag>
                {kapsamEtiketi(k.role.scope) && <Tag>{kapsamEtiketi(k.role.scope)}</Tag>}
                {(k.birimler ?? []).map((b) => (
                  <Tag key={b} color={b === k.birincil_birim ? "geekblue" : undefined}>
                    {katalog.data?.birimler.find((x) => x.kod === b)?.ad ?? b}
                  </Tag>
                ))}
                {(k.sirketler ?? []).map((s) => (
                  <Tag key={`s:${s}`} color="cyan">
                    {sirketAdi(s)}
                  </Tag>
                ))}
                {(k.sapma_sayisi ?? 0) > 0 && (
                  <Tag color="orange">Rolünden farklı ({k.sapma_sayisi})</Tag>
                )}
                {(k.vekalet_sayisi ?? 0) > 0 && (
                  <Tooltip title="Süreli vekâlet; süresi dolunca kendiliğinden biter (Personel kartı → Vekâletler)">
                    <Tag color="purple">vekâlet ({k.vekalet_sayisi})</Tag>
                  </Tooltip>
                )}
                {k.sees_cost && <Tag color="gold">maliyet görür</Tag>}
              </Space>
            ),
          },
          {
            title: "MFA",
            dataIndex: "mfa_enabled",
            render: (v: boolean) => (v ? <Tag color="green">açık</Tag> : <Tag>kapalı</Tag>),
          },
          {
            title: "Giriş",
            render: (_, k: KullaniciSatiri) =>
              k.giris_acik === false ? (
                <Tag>giriş kapalı</Tag>
              ) : kilitliler.data?.includes(k.username) ? (
                <Space size={4}>
                  <Tag color="red">kilitli</Tag>
                  <Button
                    size="small"
                    loading={kilitAc.isPending}
                    onClick={() => kilitAc.mutate(k.username)}
                  >
                    Kilidi aç
                  </Button>
                </Space>
              ) : k.parola_degismeli ? (
                <Tooltip title="Geçici parolayla açıldı; ilk girişte kendi parolasını belirleyecek">
                  <Tag color="gold">parola değişmeli</Tag>
                </Tooltip>
              ) : (
                <Tag color="green">açık</Tag>
              ),
          },
          {
            title: "Aktif",
            render: (_, k: KullaniciSatiri) => (
              <Switch
                checked={k.is_active}
                loading={guncelle.isPending}
                onChange={(deger) =>
                  guncelle.mutate({ id: k.id, is_active: deger, version: k.version })
                }
              />
            ),
          },
          {
            title: "",
            render: (_, k: KullaniciSatiri) => (
              <Space size={4}>
                <Button size="small" onClick={() => setDuzenlenen(k)}>
                  Düzenle
                </Button>
                <Popconfirm
                  title={`${k.full_name} silinsin mi?`}
                  description="Sistemde kaydı olmayan hesap kalıcı silinir; kaydı olan pasifleştirilir."
                  okText="Sil"
                  okButtonProps={{ danger: true }}
                  cancelText="Vazgeç"
                  onConfirm={() => sil.mutate(k)}
                >
                  <Button size="small" danger loading={sil.isPending && sil.variables?.id === k.id}>
                    Sil
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />

      )}

      <RolDuzenle
        acik={rolDuzenle.acik}
        rolKodu={rolDuzenle.kod}
        kullaniciSayisi={rolDuzenle.sayi}
        onKapat={() => setRolDuzenle({ acik: false })}
      />

      <Modal
        title="Yeni kullanıcı"
        open={acik}
        onCancel={() => setAcik(false)}
        onOk={() => form.submit()}
        confirmLoading={olustur.isPending}
        okText="Aç"
        cancelText="Vazgeç"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(v: Record<string, unknown>) => {
            // Boş şirket listesi = sunucu birimlerden türetsin (alanı hiç gönderme).
            const { sirketler, ...geri } = v;
            olustur.mutate(
              Array.isArray(sirketler) && sirketler.length ? { ...geri, sirketler } : geri,
            );
          }}
        >
          <Form.Item name="full_name" label="Ad Soyad" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="username"
            label="Kullanıcı adı"
            rules={[
              { required: true },
              { pattern: /^[a-z0-9_.-]+$/, message: "Küçük harf, rakam, nokta, tire" },
            ]}
          >
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="email" label="E-posta">
            <Input type="email" />
          </Form.Item>
          <Form.Item
            name="password"
            label="Geçici parola"
            rules={[{ required: true, min: 8, message: "En az 8 karakter" }]}
            extra="Kullanıcı ilk girişte kendi parolasını belirler; bu parola 72 saat ve tek giriş için geçerlidir."
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role_code" label="Rol" rules={[{ required: true }]}>
            <Select
              onChange={(v) => setYeniRol(v as string)}
              options={(roller.data ?? []).map((r) => ({ value: r.code, label: rolEtiketi(r) }))}
            />
          </Form.Item>
          {yeniRolBirimIster && (
            <>
              <Form.Item
                name="birimler"
                label="Birimler"
                rules={[{ required: true, message: "Bu rol için en az bir birim seçin" }]}
                extra="Birimi olmayan kullanıcı bu rolde hiçbir servis kaydı görmez."
              >
                <Select mode="multiple" options={birimSecenekleri} />
              </Form.Item>
              <Form.Item
                name="birincil_birim"
                label="Birincil birim"
                extra="Boş bırakılırsa seçilen ilk birim (alfabetik) birincil olur."
              >
                <Select allowClear options={birimSecenekleri} />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="sirketler"
            label="Şirketler"
            extra="Kullanıcının çalışabileceği şirketler. Boş bırakılırsa birimlerinden türetilir."
          >
            <Select mode="multiple" allowClear options={sirketSecenekleri} placeholder="Birimlerden türetilsin" />
          </Form.Item>
          <Divider style={{ margin: "4px 0 12px" }}>Erişim ve izinler</Divider>
          <RolYetkileri rolKodu={yeniRol} />
        </Form>
      </Modal>

      <Modal
        title={duzenlenen ? `${duzenlenen.full_name} — düzenle` : ""}
        open={duzenlenen !== null}
        onCancel={() => setDuzenlenen(null)}
        onOk={() => duzenleForm.submit()}
        confirmLoading={guncelle.isPending || kaydediliyor}
        okText="Kaydet"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Form
          form={duzenleForm}
          layout="vertical"
          onFinish={async (v) => {
            if (!duzenlenen) return;
            // Birim üyeliği önce yazılır: birim kapsamlı role geçişte sunucu
            // birimsiz hesabı 400 ile reddeder (personel kartı ucu, TS-002).
            const yeniBirimler: string[] = v.birimler ?? [];
            const eskiBirimler = duzenlenen.birimler ?? [];
            const birimDegisti =
              birimYazabilir &&
              duzenlenen.id !== kendisi?.id &&
              (yeniBirimler.length !== eskiBirimler.length ||
                yeniBirimler.some((b) => !eskiBirimler.includes(b)) ||
                (v.birincil_birim ?? null) !== (duzenlenen.birincil_birim ?? null));
            if (birimDegisti) {
              const birincil = yeniBirimler.includes(v.birincil_birim) ? v.birincil_birim : yeniBirimler[0];
              setKaydediliyor(true);
              try {
                await personelApi.birimleriYaz(
                  duzenlenen.id,
                  yeniBirimler.map((b) => ({ birim: b, birincil: b === birincil })),
                );
              } catch (e) {
                message.error(`Birimler kaydedilemedi: ${(e as Error).message}`);
                return;
              } finally {
                setKaydediliyor(false);
              }
            }
            // Boş bırakılan parola "parolayı silme" değil "dokunma" demek.
            const gonderilecek: Record<string, unknown> = {
              id: duzenlenen.id,
              version: duzenlenen.version,
              full_name: v.full_name,
              email: v.email || null,
              role_code: v.role_code,
              giris_acik: v.giris_acik,
              reset_mfa: v.reset_mfa || undefined,
            };
            const yeniSirketler: string[] = v.sirketler ?? [];
            const eskiSirketler = duzenlenen.sirketler ?? [];
            if (
              yeniSirketler.length !== eskiSirketler.length ||
              yeniSirketler.some((s) => !eskiSirketler.includes(s))
            ) {
              gonderilecek.sirketler = yeniSirketler;
            }
            if (v.password) gonderilecek.password = v.password;
            else if (v.parola_sifirla) gonderilecek.parola_sifirla = true;
            guncelle.mutate(gonderilecek as { id: number } & Record<string, unknown>);
            setDuzenlenen(null);
          }}
        >
          <Form.Item name="full_name" label="Ad Soyad" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="email" label="E-posta">
            <Input type="email" />
          </Form.Item>
          <Form.Item
            name="role_code"
            label="Rol"
            rules={[{ required: true }]}
            extra="Rol değişince kullanıcının açık oturumları düşer."
          >
            <Select
              onChange={(v) => setDuzenlenenRol(v as string)}
              options={(roller.data ?? []).map((r) => ({ value: r.code, label: rolEtiketi(r) }))}
            />
          </Form.Item>
          <Form.Item
            name="sirketler"
            label="Şirketler"
            rules={[{ required: (duzenlenen?.sirketler?.length ?? 0) > 0, message: "En az bir şirket seçin" }]}
            extra="Kullanıcı yalnız üye olduğu şirketleri seçebilir; çıkarılan şirkette açık oturumu varsa kendiliğinden başka şirkete geçer."
          >
            <Select mode="multiple" options={sirketSecenekleri} />
          </Form.Item>
          {birimYazabilir && duzenlenen?.id !== kendisi?.id && (
            <>
              <Form.Item
                name="birimler"
                label="Birimler"
                extra="Birim kapsamlı rolde kullanıcı yalnız bu birimlerin kayıtlarını görür. Değişince açık oturumları düşer."
              >
                <Select mode="multiple" allowClear options={birimSecenekleri} />
              </Form.Item>
              <Form.Item name="birincil_birim" label="Birincil birim" extra="Boş bırakılırsa ilk birim birincil olur.">
                <Select allowClear options={birimSecenekleri} />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="giris_acik"
            label="Oturum açabilir"
            valuePropName="checked"
            extra="Kapatılırsa kayıt (personel kartı) durur, açık oturumları hemen düşer."
          >
            <Switch disabled={duzenlenen?.id === kendisi?.id} />
          </Form.Item>
          <Divider style={{ margin: "4px 0 12px" }}>Erişim ve izinler</Divider>
          {/* 2026-11-09: sayfa ve aksiyon listesi rolden gelir; yönetici rolü
              buradan da düzenler (değişiklik o roldeki herkesi etkiler). */}
          {duzenlenen && (!duzenlenenRol || duzenlenenRol === duzenlenen.role.code) && (
            <div style={{ textAlign: "right", marginBottom: 8 }}>
              <Button
                size="small"
                onClick={() =>
                  setRolDuzenle({
                    acik: true,
                    kod: duzenlenen.role.code,
                    sayi: (kullanicilar.data ?? []).filter((k) => k.role.code === duzenlenen.role.code)
                      .length,
                  })
                }
              >
                Rolün sayfa ve izinlerini düzenle
              </Button>
            </div>
          )}
          {/* Rol açılır menüden DEĞİŞTİRİLDİYSE henüz kaydedilmemiş o rolün
              listesini göster; değişmediyse kişinin istisnalar dahil etkin
              yetkisini. */}
          {duzenlenenRol && duzenlenenRol !== duzenlenen?.role.code ? (
            <RolYetkileri rolKodu={duzenlenenRol} />
          ) : (
            <RolYetkileri userId={duzenlenen?.id} />
          )}
          <Divider style={{ margin: "12px 0" }}>Bu kullanıcıya özel istisnalar</Divider>
          {duzenlenen && (
            <IzinIstisnalari
              userId={duzenlenen.id}
              kendisiMi={duzenlenen.id === kendisi?.id}
            />
          )}
          <Divider style={{ margin: "12px 0" }} />
          {duzenlenen?.id !== kendisi?.id && (
            <>
              <Form.Item
                name="parola_sifirla"
                label="Geçici parola üret"
                valuePropName="checked"
                extra="Sunucu tek seferlik bir parola üretir ve kaydettikten sonra BİR KEZ gösterir. Açık oturumlar düşer; kullanıcı ilk girişte kendi parolasını belirler (72 saat geçerli)."
              >
                <Switch />
              </Form.Item>
              <Form.Item
                name="password"
                label="ya da geçici parolayı siz belirleyin"
                rules={[{ min: 8, message: "En az 8 karakter" }]}
                extra="Boş bırakırsanız parola değişmez. Belirlenen parola da geçicidir: ilk girişte değiştirilir."
              >
                <Input.Password autoComplete="new-password" placeholder="(değiştirmek için doldurun)" />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="reset_mfa"
            label="İki adımlı doğrulamayı sıfırla"
            valuePropName="checked"
            extra="Telefonunu kaybeden kullanıcı için. Bir sonraki girişte yeniden kurar."
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
