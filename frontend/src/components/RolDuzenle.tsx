import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Checkbox, Form, Input, Modal, Select, Typography } from "antd";
import { useEffect, useState } from "react";

import { api } from "../api/client";

interface Izin {
  kod: string;
  modul: string;
  aciklama: string;
}

interface Yetki {
  code: string;
  name: string;
  scope: string;
  izinler: Izin[];
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

  useEffect(() => {
    if (!acik) return;
    if (rolKodu && mevcut.data) {
      form.setFieldsValue({ name: mevcut.data.name, scope: mevcut.data.scope });
      setSecili(mevcut.data.izinler.map((i) => i.kod));
    } else if (!rolKodu) {
      form.resetFields();
      setSecili([]);
    }
  }, [acik, rolKodu, mevcut.data, form]);

  const kaydet = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      rolKodu ? api.patch(`/api/roller/${rolKodu}`, v) : api.post("/api/roller", v),
    onSuccess: () => {
      message.success(rolKodu ? "Rol güncellendi" : "Rol oluşturuldu");
      void qc.invalidateQueries({ queryKey: ["roller"] });
      void qc.invalidateQueries({ queryKey: ["rol-yetkileri"] });
      onKapat();
    },
    onError: (e: Error) => message.error(e.message),
  });

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
      width={640}
      confirmLoading={kaydet.isPending}
      onCancel={onKapat}
      onOk={() =>
        form.validateFields().then((v) =>
          kaydet.mutate(
            rolKodu
              ? { name: v.name, scope: v.scope, izinler: secili }
              : { code: v.code, name: v.name, scope: v.scope, izinler: secili },
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
          name="scope"
          label="Kayıt kapsamı"
          initialValue="TUMU"
          extra="'Yalnız kendi müşterileri' seçilirse kullanıcı, temsilcisi olmadığı hesapları ve onlara bağlı araç, cihaz, iş emrini göremez."
        >
          <Select
            options={[
              { value: "TUMU", label: "Tüm kayıtlar" },
              { value: "KENDI_MUSTERILERI", label: "Yalnız kendi müşterileri" },
            ]}
          />
        </Form.Item>
      </Form>

      <Typography.Text strong style={{ fontSize: 12 }}>
        İzinler ({secili.length} seçili)
      </Typography.Text>
      <div style={{ maxHeight: 300, overflowY: "auto", marginTop: 8 }}>
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
                </Checkbox>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Modal>
  );
}
