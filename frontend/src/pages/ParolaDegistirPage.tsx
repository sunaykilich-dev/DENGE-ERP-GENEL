import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/**
 * Parola değiştirme (TS-212, E13-13).
 *
 * Zorunlu değişimde (`parola_degismeli`: yöneticinin belirlediği/ürettiği
 * geçici parola ya da ilk kurulum parolası) uygulamanın önünde durur — sunucu
 * zaten `/me`, `/logout`, `/parola` dışındaki her ucu 403 `PAROLA_DEGISMELI`
 * ile kapatıyor (`deps.PAROLA_MUAF_YOLLAR`). "Sonra yaparım" düğmesi YOK;
 * kullanıcı ya değiştirir ya çıkar. Geçici parola tek seferliktir: değiştirmeden
 * çıkan kullanıcı aynı parolayla bir daha giremez.
 *
 * Kurallar sunucuda tek yerde (`services/auth.parola_kurali_hatalari`); burada
 * yalnız kullanıcıyı erken uyaran aynı iki kural ve tekrar alanı var.
 */

interface ParolaFormu {
  mevcut: string;
  yeni: string;
  tekrar: string;
}

const PAROLA_ASGARI_UZUNLUK = 10;

export default function ParolaDegistirPage({ zorunlu = true }: { zorunlu?: boolean }) {
  const [form] = Form.useForm<ParolaFormu>();
  const { kullanici, cikisYap } = useAuth();
  const [hata, setHata] = useState<string | null>(null);
  const [calisiyor, setCalisiyor] = useState(false);

  const kaydet = async (v: ParolaFormu) => {
    setCalisiyor(true);
    setHata(null);
    try {
      await api.post("/api/auth/parola", { mevcut: v.mevcut, yeni: v.yeni });
      // Menü ve yetkiler kullanıcıdan kuruluyor; en temiz yol yeniden yükleme
      // (MFA kurulum ekranıyla aynı). Bu oturum açık kalır, diğerleri düştü.
      window.location.reload();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        // Art arda yanlış mevcut parola hesabı kilitledi; oturum düştü.
        window.location.reload();
        return;
      }
      setHata(e instanceof Error ? e.message : "Parola değiştirilemedi");
    } finally {
      setCalisiyor(false);
    }
  };

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: zorunlu ? "100vh" : undefined, padding: 16 }}>
      <Card style={{ maxWidth: 460, width: "100%" }} title="Parola değiştir">
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          {zorunlu && (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              {kullanici?.full_name}, devam etmeden önce kendi parolanızı belirlemelisiniz.
              Yöneticinin verdiği parola geçicidir ve yalnız bu giriş için geçerlidir.
            </Typography.Paragraph>
          )}

          {hata && <Alert type="error" showIcon title={hata} />}

          <Form form={form} layout="vertical" onFinish={(v) => void kaydet(v)}>
            <Form.Item
              name="mevcut"
              label="Mevcut (geçici) parola"
              rules={[{ required: true, message: "Mevcut parolayı girin" }]}
            >
              <Input.Password autoComplete="current-password" autoFocus />
            </Form.Item>
            <Form.Item
              name="yeni"
              label="Yeni parola"
              extra={`En az ${PAROLA_ASGARI_UZUNLUK} karakter; kullanıcı adınızı ya da adınızı içermesin. Uzun bir cümle iyi bir paroladır.`}
              rules={[
                { required: true, message: "Yeni parolayı girin" },
                { min: PAROLA_ASGARI_UZUNLUK, message: `En az ${PAROLA_ASGARI_UZUNLUK} karakter` },
                { max: 200, message: "En çok 200 karakter" },
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Form.Item
              name="tekrar"
              label="Yeni parola (tekrar)"
              dependencies={["yeni"]}
              rules={[
                { required: true, message: "Yeni parolayı tekrar girin" },
                ({ getFieldValue }) => ({
                  validator: (_, deger) =>
                    !deger || deger === getFieldValue("yeni")
                      ? Promise.resolve()
                      : Promise.reject(new Error("İki parola aynı değil")),
                }),
              ]}
            >
              <Input.Password autoComplete="new-password" onPressEnter={() => form.submit()} />
            </Form.Item>
            <Space wrap>
              <Button type="primary" htmlType="submit" loading={calisiyor}>
                Parolayı değiştir
              </Button>
              {zorunlu && <Button onClick={() => void cikisYap()}>Çıkış yap</Button>}
            </Space>
          </Form>
        </Space>
      </Card>
    </div>
  );
}
