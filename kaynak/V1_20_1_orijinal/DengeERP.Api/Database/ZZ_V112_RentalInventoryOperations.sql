-- V1.12 - Kiralama çoklu ürün, çoklu irtibat, depolar, envanter ve süreç geçmişi.
-- Tekrar çalıştırılabilir; mevcut kiralamaları ve kullanıcı verilerini silmez.
IF OBJECT_ID('dbo.RentalOrderItems','U') IS NULL
BEGIN
  CREATE TABLE dbo.RentalOrderItems(
    RentalOrderItemId BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    RentalOrderId BIGINT NOT NULL REFERENCES dbo.RentalOrders(RentalOrderId),
    RentalProductId INT NOT NULL REFERENCES dbo.RentalProducts(RentalProductId),
    Quantity INT NOT NULL CHECK(Quantity>0),
    SerialNumbers NVARCHAR(MAX) NULL,
    Notes NVARCHAR(1000) NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
  );
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_RentalOrderItems_Rental' AND object_id=OBJECT_ID('dbo.RentalOrderItems'))
  CREATE INDEX IX_RentalOrderItems_Rental ON dbo.RentalOrderItems(RentalOrderId);
GO
IF OBJECT_ID('dbo.RentalOrderContacts','U') IS NULL
BEGIN
  CREATE TABLE dbo.RentalOrderContacts(
    RentalOrderContactId BIGINT IDENTITY(1,1) PRIMARY KEY,
    RentalOrderId BIGINT NOT NULL REFERENCES dbo.RentalOrders(RentalOrderId),
    ContactType NVARCHAR(60) NOT NULL DEFAULT N'Saha Operasyon',
    FullName NVARCHAR(180) NOT NULL,
    JobTitle NVARCHAR(180) NULL,
    Phone NVARCHAR(80) NULL,
    Email NVARCHAR(250) NULL,
    Notes NVARCHAR(500) NULL
  );
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_RentalOrderContacts_Rental' AND object_id=OBJECT_ID('dbo.RentalOrderContacts'))
  CREATE INDEX IX_RentalOrderContacts_Rental ON dbo.RentalOrderContacts(RentalOrderId);
GO
IF OBJECT_ID('dbo.RentalWarehouses','U') IS NULL
BEGIN
 CREATE TABLE dbo.RentalWarehouses(
  RentalWarehouseId INT IDENTITY(1,1) PRIMARY KEY,
  Code NVARCHAR(50) NOT NULL UNIQUE,
  Name NVARCHAR(120) NOT NULL,
  IsActive BIT NOT NULL DEFAULT 1
 );
END
GO
MERGE dbo.RentalWarehouses AS target
USING (VALUES (N'DEPO-1',N'Depo 1'),(N'DEPO-2',N'Depo 2'),(N'DEPO-3',N'Depo 3')) AS source(Code,Name)
ON target.Code=source.Code
WHEN NOT MATCHED THEN INSERT(Code,Name) VALUES(source.Code,source.Name);
GO
IF OBJECT_ID('dbo.RentalInventory','U') IS NULL
BEGIN
 CREATE TABLE dbo.RentalInventory(
  RentalInventoryId BIGINT IDENTITY(1,1) PRIMARY KEY,
  RentalProductId INT NOT NULL REFERENCES dbo.RentalProducts(RentalProductId),
  RentalWarehouseId INT NOT NULL REFERENCES dbo.RentalWarehouses(RentalWarehouseId),
  SerialNo NVARCHAR(200) NULL,
  Quantity INT NOT NULL DEFAULT 1 CHECK(Quantity>0),
  ConditionStatus NVARCHAR(40) NOT NULL DEFAULT N'Hazır',
  MissingNotes NVARCHAR(1500) NULL,
  Notes NVARCHAR(1500) NULL,
  RentalOrderItemId BIGINT NULL REFERENCES dbo.RentalOrderItems(RentalOrderItemId),
  UpdatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
 );
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_RentalInventory_ProductSerial' AND object_id=OBJECT_ID('dbo.RentalInventory'))
  CREATE UNIQUE INDEX UX_RentalInventory_ProductSerial ON dbo.RentalInventory(RentalProductId,SerialNo) WHERE SerialNo IS NOT NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_RentalInventory_Warehouse_Status' AND object_id=OBJECT_ID('dbo.RentalInventory'))
  CREATE INDEX IX_RentalInventory_Warehouse_Status ON dbo.RentalInventory(RentalWarehouseId,ConditionStatus,RentalProductId);
GO
IF OBJECT_ID('dbo.RentalStageHistory','U') IS NULL
BEGIN
 CREATE TABLE dbo.RentalStageHistory(
  RentalStageHistoryId BIGINT IDENTITY(1,1) PRIMARY KEY,
  RentalOrderId BIGINT NOT NULL REFERENCES dbo.RentalOrders(RentalOrderId),
  StageName NVARCHAR(80) NOT NULL,
  EventAt DATETIME2 NOT NULL,
  TeamName NVARCHAR(200) NULL,
  RentalWarehouseId INT NULL REFERENCES dbo.RentalWarehouses(RentalWarehouseId),
  Notes NVARCHAR(1500) NULL,
  SerialSnapshot NVARCHAR(MAX) NULL,
  CreatedByUserId INT NULL REFERENCES dbo.ErpUsers(UserId),
  CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
 );
END
GO
IF COL_LENGTH('dbo.RentalStageHistory','SerialSnapshot') IS NULL
  ALTER TABLE dbo.RentalStageHistory ADD SerialSnapshot NVARCHAR(MAX) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_RentalStageHistory_Order' AND object_id=OBJECT_ID('dbo.RentalStageHistory'))
  CREATE INDEX IX_RentalStageHistory_Order ON dbo.RentalStageHistory(RentalOrderId,EventAt,RentalStageHistoryId);
GO
-- Eski tek ürünlü kiralamaları ilk kalem olarak koru (çift kayıt açma).
INSERT INTO dbo.RentalOrderItems(RentalOrderId,RentalProductId,Quantity,SerialNumbers)
SELECT r.RentalOrderId,r.RentalProductId,r.Quantity,r.SerialNumbers
FROM dbo.RentalOrders r
WHERE r.RentalProductId IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dbo.RentalOrderItems i WHERE i.RentalOrderId=r.RentalOrderId);
GO
-- Eski irtibatı da kayıpsız yeni ilişki tablosuna taşı.
INSERT INTO dbo.RentalOrderContacts(RentalOrderId,ContactType,FullName,Phone)
SELECT r.RentalOrderId,N'Saha Operasyon',r.ContactName,r.ContactPhone
FROM dbo.RentalOrders r
WHERE NULLIF(LTRIM(RTRIM(r.ContactName)),N'') IS NOT NULL
AND NOT EXISTS(SELECT 1 FROM dbo.RentalOrderContacts c WHERE c.RentalOrderId=r.RentalOrderId);
GO
