/*
  Göç-2 dışa aktarım (D3-G, TS-205…208) — DengeERP V1.20.1 (SQL Server) — YALNIZ SELECT.
  Canlı SQL Server'a BAĞLANILMAZ: .bak yedeği ayrı bir test örneğine geri yüklenir,
  bu dosya orada disa_aktar.ps1 ile koşulur. Çıktı: <Tablo>.csv (UTF-8).
  Tarih/saat ISO 8601 (CONVERT 126, yerel saat), seri no METİN. Kişisel iletişim
  verisi (telefon, e-posta, adres) ve parola özeti ALINMAZ.
*/
SET NOCOUNT ON;SELECT TrainingPlanId, PersonnelId, CourseId, PlanYear,
       CONVERT(NVARCHAR(10), DueDate, 126) AS DueDate, Status, PersonalGoal,
       CONVERT(NVARCHAR(19), CompletedAt, 126) AS CompletedAt
FROM dbo.TrainingPlans
ORDER BY TrainingPlanId;
