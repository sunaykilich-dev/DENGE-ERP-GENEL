import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { marka } from "../theme";

export default function LoginPage() {
  const { girisYap, mfaDogrula } = useAuth();
  const [hata, setHata] = useState<string | null>(null);
  const [bekleyen, setBekleyen] = useState<string | null>(null);
  const [gonderiliyor, setGonderiliyor] = useState(false);

  async function calistir(fn: () => Promise<void>) {
    setGonderiliyor(true);
    setHata(null);
    try {
      await fn();
    } catch (e) {
      setHata(e instanceof ApiError ? e.message : "Bağlantı kurulamadı");
    } finally {
      setGonderiliyor(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: marka.paper,
      }}
    >
      <Card style={{ width: 380 }} styles={{ body: { padding: 28 } }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <img src="/brand/denge-mobilite.png" alt="Denge Mobilite" style={{ height: 34 }} />
          <Typography.Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0 }}>
            Kurumsal Kaynak Planlama
          </Typography.Paragraph>
        </div>

        {hata && (
          <Alert
            type="error"
            title={hata}
            description="Art arda hatalı girişte hesap kilitlenir; kilitlendiyse yöneticinize başvurun."
            style={{ marginBottom: 16 }}
            showIcon
          />
        )}

        {bekleyen === null ? (
          <Form
            layout="vertical"
            onFinish={(v) =>
              calistir(async () => {
                const sonuc = await girisYap(v.username, v.password);
                if (sonuc.mfa_required) setBekleyen(sonuc.pending_token);
              })
            }
          >
            <Form.Item
              name="username"
              label="Kullanıcı adı"
              rules={[{ required: true, message: "Kullanıcı adı gerekli" }]}
            >
              <Input autoFocus autoComplete="username" />
            </Form.Item>
            <Form.Item
              name="password"
              label="Parola"
              rules={[{ required: true, message: "Parola gerekli" }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={gonderiliyor}>
              Giriş yap
            </Button>
          </Form>
        ) : (
          <Form
            layout="vertical"
            onFinish={(v) => calistir(async () => void (await mfaDogrula(bekleyen, v.code)))}
          >
            <Typography.Paragraph type="secondary">
              Doğrulama uygulamanızdaki 6 haneli kodu girin.
            </Typography.Paragraph>
            <Form.Item name="code" label="Doğrulama kodu" rules={[{ required: true }]}>
              <Input autoFocus inputMode="numeric" maxLength={6} className="mono" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={gonderiliyor}>
              Doğrula
            </Button>
          </Form>
        )}
      </Card>
    </div>
  );
}
