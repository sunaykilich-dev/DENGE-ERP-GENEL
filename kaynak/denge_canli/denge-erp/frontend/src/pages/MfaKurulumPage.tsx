import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";

/**
 * İki adımlı doğrulama kurulumu — zorunluysa uygulamanın önünde durur.
 *
 * Parola doğru olsa da kurulum bitene kadar hiçbir uca erişilemiyor
 * (backend: `deps.MFA_MUAF_YOLLAR`). Bu ekran o kapının tek çıkışı, bu yüzden
 * "sonra yaparım" düğmesi YOK; kullanıcı ya kurar ya çıkar.
 */

interface Kayit {
  secret: string;
  qr_svg: string;
}

export default function MfaKurulumPage() {
  const [form] = Form.useForm();
  const { kullanici, cikisYap } = useAuth();
  const [kayit, setKayit] = useState<Kayit | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const [calisiyor, setCalisiyor] = useState(false);

  // StrictMode effect'i geliştirmede iki kez koşuyor; ikinci `enroll` çağrısı
  // aynı kullanıcı satırını yeniden yazdığı için iyimser kilide takılıp 409
  // veriyordu. Sır bir kez üretilir.
  const istendi = useRef(false);
  useEffect(() => {
    if (istendi.current) return;
    istendi.current = true;
    api
      .post<Kayit>("/api/auth/mfa/enroll")
      .then(setKayit)
      .catch((e) => setHata(e.message));
  }, []);

  const onayla = async (kod: string) => {
    setCalisiyor(true);
    setHata(null);
    try {
      await api.post("/api/auth/mfa/confirm", { code: kod });
      // Yetkiler ve menü kullanıcıya göre kuruluyor; en temiz yol yeniden yükleme.
      window.location.reload();
    } catch (e) {
      setHata(e instanceof Error ? e.message : "Kod doğrulanamadı");
    } finally {
      setCalisiyor(false);
    }
  };

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 24 }}>
      <Card style={{ maxWidth: 460, width: "100%" }} title="İki adımlı doğrulama kurulumu">
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            {kullanici?.full_name}, bu kurulumda iki adımlı doğrulama zorunlu. Google
            Authenticator, 1Password ya da benzeri bir uygulamayla aşağıdaki kodu okutun,
            sonra ürettiği 6 haneli kodu girin.
          </Typography.Paragraph>

          {hata && <Alert type="error" showIcon title={hata} />}

          {kayit && (
            <>
              <div style={{ display: "grid", placeItems: "center" }}>
                <img src={kayit.qr_svg} alt="QR kodu" style={{ width: 200, height: 200 }} />
              </div>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
                QR okutamıyorsanız bu anahtarı elle girin:
              </Typography.Paragraph>
              <Typography.Text copyable className="mono" style={{ wordBreak: "break-all" }}>
                {kayit.secret}
              </Typography.Text>
            </>
          )}

          <Form form={form} layout="vertical" onFinish={(v) => onayla(v.code)}>
            <Form.Item
              name="code"
              label="Uygulamadaki 6 haneli kod"
              rules={[{ required: true, message: "Kodu girin" }]}
            >
              {/* Enter kendiliğinden göndermiyordu: kod yazıp Enter'a basan
                  kullanıcı hiçbir şey olmadığını görüyordu. */}
              <Input
                className="mono"
                inputMode="numeric"
                maxLength={10}
                autoFocus
                onPressEnter={() => form.submit()}
              />
            </Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={calisiyor} disabled={!kayit}>
                Doğrula ve bitir
              </Button>
              <Button onClick={() => void cikisYap()}>Çıkış yap</Button>
            </Space>
          </Form>
        </Space>
      </Card>
    </div>
  );
}
