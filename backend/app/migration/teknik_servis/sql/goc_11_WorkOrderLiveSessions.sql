/*
  Göç-1 dışa aktarım — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT (TS-170…177, plan §5.3)
  Canlı SQL Server'a BAĞLANILMAZ: .bak yedeği ayrı bir test örneğine geri yüklenir,
  bu dosya orada disa_aktar.ps1 ile koşulur. Çıktı: <Tablo>.csv (UTF-8).
  Tarih/saat ISO 8601 (CONVERT 126, yerel saat — hazırlama UTC'ye çevirir),
  seri no METİN (CAST NVARCHAR). Kaynağa yazma komutu YOKTUR (test denetler).
*/
SET NOCOUNT ON;
-- Yalnız TAMAMLANMIŞ mola oturumları: diğer faaliyetler oturum kapanınca
-- WorkOrderTimeLogs'a yazılmıştır (ResultTimeLogId); iki kez sayılmasın.
SELECT SessionId, WorkOrderId, TechnicianName, ActivityType,
       CONVERT(NVARCHAR(19), StartedAt, 126) AS StartedAt,
       CONVERT(NVARCHAR(19), EndedAt, 126) AS EndedAt,
       LocationNote, WorkNote,
       CONVERT(NVARCHAR(19), StartedAt, 126) AS CreatedAt,
       0 AS IsVoided
FROM dbo.WorkOrderLiveSessions
WHERE ActivityType = N'Mola / Ara' AND EndedAt IS NOT NULL
  AND (StopReason IS NULL OR StopReason <> N'İptal')
ORDER BY SessionId;