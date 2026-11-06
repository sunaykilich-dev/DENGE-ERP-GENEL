// V1.20 operations, inventory, mobile and cost screens.
const ops120={overview:null,stock:null,finance:null,tab:'orders',only:'all',search:'',error:'',days:30};
function ops120Page(view){
 const e=esc;
 const menu=`<div class="toolbar"><button class="btn primary" id="opsRefresh">Yenile</button>${view==='operations120'?'<button class="btn" id="opsExport">Operasyon CSV</button>':''}</div>`;
 if(view==='mobile120'){
  const items=state.workOrders.filter(w=>state.user.roleName==='Teknisyen'?(w.assignedStaff||'').split(',').map(x=>x.trim()).includes(state.user.fullName):true).filter(w=>!['Tamamlandı','Kapatıldı','İptal'].includes(w.status));
  return `<div class="panel"><div class="panel-h">Mobil İş Emirleri <span id="opsNetwork" class="badge">${navigator.onLine?'Çevrimiçi':'Çevrimdışı'}</span></div><div class="panel-b"><p class="notice">Mobilde iş emrini ve canlı sayacı açabilirsin. <b>Offline kayıt senkronizasyonu henüz etkin değildir.</b> Çevrimdışıyken kayıt gönderme.</p>${menu}<div class="ops-grid">${items.slice(0,120).map(w=>`<div class="ops-job"><b>${e(w.workOrderNo)}</b><p>${e(w.customerName)}</p><p>${e(w.siteCity||w.location||'Konum yok')}</p><p>${statusBadge(w.status)}</p><button class="btn primary" data-open="${w.workOrderId}">İşi Aç</button></div>`).join('')||'<p>Aktif iş bulunmuyor.</p>'}</div></div></div>`;
 }
 if(view==='stock120'){
  const d=ops120.stock;
  if(!d)return menu+(ops120.error?`<p class="notice">${e(ops120.error)}</p>`:'Yükleniyor…');
  return `${menu}<div class="panel"><div class="panel-h">Yedek Parça / Depo</div><div class="panel-b"><div class="toolbar">${can('warehouse.manage')?'<button class="btn primary" id="opsNewPart">+ Parça Tanımla</button><button class="btn" id="opsMovement">Stok Giriş / Çıkış</button>':''}</div><table><thead><tr><th>ID</th><th>Kod</th><th>Ürün</th><th>Depo</th><th>Stok</th><th>Minimum</th><th>Durum</th>${can('finance.prices.view')?'<th>İç Maliyet</th>':''}</tr></thead><tbody>${d.stocks.map(x=>`<tr><td>${x.id}</td><td>${e(x.code)}</td><td>${e(x.name)}</td><td>${e(x.warehouse)}</td><td>${x.quantity}</td><td>${x.minimum}</td><td>${Number(x.quantity)<Number(x.minimum)?'<span class="badge b-red">Azaldı</span>':'<span class="badge b-green">Yeterli</span>'}</td>${can('finance.prices.view')?`<td>${x.cost==null?'—':money(x.cost)+' TL'}</td>`:''}</tr>`).join('')}</tbody></table></div></div>`;
 }
 if(view==='finance120'){
  const d=ops120.finance;
  if(!d)return menu+(ops120.error?`<p class="notice">${e(ops120.error)}</p>`:'Yükleniyor…');
  const r=d.orders||[];const rev=r.reduce((a,x)=>a+Number(x.revenue),0),cost=r.reduce((a,x)=>a+Number(x.total),0);
  return `${menu}<div class="notice">Bu analiz kayıtlı gelir, malzeme çıkışları ve gerçek süreye uygulanan iç işçilik tarifesini kullanır. Fatura veya resmi kârlılık raporu değildir.</div><div class="ops-grid"><div class="ops-stat">Gelir<b>${money(rev)} TL</b></div><div class="ops-stat">Maliyet<b>${money(cost)} TL</b></div><div class="ops-stat">Fark<b>${money(rev-cost)} TL</b></div></div>
  <div class="panel"><div class="panel-h">Birim Saatlik İç Maliyeti</div><div class="panel-b toolbar">${d.rates.map(x=>`<button class="btn" ${can('finance.costs.manage')?`data-opsrate="${e(x.unit)}" data-cost="${x.cost}"`:''}>${e(x.unit)}: ${money(x.cost)} TL/sa</button>`).join('')}</div></div>
  <div class="panel" style="margin-top:12px"><div class="panel-h">İş Bazlı Maliyet / Gelir</div><div class="panel-b ops-scroll"><table><thead><tr><th>İş</th><th>Müşteri</th><th>Gelir</th><th>Malzeme</th><th>İşçilik</th><th>Diğer</th><th>Toplam</th><th>Fark</th><th></th></tr></thead><tbody>${r.slice(0,350).map(x=>`<tr><td><button class="ops-link" data-open="${x.id}">${e(x.no)}</button></td><td>${e(x.customer)}</td><td>${money(x.revenue)}</td><td>${money(x.material)}</td><td>${money(x.labor)}</td><td>${money(x.other)}</td><td>${money(x.total)}</td><td>${money(x.margin)}</td><td>${can('finance.costs.manage')?`<button class="btn" data-finchange="${x.id}">Düzenle</button>`:''}</td></tr>`).join('')}</tbody></table></div></div>`;
 }
 if(view==='operations120'){
  const d=ops120.overview;
  if(!d)return menu+(ops120.error?`<p class="notice">${e(ops120.error)}</p>`:'Yükleniyor…');
  const c=d.counters;
  const cats=[['Açık İş',c.open,'open'],['Geciken',c.overdue,'overdue'],['Bugün Planlı',c.today,'today'],['Yarın Planlı',c.tomorrow,'tomorrow'],['Günlük Servis',c.service,'service'],['Planlı Bakım',c.maintenance,'maintenance'],['Bekleme',c.hold,'hold'],['Kapanan',c.closed,'closed']];
  const tabs=[['orders','İş Listesi'],['alerts',`Uyarılar (${d.alerts.length})`],['personnel','Personel İş Yükü'],['repeats','Tekrar Arıza'],['sla','SLA Hedefleri']];
  let body='';
  if(ops120.tab==='orders'){
   const filtered=d.orders.filter(w=>{
    if(ops120.search&&![w.no,w.customer,w.location,w.city,w.assigned].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(ops120.search.toLocaleLowerCase('tr-TR'))))return false;
    if(ops120.only==='overdue')return w.overdue;
    if(ops120.only==='service')return !w.isMaintenance;
    if(ops120.only==='maintenance')return w.isMaintenance;
    if(ops120.only==='open')return !['Kapatıldı','İptal','Tamamlandı'].includes(w.status);
    if(ops120.only==='closed')return ['Kapatıldı','İptal','Tamamlandı'].includes(w.status);
    if(ops120.only==='hold')return !!w.holdReason;
    if(ops120.only==='today')return w.planDate===new Date().toLocaleDateString('sv-SE');
    if(ops120.only==='tomorrow'){let t=new Date();t.setDate(t.getDate()+1);return w.planDate===t.toLocaleDateString('sv-SE');}
    return true;
   });
   body=`<div class="toolbar"><input id="opsSearch" class="search" placeholder="Müşteri / Lokasyon / Personel / İş No" value="${e(ops120.search)}"><span>${filtered.length} iş emri</span><button class="btn" id="opsReset">Filtreleri Sıfırla</button></div><div class="ops-scroll"><table><thead><tr><th>İş No</th><th>Müşteri / Şehir</th><th>İş Türü</th><th>Durum</th><th>Personel</th><th>Plan</th><th>İşlem</th></tr></thead><tbody>${filtered.slice(0,250).map(w=>`<tr><td><button class="ops-link" data-open="${w.id}">${e(w.no)}</button></td><td>${e(w.customer)}<br><small>${e(w.city||w.location)}</small></td><td>${w.isMaintenance?'Planlı Bakım':'Servis'}</td><td>${statusBadge(w.status)}${w.overdue?'<br><span class="badge b-red">Gecikti</span>':''}</td><td>${e(w.assigned||'—')}</td><td>${e(w.planDate||'—')}</td><td>${w.holdReason?`<button class="btn" data-opsrelease="${w.id}">Beklemeyi Kaldır</button>`:(!['Kapatıldı','Tamamlandı','İptal'].includes(w.status)?`<button class="btn" data-opshold="${w.id}">Beklet</button>`:'—')}</td></tr>`).join('')}</tbody></table></div>`;
  }else if(ops120.tab==='alerts')body=d.alerts.length?d.alerts.map(a=>`<div class="ops-alert"><span>${e(a.message)}</span><div><button class="btn" data-ack="${e(a.key)}">Görüldü</button>${a.workOrderId?` <button class="btn" data-open="${a.workOrderId}">İş Emri</button>`:''}</div></div>`).join(''):'<p>Yeni uyarı yok.</p>';
  else if(ops120.tab==='personnel')body=`<table><thead><tr><th>Personel</th><th>Toplam Atama</th><th>Açık</th><th>Kapalı</th></tr></thead><tbody>${d.personnel.map(x=>`<tr><td>${e(x.name)}</td><td>${x.total}</td><td>${x.open}</td><td>${x.closed}</td></tr>`).join('')}</tbody></table><p class="subtle">Kesin kişi-saat raporu için mevcut Saha / Zaman Takibi bölümünü kullanın.</p>`;
  else if(ops120.tab==='repeats')body=`<table><thead><tr><th>Seri No</th><th>Adet</th><th>İşler</th></tr></thead><tbody>${d.repeats.map(x=>`<tr><td>${e(x.serialNo)}</td><td>${x.count}</td><td>${e(x.orders.join(', '))}</td></tr>`).join('')}</tbody></table>`;
  else if(ops120.tab==='sla')body=`<div class="notice">SLA hedefleri sözleşme doğrulaması yapılmamış takvim saatidir; mesai takvimi uygulanmaz.</div><table><thead><tr><th>Öncelik</th><th>Çözüm Süresi</th><th></th></tr></thead><tbody>${d.sla.map(x=>`<tr><td>${e(x.priority)}</td><td>${x.hours} sa.</td><td>${can('operations.manage')?`<button class="btn" data-sla="${e(x.priority)}" data-hours="${x.hours}">Düzenle</button>`:''}</td></tr>`).join('')}</tbody></table>`;
  return `${menu}<div class="ops-grid">${cats.map(([label,n,key])=>`<button class="ops-stat" data-filter="${key}"><span>${label}</span><b>${n}</b></button>`).join('')}</div><div class="panel"><div class="panel-b"><div class="tabbar">${tabs.map(([key,label])=>`<button class="tabbtn ${ops120.tab===key?'active':''}" data-opstab="${key}">${label}</button>`).join('')}</div>${body}</div></div>`;
 }
 return '';
}
async function ops120Refresh(){
 ops120.error='';try{
  if(state.view==='operations120')ops120.overview=await api(`/api/ops/overview?days=${ops120.days}`);
  if(state.view==='stock120')ops120.stock=await api('/api/ops/stock');
  if(state.view==='finance120')ops120.finance=await api('/api/ops/finance');
  if(state.view==='mobile120')await reloadWork();
 }catch(err){ops120.error=err.message;}
}
async function ops120Save(path,obj,method='POST'){
 try{await api(path,{method,body:obj===null?undefined:JSON.stringify(obj)});await ops120Refresh();render();}catch(err){alert(err.message);}
}
function ops120Bind(){
 $('#opsRefresh')?.addEventListener('click',async()=>{await ops120Refresh();render();});
 $('#opsExport')?.addEventListener('click',()=>downloadBlob('/api/ops/export.csv','DengeERP_Operasyon.csv').catch(e=>alert(e.message)));
 $('#opsSearch')?.addEventListener('change',e=>{ops120.search=e.target.value;render();});
 $('#opsReset')?.addEventListener('click',()=>{ops120.search='';ops120.only='all';render();});
 $$('[data-filter]').forEach(b=>b.onclick=()=>{ops120.only=b.dataset.filter;ops120.tab='orders';render();});
 $$('[data-opstab]').forEach(b=>b.onclick=()=>{ops120.tab=b.dataset.opstab;render();});
 $$('[data-ack]').forEach(b=>b.onclick=()=>ops120Save('/api/ops/alerts/ack',{key:b.dataset.ack}));
 $$('[data-sla]').forEach(b=>b.onclick=async()=>{const val=prompt(`${b.dataset.sla} çözüm hedefi (saat):`,b.dataset.hours);if(val!==null)await ops120Save('/api/ops/sla/'+encodeURIComponent(b.dataset.sla),{hours:Number(val)},'PUT');});
 $$('[data-opshold]').forEach(b=>b.onclick=async()=>{
  const reason=prompt('Bekleme nedeni: Malzeme / Müşteri Onayı / Teklif / Personel / Diğer','Malzeme Bekleniyor');if(!reason)return;
  const notes=prompt('Bekleme notu (opsiyonel):','');if(notes===null)return;
  await ops120Save(`/api/ops/workorders/${b.dataset.opshold}/hold`,{reason,notes});
 });
 $$('[data-opsrelease]').forEach(b=>b.onclick=async()=>{if(confirm('Beklemeyi kaldır?'))await ops120Save(`/api/ops/workorders/${b.dataset.opsrelease}/release`,null);});
 $('#opsNewPart')?.addEventListener('click',async()=>{
  const code=prompt('Parça kodu:');if(!code)return;const name=prompt('Parça adı:');if(!name)return;
  const min=prompt('Minimum stok:',1);if(min===null)return;
  const cost=can('finance.costs.manage')?prompt('Birim iç maliyet (TL):',0):'0';if(cost===null)return;
  await ops120Save('/api/ops/stock/part',{code,name,minimum:Number(min),cost:Number(cost)});
 });
 $('#opsMovement')?.addEventListener('click',async()=>{
  const partId=prompt('Parça ID (stok listesindeki kayıt):');if(!partId)return;
  const warehouseId=prompt('Depo ID (1/2/3):',1);if(!warehouseId)return;
  const kind=prompt('Hareket türü: Giriş / Çıkış','Giriş');if(!kind)return;
  const quantity=prompt('Miktar:',1);if(!quantity)return;
  const workOrderId=kind==='Çıkış'?prompt('İş Emri ID (zorunlu):'):null;
  if(kind==='Çıkış'&&!workOrderId){alert('İş emri zorunlu.');return;}
  await ops120Save('/api/ops/stock/movement',{partId:Number(partId),warehouseId:Number(warehouseId),kind,quantity:Number(quantity),workOrderId:workOrderId?Number(workOrderId):null});
 });
 $$('[data-opsrate]').forEach(b=>b.onclick=async()=>{const val=prompt(`${b.dataset.opsrate} saatlik iç maliyet:`,b.dataset.cost);if(val!==null)await ops120Save('/api/ops/finance/rate',{unit:b.dataset.opsrate,cost:Number(val)},'PUT');});
 $$('[data-finchange]').forEach(b=>b.onclick=async()=>{
  const r=ops120.finance.orders.find(x=>String(x.id)===b.dataset.finchange);if(!r)return;
  const rev=prompt('Kaydedilen gelir (TL):',r.revenue);if(rev===null)return;
  const other=prompt('Diğer maliyet (TL):',r.other);if(other===null)return;
  const notes=prompt('Not (opsiyonel):','');if(notes===null)return;
  await ops120Save(`/api/ops/finance/${r.id}`,{revenue:Number(rev),other:Number(other),notes},'PUT');
 });
}
setInterval(async()=>{if(state.user&&state.view==='operations120'&&!document.hidden){await ops120Refresh();render();}},180000);
