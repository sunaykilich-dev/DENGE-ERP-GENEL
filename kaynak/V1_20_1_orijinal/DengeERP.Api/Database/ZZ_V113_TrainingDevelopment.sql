-- DengeERP V1.13 | Egitim, yetkinlik ve saha gelisim yonetimi.
-- Yalnizca yeni tablolar / tekrar calistirilabilir tohum veriler. Mevcut kayitlari SILMEZ.
IF OBJECT_ID(N'dbo.TrainingCourses',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TrainingCourses (
    CourseId INT IDENTITY(1,1) PRIMARY KEY,
    CourseCode NVARCHAR(50) NOT NULL UNIQUE,
    Title NVARCHAR(220) NOT NULL,
    Category NVARCHAR(80) NOT NULL,
    UnitCode NVARCHAR(100) NULL,
    Reason NVARCHAR(1200) NULL,
    TargetBehavior NVARCHAR(1200) NULL,
    SuccessMetric NVARCHAR(800) NULL,
    DurationHours DECIMAL(5,2) NOT NULL CONSTRAINT DF_TrainingCourse_Duration DEFAULT (2),
    Mandatory BIT NOT NULL CONSTRAINT DF_TrainingCourse_Mandatory DEFAULT (0),
    IsActive BIT NOT NULL CONSTRAINT DF_TrainingCourse_Active DEFAULT (1),
    CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_TrainingCourse_Created DEFAULT SYSDATETIME()
  );
END
GO
IF OBJECT_ID(N'dbo.TrainingCriteria',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TrainingCriteria (
    CriterionId INT IDENTITY(1,1) PRIMARY KEY,
    CourseId INT NOT NULL REFERENCES dbo.TrainingCourses(CourseId),
    CriterionText NVARCHAR(450) NOT NULL,
    IsCritical BIT NOT NULL CONSTRAINT DF_TrainingCriteria_Critical DEFAULT (0),
    SortOrder INT NOT NULL CONSTRAINT DF_TrainingCriteria_Sort DEFAULT(0)
  );
  CREATE INDEX IX_TrainingCriteria_Course ON dbo.TrainingCriteria(CourseId,SortOrder);
END
GO
IF OBJECT_ID(N'dbo.TrainingPlans',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TrainingPlans (
    TrainingPlanId BIGINT IDENTITY(1,1) PRIMARY KEY,
    PersonnelId BIGINT NOT NULL REFERENCES dbo.Personnel(PersonnelId),
    CourseId INT NOT NULL REFERENCES dbo.TrainingCourses(CourseId),
    PlanYear INT NOT NULL CHECK(PlanYear BETWEEN 2020 AND 2100),
    DueDate DATE NOT NULL,
    Status NVARCHAR(30) NOT NULL CONSTRAINT DF_TrainingPlans_Status DEFAULT N'Planlandı',
    PersonalGoal NVARCHAR(900) NULL,
    CompletedAt DATETIME2 NULL,
    CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_TrainingPlans_Created DEFAULT SYSDATETIME(),
    CONSTRAINT UQ_TrainingPlans_Year UNIQUE(PersonnelId,CourseId,PlanYear)
  );
  CREATE INDEX IX_TrainingPlans_Year ON dbo.TrainingPlans(PlanYear,DueDate,Status);
END
GO
IF OBJECT_ID(N'dbo.TrainingSessions',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TrainingSessions (
    TrainingSessionId BIGINT IDENTITY(1,1) PRIMARY KEY,
    CourseId INT NOT NULL REFERENCES dbo.TrainingCourses(CourseId),
    SessionDate DATE NOT NULL,
    TrainerName NVARCHAR(180) NOT NULL,
    DurationHours DECIMAL(5,2) NOT NULL CHECK(DurationHours>0 AND DurationHours<=24),
    Location NVARCHAR(250) NULL,
    Notes NVARCHAR(1200) NULL,
    CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_TrainingSessions_Created DEFAULT SYSDATETIME()
  );
END
GO
IF OBJECT_ID(N'dbo.TrainingAttendance',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TrainingAttendance (
    TrainingAttendanceId BIGINT IDENTITY(1,1) PRIMARY KEY,
    TrainingSessionId BIGINT NOT NULL REFERENCES dbo.TrainingSessions(TrainingSessionId),
    PersonnelId BIGINT NOT NULL REFERENCES dbo.Personnel(PersonnelId),
    Attended BIT NOT NULL,
    ScoreBefore INT NULL CHECK(ScoreBefore BETWEEN 0 AND 100),
    ScoreAfter INT NULL CHECK(ScoreAfter BETWEEN 0 AND 100),
    Notes NVARCHAR(900) NULL,
    CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_TrainingAttendance_Created DEFAULT SYSDATETIME(),
    CONSTRAINT UQ_TrainingAttendance_Person UNIQUE(TrainingSessionId,PersonnelId)
  );
END
GO
IF OBJECT_ID(N'dbo.CompetencyCatalog',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.CompetencyCatalog (
    CompetencyId INT IDENTITY(1,1) PRIMARY KEY,
    Code NVARCHAR(60) NOT NULL UNIQUE,
    Name NVARCHAR(220) NOT NULL,
    UnitCode NVARCHAR(100) NULL,
    SuggestedTargetLevel INT NOT NULL DEFAULT(3) CHECK(SuggestedTargetLevel BETWEEN 1 AND 4),
    IsCritical BIT NOT NULL DEFAULT(0)
  );
END
GO
IF OBJECT_ID(N'dbo.PersonnelCompetencies',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.PersonnelCompetencies (
    PersonnelCompetencyId BIGINT IDENTITY(1,1) PRIMARY KEY,
    PersonnelId BIGINT NOT NULL REFERENCES dbo.Personnel(PersonnelId),
    CompetencyId INT NOT NULL REFERENCES dbo.CompetencyCatalog(CompetencyId),
    CurrentLevel INT NOT NULL CHECK(CurrentLevel BETWEEN 1 AND 4),
    TargetLevel INT NOT NULL CHECK(TargetLevel BETWEEN 1 AND 4),
    AssessedAt DATE NOT NULL,
    AssessedBy NVARCHAR(180) NOT NULL,
    Evidence NVARCHAR(1200) NULL,
    NextReviewDate DATE NULL,
    UpdatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    CONSTRAINT UQ_PersonnelCompetencies UNIQUE(PersonnelId,CompetencyId)
  );
END
GO
IF OBJECT_ID(N'dbo.TrainingObservations',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TrainingObservations (
    ObservationId BIGINT IDENTITY(1,1) PRIMARY KEY,
    PersonnelId BIGINT NOT NULL REFERENCES dbo.Personnel(PersonnelId),
    CourseId INT NOT NULL REFERENCES dbo.TrainingCourses(CourseId),
    WorkOrderId BIGINT NULL REFERENCES dbo.WorkOrders(WorkOrderId),
    ObservedOn DATE NOT NULL,
    ObserverName NVARCHAR(180) NOT NULL,
    PhaseDays INT NOT NULL CHECK(PhaseDays IN(0,30,60,90)),
    Score DECIMAL(5,2) NOT NULL,
    CriticalFailure BIT NOT NULL DEFAULT(0),
    Notes NVARCHAR(1600) NULL,
    ActionPlan NVARCHAR(1600) NULL,
    NextReviewDate DATE NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT SYSDATETIME()
  );
  CREATE INDEX IX_TrainingObservations_Person ON dbo.TrainingObservations(PersonnelId,ObservedOn DESC);
END
GO
IF OBJECT_ID(N'dbo.TrainingObservationRatings',N'U') IS NULL
BEGIN
  CREATE TABLE dbo.TrainingObservationRatings (
    ObservationId BIGINT NOT NULL REFERENCES dbo.TrainingObservations(ObservationId),
    CriterionId INT NOT NULL REFERENCES dbo.TrainingCriteria(CriterionId),
    Rating INT NOT NULL CHECK(Rating IN (-1,0,1,2)),
    PRIMARY KEY (ObservationId,CriterionId)
  );
END
GO
-- Ornek egitim katalogu: plan atamasi otomatik yapilmaz, yonetici secer.
INSERT INTO dbo.TrainingCourses(CourseCode,Title,Category,UnitCode,Reason,TargetBehavior,SuccessMetric,DurationHours,Mandatory)
SELECT s.Code,s.Title,s.Category,s.UnitCode,s.Reason,s.Behavior,s.Metric,s.Hours,s.Mandatory
FROM (VALUES
(N'ISG-SAH-01',N'Sahada İSG ve Güvenli Çalışma',N'İSG',CAST(NULL AS NVARCHAR(100)),N'Koruyucu ekipman ve güvenli çalışma adımlarındaki farklı uygulamaları azaltmak',N'Sahaya çıkmadan riskleri, KKD ve güvenli kaldırma uygulamalarını kontrol etmek',N'Saha gözleminde kritik İSG uygunsuzluğunun sıfırlanması',CAST(3 AS DECIMAL(5,2)),CAST(1 AS BIT)),
(N'ILET-01',N'Müşteri İletişimi ve Servis Raporu',N'Kişisel Gelişim',CAST(NULL AS NVARCHAR(100)),N'Müşteri bilgilendirmesini ve servis kayıtlarını standartlaştırmak',N'Arıza nedenini, yapılan işlemi ve sonraki adımı anlaşılır biçimde kaydetmek',N'Örneklenen servis kayıtlarında en az %90 uygunluk',CAST(2 AS DECIMAL(5,2)),CAST(0 AS BIT)),
(N'XR-BAK-01',N'X-Ray Periyodik Bakım ve Arıza Analizi',N'Teknik',N'Güvenlik Sistemleri',N'X-Ray bakım ve arıza teşhisinde standart uygulama oluşturmak',N'Güvenlik talimatlarıyla kontrol, test ve raporu bağımsız yürütmek',N'90. gün uygulamalı gözlemde en az %85 uygunluk',CAST(5 AS DECIMAL(5,2)),CAST(0 AS BIT)),
(N'KMD-BAK-01',N'Kapı Dedektörü Test ve Kalibrasyon',N'Teknik',N'Güvenlik Sistemleri',N'Kapı tipi metal dedektörlerinin kontrol ve testlerini standartlaştırmak',N'Doğru test, hassasiyet doğrulama ve kayıt oluşturmak',N'90. gün uygulamalı gözlemde en az %85 uygunluk',CAST(4 AS DECIMAL(5,2)),CAST(0 AS BIT)),
(N'TELSIZ-01',N'Telsiz ve Röle Arıza Teşhisi',N'Teknik',N'Haberleşme',N'Telsiz/röle arızalarında tekrar servis oranını azaltmak',N'Ölçüm, programlama, test ve raporlama adımlarını tamamlamak',N'İlk müdahalede doğru arıza teşhisi ve dokümantasyonun artması',CAST(5 AS DECIMAL(5,2)),CAST(0 AS BIT)),
(N'POC-01',N'POC Uzaktan Destek ve Müşteri Çözüm Süreci',N'Teknik',N'POC',N'Telefon ve uzaktan destek süreçlerindeki farklılığı azaltmak',N'Kayıt açma, doğrulama, çözüm ve kapatma adımlarını izlemek',N'Rastgele örneklenen destek kayıtlarında %90 uygunluk',CAST(3 AS DECIMAL(5,2)),CAST(0 AS BIT)),
(N'MOB-01',N'Mobilite ve Araç Takip Saha Kontrolleri',N'Teknik',N'Mobilite',N'Saha kurulum ve test kalitesini yükseltmek',N'Kurulum, bağlantı, fonksiyon testi ve kayıtları standartlaştırmak',N'90. gün gözleminde %85 üzeri uygunluk',CAST(4 AS DECIMAL(5,2)),CAST(0 AS BIT))
) AS s(Code,Title,Category,UnitCode,Reason,Behavior,Metric,Hours,Mandatory)
WHERE NOT EXISTS (SELECT 1 FROM dbo.TrainingCourses x WHERE x.CourseCode=s.Code);
GO
-- Her kursa ilgili saha gözlem maddelerini bir defa ekle.
INSERT INTO dbo.TrainingCriteria(CourseId,CriterionText,IsCritical,SortOrder)
SELECT c.CourseId, v.Text, v.Critical, v.SortOrder
FROM (VALUES
(N'ISG-SAH-01',N'KKD ve uygun iş ayakkabısını kontrol etti',1,1),
(N'ISG-SAH-01',N'Çalışma alanı ve çevre risklerini değerlendirdi',1,2),
(N'ISG-SAH-01',N'Ekipmanı güvenli kaldırma/taşıma uyguladı',1,3),
(N'ISG-SAH-01',N'Uygunsuzlukları ilgili kişiye bildirdi',0,4),
(N'ILET-01',N'Müşteriye kendini ve işin kapsamını açıkladı',0,1),
(N'ILET-01',N'Arıza ve işlem sonucunu anlaşılır şekilde aktardı',0,2),
(N'ILET-01',N'İş emrine yapılan işlemleri eksiksiz kaydetti',0,3),
(N'ILET-01',N'Sonraki adımı ve müşteriden beklentiyi belirtti',0,4),
(N'XR-BAK-01',N'Cihaz etiketini ve seri numarasını doğruladı',0,1),
(N'XR-BAK-01',N'Güvenli enerji kesme ve X-Ray güvenlik prosedürünü uyguladı',1,2),
(N'XR-BAK-01',N'Bant, sensör ve emniyet sistemlerini kontrol etti',1,3),
(N'XR-BAK-01',N'Fonksiyon testini ve test sonuçlarını kayıt altına aldı',0,4),
(N'XR-BAK-01',N'Servis raporunu eksiksiz tamamladı',0,5),
(N'KMD-BAK-01',N'Cihaz konumu ve seri numarasını doğruladı',0,1),
(N'KMD-BAK-01',N'Güvenli saha ve enerji kontrolünü yaptı',1,2),
(N'KMD-BAK-01',N'Test nesnesiyle tüm bölgeleri kontrol etti',0,3),
(N'KMD-BAK-01',N'Kalibrasyon ve alarm sonuçlarını kaydetti',0,4),
(N'KMD-BAK-01',N'Müşteriye sonucu bildirdi',0,5),
(N'TELSIZ-01',N'Radyo ve röle kimlik/seri numarasını kontrol etti',0,1),
(N'TELSIZ-01',N'Frekans ve ilgili prosedürlere uygunluğunu doğruladı',1,2),
(N'TELSIZ-01',N'Ölçüm ile arızayı sistematik teşhis etti',0,3),
(N'TELSIZ-01',N'Görüşme/kapsama ve fonksiyon testini kaydetti',0,4),
(N'POC-01',N'Talebi ve müşteri bilgilerini doğruladı',0,1),
(N'POC-01',N'Uzaktan müdahale için gerekli onayı aldı',1,2),
(N'POC-01',N'Çözüm adımlarını ve sonucu kaydetti',0,3),
(N'MOB-01',N'Montaj ve kablo güvenliğini kontrol etti',1,1),
(N'MOB-01',N'Cihazın bağlantı ve seri bilgisini doğruladı',0,2),
(N'MOB-01',N'Konum/telemetri testini yaptı',0,3),
(N'MOB-01',N'Kurulum sonucunu ve saha notunu kaydetti',0,4)
) v(Code,Text,Critical,SortOrder)
JOIN dbo.TrainingCourses c ON c.CourseCode=v.Code
WHERE NOT EXISTS (SELECT 1 FROM dbo.TrainingCriteria tc WHERE tc.CourseId=c.CourseId AND tc.SortOrder=v.SortOrder);
GO
INSERT INTO dbo.CompetencyCatalog(Code,Name,UnitCode,SuggestedTargetLevel,IsCritical)
SELECT v.Code,v.Name,v.UnitCode,v.Target,v.Critical
FROM (VALUES
(N'ISG',N'İSG ve sahada güvenli çalışma',CAST(NULL AS NVARCHAR(100)),4,CAST(1 AS BIT)),
(N'RAPOR',N'Servis raporu ve kayıt disiplini',CAST(NULL AS NVARCHAR(100)),4,CAST(0 AS BIT)),
(N'ILETISIM',N'Müşteri iletişimi',CAST(NULL AS NVARCHAR(100)),3,CAST(0 AS BIT)),
(N'XR',N'X-Ray arıza teşhisi ve bakımı',N'Güvenlik Sistemleri',3,CAST(1 AS BIT)),
(N'KAPI',N'Kapı dedektörü test ve kalibrasyonu',N'Güvenlik Sistemleri',3,CAST(0 AS BIT)),
(N'RADYO',N'Telsiz ve röle arıza teşhisi',N'Haberleşme',3,CAST(0 AS BIT)),
(N'POC',N'POC uzaktan destek',N'POC',3,CAST(0 AS BIT)),
(N'MOB',N'Araç takip / mobilite kurulumu',N'Mobilite',3,CAST(0 AS BIT))
) v(Code,Name,UnitCode,Target,Critical)
WHERE NOT EXISTS (SELECT 1 FROM dbo.CompetencyCatalog x WHERE x.Code=v.Code);
GO
