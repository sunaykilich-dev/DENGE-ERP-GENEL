-- V1.11 plan sahasi: sadece yeni nullable kolonlar. Mevcut veri silinmez.
IF COL_LENGTH('dbo.WorkOrderPlans','SiteName') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SiteName NVARCHAR(250) NULL;
GO
IF COL_LENGTH('dbo.WorkOrderPlans','SiteCity') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SiteCity NVARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.WorkOrderPlans','SiteDistrict') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SiteDistrict NVARCHAR(120) NULL;
GO
IF COL_LENGTH('dbo.WorkOrderPlans','SiteAddress') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SiteAddress NVARCHAR(600) NULL;
GO
IF COL_LENGTH('dbo.WorkOrderPlans','SiteArea') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SiteArea NVARCHAR(250) NULL;
GO
IF COL_LENGTH('dbo.WorkOrderPlans','SiteContact') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SiteContact NVARCHAR(180) NULL;
GO
IF COL_LENGTH('dbo.WorkOrderPlans','SitePhone') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SitePhone NVARCHAR(80) NULL;
GO
IF COL_LENGTH('dbo.WorkOrderPlans','SiteDirections') IS NULL
  ALTER TABLE dbo.WorkOrderPlans ADD SiteDirections NVARCHAR(1000) NULL;
GO
