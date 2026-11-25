/**
 * Aksesuar kutucukları — atölye kabulü ve servis işi cihaz kartı ortak
 * (2026-11-24/25 sahip istekleri). Türler sunucudan (`aksesuar_turleri`).
 */
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Checkbox, Input, InputNumber, Space } from "antd";

import type { AksesuarGirdisi } from "../api/atolye";

/**
 * Aksesuar kutucukları (cihaz başına): işaretlenen türün yanında adet;
 * "Diğer" serbest metinle birden fazla eklenebilir. Boş "Diğer" satırı
 * gönderilmez (`aksesuarTemizle`).
 */
export function AksesuarSecici({
  turler,
  value,
  onChange,
}: {
  turler: { kod: string; ad: string }[];
  value?: AksesuarGirdisi[];
  onChange?: (v: AksesuarGirdisi[]) => void;
}) {
  const liste = value ?? [];
  const standart = turler.filter((t) => t.kod !== "DIGER");
  const sira = new Map(standart.map((t, i) => [t.kod, i]));
  const digerler = liste.filter((a) => a.kind === "DIGER");
  const secili = liste.filter((a) => a.kind !== "DIGER");
  const yaz = (yeniSecili: AksesuarGirdisi[], yeniDiger: AksesuarGirdisi[]) =>
    onChange?.([
      ...yeniSecili.sort((a, b) => (sira.get(a.kind) ?? 99) - (sira.get(b.kind) ?? 99)),
      ...yeniDiger,
    ]);
  const adet = (kod: string) => secili.find((a) => a.kind === kod)?.qty;
  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 4px" }}>
        {standart.map((t) => {
          const q = adet(t.kod);
          return (
            <span key={t.kod} style={{ display: "inline-flex", alignItems: "center", gap: 4, minWidth: 168 }}>
              <Checkbox
                checked={q !== undefined}
                onChange={(e) =>
                  yaz(
                    e.target.checked
                      ? [...secili, { kind: t.kod, qty: 1 }]
                      : secili.filter((a) => a.kind !== t.kod),
                    digerler,
                  )
                }
              >
                {t.ad}
              </Checkbox>
              {q !== undefined && (
                <InputNumber
                  size="small"
                  min={1}
                  max={99}
                  value={q}
                  aria-label={`${t.ad} adedi`}
                  style={{ width: 56 }}
                  onChange={(n) =>
                    yaz(
                      secili.map((a) => (a.kind === t.kod ? { ...a, qty: Number(n) || 1 } : a)),
                      digerler,
                    )
                  }
                />
              )}
            </span>
          );
        })}
      </div>
      {digerler.map((d, i) => (
        <Space key={i} size={4} style={{ marginTop: 6 }}>
          <Input
            size="small"
            maxLength={120}
            placeholder="Diğer aksesuar (ör. bel çantası)"
            value={d.description ?? ""}
            style={{ width: 260 }}
            onChange={(e) =>
              yaz(
                secili,
                digerler.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)),
              )
            }
          />
          <InputNumber
            size="small"
            min={1}
            max={99}
            value={d.qty}
            aria-label="Adet"
            style={{ width: 56 }}
            onChange={(n) =>
              yaz(
                secili,
                digerler.map((x, j) => (j === i ? { ...x, qty: Number(n) || 1 } : x)),
              )
            }
          />
          <Button
            size="small"
            type="text"
            danger
            icon={<DeleteOutlined />}
            aria-label="Diğer aksesuarı sil"
            onClick={() => yaz(secili, digerler.filter((_, j) => j !== i))}
          />
        </Space>
      ))}
      <div style={{ marginTop: 6 }}>
        <Button
          size="small"
          type="dashed"
          icon={<PlusOutlined />}
          onClick={() => yaz(secili, [...digerler, { kind: "DIGER", qty: 1, description: "" }])}
        >
          Diğer aksesuar
        </Button>
      </div>
    </div>
  );
}

/** Gönderilecek aksesuarlar: boş "Diğer" atılır, açıklama kırpılır. */
export function aksesuarTemizle(liste?: AksesuarGirdisi[]): AksesuarGirdisi[] {
  return (liste ?? [])
    .map((a) => ({ kind: a.kind, qty: a.qty, description: a.description?.trim() || null }))
    .filter((a) => a.kind !== "DIGER" || !!a.description);
}

