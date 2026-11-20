import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Form, Input, Modal, Select, Tag, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { kapsamKataloguSorgusu } from "../auth/AuthContext";

interface Izin {
  kod: string;
  modul: string;
  aciklama: string;
  /** Kişisel veri, ücret/maliyet, sistem yönetimi: ayrıca işaretlenir. */
  hassas?: boolean;
  /** Bu iznin açtığı sayfalar (sayfa listesi izinden türetilir). */
  sayfalar?: string[];
}

interface Yetki {
  code: string;
  name: string;
  scope: string;
  yalniz_ofis?: boolean;
  izinler: Izin[];
  version?: number;
  ozellestirildi?: boolean;
  varsayilana_donebilir?: boolean;
}

/**
 * Rol düzenleme / yeni rol.
 *
 * Rol omurgadır: değişiklik o roldeki HERKESİ etkiler ve açık oturumları
 * düşürür (eski yetkiyle açılmış oturum yeni kısıtı görmezdi). Bu yüzden
 * pencere kaç kullanıcının etkileneceğini önden söyler.
 *
 * Sistem rolleri de düzenlenebilir; düzenlenen rol "özelleştirilmiş"
 * işaretlenir ve açılıştaki katalog senkronu ona bir daha dokunmaz — aksi
 * halde değişiklik bir sonraki yeniden başlatmada sessizce geri alınırdı.
 *
 * 2026-11-09: "Erişebileceği sayfalar" izinden türetilir; her izin satırı açtığı
 * sayfaları gösterir, üstte seçimin açtığı sayfaların özeti durur. Hassas
 * izinler rozetle işaretlenir. Kayıt iyimser kilitlidir (`version`); sistem
 * rolü koddaki varsayılana döndürülebilir. Ek onay adımı yok (G1.9).
 */
export default function RolDuzenle({
  acik,
  rolKodu,
  kullaniciSayisi,
  onKapat,
}: {
  acik: boolean;
  rolKodu?: string; // yoksa yeni rol
  kullaniciSayisi?: number;
  onKapat: () => void;
}) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [secili, setSecili] = useState<string[]>([]);

  const katalog = useQuery({
    queryKey: ["izin-katalogu"],
    queryFn: () => api.get<Izin[]>("/api/izinler"),
    enabled: acik,
  });
  const mevcut = useQuery({
    queryKey: ["rol-yetkileri", rolKodu],
    queryFn: () => api.get<Yetki>(`/api/roller/${rolKodu}/yetkiler`),
    enabled: acik && Boolean(rolKodu),
  });
  const kapsamlar = useQuery({ ...kapsamKataloguSorgusu, enabled: acik });
  const seciliKapsam = Form.useWatch("scope", form) as string | undefined;
  const kapsamAciklamasi = kapsamlar.data?.kapsamlar.find((k) => k.kod === seciliKapsam);

  useEffect(() => {
    if (!acik) return;
    if (rolKodu && mevcut.data) {
      form.setFieldsValue({
        name: mevcut.data.name,
        scope: mevcut.data.scope,
        yalniz_ofis: mevcut.data.yalniz_ofis ?? false,
      });
      setSecili(mevcut.data.izinler.map((i) => i.kod));
    } else if (!rolKodu) {
      form.resetFields();
      setSecili([]);
    }
  }, [acik, rolKodu, mevcut.data, form]);

  const tazele = () => {
    void qc.invalidateQueries({ queryKey: ["roller"] });
    void qc.invalidateQueries({ queryKey: ["rol-yetkileri"] });
    void qc.invalidateQueries({ queryKey: ["kullanici-yetkileri"] });
  };
  const kaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      rolKodu ? api.patch(`/api/roller/${rolKodu}`, v) : api.post("/api/roller", v),
    onSuccess: () => {
      message.success(
        rolKodu
          ? `Rol güncellendi${kullaniciSayisi ? ` (${kullaniciSayisi} kullanıcı etkilendi)` : ""}`
          : "Rol oluşturuldu",
      );
      tazele();
      onKapat();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  const varsayilan = useMutation({
    mutationFn: () => api.post(`/api/roller/${rolKodu}/varsayilan`, { version: mevcut.data?.version }),
    onSuccess: () => {
      message.success("Rol varsayılan sayfa ve izinlerine döndü");
      tazele();
      onKapat();
    },
    onError: (e: Error) => void message.error(e.message),
  });
  const izinSayfalari = new Map((katalog.data ?? []).map((i) => [i.kod, i.sayfalar ?? []]));
  const acilanSayfalar = [...new Set(secili.flatMap((k) => izinSayfalari.get(k) ?? []))].sort((a, b) =>
    a.localeCompare(b, "tr"),
  );

  const modulller = new Map<string, Izin[]>();
  for (const i of katalog.data ?? []) {
    modulller.set(i.modul, [...(modulller.get(i.modul) ?? []), i]);
  }

  return (
    <Modal
      open={acik}
      title={rolKodu ? `${mevcut.data?.name ?? rolKodu} — rolü düzenle` : "Yeni rol"}
      okText="Kaydet"
      cancelText="Vazgeç"
      width={720}
      confirmLoading={kaydet.isPending}
      onCancel={onKapat}
      footer={(_, { OkBtn, CancelBtn }) => (
        <>
          {rolKodu && mevcut.data?.varsayilana_donebilir && (
            <Button
              style={{ float: "left" }}
              disabled={!mevcut.data.ozellestirildi}
              loading={varsayilan.isPending}
              onClick={() => varsayilan.mutate()}
              title={mevcut.data.ozellestirildi ? undefined : "Rol zaten varsayılan izinlerinde"}
            >
              Varsayılana dön
            </Button>
          )}
          <CancelBtn />
          <OkBtn />
        </>
      )}
      onOk={() =>
        form.validateFields().then((v) =>
          kaydet.mutate(
            rolKodu
              ? {
                  name: v.name,
                  scope: v.scope,
                  yalniz_ofis: !!v.yalniz_ofis,
                  izinler: secili,
                  version: mevcut.data?.version,
                }
              : {
                  code: v.code,
                  name: v.name,
                  scope: v.scope,
                  yalniz_ofis: !!v.yalniz_ofis,
                  izinler: secili,
                },
          ),
        )
      }
    >
      {rolKodu && kullaniciSayisi ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title={`Bu rolde ${kullaniciSayisi} kullanıcı var`}
          description="Değişiklik hepsini etkiler ve açık oturumları düşürür. Tek bir kişi için istisna gerekiyorsa kullanıcı kartındaki 'İzin istisnaları' bölümünü kullanın."
        />
      ) : null}

      <Form form={form} layout="vertical">
        {!rolKodu && (
          <Form.Item
            name="code"
            label="Rol kodu"
            rules={[
              { required: true, message: "Kod girin" },
              {
                pattern: /^[A-Z][A-Z0-9_]*$/,
                message: "BÜYÜK HARF, rakam ve alt çizgi (ör. BOLGE_MUDURU)",
              },
            ]}
            extra="Değiştirilemez — yetki kontrolleri bu koda bakar."
          >
            <Input placeholder="BOLGE_MUDURU" />
          </Form.Item>
        )}
        <Form.Item name="name" label="Rol adı" rules={[{ required: true }]}>
          <Input placeholder="Bölge Müdürü" />
        </Form.Item>
        <Form.Item
          name="yalniz_ofis"
          valuePropName="checked"
          extra="İşaretliyse bu roldeki kullanıcılar yalnız Parametreler'deki ofis ağından girer ve işlem yapar (liste boşsa kısıt yok)."
        >
          <Checkbox>Yalnız ofis ağından erişim</Checkbox>
        </Form.Item>
        <Form.Item
          name="scope"
          label="Kayıt kapsamı"
          initialValue="TUMU"
          extra={
            kapsamAciklamasi
              ? `${kapsamAciklamasi.aciklama}.${
                  kapsamAciklamasi.birim_zorunlu
                    ? " Bu roldeki kullanıcıya en az bir birim verilmelidir."
                    : ""
                }`
              : undefined
          }
        >
          <Select
            loading={kapsamlar.isLoading}
            options={(kapsamlar.data?.kapsamlar ?? []).map((k) => ({ value: k.kod, label: k.ad }))}
          />
        </Form.Item>
      </Form>

      <Typography.Text strong style={{ fontSize: 12 }}>
        Erişebileceği sayfalar ({acilanSayfalar.length})
      </Typography.Text>
      <div style={{ margin: "6px 0 12px", display: "flex", flexWrap: "wrap", gap: 4 }}>
        {acilanSayfalar.length ? (
          acilanSayfalar.map((s) => <Tag key={s}>{s}</Tag>)
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Sayfa yok — aşağıdan izin seçin.
          </Typography.Text>
        )}
      </div>
      <Typography.Text strong style={{ fontSize: 12 }}>
        İzin verilen aksiyonlar ({secili.length} seçili)
      </Typography.Text>
      <div style={{ maxHeight: 340, overflowY: "auto", marginTop: 8 }}>
        {[...modulller.entries()].map(([modul, izinler]) => (
          <div key={modul} style={{ marginBottom: 10 }}>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {modul}
            </Typography.Text>
            {izinler.map((i) => (
              <div key={i.kod}>
                <Checkbox
                  checked={secili.includes(i.kod)}
                  onChange={(e) =>
                    setSecili((o) =>
                      e.target.checked ? [...o, i.kod] : o.filter((k) => k !== i.kod),
                    )
                  }
                >
                  <span style={{ fontSize: 12 }}>{i.aciklama}</span>{" "}
                  <Typography.Text type="secondary" className="mono" style={{ fontSize: 10 }}>
                    {i.kod}
                  </Typography.Text>
                  {i.hassas && (
                    <Tooltip title="Kişisel veri, ücret/maliyet ya da sistem yönetimi: bilerek verin">
                      <Tag color="red" style={{ marginLeft: 6, fontSize: 10 }}>
                        hassas
                      </Tag>
                    </Tooltip>
                  )}
                  {(i.sayfalar ?? []).length > 0 && (
                    <Typography.Text type="secondary" style={{ fontSize: 10, marginLeft: 6 }}>
                      → {(i.sayfalar ?? []).join(", ")}
                    </Typography.Text>
                  )}
                </Checkbox>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Modal>
  );
}
