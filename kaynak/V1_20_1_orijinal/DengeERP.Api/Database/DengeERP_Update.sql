USE DengeERP;
GO

IF OBJECT_ID('dbo.WorkOrders','U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkOrders
    (
        WorkOrderId BIGINT IDENTITY(1,1) PRIMARY KEY,
        WorkOrderNo NVARCHAR(50) NOT NULL UNIQUE,
        UnitCode NVARCHAR(100) NOT NULL,
        WorkType NVARCHAR(150) NOT NULL,
        CustomerName NVARCHAR(250) NOT NULL,
        ProjectName NVARCHAR(250) NULL,
        Location NVARCHAR(250) NULL,
        Subject NVARCHAR(250) NOT NULL,
        Description NVARCHAR(MAX) NULL,
        Priority NVARCHAR(50) NOT NULL DEFAULT N'Normal',
        Status NVARCHAR(100) NOT NULL DEFAULT N'Müşteri Talebi',
        CreatedByUserId INT NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        RowVersion ROWVERSION
    );
END
GO

IF COL_LENGTH('dbo.WorkOrders','SystemName') IS NULL ALTER TABLE dbo.WorkOrders ADD SystemName NVARCHAR(150) NULL;
IF COL_LENGTH('dbo.WorkOrders','SerialNo') IS NULL ALTER TABLE dbo.WorkOrders ADD SerialNo NVARCHAR(200) NULL;
IF COL_LENGTH('dbo.WorkOrders','CustomerEmail') IS NULL ALTER TABLE dbo.WorkOrders ADD CustomerEmail NVARCHAR(250) NULL;
IF COL_LENGTH('dbo.WorkOrders','UpdatedAt') IS NULL ALTER TABLE dbo.WorkOrders ADD UpdatedAt DATETIME2 NULL;
IF COL_LENGTH('dbo.WorkOrders','ClosedAt') IS NULL ALTER TABLE dbo.WorkOrders ADD ClosedAt DATETIME2 NULL;
GO

IF OBJECT_ID('dbo.WorkOrderAssignments','U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkOrderAssignments
    (
        AssignmentId BIGINT IDENTITY(1,1) PRIMARY KEY,
        WorkOrderId BIGINT NOT NULL,
        AssignedName NVARCHAR(150) NOT NULL,
        AssignmentRole NVARCHAR(50) NOT NULL DEFAULT N'Teknisyen',
        IsActive BIT NOT NULL DEFAULT 1,
        AssignedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        CONSTRAINT FK_WorkOrderAssignments_WorkOrders FOREIGN KEY (WorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId)
    );
END
GO

IF OBJECT_ID('dbo.WorkOrderPlans','U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkOrderPlans
    (
        WorkOrderPlanId BIGINT IDENTITY(1,1) PRIMARY KEY,
        WorkOrderId BIGINT NOT NULL,
        PlanDate DATE NOT NULL,
        StartTime TIME NULL,
        EstimatedMinutes INT NULL,
        VehiclePlate NVARCHAR(30) NULL,
        RouteGroupNo NVARCHAR(50) NULL,
        PlanNote NVARCHAR(1000) NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        PlannedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        CONSTRAINT FK_WorkOrderPlans_WorkOrders FOREIGN KEY (WorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId)
    );
END
GO

IF OBJECT_ID('dbo.WorkOrderDevices','U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkOrderDevices
    (
        WorkOrderDeviceId BIGINT IDENTITY(1,1) PRIMARY KEY,
        WorkOrderId BIGINT NOT NULL,
        SerialNo NVARCHAR(200) NOT NULL,
        ProductName NVARCHAR(200) NULL,
        Brand NVARCHAR(120) NULL,
        Model NVARCHAR(120) NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        AddedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        CONSTRAINT FK_WorkOrderDevices_WorkOrders FOREIGN KEY (WorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId)
    );
END
GO

IF OBJECT_ID('dbo.WorkOrderStatusLogs','U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkOrderStatusLogs
    (
        StatusLogId BIGINT IDENTITY(1,1) PRIMARY KEY,
        WorkOrderId BIGINT NOT NULL,
        OldStatus NVARCHAR(100) NULL,
        NewStatus NVARCHAR(100) NOT NULL,
        Note NVARCHAR(1000) NULL,
        ChangedByUserId INT NULL,
        ChangedByName NVARCHAR(150) NULL,
        ChangedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        CONSTRAINT FK_WorkOrderStatusLogs_WorkOrders FOREIGN KEY (WorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId)
    );
END
GO

IF OBJECT_ID('dbo.WorkTypeRules','U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkTypeRules
    (
        RuleId INT IDENTITY(1,1) PRIMARY KEY,
        UnitCode NVARCHAR(100) NOT NULL,
        WorkType NVARCHAR(150) NOT NULL,
        SerialRequiredOnCreate BIT NOT NULL DEFAULT 0,
        SerialRequiredOnClose BIT NOT NULL DEFAULT 0,
        IsActive BIT NOT NULL DEFAULT 1,
        CONSTRAINT UQ_WorkTypeRules UNIQUE(UnitCode,WorkType)
    );
END
GO

MERGE dbo.WorkTypeRules AS t
USING (VALUES
(N'Güvenlik Sistemleri',N'Atölye Tamir',1,1),
(N'Güvenlik Sistemleri',N'Saha Arızası',0,1),
(N'Güvenlik Sistemleri',N'Saha Kurulumu / Devreye Alma',0,1),
(N'Güvenlik Sistemleri',N'Kontrol / Test',0,1),
(N'Haberleşme',N'Atölye Teknik Servis',1,1),
(N'Haberleşme',N'Saha Arızası',0,1),
(N'Haberleşme',N'Saha Kurulumu',0,1),
(N'Haberleşme',N'Kiralık El Telsizi Hazırlığı',1,1),
(N'Haberleşme',N'Kiradan Dönen El Telsizi Testi',1,1),
(N'Mobilite',N'Kurulum',0,1),
(N'Mobilite',N'Arıza',0,1),
(N'Araç Takip',N'Kurulum',0,1),
(N'Araç Takip',N'Arıza',0,1),
(N'Araç Takip',N'Bakım',0,1),
(N'POC',N'Uzaktan Müdahale',0,0),
(N'POC',N'Telefonla Destek',0,0),
(N'POC',N'Yerinde Müdahale',0,0)
) AS s(UnitCode,WorkType,SerialRequiredOnCreate,SerialRequiredOnClose)
ON t.UnitCode=s.UnitCode AND t.WorkType=s.WorkType
WHEN MATCHED THEN UPDATE SET SerialRequiredOnCreate=s.SerialRequiredOnCreate,SerialRequiredOnClose=s.SerialRequiredOnClose,IsActive=1
WHEN NOT MATCHED THEN INSERT(UnitCode,WorkType,SerialRequiredOnCreate,SerialRequiredOnClose) VALUES(s.UnitCode,s.WorkType,s.SerialRequiredOnCreate,s.SerialRequiredOnClose);
GO

IF OBJECT_ID('dbo.ErpUsers','U') IS NULL
BEGIN
    CREATE TABLE dbo.ErpUsers
    (
        UserId INT IDENTITY(1,1) PRIMARY KEY,
        Username NVARCHAR(100) NOT NULL UNIQUE,
        PasswordHash NVARCHAR(200) NOT NULL,
        PasswordSalt NVARCHAR(200) NOT NULL,
        FullName NVARCHAR(150) NOT NULL,
        RoleName NVARCHAR(100) NOT NULL,
        AllowedUnits NVARCHAR(MAX) NOT NULL DEFAULT N'',
        Permissions NVARCHAR(MAX) NOT NULL DEFAULT N'',
        IsActive BIT NOT NULL DEFAULT 1,
        MustChangePassword BIT NOT NULL DEFAULT 1,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        UpdatedAt DATETIME2 NULL
    );
END
GO

-- Pilot V1.1: Yeni ERP kullanıcıları ile eski AppUsers ilişkisini birbirinden ayır.
-- Mevcut CreatedByUserId kolonu eski sistemle uyumluluk için korunur ve nullable yapılır.
IF COL_LENGTH('dbo.WorkOrders','CreatedByUserId') IS NOT NULL
BEGIN
    ALTER TABLE dbo.WorkOrders ALTER COLUMN CreatedByUserId INT NULL;
END
GO

IF COL_LENGTH('dbo.WorkOrders','CreatedByErpUserId') IS NULL
BEGIN
    ALTER TABLE dbo.WorkOrders ADD CreatedByErpUserId INT NULL;
END
GO

IF NOT EXISTS
(
    SELECT 1
    FROM sys.foreign_keys
    WHERE name = 'FK_WorkOrders_ErpUsers'
      AND parent_object_id = OBJECT_ID('dbo.WorkOrders')
)
BEGIN
    ALTER TABLE dbo.WorkOrders
    ADD CONSTRAINT FK_WorkOrders_ErpUsers
        FOREIGN KEY (CreatedByErpUserId) REFERENCES dbo.ErpUsers(UserId);
END
GO

IF OBJECT_ID('dbo.Offers','U') IS NULL
BEGIN
    CREATE TABLE dbo.Offers
    (
        OfferId BIGINT IDENTITY(1,1) PRIMARY KEY,
        OfferNo NVARCHAR(50) NOT NULL UNIQUE,
        WorkOrderId BIGINT NULL,
        UnitCode NVARCHAR(100) NOT NULL,
        CustomerName NVARCHAR(250) NOT NULL,
        CustomerEmail NVARCHAR(250) NULL,
        Status NVARCHAR(50) NOT NULL DEFAULT N'Taslak',
        ValidUntil DATE NULL,
        Notes NVARCHAR(1000) NULL,
        SubTotal DECIMAL(18,2) NOT NULL DEFAULT 0,
        DiscountTotal DECIMAL(18,2) NOT NULL DEFAULT 0,
        VatTotal DECIMAL(18,2) NOT NULL DEFAULT 0,
        GrandTotal DECIMAL(18,2) NOT NULL DEFAULT 0,
        CreatedByUserId INT NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        ApprovedByUserId INT NULL,
        ApprovedAt DATETIME2 NULL,
        SentAt DATETIME2 NULL,
        CONSTRAINT FK_Offers_WorkOrders FOREIGN KEY (WorkOrderId) REFERENCES dbo.WorkOrders(WorkOrderId)
    );
END
GO

IF OBJECT_ID('dbo.OfferItems','U') IS NULL
BEGIN
    CREATE TABLE dbo.OfferItems
    (
        OfferItemId BIGINT IDENTITY(1,1) PRIMARY KEY,
        OfferId BIGINT NOT NULL,
        ItemCode NVARCHAR(100) NULL,
        Description NVARCHAR(500) NOT NULL,
        Quantity DECIMAL(18,2) NOT NULL DEFAULT 1,
        UnitPrice DECIMAL(18,2) NOT NULL DEFAULT 0,
        DiscountPercent DECIMAL(9,2) NOT NULL DEFAULT 0,
        VatPercent DECIMAL(9,2) NOT NULL DEFAULT 20,
        CONSTRAINT FK_OfferItems_Offers FOREIGN KEY (OfferId) REFERENCES dbo.Offers(OfferId) ON DELETE CASCADE
    );
END
GO

IF OBJECT_ID('dbo.EmailLogs','U') IS NULL
BEGIN
    CREATE TABLE dbo.EmailLogs
    (
        EmailLogId BIGINT IDENTITY(1,1) PRIMARY KEY,
        OfferId BIGINT NULL,
        Recipient NVARCHAR(250) NOT NULL,
        Subject NVARCHAR(500) NOT NULL,
        Status NVARCHAR(50) NOT NULL,
        ErrorMessage NVARCHAR(1000) NULL,
        SentByUserId INT NULL,
        SentAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        CONSTRAINT FK_EmailLogs_Offers FOREIGN KEY (OfferId) REFERENCES dbo.Offers(OfferId)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_WorkOrders_Unit_Status' AND object_id=OBJECT_ID('dbo.WorkOrders'))
    CREATE INDEX IX_WorkOrders_Unit_Status ON dbo.WorkOrders(UnitCode,Status,CreatedAt DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_WorkOrderAssignments_Active' AND object_id=OBJECT_ID('dbo.WorkOrderAssignments'))
    CREATE INDEX IX_WorkOrderAssignments_Active ON dbo.WorkOrderAssignments(WorkOrderId,IsActive,AssignmentRole);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_WorkOrderPlans_Active' AND object_id=OBJECT_ID('dbo.WorkOrderPlans'))
    CREATE INDEX IX_WorkOrderPlans_Active ON dbo.WorkOrderPlans(WorkOrderId,IsActive);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_WorkOrderDevices_Active' AND object_id=OBJECT_ID('dbo.WorkOrderDevices'))
    CREATE INDEX IX_WorkOrderDevices_Active ON dbo.WorkOrderDevices(WorkOrderId,IsActive);
GO

-- Pilot V1.4: Kiralama + Personel / Organizasyon
IF OBJECT_ID('dbo.RentalProducts','U') IS NULL
BEGIN
    CREATE TABLE dbo.RentalProducts
    (
        RentalProductId INT IDENTITY(1,1) PRIMARY KEY,
        UnitCode NVARCHAR(100) NOT NULL,
        Category NVARCHAR(120) NOT NULL,
        ProductCode NVARCHAR(100) NOT NULL,
        ProductName NVARCHAR(250) NOT NULL,
        RequiresSerial BIT NOT NULL DEFAULT 0,
        IsActive BIT NOT NULL DEFAULT 1,
        DisplayOrder INT NOT NULL DEFAULT 0,
        CONSTRAINT UQ_RentalProducts UNIQUE(UnitCode,ProductCode)
    );
END
GO

MERGE dbo.RentalProducts AS t
USING (VALUES
(N'Güvenlik Sistemleri',N'X-Ray',N'PG-5030',N'PG 5030 X-Ray',1,10),
(N'Güvenlik Sistemleri',N'X-Ray',N'PG-6040',N'PG 6040 X-Ray',1,20),
(N'Güvenlik Sistemleri',N'X-Ray',N'PG-6550',N'PG 6550 X-Ray',1,30),
(N'Güvenlik Sistemleri',N'X-Ray',N'PG-100100',N'PG 100100 X-Ray',1,40),
(N'Güvenlik Sistemleri',N'Kapı Tipi Metal Dedektörü',N'PG-3000-KING',N'PG 3000 King Kapı Tipi Metal Dedektörü',1,50),
(N'Güvenlik Sistemleri',N'Kapı Tipi Metal Dedektörü',N'PG-2000-KING',N'PG 2000 King Kapı Tipi Metal Dedektörü',1,60),
(N'Güvenlik Sistemleri',N'Kapı Tipi Metal Dedektörü',N'PGDH-D118',N'PG&DH D118 Kapı Tipi Metal Dedektörü',1,70),
(N'Güvenlik Sistemleri',N'Akordiyon Bariyer',N'BS-500-2R',N'BS-500-2R Akordiyon Bariyer',0,100),
(N'Güvenlik Sistemleri',N'Akordiyon Bariyer',N'BS-500-4R',N'BS-500-4R Akordiyon Bariyer',0,110),
(N'Güvenlik Sistemleri',N'Akordiyon Bariyer',N'BS-1000',N'BS-1000 Akordiyon Bariyer',0,120),
(N'Güvenlik Sistemleri',N'Akordiyon Bariyer',N'BS-2000',N'BS-2000 Akordiyon Bariyer',0,130),
(N'Güvenlik Sistemleri',N'Şerit / Protokol Bariyer',N'ST-100',N'ST-100 Şerit-Rop Bariyer',0,140),
(N'Güvenlik Sistemleri',N'Şerit / Protokol Bariyer',N'ST-200',N'ST-200 VIP Protokol Bariyer',0,150),
(N'Güvenlik Sistemleri',N'Şerit / Protokol Bariyer',N'ST-210',N'ST-210 Protokol Bariyer',0,160),
(N'Güvenlik Sistemleri',N'Mojo Bariyer',N'ST-10',N'ST-10 Mojo Sahne Önü Bariyer',0,170),
(N'Güvenlik Sistemleri',N'Güvenlik Bariyeri',N'ST-1000',N'ST-1000 Güvenlik Polis Bariyeri',0,180),
(N'Güvenlik Sistemleri',N'Güvenlik Bariyeri',N'ST-3000',N'ST-3000 Çift Katlı NATO Güvenlik Bariyeri',0,190),
(N'Güvenlik Sistemleri',N'Güvenlik Bariyeri',N'ST-4000',N'ST-4000 Çit Bariyer',0,200),
(N'Güvenlik Sistemleri',N'Güvenlik Bariyeri',N'ST-2000',N'ST-2000 Tek Katlı NATO Bariyer',0,210),
(N'Güvenlik Sistemleri',N'Güvenlik Bariyeri',N'ST-5000',N'ST-5000 Bisiklet Bariyeri',0,220),
(N'Haberleşme',N'Telsiz',N'HYT-DMR',N'Hytera Dijital / DMR Telsiz',1,300),
(N'Haberleşme',N'Telsiz',N'HYT-TETRA',N'Hytera TETRA Telsiz',1,310),
(N'Haberleşme',N'Telsiz',N'HYT-LTE-POC',N'Hytera LTE / PoC Telsiz',1,320)
) AS s(UnitCode,Category,ProductCode,ProductName,RequiresSerial,DisplayOrder)
ON t.UnitCode=s.UnitCode AND t.ProductCode=s.ProductCode
WHEN MATCHED THEN UPDATE SET Category=s.Category,ProductName=s.ProductName,RequiresSerial=s.RequiresSerial,IsActive=1,DisplayOrder=s.DisplayOrder
WHEN NOT MATCHED THEN INSERT(UnitCode,Category,ProductCode,ProductName,RequiresSerial,IsActive,DisplayOrder)
VALUES(s.UnitCode,s.Category,s.ProductCode,s.ProductName,s.RequiresSerial,1,s.DisplayOrder);
GO

IF OBJECT_ID('dbo.RentalOrders','U') IS NULL
BEGIN
    CREATE TABLE dbo.RentalOrders
    (
        RentalOrderId BIGINT IDENTITY(1,1) PRIMARY KEY,
        RentalNo NVARCHAR(50) NOT NULL UNIQUE,
        UnitCode NVARCHAR(100) NOT NULL,
        Category NVARCHAR(120) NOT NULL,
        RentalProductId INT NULL,
        ProductCode NVARCHAR(100) NULL,
        ProductName NVARCHAR(250) NOT NULL,
        CustomerName NVARCHAR(250) NOT NULL,
        CustomerEmail NVARCHAR(250) NULL,
        ProjectName NVARCHAR(250) NULL,
        Location NVARCHAR(250) NULL,
        ContactName NVARCHAR(150) NULL,
        ContactPhone NVARCHAR(80) NULL,
        Quantity INT NOT NULL DEFAULT 1,
        SerialNumbers NVARCHAR(MAX) NULL,
        StartDate DATE NOT NULL,
        EndDate DATE NOT NULL,
        Status NVARCHAR(100) NOT NULL DEFAULT N'Talep',
        ResponsibleName NVARCHAR(150) NULL,
        Notes NVARCHAR(1500) NULL,
        CreatedByUserId INT NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        UpdatedAt DATETIME2 NULL,
        ClosedAt DATETIME2 NULL,
        CONSTRAINT FK_RentalOrders_RentalProducts FOREIGN KEY (RentalProductId) REFERENCES dbo.RentalProducts(RentalProductId),
        CONSTRAINT FK_RentalOrders_ErpUsers FOREIGN KEY (CreatedByUserId) REFERENCES dbo.ErpUsers(UserId)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_RentalOrders_Unit_Status' AND object_id=OBJECT_ID('dbo.RentalOrders'))
    CREATE INDEX IX_RentalOrders_Unit_Status ON dbo.RentalOrders(UnitCode,Status,StartDate DESC);
GO

IF OBJECT_ID('dbo.Personnel','U') IS NULL
BEGIN
    CREATE TABLE dbo.Personnel
    (
        PersonnelId BIGINT IDENTITY(1,1) PRIMARY KEY,
        FullName NVARCHAR(180) NOT NULL,
        DepartmentName NVARCHAR(180) NOT NULL,
        AdditionalDepartments NVARCHAR(MAX) NULL,
        Title NVARCHAR(180) NULL,
        UnitCode NVARCHAR(100) NULL,
        ManagerName NVARCHAR(180) NULL,
        StartDate DATE NULL,
        EndDate DATE NULL,
        IsActive BIT NOT NULL DEFAULT 1,
        ErpUserId INT NULL,
        Notes NVARCHAR(1000) NULL,
        CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
        UpdatedAt DATETIME2 NULL,
        CONSTRAINT FK_Personnel_ErpUsers FOREIGN KEY (ErpUserId) REFERENCES dbo.ErpUsers(UserId)
    );
END
GO

-- Organizasyon şeması başlangıç personel listesi. Var olan isimleri tekrar eklemez.
DECLARE @Org TABLE(FullName NVARCHAR(180), DepartmentName NVARCHAR(180), AdditionalDepartments NVARCHAR(MAX), Title NVARCHAR(180), UnitCode NVARCHAR(100), ManagerName NVARCHAR(180));
INSERT INTO @Org VALUES
(N'Nurettin Erzurum',N'Üst Yönetim',NULL,N'Genel Müdür',NULL,NULL),
(N'Neriman Boyacı',N'Üst Yönetim',NULL,N'Genel Müdür Asistanı',NULL,N'Nurettin Erzurum'),
(N'Emre Utku',N'Genel Koordinatörlük',N'Satış Yönetimi',N'Genel Koordinatör',NULL,N'Nurettin Erzurum'),
(N'Nazım Köse',N'Teknik Servis',N'Güvenlik Satış',N'Teknik Servis Yöneticisi',N'Güvenlik Sistemleri',N'Emre Utku'),
(N'Sunay Kılıç',N'Teknik Servis',NULL,N'Teknik Servis Yöneticisi',NULL,N'Emre Utku'),
(N'Beytullah Numan Özdek',N'Depo & Lojistik',NULL,N'Depo ve Lojistik Yöneticisi',NULL,N'Emre Utku'),
(N'Filiz Bigeç',N'Müşteri İlişkileri & Kurumsal İletişim',NULL,N'Kurumsal İletişim ve Müşteri İlişkileri Yöneticisi',NULL,N'Emre Utku'),
(N'Hakan Erdal',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Saha Takım Lideri',N'Güvenlik Sistemleri',N'Nazım Köse'),
(N'Ali Kaya',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Kıdemli Laboratuvar Teknisyeni',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Arda Çiftçi',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Saha Teknisyeni',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Burak Mehmet Şahinbaş',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Saha Teknisyeni',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Ali Güler',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Kıdemli Saha Teknisyeni',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Emirhan Pehlivan',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Saha Teknisyeni',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Özgür Çavdar',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Saha Teknisyeni',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Alperen Kurahmetoğlu',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Stajyer (Lise)',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Bilal Emir Mengü',N'Güvenlik Sistemleri Teknik Servis',NULL,N'Stajyer (Lise)',N'Güvenlik Sistemleri',N'Hakan Erdal'),
(N'Umut Can Yıldırım',N'Güvenlik Satış',NULL,N'Satış Destek Uzmanı',N'Güvenlik Sistemleri',N'Nazım Köse'),
(N'Çağatay Koruç',N'Haberleşme Sistemleri Teknik Servis Yönetimi',N'Haberleşme Sistemleri Satış',N'Haberleşme Satış Yöneticisi',N'Haberleşme',N'Emre Utku'),
(N'Fatma Lale Şahingöz',N'Haberleşme Sistemleri Satış',NULL,N'Kurumsal Satış Uzmanı',N'Haberleşme',N'Çağatay Koruç'),
(N'Seray Eren',N'Haberleşme Sistemleri Satış',NULL,N'Satış Destek Uzmanı',N'Haberleşme',N'Çağatay Koruç'),
(N'Muharrem Ali Şahinbaş',N'Haberleşme Sistemleri Satış',NULL,N'OKTH Uzmanı',N'Haberleşme',N'Çağatay Koruç'),
(N'Samet Alpat',N'Haberleşme Sistemleri Satış',NULL,N'Kurumsal Satış Uzmanı',N'Haberleşme',N'Çağatay Koruç'),
(N'Fatih Bayındır',N'Denge Mobil',NULL,N'Operasyon Destek Uzmanı',N'Mobilite',NULL),
(N'Serkan Doğan',N'Denge Mobil',NULL,N'Operasyon Müdürü',N'Mobilite',NULL),
(N'Güngör Sima Aktüre',N'Denge Mobil',NULL,N'Operasyon Destek Uzmanı',N'Mobilite',N'Serkan Doğan'),
(N'Baran Tefiye',N'Denge Mobil',NULL,N'Operasyon Destek Uzmanı',N'Mobilite',N'Serkan Doğan'),
(N'Ertuğrul Çakır',N'Haberleşme Sistemleri Teknik Servis',NULL,N'Laboratuvar Takım Lideri',N'Haberleşme',N'Çağatay Koruç'),
(N'Mehmet Can Şahin',N'Haberleşme Sistemleri Teknik Servis',NULL,N'Sistem Mühendisi',N'Haberleşme',N'Ertuğrul Çakır'),
(N'Emre Çevre',N'Haberleşme Sistemleri Teknik Servis',NULL,N'Laboratuvar Teknisyeni',N'Haberleşme',N'Ertuğrul Çakır'),
(N'Cem Ülger',N'Haberleşme Sistemleri Teknik Servis',NULL,N'Saha Teknisyeni',N'Haberleşme',N'Ertuğrul Çakır'),
(N'Hazal Çelik',N'Haberleşme Sistemleri Teknik Servis',NULL,N'Teknik Servis Operasyon Uzmanı',N'Haberleşme',N'Ertuğrul Çakır'),
(N'Ramazan Furkan Ermiş',N'Haberleşme Sistemleri Teknik Servis',NULL,N'POC Destek Uzmanı',N'POC',N'Ertuğrul Çakır'),
(N'Batuhan Yıldız',N'Haberleşme Sistemleri Teknik Servis',NULL,N'Kıdemli Saha Teknisyeni',N'Haberleşme',N'Ertuğrul Çakır'),
(N'Ebrar Yayla Almıkarı',N'Haberleşme Sistemleri Teknik Servis',NULL,N'Teknik Servis Operasyon Uzmanı',N'Haberleşme',N'Ertuğrul Çakır'),
(N'Sevgi Çetin',N'İnsan Kaynakları',N'İdari İşler',N'İnsan Kaynakları Yöneticisi',NULL,N'Nurettin Erzurum'),
(N'Ayşegül Aydoğmuş',N'Muhasebe & Finans GMY',N'Kiralama & Satış Yönetimi',N'Genel Müdür Yardımcısı',NULL,N'Nurettin Erzurum'),
(N'Ahmet Erzurum',N'GMY',NULL,N'Genel Müdür Yardımcısı',NULL,N'Nurettin Erzurum'),
(N'Hülya Kaplan',N'İdari İşler',NULL,N'Temizlik ve Servis Görevlisi',NULL,N'Sevgi Çetin'),
(N'Ramazan Dinç',N'İdari İşler',NULL,N'Gece Güvenlik ve Destek Görevlisi',NULL,N'Sevgi Çetin'),
(N'Ayşe Demirkaplan',N'İdari İşler',NULL,N'Danışma ve Santral Görevlisi',NULL,N'Sevgi Çetin'),
(N'Nuri Demir',N'Kiralama & Operasyon Yönetimi',NULL,N'Kiralama Operasyon Personel',N'Güvenlik Sistemleri',N'Ayşegül Aydoğmuş'),
(N'Tekin Uzunalp',N'Kiralama & Operasyon Yönetimi',NULL,N'Kiralama Operasyon Personel',N'Güvenlik Sistemleri',N'Ayşegül Aydoğmuş'),
(N'Daniyar Setdarkulyyev',N'Kiralama & Operasyon Yönetimi',NULL,N'Kiralama Operasyon Personel',N'Güvenlik Sistemleri',N'Ayşegül Aydoğmuş'),
(N'Uysal Aydoğmuş',N'Kiralama & Operasyon Yönetimi',NULL,N'Kiralama Operasyon Personel',N'Güvenlik Sistemleri',N'Ayşegül Aydoğmuş'),
(N'Tuğba Serbest',N'Muhasebe Yönetimi',NULL,N'Muhasebe Yöneticisi',NULL,N'Ayşegül Aydoğmuş'),
(N'Tuğba Gayır',N'Muhasebe Yönetimi',NULL,N'Muhasebe Uzmanı',NULL,N'Tuğba Serbest'),
(N'Canan Güllü',N'Muhasebe Yönetimi',NULL,N'Muhasebe Uzmanı',NULL,N'Tuğba Serbest');

INSERT INTO dbo.Personnel(FullName,DepartmentName,AdditionalDepartments,Title,UnitCode,ManagerName,IsActive)
SELECT o.FullName,o.DepartmentName,o.AdditionalDepartments,o.Title,o.UnitCode,o.ManagerName,1
FROM @Org o
WHERE NOT EXISTS (SELECT 1 FROM dbo.Personnel p WHERE p.FullName=o.FullName);
GO

UPDATE p
SET ErpUserId=u.UserId, UpdatedAt=SYSDATETIME()
FROM dbo.Personnel p
JOIN dbo.ErpUsers u ON u.FullName=p.FullName
WHERE p.ErpUserId IS NULL;
GO
