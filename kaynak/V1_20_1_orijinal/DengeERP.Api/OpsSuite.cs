using Microsoft.Data.SqlClient;
using System.Globalization;
using System.Text;

// V1.20 Operations: additional API endpoints, existing V1.14 API untouched.
internal static class OpsSuite
{
  private static bool Open(string s)=>s is not ("Kapatıldı" or "Tamamlandı" or "İptal");
  private static bool Maint(WorkOrderRow w)=>w.WorkOrderNo.StartsWith("PB-")||w.WorkType=="Planlı Bakım";
  private static object P(string? s)=>string.IsNullOrWhiteSpace(s)?DBNull.Value:s.Trim();
  private static async Task<SqlConnection> Db(string c){var db=new SqlConnection(c);await db.OpenAsync();return db;}
  private sealed record Alert(string Key,string Severity,string Message,long? WorkOrderId);
  private static async Task<Dictionary<string,int>> Targets(string conn)
  {
    var t=new Dictionary<string,int>(StringComparer.OrdinalIgnoreCase);
    await using var db=await Db(conn);using var cmd=new SqlCommand("SELECT Priority,ResolutionHours FROM dbo.OpsSlaTargets",db);
    await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())t[r.GetString(0)]=r.GetInt32(1);
    return t;
  }
  private static async Task<Dictionary<long,string>> Holds(string conn)
  {
    var h=new Dictionary<long,string>();await using var db=await Db(conn);
    using var cmd=new SqlCommand("SELECT WorkOrderId,Reason FROM dbo.OpsHolds WHERE ReleasedAt IS NULL",db);
    await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())h[r.GetInt64(0)]=r.GetString(1);return h;
  }
  private static List<Alert> Alerts(List<WorkOrderRow> rows,Dictionary<string,int> sla,Dictionary<long,string> holds)
  {
    var a=new List<Alert>();var now=DateTime.Now;
    foreach(var w in rows.Where(x=>Open(x.Status)))
    {
      var t=w.CreatedAt.AddHours(sla.GetValueOrDefault(w.Priority,72));
      if(t<now)a.Add(new($"sla:{w.WorkOrderId}:{now:yyyyMMdd}","Kritik",$"Geciken: {w.WorkOrderNo} • {w.CustomerName}",w.WorkOrderId));
      if(w.PlanDate==DateOnly.FromDateTime(now.AddDays(1)))a.Add(new($"plan:{w.WorkOrderId}:{now:yyyyMMdd}","Bilgi",$"Yarın: {w.WorkOrderNo} • {w.CustomerName}",w.WorkOrderId));
      if(holds.TryGetValue(w.WorkOrderId,out var reason))a.Add(new($"hold:{w.WorkOrderId}:{now:yyyyMMdd}","Uyarı",$"Beklemede: {w.WorkOrderNo} • {reason}",w.WorkOrderId));
    }
    return a;
  }
  private static async Task<List<Alert>> AuxiliaryAlerts(string conn,SessionUser u,Func<SessionUser,string,bool> can,
    Func<SessionUser,string,bool> unitAllowed)
  {
    var list=new List<Alert>();await using var db=await Db(conn);
    if(can(u,"warehouse.view"))
    {
      using var cmd=new SqlCommand(@"SELECT p.PartId,p.Code,p.MinimumQty,COALESCE(SUM(b.Quantity),0)
FROM dbo.ServicePartCatalog p LEFT JOIN dbo.ServiceStockBalances b ON b.PartId=p.PartId
WHERE p.MinimumQty>0 GROUP BY p.PartId,p.Code,p.MinimumQty HAVING COALESCE(SUM(b.Quantity),0)<p.MinimumQty",db);
      await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())list.Add(new(
        $"stock:{r.GetInt32(0)}:{DateTime.Today:yyyyMMdd}","Uyarı",$"Düşük stok: {r.GetString(1)} ({r.GetValue(3)} / {r.GetValue(2)})",null));
    }
    if(can(u,"training.view"))
    {
      using var cmd=new SqlCommand(@"SELECT TOP(40) p.TrainingPlanId,c.Title,s.FullName,p.DueDate,COALESCE(s.UnitCode,N'')
FROM dbo.TrainingPlans p JOIN dbo.TrainingCourses c ON p.CourseId=c.CourseId
JOIN dbo.Personnel s ON p.PersonnelId=s.PersonnelId
WHERE p.Status<>N'Tamamlandı' AND p.DueDate<=DATEADD(DAY,7,CAST(GETDATE() AS DATE)) ORDER BY p.DueDate",db);
      await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())
      {
        string unit=r.GetString(4);
        if(!string.IsNullOrWhiteSpace(unit)&&!unitAllowed(u,unit))continue;
        list.Add(new($"train:{r.GetInt64(0)}:{DateTime.Today:yyyyMMdd}","Bilgi",
          $"Eğitim tarihi: {r.GetString(2)} / {r.GetString(1)} ({r.GetDateTime(3):dd.MM.yyyy})",null));
      }
    }
    return list.Take(80).ToList();
  }
  private static string Csv(params object?[] fields)=>string.Join(";",fields.Select(x=>{
    var v=Convert.ToString(x,CultureInfo.InvariantCulture)??"";
    if(v.Length>0&&"=+-@\t\r".Contains(v[0]))v="'"+v;
    return "\""+v.Replace("\"","\"\"")+"\"";
  }));
  public static void Map(WebApplication app,string conn,Func<HttpContext,SessionUser?> current,
    Func<SessionUser,string,bool> can,Func<SessionUser,string,bool> unitAllowed,
    Func<Task<List<WorkOrderRow>>> loadOrders, Func<List<WorkOrderRow>,SessionUser,List<WorkOrderRow>> filterOrders,
    Func<Task<List<TimeLogRow>>> loadLogs)
  {
    app.MapGet("/api/ops/overview",async(HttpContext ctx,int? days)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();
      if(!can(u,"dashboard.view"))return Results.Forbid();
      var n=Math.Clamp(days??30,1,366);var rows=filterOrders(await loadOrders(),u);
      var targets=await Targets(conn);var holds=await Holds(conn);
      var logs=await loadLogs();var minutes=logs.GroupBy(x=>x.WorkOrderId).ToDictionary(x=>x.Key,x=>x.Sum(y=>y.Minutes));
      var eligible=rows.Where(w=>w.CreatedAt>=DateTime.Now.AddDays(-n)||Open(w.Status)).ToList();
      var data=eligible.Select(w=>new{ id=w.WorkOrderId,no=w.WorkOrderNo,unit=w.UnitCode,type=w.WorkType,
        customer=w.CustomerName,location=w.Location,city=w.SiteCity,subject=w.Subject,priority=w.Priority,status=w.Status,
        createdAt=w.CreatedAt,closedAt=w.ClosedAt,planDate=w.PlanDate,assigned=w.AssignedStaff,chief=w.ChiefName,
        isMaintenance=Maint(w),overdue=Open(w.Status)&&DateTime.Now>w.CreatedAt.AddHours(targets.GetValueOrDefault(w.Priority,72)),
        holdReason=holds.GetValueOrDefault(w.WorkOrderId),recordedMinutes=minutes.GetValueOrDefault(w.WorkOrderId,0)}).ToList();
      var person=eligible.SelectMany(w=>(w.AssignedStaff??"").Split(',',StringSplitOptions.TrimEntries|StringSplitOptions.RemoveEmptyEntries)
        .Select(p=>new{name=p,order=w})).GroupBy(x=>x.name,StringComparer.OrdinalIgnoreCase)
        .Select(g=>new{name=g.Key,total=g.Count(),open=g.Count(x=>Open(x.order.Status)),closed=g.Count(x=>!Open(x.order.Status))})
        .OrderByDescending(x=>x.open).ToList();
      var repeat=eligible.Where(w=>!Maint(w)).SelectMany(w=>(w.SerialNumbers??"").Split(',',StringSplitOptions.TrimEntries|StringSplitOptions.RemoveEmptyEntries)
        .Select(serial=>new{serial,order=w})).GroupBy(x=>x.serial,StringComparer.OrdinalIgnoreCase)
        .Where(g=>g.Count()>1).Select(g=>new{serialNo=g.Key,count=g.Count(),orders=g.Select(x=>x.order.WorkOrderNo).Take(8)})
        .OrderByDescending(x=>x.count).Take(25).ToList();
      var alerts=Alerts(rows,targets,holds);
      alerts.AddRange(await AuxiliaryAlerts(conn,u,can,unitAllowed));
      var seen=await Acks(conn,u.UserId);
      return Results.Ok(new{
        generatedAt=DateTime.Now,
        counters=new{open=data.Count(x=>Open(x.status)),overdue=data.Count(x=>x.overdue),service=data.Count(x=>!x.isMaintenance),
          maintenance=data.Count(x=>x.isMaintenance),today=data.Count(x=>x.planDate==DateOnly.FromDateTime(DateTime.Today)),
          tomorrow=data.Count(x=>x.planDate==DateOnly.FromDateTime(DateTime.Today.AddDays(1))),
          hold=data.Count(x=>x.holdReason is not null),closed=data.Count(x=>!Open(x.status))},
        orders=data.OrderByDescending(x=>x.overdue).ThenByDescending(x=>x.createdAt).Take(1500),
        personnel=person,repeats=repeat,alerts=alerts.Where(x=>!seen.Contains(x.Key)).Take(100),
        sla=targets.Select(x=>new{priority=x.Key,hours=x.Value}).OrderBy(x=>x.hours)
      });
    });
    app.MapPost("/api/ops/alerts/ack",async(HttpContext ctx,AckRequest req)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();if(!can(u,"dashboard.view"))return Results.Forbid();
      var rows=filterOrders(await loadOrders(),u);var alarms=Alerts(rows,await Targets(conn),await Holds(conn));
      alarms.AddRange(await AuxiliaryAlerts(conn,u,can,unitAllowed));
      if(!alarms.Any(x=>x.Key==req.Key))return Results.NotFound();
      await using var db=await Db(conn);using var cmd=new SqlCommand(@"IF NOT EXISTS(SELECT 1 FROM dbo.OpsAlertAcks WHERE AlertKey=@Key AND UserId=@User)
INSERT INTO dbo.OpsAlertAcks(AlertKey,UserId) VALUES(@Key,@User)",db);
      cmd.Parameters.AddWithValue("@Key",req.Key);cmd.Parameters.AddWithValue("@User",u.UserId);await cmd.ExecuteNonQueryAsync();
      return Results.Ok(new{message="Uyarı görüldü olarak işaretlendi."});
    });
    app.MapPut("/api/ops/sla/{priority}",async(HttpContext ctx,string priority,SlaRequest req)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();if(!can(u,"operations.manage"))return Results.Forbid();
      if(req.Hours<1||req.Hours>8760)return Results.BadRequest(new{message="Geçerli bir saat hedefi girin."});
      await using var db=await Db(conn);using var cmd=new SqlCommand("UPDATE dbo.OpsSlaTargets SET ResolutionHours=@Hours WHERE Priority=@Priority",db);
      cmd.Parameters.AddWithValue("@Hours",req.Hours);cmd.Parameters.AddWithValue("@Priority",priority);
      return await cmd.ExecuteNonQueryAsync()==0?Results.NotFound():Results.Ok(new{message="SLA güncellendi."});
    });
    app.MapPost("/api/ops/workorders/{id:long}/hold",async(HttpContext ctx,long id,HoldRequest req)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();
      if(!can(u,"operations.manage")&&!can(u,"workorders.edit"))return Results.Forbid();
      if(string.IsNullOrWhiteSpace(req.Reason)||req.Reason.Length>100||req.Notes?.Length>1000)return Results.BadRequest(new{message="Neden/not kontrol edin."});
      var w=filterOrders(await loadOrders(),u).FirstOrDefault(w=>w.WorkOrderId==id);
      if(w is null)return Results.NotFound();if(!Open(w.Status))return Results.BadRequest(new{message="Kapalı iş bekletilemez."});
      await using var db=await Db(conn);await using var tx=(SqlTransaction)await db.BeginTransactionAsync();
      using(var cmd=new SqlCommand(@"INSERT dbo.OpsHolds(WorkOrderId,Reason,Notes,PreviousStatus,CreatedBy)
VALUES(@Id,@Reason,@Notes,@Previous,@User);
UPDATE dbo.WorkOrders SET Status=N'Beklemede',UpdatedAt=SYSDATETIME() WHERE WorkOrderId=@Id;",db,tx)){
        cmd.Parameters.AddWithValue("@Id",id);cmd.Parameters.AddWithValue("@Reason",req.Reason);
        cmd.Parameters.AddWithValue("@Notes",P(req.Notes));cmd.Parameters.AddWithValue("@Previous",w.Status);
        cmd.Parameters.AddWithValue("@User",u.UserId);await cmd.ExecuteNonQueryAsync();}
      await tx.CommitAsync();return Results.Ok(new{message="Bekleme kaydedildi."});
    });
    app.MapPost("/api/ops/workorders/{id:long}/release",async(HttpContext ctx,long id)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();
      if(!can(u,"operations.manage")&&!can(u,"workorders.edit"))return Results.Forbid();
      if(!filterOrders(await loadOrders(),u).Any(w=>w.WorkOrderId==id))return Results.NotFound();
      await using var db=await Db(conn);await using var tx=(SqlTransaction)await db.BeginTransactionAsync();
      using var cmd=new SqlCommand(@"UPDATE dbo.OpsHolds SET ReleasedAt=SYSDATETIME() OUTPUT INSERTED.PreviousStatus
WHERE WorkOrderId=@Id AND ReleasedAt IS NULL",db,tx);cmd.Parameters.AddWithValue("@Id",id);
      var previous=(string?)await cmd.ExecuteScalarAsync();
      if(previous is null){await tx.RollbackAsync();return Results.BadRequest(new{message="Aktif bekleme kaydı yok."});}
      using var up=new SqlCommand("UPDATE dbo.WorkOrders SET Status=@Previous,UpdatedAt=SYSDATETIME() WHERE WorkOrderId=@Id AND Status=N'Beklemede'",db,tx);
      up.Parameters.AddWithValue("@Previous",previous);up.Parameters.AddWithValue("@Id",id);await up.ExecuteNonQueryAsync();
      await tx.CommitAsync();return Results.Ok(new{message="Bekleme kaldırıldı."});
    });
    app.MapGet("/api/ops/stock",async(HttpContext ctx)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();if(!can(u,"warehouse.view"))return Results.Forbid();
      var stocks=new List<object>();var wh=new List<object>();
      await using var db=await Db(conn);
      using(var cmd=new SqlCommand("SELECT RentalWarehouseId,Name FROM dbo.RentalWarehouses WHERE IsActive=1",db)){
        await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())wh.Add(new{id=r.GetInt32(0),name=r.GetString(1)});}
      using(var cmd=new SqlCommand(@"SELECT p.PartId,p.Code,p.Name,p.Unit,p.MinimumQty,p.UnitCost,
 b.WarehouseId,COALESCE(b.Quantity,0),COALESCE(w.Name,N'Kayıt bekliyor')
FROM dbo.ServicePartCatalog p LEFT JOIN dbo.ServiceStockBalances b ON b.PartId=p.PartId
LEFT JOIN dbo.RentalWarehouses w ON w.RentalWarehouseId=b.WarehouseId ORDER BY p.Name",db)){
        await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())stocks.Add(new{
          id=r.GetInt32(0),code=r.GetString(1),name=r.GetString(2),unit=r.GetString(3),minimum=r.GetDecimal(4),
          cost=can(u,"finance.prices.view")?(decimal?)r.GetDecimal(5):null,
          warehouseId=r.IsDBNull(6)?(int?)null:r.GetInt32(6),quantity=r.GetDecimal(7),warehouse=r.GetString(8)});}
      return Results.Ok(new{warehouses=wh,stocks});
    });
    app.MapPost("/api/ops/stock/part",async(HttpContext ctx,PartRequest req)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();if(!can(u,"warehouse.manage"))return Results.Forbid();
      if(req.Code.Length is <1 or >80||req.Name.Length is <1 or >200||req.Minimum<0||req.Cost<0)return Results.BadRequest();
      if(req.Cost>0&&!can(u,"finance.costs.manage"))return Results.Forbid();
      await using var db=await Db(conn);using var cmd=new SqlCommand(@"INSERT dbo.ServicePartCatalog(Code,Name,Unit,MinimumQty,UnitCost)
VALUES(@Code,@Name,@Unit,@Minimum,@Cost)",db);
      cmd.Parameters.AddWithValue("@Code",req.Code.Trim());cmd.Parameters.AddWithValue("@Name",req.Name.Trim());
      cmd.Parameters.AddWithValue("@Unit","Adet");cmd.Parameters.AddWithValue("@Minimum",req.Minimum);cmd.Parameters.AddWithValue("@Cost",req.Cost);
      await cmd.ExecuteNonQueryAsync();return Results.Ok(new{message="Parça kaydedildi."});
    });
    app.MapPost("/api/ops/stock/movement",async(HttpContext ctx,MovementRequest req)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();if(!can(u,"warehouse.manage"))return Results.Forbid();
      if(req.Quantity<=0||req.Quantity>100000||req.Kind is not("Giriş" or "Çıkış"))return Results.BadRequest();
      if(req.Kind=="Çıkış"&&!req.WorkOrderId.HasValue)return Results.BadRequest(new{message="Çıkış için iş emri zorunlu."});
      if(req.WorkOrderId.HasValue&&!filterOrders(await loadOrders(),u).Any(w=>w.WorkOrderId==req.WorkOrderId.Value))return Results.Forbid();
      await using var db=await Db(conn);await using var tx=(SqlTransaction)await db.BeginTransactionAsync(System.Data.IsolationLevel.Serializable);
      using var price=new SqlCommand(@"SELECT p.UnitCost FROM dbo.ServicePartCatalog p
JOIN dbo.RentalWarehouses w ON w.RentalWarehouseId=@Wh AND w.IsActive=1 WHERE p.PartId=@Part",db,tx);
      price.Parameters.AddWithValue("@Wh",req.WarehouseId);price.Parameters.AddWithValue("@Part",req.PartId);
      var cost=await price.ExecuteScalarAsync();if(cost is null){await tx.RollbackAsync();return Results.BadRequest(new{message="Parça / depo bulunamadı."});}
      using var bal=new SqlCommand("SELECT Quantity FROM dbo.ServiceStockBalances WITH(UPDLOCK,HOLDLOCK) WHERE PartId=@Part AND WarehouseId=@Wh",db,tx);
      bal.Parameters.AddWithValue("@Part",req.PartId);bal.Parameters.AddWithValue("@Wh",req.WarehouseId);
      decimal before=Convert.ToDecimal(await bal.ExecuteScalarAsync()??0);decimal after=before+(req.Kind=="Giriş"?req.Quantity:-req.Quantity);
      if(after<0){await tx.RollbackAsync();return Results.BadRequest(new{message="Stok yetersiz."});}
      using var update=new SqlCommand(@"IF EXISTS(SELECT 1 FROM dbo.ServiceStockBalances WHERE PartId=@Part AND WarehouseId=@Wh)
UPDATE dbo.ServiceStockBalances SET Quantity=@Qty WHERE PartId=@Part AND WarehouseId=@Wh
ELSE INSERT dbo.ServiceStockBalances(PartId,WarehouseId,Quantity) VALUES(@Part,@Wh,@Qty);
INSERT dbo.ServicePartMovements(PartId,WarehouseId,WorkOrderId,Kind,Quantity,UnitCost,CreatedBy)
VALUES(@Part,@Wh,@Work,@Kind,@MoveQty,@Cost,@User);",db,tx);
      update.Parameters.AddWithValue("@Part",req.PartId);update.Parameters.AddWithValue("@Wh",req.WarehouseId);
      update.Parameters.AddWithValue("@Qty",after);update.Parameters.AddWithValue("@Work",req.WorkOrderId.HasValue?(object)req.WorkOrderId.Value:DBNull.Value);
      update.Parameters.AddWithValue("@Kind",req.Kind);update.Parameters.AddWithValue("@MoveQty",req.Quantity);
      update.Parameters.AddWithValue("@Cost",Convert.ToDecimal(cost));update.Parameters.AddWithValue("@User",u.UserId);
      await update.ExecuteNonQueryAsync();await tx.CommitAsync();return Results.Ok(new{message="Stok hareketi kaydedildi.",remaining=after});
    });
    app.MapGet("/api/ops/finance",async(HttpContext ctx)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();
      if(!can(u,"finance.prices.view")||!can(u,"reports.view"))return Results.Forbid();
      var rows=filterOrders(await loadOrders(),u);var logs=await loadLogs();var result=new List<object>();
      var rates=new Dictionary<string,decimal>(StringComparer.OrdinalIgnoreCase);
      var money=new Dictionary<long,(decimal Revenue,decimal Other,decimal Material)>();
      await using var db=await Db(conn);
      using(var cmd=new SqlCommand("SELECT UnitCode,HourlyCost FROM dbo.OpsLaborRates",db)){
        await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())rates[r.GetString(0)]=r.GetDecimal(1);}
      using(var cmd=new SqlCommand(@"SELECT w.WorkOrderId,COALESCE(f.Revenue,0),COALESCE(f.OtherCost,0),
 COALESCE((SELECT SUM(CASE WHEN m.Kind=N'Çıkış' THEN m.Quantity*m.UnitCost ELSE -m.Quantity*m.UnitCost END)
 FROM dbo.ServicePartMovements m WHERE m.WorkOrderId=w.WorkOrderId),0)
FROM dbo.WorkOrders w LEFT JOIN dbo.OpsWorkFinancials f ON f.WorkOrderId=w.WorkOrderId",db)){
        await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())money[r.GetInt64(0)]=(r.GetDecimal(1),r.GetDecimal(2),Convert.ToDecimal(r.GetValue(3)));}
      foreach(var w in rows){var m=money.GetValueOrDefault(w.WorkOrderId);
        var hours=logs.Where(x=>x.WorkOrderId==w.WorkOrderId).Sum(x=>x.Minutes)/60m;
        var labor=decimal.Round(hours*rates.GetValueOrDefault(w.UnitCode),2);
        var total=m.Other+m.Material+labor;
        result.Add(new{id=w.WorkOrderId,no=w.WorkOrderNo,unit=w.UnitCode,customer=w.CustomerName,revenue=m.Revenue,
          other=m.Other,material=m.Material,labor,total,margin=m.Revenue-total,hours});}
      return Results.Ok(new{orders=result,rates=rates.Where(x=>unitAllowed(u,x.Key)).Select(x=>new{unit=x.Key,cost=x.Value})});
    });
    app.MapPut("/api/ops/finance/rate",async(HttpContext ctx,RateRequest req)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();
      if(!can(u,"finance.prices.view")||!can(u,"finance.costs.manage")||!unitAllowed(u,req.Unit))return Results.Forbid();
      if(req.Cost<0||req.Cost>1000000)return Results.BadRequest();
      await using var db=await Db(conn);using var cmd=new SqlCommand("UPDATE dbo.OpsLaborRates SET HourlyCost=@Cost WHERE UnitCode=@Unit",db);
      cmd.Parameters.AddWithValue("@Cost",req.Cost);cmd.Parameters.AddWithValue("@Unit",req.Unit);
      return await cmd.ExecuteNonQueryAsync()==0?Results.NotFound():Results.Ok(new{message="Tarife kaydedildi."});
    });
    app.MapPut("/api/ops/finance/{id:long}",async(HttpContext ctx,long id,FinanceRequest req)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();
      if(!can(u,"finance.prices.view")||!can(u,"finance.costs.manage"))return Results.Forbid();
      if(!filterOrders(await loadOrders(),u).Any(w=>w.WorkOrderId==id))return Results.Forbid();
      if(req.Revenue<0||req.Other<0||req.Revenue>1000000000||req.Other>1000000000)return Results.BadRequest();
      await using var db=await Db(conn);using var cmd=new SqlCommand(@"IF EXISTS(SELECT 1 FROM dbo.OpsWorkFinancials WHERE WorkOrderId=@Id)
UPDATE dbo.OpsWorkFinancials SET Revenue=@Revenue,OtherCost=@Other,Notes=@Notes,UpdatedBy=@User,UpdatedAt=SYSDATETIME() WHERE WorkOrderId=@Id
ELSE INSERT dbo.OpsWorkFinancials(WorkOrderId,Revenue,OtherCost,Notes,UpdatedBy) VALUES(@Id,@Revenue,@Other,@Notes,@User)",db);
      cmd.Parameters.AddWithValue("@Id",id);cmd.Parameters.AddWithValue("@Revenue",req.Revenue);
      cmd.Parameters.AddWithValue("@Other",req.Other);cmd.Parameters.AddWithValue("@Notes",P(req.Notes));cmd.Parameters.AddWithValue("@User",u.UserId);
      await cmd.ExecuteNonQueryAsync();return Results.Ok(new{message="Maliyet kaydı tamam."});
    });
    app.MapGet("/api/ops/export.csv",async(HttpContext ctx)=>
    {
      var u=current(ctx);if(u is null)return Results.Unauthorized();if(!can(u,"reports.export"))return Results.Forbid();
      var lines=new List<string>{Csv("İş Emri","Birim","Müşteri","Tür","Durum","Oluşturma","Plan","Teknisyen")};
      foreach(var w in filterOrders(await loadOrders(),u))lines.Add(Csv(w.WorkOrderNo,w.UnitCode,w.CustomerName,w.WorkType,w.Status,w.CreatedAt,w.PlanDate,w.AssignedStaff));
      return Results.File(Encoding.UTF8.GetPreamble().Concat(Encoding.UTF8.GetBytes(string.Join("\r\n",lines))).ToArray(),"text/csv; charset=utf-8","DengeERP_Operasyon.csv");
    });
  }
  private static async Task<HashSet<string>> Acks(string conn,int userId)
  {
    var result=new HashSet<string>();await using var db=await Db(conn);
    using var cmd=new SqlCommand("SELECT AlertKey FROM dbo.OpsAlertAcks WHERE UserId=@Id",db);cmd.Parameters.AddWithValue("@Id",userId);
    await using var r=await cmd.ExecuteReaderAsync();while(await r.ReadAsync())result.Add(r.GetString(0));return result;
  }
  internal sealed record AckRequest(string Key);
  internal sealed record SlaRequest(int Hours);
  internal sealed record HoldRequest(string Reason,string? Notes);
  internal sealed record PartRequest(string Code,string Name,decimal Minimum,decimal Cost);
  internal sealed record MovementRequest(int PartId,int WarehouseId,long? WorkOrderId,string Kind,decimal Quantity);
  internal sealed record RateRequest(string Unit,decimal Cost);
  internal sealed record FinanceRequest(decimal Revenue,decimal Other,string? Notes);
}
