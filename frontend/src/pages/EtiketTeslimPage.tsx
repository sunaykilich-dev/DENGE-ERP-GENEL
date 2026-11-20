/**
 * Karekodla teslim (KARARLAR 2026-11-20 §3): cihazın etiketi telefonla
 * okutulunca açılan sayfa. Cihaz ve bulunduğu kiralama görünür; gidişte
 * müşteriye, dönüşte depoya "teslim alındı" bir dokunuşla kapatılır.
 * Giriş gerekir (oturum yoksa giriş sayfasına yönlenir, sonra buraya döner).
 */
import { CheckCircleOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Descriptions, Input, Result, Space, Spin } from "antd";
import dayjs from "dayjs";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { kiralamaApi } from "../api/kiralama";
import { useAuth } from "../auth/AuthContext";

const BUYUK = { height: 56, fontSize: 18 } as const;

export default function EtiketTeslimPage() {
  const { kod = "" } = useParams();
  const { yetkili } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [not, setNot] = useState("");
  const etiket = useQuery({ queryKey: ["etiket", kod], queryFn: () => kiralamaApi.etiket(kod), retry: false });
  const teslim = useMutation({
    mutationFn: (yon: "GIDIS" | "DONUS") => kiralamaApi.etiketTeslim(kod, yon, not.trim() || undefined),
    onSuccess: (v) => {
      qc.setQueryData(["etiket", kod], v);
      message.success("Teslim kaydedildi");
      setNot("");
    },
    onError: (e: Error) => message.error(e.message),
  });

  if (etiket.isLoading) return <Spin style={{ display: "block", margin: 48 }} />;
  if (etiket.isError || !etiket.data)
    return <Result status="404" title="Etiket bulunamadı" subTitle={(etiket.error as Error | null)?.message} />;
  const e = etiket.data;
  const okutabilir = yetkili("kiralama.asama") && e.kiralama != null;
  const zaman = (x: string | null) => (x ? dayjs(x).format("DD.MM.YYYY HH:mm") : null);

  return (
    <Space orientation="vertical" style={{ width: "100%", maxWidth: 520, margin: "0 auto", padding: 12 }}>
      <Card title={e.urun || "Kiralık cihaz"}>
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="Seri no">
            <span className="mono">{e.seri}</span>
          </Descriptions.Item>
          <Descriptions.Item label="Kiralama">
            {e.kiralama ? <Link to={`/kiralamalar/${e.kiralama.id}`}>{e.kiralama.rental_no}</Link> : "Depoda / kirada değil"}
          </Descriptions.Item>
          <Descriptions.Item label="Gidiş teslimi">{zaman(e.gidis_teslim_at) ?? "Okutulmadı"}</Descriptions.Item>
          <Descriptions.Item label="Dönüş teslimi">{zaman(e.donus_teslim_at) ?? "Okutulmadı"}</Descriptions.Item>
        </Descriptions>
      </Card>
      {!e.kiralama && <Alert type="info" showIcon title="Cihaz sevk edilmiş bir kiralamada değil; teslim okutulamaz." />}
      {okutabilir && (
        <Card>
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Input placeholder="Not (isteğe bağlı)" maxLength={300} value={not} onChange={(x) => setNot(x.target.value)} />
            <Button
              block
              type="primary"
              style={BUYUK}
              icon={<CheckCircleOutlined />}
              disabled={!!e.gidis_teslim_at}
              loading={teslim.isPending && teslim.variables === "GIDIS"}
              onClick={() => teslim.mutate("GIDIS")}
            >
              Gidişte teslim alındı
            </Button>
            <Button
              block
              style={BUYUK}
              icon={<CheckCircleOutlined />}
              disabled={!!e.donus_teslim_at}
              loading={teslim.isPending && teslim.variables === "DONUS"}
              onClick={() => teslim.mutate("DONUS")}
            >
              Dönüşte teslim alındı
            </Button>
          </Space>
        </Card>
      )}
    </Space>
  );
}
