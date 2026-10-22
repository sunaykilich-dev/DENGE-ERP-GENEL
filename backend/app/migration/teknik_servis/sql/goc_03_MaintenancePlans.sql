/*
  Göç-1 dışa aktarım — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT (TS-170…177, plan §5.3)
  Canlı SQL Server'a BAĞLANILMAZ: .bak yedeği ayrı bir test örneğine geri yüklenir,
  bu dosya orada disa_aktar.ps1 ile koşulur. Çıktı: <Tablo>.csv (UTF-8).
  Tarih/saat ISO 8601 (CONVERT 126, yerel saat — hazırlama UTC'ye çevirir),
  seri no METİN (CAST NVARCHAR). Kaynağa yazma komutu YOKTUR (test denetler).
*/
SET NOCOUNT ON;
SELECT MaintenancePlanId, MaintenanceContractId, PlanYear, SequenceNo,
       CONVERT(NVARCHAR(10), TargetDate, 23) AS TargetDate, CAST(IsCompleted AS INT) AS IsCompleted,
       CONVERT(NVARCHAR(19), CompletedAt, 126) AS CompletedAt, GeneratedWorkOrderId
FROM dbo.MaintenancePlans
ORDER BY MaintenancePlanId;