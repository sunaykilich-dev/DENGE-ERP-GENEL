/**
 * Kiralama tarih çakışması onayı (M10.1, KARARLAR 2026-10-28 §7 Faz A/4).
 *
 * Seri kiralık cihaz başka bir kiralamada aynı tarihlere tahsisliyse sunucu
 * 409 + `kod: "KIRALAMA_CAKISMA"` + çakışan kiralama listesi döner. Bu kanca
 * isteği bir kez dener; çakışma gelirse listeyi gösterip GEREKÇE ister ve
 * isteği `cakisma_onay` + `cakisma_gerekcesi` ile yeniden yollar. Gerekçe
 * sunucuda denetim izine yazılır. Vazgeçilirse hiçbir şey kaydedilmez.
 */
import { Alert, App, Input, List, Space, Typography } from "antd";
import { useCallback } from "react";

import { ApiError } from "../api/client";
import type { CakismaOnayi, KiralamaCakismasi } from "../api/kiralama";

/** Hata kiralama çakışma uyarısıysa çakışma listesi; değilse null. */
export function kiralamaCakismasi(e: unknown): KiralamaCakismasi[] | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const detay = (e.govde as { detail?: unknown } | undefined)?.detail as
    | { kod?: string; cakismalar?: KiralamaCakismasi[] }
    | undefined;
  return detay?.kod === "KIRALAMA_CAKISMA" ? (detay.cakismalar ?? []) : null;
}

export class CakismaVazgecildi extends Error {
  constructor() {
    super("Çakışma onaylanmadı; kayıt yapılmadı.");
  }
}

const tarih = (iso: string) => iso.split("-").reverse().join(".");

export function useCakismaOnayi() {
  const { modal, message } = App.useApp();

  const gerekceIste = useCallback(
    (cakismalar: KiralamaCakismasi[]) =>
      new Promise<string | null>((coz) => {
        let gerekce = "";
        modal.confirm({
          title: "Cihaz bu tarihlerde başka kiralamada",
          width: 560,
          okText: "Gerekçeyle kaydet",
          cancelText: "Vazgeç",
          content: (
            <Space orientation="vertical" style={{ width: "100%" }}>
              <Alert
                type="warning"
                showIcon
                title="Aynı cihaz çakışan tarihlerde iki kiralamaya bağlanacak. Bu bir uyarıdır; gerekçe yazarak devam edebilirsiniz."
              />
              <List
                size="small"
                bordered
                dataSource={cakismalar}
                renderItem={(c) => (
                  <List.Item>
                    <Typography.Text strong>{c.seri_no}</Typography.Text>
                    <span>
                      {c.kiralama_no ?? `#${c.kiralama_id}`} · {tarih(c.baslangic)} – {tarih(c.bitis)}
                    </span>
                  </List.Item>
                )}
              />
              <Input.TextArea
                autoFocus
                rows={3}
                maxLength={500}
                placeholder="Gerekçe (zorunlu) — ör. önceki kiracı erken iade edecek"
                onChange={(e) => {
                  gerekce = e.target.value;
                }}
              />
            </Space>
          ),
          onOk: () => {
            if (!gerekce.trim()) {
              message.warning("Gerekçe yazın");
              return Promise.reject(new Error("gerekçe boş"));
            }
            coz(gerekce.trim());
            return undefined;
          },
          onCancel: () => coz(null),
        });
      }),
    [modal, message],
  );

  /** `f` önce onaysız çağrılır; çakışma uyarısında gerekçe alınıp onayla tekrar çağrılır. */
  return useCallback(
    async <T,>(f: (onay?: CakismaOnayi) => Promise<T>): Promise<T> => {
      try {
        return await f();
      } catch (e) {
        const cakismalar = kiralamaCakismasi(e);
        if (!cakismalar) throw e;
        const gerekce = await gerekceIste(cakismalar);
        if (!gerekce) throw new CakismaVazgecildi();
        return f({ cakisma_onay: true, cakisma_gerekcesi: gerekce });
      }
    },
    [gerekceIste],
  );
}
