
-- Pilot V1.5: Güvenlik cihaz kütüğü + bakım sözleşmeleri + Haberleşme atölye CRM alanları
IF OBJECT_ID('dbo.SecurityDevices','U') IS NULL
BEGIN
    CREATE TABLE dbo.SecurityDevices
    (
        SecurityDeviceId BIGINT IDENTITY(1,1) PRIMARY KEY,
        SourceKey NVARCHAR(80) NOT NULL UNIQUE,
        SourceRowNo INT NULL,
        DeviceType NVARCHAR(100) NOT NULL,
        Brand NVARCHAR(120) NOT NULL,
        Model NVARCHAR(250) NOT NULL,
        ProductRaw NVARCHAR(500) NULL,
        SerialNo NVARCHAR(200) NULL,
        CustomerName NVARCHAR(250) NULL,
        Location NVARCHAR(250) NULL,
        ContactName NVARCHAR(180) NULL,
        DeliveryDateText NVARCHAR(100) NULL,
        InstallStatus NVARCHAR(100) NULL,
        Notes NVARCHAR(1000) NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        ImportedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_SecurityDevices_Search' AND object_id=OBJECT_ID('dbo.SecurityDevices'))
    CREATE INDEX IX_SecurityDevices_Search ON dbo.SecurityDevices(DeviceType,Brand,Model,SerialNo);
GO

IF OBJECT_ID('dbo.MaintenanceContracts','U') IS NULL
BEGIN
    CREATE TABLE dbo.MaintenanceContracts
    (
        MaintenanceContractId BIGINT IDENTITY(1,1) PRIMARY KEY,
        SourceKey NVARCHAR(80) NOT NULL UNIQUE,
        CustomerName NVARCHAR(250) NOT NULL,
        CurrentAddress NVARCHAR(500) NULL,
        ProductsText NVARCHAR(500) NULL,
        FrequencyText NVARCHAR(100) NULL,
        AnnualFrequency INT NOT NULL DEFAULT 0,
        MaintenanceFeeText NVARCHAR(100) NULL,
        PeriodText NVARCHAR(150) NULL,
        CompletedCount INT NOT NULL DEFAULT 0,
        ContractTotal DECIMAL(18,2) NULL,
        Total2026 DECIMAL(18,2) NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        ImportedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        UpdatedAt DATETIME2 NULL
    );
END
GO

IF OBJECT_ID('dbo.MaintenancePlans','U') IS NULL
BEGIN
    CREATE TABLE dbo.MaintenancePlans
    (
        MaintenancePlanId BIGINT IDENTITY(1,1) PRIMARY KEY,
        MaintenanceContractId BIGINT NOT NULL,
        PlanYear INT NOT NULL,
        SequenceNo INT NOT NULL,
        TargetDate DATE NOT NULL,
        IsCompleted BIT NOT NULL DEFAULT 0,
        CompletedAt DATETIME2 NULL,
        GeneratedWorkOrderId BIGINT NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        CONSTRAINT FK_MaintenancePlans_Contracts FOREIGN KEY (MaintenanceContractId) REFERENCES dbo.MaintenanceContracts(MaintenanceContractId),
        CONSTRAINT FK_MaintenancePlans_WorkOrders FOREIGN KEY (GeneratedWorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId),
        CONSTRAINT UQ_MaintenancePlans UNIQUE(MaintenanceContractId,PlanYear,SequenceNo)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_MaintenancePlans_Due' AND object_id=OBJECT_ID('dbo.MaintenancePlans'))
    CREATE INDEX IX_MaintenancePlans_Due ON dbo.MaintenancePlans(TargetDate,IsCompleted,GeneratedWorkOrderId);
GO

IF OBJECT_ID('dbo.WorkshopTickets','U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkshopTickets
    (
        WorkshopTicketId BIGINT IDENTITY(1,1) PRIMARY KEY,
        WorkshopNo NVARCHAR(50) NOT NULL UNIQUE,
        WorkOrderId BIGINT NULL,
        LogoFormNo NVARCHAR(80) NULL,
        LogoMainServiceNo NVARCHAR(80) NULL,
        CompanyName NVARCHAR(250) NOT NULL,
        CompanyAddress NVARCHAR(500) NULL,
        ContactName NVARCHAR(180) NULL,
        CustomerEmail NVARCHAR(250) NULL,
        CustomerPhone NVARCHAR(100) NULL,
        EntryDate DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        EstimatedFinishDate DATE NULL,
        CompletionDate DATETIME2 NULL,
        IntegrationCompany NVARCHAR(150) NULL,
        ServiceType NVARCHAR(120) NOT NULL,
        Status NVARCHAR(100) NOT NULL DEFAULT N'Yeni Kayıt',
        RepairAmount DECIMAL(18,2) NULL,
        ReceiveType NVARCHAR(120) NULL,
        ReceivedBy NVARCHAR(180) NULL,
        DeliveredBy NVARCHAR(180) NULL,
        DeliveryType NVARCHAR(120) NULL,
        CargoTrackingNo NVARCHAR(150) NULL,
        AssignedTo NVARCHAR(180) NULL,
        Brand NVARCHAR(120) NOT NULL,
        Model NVARCHAR(180) NULL,
        SerialNo NVARCHAR(180) NOT NULL,
        WarrantyStartDate DATE NULL,
        WarrantyEndDate DATE NULL,
        WarrantyStatus NVARCHAR(100) NULL,
        Accessory1 NVARCHAR(120) NULL,
        Accessory2 NVARCHAR(120) NULL,
        Accessory3 NVARCHAR(120) NULL,
        Accessory4 NVARCHAR(120) NULL,
        Accessory5 NVARCHAR(120) NULL,
        ProjectName NVARCHAR(250) NULL,
        Notes NVARCHAR(MAX) NULL,
        CustomerComplaint NVARCHAR(MAX) NULL,
        DeviceCondition NVARCHAR(MAX) NULL,
        RepairInfo NVARCHAR(MAX) NULL,
        CreatedByUserId INT NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        UpdatedAt DATETIME2 NULL,
        CONSTRAINT FK_WorkshopTickets_WorkOrders FOREIGN KEY (WorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId),
        CONSTRAINT FK_WorkshopTickets_ErpUsers FOREIGN KEY (CreatedByUserId) REFERENCES dbo.ErpUsers(UserId)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_WorkshopTickets_Status' AND object_id=OBJECT_ID('dbo.WorkshopTickets'))
    CREATE INDEX IX_WorkshopTickets_Status ON dbo.WorkshopTickets(Status,EntryDate DESC);
GO



MERGE dbo.WorkTypeRules AS t
USING (VALUES
(N'Güvenlik Sistemleri',N'Planlı Bakım',0,1)
) AS s(UnitCode,WorkType,SerialRequiredOnCreate,SerialRequiredOnClose)
ON t.UnitCode=s.UnitCode AND t.WorkType=s.WorkType
WHEN MATCHED THEN UPDATE SET SerialRequiredOnCreate=s.SerialRequiredOnCreate,SerialRequiredOnClose=s.SerialRequiredOnClose,IsActive=1
WHEN NOT MATCHED THEN INSERT(UnitCode,WorkType,SerialRequiredOnCreate,SerialRequiredOnClose)
VALUES(s.UnitCode,s.WorkType,s.SerialRequiredOnCreate,s.SerialRequiredOnClose);
GO

-- Mevcut pilot kullanıcılarına yeni V1.5 modül yetkilerini rol bazında ekle.
UPDATE dbo.ErpUsers
SET Permissions = Permissions + CASE WHEN Permissions=N'' THEN N'' ELSE N'|' END + N'devices.view'
WHERE RoleName IN (N'Üst Yönetim',N'Teknik Servis Müdürü',N'Teknik Servis Müdür Yardımcısı',N'Genel Koordinatör',N'Operasyon Uzmanı',N'Şef',N'Teknisyen')
  AND N'|'+Permissions+N'|' NOT LIKE N'%|devices.view|%';

UPDATE dbo.ErpUsers
SET Permissions = Permissions + CASE WHEN Permissions=N'' THEN N'' ELSE N'|' END + N'maintenance.view'
WHERE RoleName IN (N'Üst Yönetim',N'Teknik Servis Müdürü',N'Teknik Servis Müdür Yardımcısı',N'Genel Koordinatör',N'Operasyon Uzmanı',N'Şef')
  AND N'|'+Permissions+N'|' NOT LIKE N'%|maintenance.view|%';

UPDATE dbo.ErpUsers
SET Permissions = Permissions + CASE WHEN Permissions=N'' THEN N'' ELSE N'|' END + N'maintenance.manage'
WHERE RoleName IN (N'Üst Yönetim',N'Teknik Servis Müdürü',N'Teknik Servis Müdür Yardımcısı',N'Şef')
  AND N'|'+Permissions+N'|' NOT LIKE N'%|maintenance.manage|%';

UPDATE dbo.ErpUsers
SET Permissions = Permissions + CASE WHEN Permissions=N'' THEN N'' ELSE N'|' END + N'workshop.view'
WHERE RoleName IN (N'Üst Yönetim',N'Teknik Servis Müdürü',N'Teknik Servis Müdür Yardımcısı',N'Genel Koordinatör',N'Operasyon Uzmanı',N'Şef',N'Teknisyen')
  AND N'|'+Permissions+N'|' NOT LIKE N'%|workshop.view|%';

UPDATE dbo.ErpUsers
SET Permissions = Permissions + CASE WHEN Permissions=N'' THEN N'' ELSE N'|' END + N'workshop.manage'
WHERE RoleName IN (N'Üst Yönetim',N'Teknik Servis Müdürü',N'Teknik Servis Müdür Yardımcısı',N'Şef',N'Teknisyen')
  AND N'|'+Permissions+N'|' NOT LIKE N'%|workshop.manage|%';
GO
