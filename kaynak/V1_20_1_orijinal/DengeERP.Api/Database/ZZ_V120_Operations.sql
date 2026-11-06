-- V1.20: idempotent additive SQL, no existing workorder modifications.
IF OBJECT_ID('dbo.OpsSlaTargets','U') IS NULL
 CREATE TABLE dbo.OpsSlaTargets(Priority NVARCHAR(50) PRIMARY KEY,ResolutionHours INT NOT NULL CHECK(ResolutionHours BETWEEN 1 AND 8760));
GO
MERGE dbo.OpsSlaTargets AS t USING(VALUES(N'Kritik',12),(N'Yüksek',24),(N'Normal',72),(N'Düşük',120))s(Priority,ResolutionHours)
 ON t.Priority=s.Priority WHEN NOT MATCHED THEN INSERT(Priority,ResolutionHours) VALUES(s.Priority,s.ResolutionHours);
GO
IF OBJECT_ID('dbo.OpsHolds','U') IS NULL
 CREATE TABLE dbo.OpsHolds(HoldId BIGINT IDENTITY PRIMARY KEY,WorkOrderId BIGINT NOT NULL REFERENCES dbo.WorkOrders(WorkOrderId),Reason NVARCHAR(100) NOT NULL,Notes NVARCHAR(1000) NULL,PreviousStatus NVARCHAR(100) NOT NULL,CreatedBy INT NOT NULL REFERENCES dbo.ErpUsers(UserId),CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),ReleasedAt DATETIME2 NULL);
GO
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.OpsHolds') AND name='UX_OpsHolds_Open')
 CREATE UNIQUE INDEX UX_OpsHolds_Open ON dbo.OpsHolds(WorkOrderId) WHERE ReleasedAt IS NULL;
GO
IF OBJECT_ID('dbo.OpsAlertAcks','U') IS NULL
 CREATE TABLE dbo.OpsAlertAcks(AlertKey NVARCHAR(120) NOT NULL,UserId INT NOT NULL REFERENCES dbo.ErpUsers(UserId),AckAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),CONSTRAINT PK_OpsAlertAcks PRIMARY KEY(AlertKey,UserId));
GO
IF OBJECT_ID('dbo.ServicePartCatalog','U') IS NULL
 CREATE TABLE dbo.ServicePartCatalog(PartId INT IDENTITY PRIMARY KEY,Code NVARCHAR(80) NOT NULL UNIQUE,Name NVARCHAR(200) NOT NULL,Unit NVARCHAR(20) NOT NULL DEFAULT N'Adet',MinimumQty DECIMAL(18,3) NOT NULL DEFAULT 0 CHECK(MinimumQty>=0),UnitCost DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK(UnitCost>=0));
GO
IF OBJECT_ID('dbo.ServiceStockBalances','U') IS NULL
 CREATE TABLE dbo.ServiceStockBalances(PartId INT NOT NULL REFERENCES dbo.ServicePartCatalog(PartId),WarehouseId INT NOT NULL REFERENCES dbo.RentalWarehouses(RentalWarehouseId),Quantity DECIMAL(18,3) NOT NULL DEFAULT 0 CHECK(Quantity>=0),CONSTRAINT PK_ServiceStockBalances PRIMARY KEY(PartId,WarehouseId));
GO
IF OBJECT_ID('dbo.ServicePartMovements','U') IS NULL
 CREATE TABLE dbo.ServicePartMovements(MovementId BIGINT IDENTITY PRIMARY KEY,PartId INT NOT NULL REFERENCES dbo.ServicePartCatalog(PartId),WarehouseId INT NOT NULL REFERENCES dbo.RentalWarehouses(RentalWarehouseId),WorkOrderId BIGINT NULL REFERENCES dbo.WorkOrders(WorkOrderId),Kind NVARCHAR(10) NOT NULL CHECK(Kind IN(N'Giriş',N'Çıkış')),Quantity DECIMAL(18,3) NOT NULL CHECK(Quantity>0),UnitCost DECIMAL(18,2) NOT NULL,CreatedBy INT NOT NULL REFERENCES dbo.ErpUsers(UserId),CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME());
GO
IF OBJECT_ID('dbo.OpsLaborRates','U') IS NULL
 CREATE TABLE dbo.OpsLaborRates(UnitCode NVARCHAR(100) PRIMARY KEY,HourlyCost DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK(HourlyCost>=0));
GO
MERGE dbo.OpsLaborRates AS t USING(VALUES(N'Güvenlik Sistemleri'),(N'Haberleşme'),(N'POC'),(N'Mobilite'),(N'Araç Takip'))s(UnitCode)
 ON t.UnitCode=s.UnitCode WHEN NOT MATCHED THEN INSERT(UnitCode,HourlyCost) VALUES(s.UnitCode,0);
GO
IF OBJECT_ID('dbo.OpsWorkFinancials','U') IS NULL
 CREATE TABLE dbo.OpsWorkFinancials(WorkOrderId BIGINT PRIMARY KEY REFERENCES dbo.WorkOrders(WorkOrderId),Revenue DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK(Revenue>=0),OtherCost DECIMAL(18,2) NOT NULL DEFAULT 0 CHECK(OtherCost>=0),Notes NVARCHAR(1000) NULL,UpdatedBy INT NOT NULL REFERENCES dbo.ErpUsers(UserId),UpdatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME());
GO
