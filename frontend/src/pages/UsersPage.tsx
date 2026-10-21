import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Divider,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError, type Kullanici, type Rol } from "../api/client";
import { kapsamEtiketi, kapsamKataloguSorgusu, useAuth } from "../auth/AuthContext";
import IzinIstisnalari from "../components/IzinIstisnalari";
import RolDuzenle from "../components/RolDuzenle";
import RolYetkileri from "../components/RolYetkileri";

/** Liste satırı: kullanıcı + giriş/birim bilgisi + rolünden sapma (E13-10). */
type KullaniciSatiri = Kullanici & {
  giris_acik?: boolean;
  birimler?: string[];
  birincil_birim?: string | null;
  sapma_sayisi?: number;
};

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
  const { message } = App.useApp();
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
        giris_acik: duzenlenen.giris_acik ?? true,
        password: undefined,
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
    onError: (e: ApiError) => message.error(e.message),
  });

  const guncelle = useMutation({
    mutationFn: ({ id, ...v }: { id: number } & Record<string, unknown>) =>
      api.patch<Kullanici>(`/api/kullanicilar/${id}`, v),
    onSuccess: () => void yenile(),
    onError: (e: ApiError) => {
      // 409 = iyimser kilitleme çakışması; kullanıcıya sessiz kayıp yerine
      // net mesaj gider ve liste tazelenir.
      message.error(e.message);
      if (e.cakisma) void yenile();
    },
  });

  return (
    <Card
      title="Kullanıcılar ve roller"
      extra={
        sekme === "kullanicilar" ? (
          <Button type="primary" onClick={() => setAcik(true)}>
            Yeni kullanıcı
          </Button>
        ) : (
          <Button type="primary" onClick={() => setRolDuzenle({ acik: true })}>
            Yeni rol
          </Button>
        )
      }
    >
      <Tabs
        activeKey={sekme}
        onChange={setSekme}
        items={[
          { key: "kullanicilar", label: "Kullanıcılar" },
          { key: "roller", label: `Roller (${roller.data?.length ?? 0})` },
        ]}
      />
      {sekme === "roller" ? (
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
        dataSource={kullanicilar.data ?? []}
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
                {(k.sapma_sayisi ?? 0) > 0 && (
                  <Tag color="orange">Rolünden farklı ({k.sapma_sayisi})</Tag>
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
              ) : (
                <Tag color="green">açık</Tag>
              ),
          },
          {
            title: "Aktif",
            render: (_, k: Kullanici) => (
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
            render: (_, k: Kullanici) => (
              <Button size="small" onClick={() => setDuzenlenen(k)}>
                Düzenle
              </Button>
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
        <Form form={form} layout="vertical" onFinish={(v) => olustur.mutate(v)}>
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
            label="Parola"
            rules={[{ required: true, min: 8, message: "En az 8 karakter" }]}
          >
            <Input.Password />
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
          <Divider style={{ margin: "4px 0 12px" }}>Erişim ve izinler</Divider>
          <RolYetkileri rolKodu={yeniRol} />
        </Form>
      </Modal>

      <Modal
        title={duzenlenen ? `${duzenlenen.full_name} — düzenle` : ""}
        open={duzenlenen !== null}
        onCancel={() => setDuzenlenen(null)}
        onOk={() => duzenleForm.submit()}
        confirmLoading={guncelle.isPending}
        okText="Kaydet"
        cancelText="Vazgeç"
        destroyOnHidden
      >
        <Form
          form={duzenleForm}
          layout="vertical"
          onFinish={(v) => {
            if (!duzenlenen) return;
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
            if (v.password) gonderilecek.password = v.password;
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
            name="giris_acik"
            label="Oturum açabilir"
            valuePropName="checked"
            extra="Kapatılırsa kayıt (personel kartı) durur, açık oturumları hemen düşer."
          >
            <Switch disabled={duzenlenen?.id === kendisi?.id} />
          </Form.Item>
          <Divider style={{ margin: "4px 0 12px" }}>Erişim ve izinler</Divider>
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
          <Form.Item
            name="password"
            label="Yeni parola"
            rules={[{ min: 8, message: "En az 8 karakter" }]}
            extra="Boş bırakırsanız parola değişmez. Değiştirirseniz açık oturumlar düşer."
          >
            <Input.Password autoComplete="new-password" placeholder="(değiştirmek için doldurun)" />
          </Form.Item>
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
