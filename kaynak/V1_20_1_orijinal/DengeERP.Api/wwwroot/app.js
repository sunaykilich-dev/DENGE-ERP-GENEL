const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const money = n => new Intl.NumberFormat('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(n||0));
const todayIso = () => new Date().toISOString().slice(0,10);
const monthStartIso = () => { const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`; };

const allUnits = ["Güvenlik Sistemleri","Haberleşme","POC","Mobilite","Araç Takip"];
const workTypes = {
  "Güvenlik Sistemleri":["Saha Arızası","Saha Kurulumu / Devreye Alma","Atölye Tamir","Kontrol / Test","Plansız Bakım"],
  "Haberleşme":["Atölye Teknik Servis","Saha Arızası","Saha Kurulumu","Test / Devreye Alma","Programlama / Konfigürasyon","Keşif / Kapsama Çalışması","AR-GE Çalışması","Kiralık El Telsizi Hazırlığı","Kiradan Dönen El Telsizi Testi","Plansız Bakım"],
  "POC":["Uzaktan Müdahale","Telefonla Destek","Yerinde Müdahale"],
  "Mobilite":["Kurulum","Arıza","Talep"],
  "Araç Takip":["Kurulum","Arıza","Bakım","Talep"]
};
const systems = {
  "Güvenlik Sistemleri":["X-Ray","Kapı Tipi Metal Dedektörü"],
  "Haberleşme":["El Telsizi","Araç Telsizi","Sabit / Masa Telsizi","Repeater / Röle Sistemi","DMR Sistem Altyapısı","TETRA Sistem / Terminal","LTE / PoC Telsiz","Anten / Feeder Sistemi","Dispatcher / Konsol","Güç Kaynağı / Batarya / Şarj Sistemi"],
  "POC":["GSM / PoC Hat","PoC Terminal","PoC Yönetim Platformu"],
  "Mobilite":["Mobilite Cihazı","Mobil Uygulama","Araç Üstü Terminal"],
  "Araç Takip":["GPS Araç Takip Cihazı","CAN / Sensör","Mobil DVR"]
};
const personnelFallback = {
  "Güvenlik Sistemleri":{chiefs:["Hakan Erdal"],technicians:["Ali Kaya","Arda Çiftçi","Burak Mehmet Şahinbaş","Ali Güler","Emirhan Pehlivan","Özgür Çavdar","Alperen Kurahmetoğlu","Bilal Emir Mengü"]},
  "Haberleşme":{chiefs:["Ertuğrul Çakır"],technicians:["Mehmet Can Şahin","Emre Çevre","Cem Ülger","Hazal Çelik","Batuhan Yıldız","Ebrar Yayla Almıkarı"]},
  "POC":{chiefs:["Ertuğrul Çakır"],technicians:["Ramazan Furkan Ermiş"]},
  "Mobilite":{chiefs:["Serkan Doğan"],technicians:["Fatih Bayındır","Güngör Sima Aktüre","Baran Tefiye"]},
  "Araç Takip":{chiefs:["Serkan Doğan"],technicians:["Fatih Bayındır","Güngör Sima Aktüre","Baran Tefiye"]}
};
const statuses = ["Müşteri Talebi","Planlamada","Planlandı","Yola Çıkıldı","Sahada","İşlemde","Atölyede","Kargoda","Beklemede","Test / Kontrol","Tamamlandı","Kapatıldı","Tekrar Açıldı","İptal"];
const pocStatuses = ["Müşteri Talebi","Planlamada","Planlandı","İnceleniyor","Telefonla Destek","Uzaktan Müdahale","Yerinde Müdahale","Beklemede","Tamamlandı","Kapatıldı","Tekrar Açıldı","İptal"];
const rentalStatuses = ["Talep","Teklif","Planlama","Hazırlanıyor","Teslimata Hazır","Teslim Edildi","Kirada","İade Bekliyor","İade Alındı","Test / Kontrol","Kapandı","İptal"];

const state = {
  token: localStorage.getItem('denge_token') || '',
  user: null,
  view: 'dashboard',
  unit: 'Güvenlik Sistemleri',
  workOrders: [],
  workLogs: [],
  users: [],
  offers: [],
  rentals: [],
  rentalCatalog: [],
  rentalInventory: {warehouses:[],assets:[]},
  rentalTab: 'orders',
  rentalInventorySearch: '',
  rentalInventoryWarehouse: 'all',
  rentalInventoryStatus: 'all',
  personnel: [],
  trainingData: null,
  trainingYear: new Date().getFullYear(),
  trainingUnit: 'all',
  trainingTab: 'overview',
  trainingPerson: null,
  trainingDraft: null,
  liveTracking: null,
  timeWorkOrder: null,
  timeFilters: {start:monthStartIso(),end:todayIso(),unit:'Tümü',person:'',search:''},
  securityDevices: [],
  maintenanceContracts: [],
  workshopTickets: [],
  rules: [],
  meta: null,
  workFilter: 'all',
  workKind: 'service',
  workStatusGroup: 'open',
  planningKind: 'service',
  planningCustomerSearch: '',
  reportFilters: { start:'', end:'', dateField:'created', kind:'all', unit:'Tümü', status:'Tümü', workType:'Tümü', person:'', chief:'', customer:'' },
  rentalFilter: 'all',
  personnelDepartment: 'all',
  securityType: 'all',
  securityBrand: 'all',
  securityModel: 'all',
  securitySearch: '',
  planningMode: 'week',
  planningVisitGroups: {},
  planningAnchor: todayIso(),
  planningUnit: 'all',
  planningPerson: 'all',
  bulkSelectedIds: [],
  assignmentSelectedIds: []
};

async function api(path, options={}){
  const headers = {...(options.headers||{})};
  if(state.token) headers.Authorization = `Bearer ${state.token}`;
  if(options.body && !(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type']='application/json; charset=utf-8';
  const r = await fetch(path,{...options,headers,cache:'no-store'});
  if(r.status===401){ logoutLocal(); throw new Error('Oturum süresi doldu. Tekrar giriş yapın.'); }

  const ct=r.headers.get('content-type')||'';
  const raw=await r.text();

  if(!r.ok){
    let msg=`İşlem başarısız (${r.status})`;
    if(raw){
      try{
        const j=JSON.parse(raw);
        msg=j.message||j.detail||j.title||msg;
      }catch{
        msg=raw;
      }
    }
    throw new Error(msg);
  }

  if(!raw) return null;
  if(ct.includes('application/json')) return JSON.parse(raw);
  return raw;
}

function logoutLocal(){ state.token=''; state.user=null; localStorage.removeItem('denge_token'); }
function can(p){ return !!state.user && (state.user.permissions?.includes('*') || state.user.permissions?.includes(p)); }
function unitAllowed(u){ return !!state.user && (state.user.permissions?.includes('*') || !state.user.allowedUnits?.length || state.user.allowedUnits.includes(u)); }
function availableUnits(){ return allUnits.filter(unitAllowed); }
function statusBadge(s){
  let c='b-gray';
  if(["Tamamlandı","Kapatıldı"].includes(s)) c='b-green';
  else if(["Müşteri Talebi","Planlamada","Planlandı","Yola Çıkıldı","Sahada","İşlemde","İnceleniyor","Telefonla Destek","Uzaktan Müdahale","Yerinde Müdahale"].includes(s)) c='b-blue';
  else if(["Beklemede","Atölyede","Kargoda"].includes(s)) c='b-amber';
  else if(["İptal"].includes(s)) c='b-red';
  else if(["Test / Kontrol"].includes(s)) c='b-purple';
  return `<span class="badge ${c}">${esc(s)}</span>`;
}
function isMaintenanceOrder(w){ return String(w.workOrderNo||'').startsWith('PB-') || String(w.workType||'').toLocaleLowerCase('tr-TR')==='planlı bakım'; }
function reportIsOpen(w){ return !['Tamamlandı','Kapatıldı','İptal'].includes(w.status); }
function reportIsCompleted(w){ return ['Tamamlandı','Kapatıldı'].includes(w.status); }
function reportKind(w){return isMaintenanceOrder(w)?'maintenance':'service';}
function isOpen(w){ return !['Kapatıldı','İptal'].includes(w.status); }
function fmtDate(v){ if(!v) return '-'; const d=new Date(v); return Number.isNaN(d.getTime())?String(v):d.toLocaleString('tr-TR'); }
function fmtPlanDate(v){ if(!v) return '-'; if(/^\d{4}-\d{2}-\d{2}$/.test(v)){ const [y,m,d]=v.split('-'); return `${d}.${m}.${y}`; } return v; }

function ruleFor(unit,type){ return state.rules.find(r=>r.unitCode===unit && r.workType===type) || {serialRequiredOnCreate:false,serialRequiredOnClose:/(Atölye)/i.test(type)}; }

async function loadCore(){
  const [work,rules,meta] = await Promise.all([
    api('/api/workorders'), api('/api/rules/worktypes'), api('/api/meta/permissions')
  ]);
  state.workOrders=work; state.rules=rules; state.meta=meta;
  if(can('reports.view')) state.workLogs=await api('/api/reports/worklogs');
  if(can('workorders.view')) state.liveTracking=await api('/api/timetracking/summary');
  if(!availableUnits().includes(state.unit)) state.unit=availableUnits()[0]||'Güvenlik Sistemleri';
  if(can('users.manage')) state.users=await api('/api/users');
  if(can('offers.view')) state.offers=await api('/api/offers');
  if(can('rentals.view') || can('rentals.create')){
    state.rentalCatalog=await api('/api/rentals/catalog');
    if(can('rentals.view')) { state.rentals=await api('/api/rentals'); state.rentalInventory=await api('/api/rentals/inventory'); }
  }
  if(can('personnel.view')) state.personnel=await api('/api/personnel');
  if(can('devices.view') && unitAllowed('Güvenlik Sistemleri')) state.securityDevices=await api('/api/security/devices');
  if(can('maintenance.view') && unitAllowed('Güvenlik Sistemleri')) state.maintenanceContracts=await api('/api/maintenance/contracts');
  if(can('workshop.view') && unitAllowed('Haberleşme')) state.workshopTickets=await api('/api/workshop/tickets');
}

function loginPage(){
  return `<div class="login-wrap"><div class="login-card">
    <div class="login-brand"><div class="brandmark">D</div><div><h1>Denge Elektronik</h1><p>Teknik Servis ERP • Pilot</p></div></div>
    <h2>Sisteme Giriş</h2><p class="subtle">Şirket içi pilot kullanıcı hesabınızla giriş yapın.</p>
    <form id="loginForm">
      <div class="field"><label>Kullanıcı Adı</label><input name="username" required autocomplete="username" value="admin"></div>
      <div class="field" style="margin-top:10px"><label>Şifre</label><input name="password" type="password" required autocomplete="current-password"></div>
      <div id="loginError" class="login-error hidden"></div>
      <button class="btn primary login-btn" type="submit">Giriş Yap</button>
    </form>
    <div class="demo-box"><b>Şirket içi giriş:</b> İT tarafından yetkilendirilmiş hesap bilgileriyle giriş yapın.</div>
  </div></div>`;
}

function passwordPage(){
  return `<div class="login-wrap"><div class="login-card password-card">
    <div class="login-brand"><div class="brandmark">D</div><div><h1>Denge Elektronik</h1><p>İlk Giriş Güvenliği</p></div></div>
    <h2>Yeni şifrenizi belirleyin</h2><p class="subtle">${esc(state.user?.fullName)} için geçici şifre değişikliği zorunlu.</p>
    <form id="passwordForm"><div class="field"><label>Yeni Şifre</label><input name="p1" type="password" minlength="8" required></div><div class="field" style="margin-top:10px"><label>Tekrar</label><input name="p2" type="password" minlength="8" required></div><div id="passwordError" class="login-error hidden"></div><button class="btn primary login-btn">Şifreyi Kaydet</button></form>
  </div></div>`;
}

function navItems(){
  const a=[];
  if(can('dashboard.view')) a.push(['Ana Panel','dashboard','⌂']);
  if(can('dashboard.view')) a.push(['Operasyon Merkezi','operations120','◉']);
  if(can('workorders.view')) a.push(['Mobil İşler','mobile120','▣']);
  if(can('warehouse.view')) a.push(['Yedek Parça','stock120','▤']);
  if(can('finance.prices.view')&&can('reports.view')) a.push(['Maliyet Analizi','finance120','₺']);
  if(can('workorders.create')) a.push(['Yeni İş Açılışı','create','＋']);
  if(can('workorders.view')) a.push(['İş Emirleri','workorders','▣']);
  if(can('workorders.plan')) a.push(['Planlama','planning','▦']);
  if(can('devices.view') && unitAllowed('Güvenlik Sistemleri')) a.push(['Güvenlik Cihaz Kütüğü','securitydevices','▦']);
  if(can('maintenance.view') && unitAllowed('Güvenlik Sistemleri')) a.push(['Planlı Bakımlar','maintenance','☑']);
  if(can('workshop.view') && unitAllowed('Haberleşme')) a.push(['Haberleşme Atölye','workshop','⚙']);
  if(can('rentals.view')) a.push(['Kiralama','rentals','⇄']);
  if(can('workorders.view')) a.push(['POC / Mobilite','pocmobility','◉']);
  if(can('offers.view')) a.push(['Teklif Yönetimi','offers','₺']);
  if(can('workorders.view')) a.push(['Saha / Zaman Takibi','timetracking','◷']);
  if(can('reports.view')) a.push(['Raporlar','reports','▥']);
  if(can('training.view')) a.push(['Eğitim / Personel Gelişimi','training','◈']);
  if(can('warehouse.view')) a.push(['Depo','warehouse','▤']);
  if(can('accounting.view')) a.push(['Muhasebe','accounting','◫']);
  if(can('personnel.view')) a.push(['Personel / Organizasyon','personnel','♟']);
  if(can('users.manage')) a.push(['Kullanıcı / Yetki','users','♙']);
  return a;
}
function pageTitle(){ const m={dashboard:'Ana Panel',operations120:'Operasyon Merkezi',mobile120:'Mobil Teknisyen Paneli',stock120:'Yedek Parça Stokları',finance120:'Maliyet Analizi',create:'Yeni İş Açılışı',workorders:'İş Emirleri',planning:'Planlama Takvimi',securitydevices:'Güvenlik Cihaz Kütüğü',maintenance:'Planlı Bakımlar',workshop:'Haberleşme Atölye Teknik Servis',rentals:'Kiralama Yönetimi',pocmobility:'POC / Mobilite',offers:'Teklif Yönetimi',reports:'Raporlar',timetracking:'Saha / Zaman Takibi',training:'Eğitim ve Personel Gelişimi',personnel:'Personel / Organizasyon',users:'Kullanıcı ve Yetki Yönetimi',warehouse:'Depo',accounting:'Muhasebe'}; return m[state.view]||'DengeERP'; }
function layout(content){
  const nav=navItems();
  return `<div class="shell"><aside class="sidebar"><div class="brand"><div class="brandmark">D</div><div><strong>Denge Elektronik</strong><small>Teknik Servis ERP</small></div></div><div class="navgroup"><div class="navtitle">Menü</div>${nav.map(i=>`<a href="#" class="navitem ${state.view===i[1]?'active':''}" data-nav="${i[1]}"><span class="navicon">${i[2]}</span>${i[0]}</a>`).join('')}</div></aside>
  <main class="main"><div class="ops-mobilebar">${nav.map(i=>`<a href="#" class="navitem ${state.view===i[1]?'active':''}" data-nav="${i[1]}">${i[2]} ${i[0]}</a>`).join('')}</div><header class="topbar"><div><div class="pagetitle">${pageTitle()}</div><div class="crumb">Pilot ortam • SQL Server kalıcı kayıt</div></div><div class="spacer"></div><span class="server-chip ok">SQL Bağlı</span><div class="userchip"><div class="avatar">${esc((state.user?.fullName||'U').split(' ').map(x=>x[0]).join('').slice(0,2).toUpperCase())}</div><div><b>${esc(state.user?.fullName)}</b><small>${esc(state.user?.roleName)}</small></div></div><button class="btn" id="logoutBtn">Çıkış</button></header><section class="content">${content}</section></main></div><div id="modalHost"></div>`;
}

function dashboard(){
  const w=state.workOrders.filter(x=>unitAllowed(x.unitCode));
  const service=w.filter(x=>!isMaintenanceOrder(x));
  const upkeep=w.filter(isMaintenanceOrder);
  const units=availableUnits();
  const stats=(data)=>({open:data.filter(reportIsOpen).length,done:data.filter(reportIsCompleted).length,planned:data.filter(x=>x.status==='Planlandı').length,waiting:data.filter(x=>x.status==='Beklemede').length});
  const svc=stats(service), pb=stats(upkeep);
  const card=(label,count,kind)=>`<button type="button" class="kpi kpi-button" data-kpidetail="${kind}" title="${esc(label)} kayıtlarını gör"><span class="label">${esc(label)}</span><span class="num">${count}</span><span class="kpi-action">Listeyi aç ↗</span></button>`;
  return `<div class="report-section-head"><div><b>Günlük Servis / Arıza</b><span class="subtle">Planlı bakımlar bu göstergelere dahil değildir.</span></div><button class="btn soft" data-dashcategory="service">Servis işlerini göster ↗</button></div>
    <div class="kpis">${card('Açık Servis',svc.open,'serviceOpen')}${card('Müşteri Talebi',service.filter(x=>x.status==='Müşteri Talebi').length,'request')}${card('Planlandı',svc.planned,'planned')}${card('Sahada',service.filter(x=>['Sahada','İşlemde'].includes(x.status)).length,'field')}${card('Atölyede',service.filter(x=>x.status==='Atölyede').length,'workshop')}${card('Beklemede',svc.waiting,'waiting')}${card('Tamamlanan Servis',svc.done,'serviceDone')}${card('Kritik Servis',service.filter(x=>reportIsOpen(x)&&x.priority==='Kritik').length,'critical')}</div>
    <div class="report-section-head"><div><b>Planlı Bakım / Yıllık Bakım</b><span class="subtle">Her cihaz bağımsız PB iş emridir.</span></div><button class="btn soft" data-dashcategory="maintenance">Bakım işlerini göster ↗</button></div>
    <div class="kpis report-four">${card('Açık Bakım',pb.open,'maintenanceOpen')}${card('Planlanan Bakım',pb.planned,'maintenancePlanned')}${card('Tamamlanan Bakım',pb.done,'maintenanceDone')}${card('Bekleyen Bakım',upkeep.filter(x=>reportIsOpen(x)&&!x.planDate).length,'maintenanceWaiting')}</div>
    <div class="panel"><div class="panel-h">Birim Bazlı Operasyon Özeti</div><div class="panel-b cards4">${units.map(u=>{const us=w.filter(x=>x.unitCode===u);return `<button class="module-card module-button" data-unitfilter="${esc(u)}"><h4>${esc(u)}</h4><div class="stats"><div><b>${us.filter(x=>!isMaintenanceOrder(x)&&reportIsOpen(x)).length}</b>Servis Açık</div><div><b>${us.filter(x=>isMaintenanceOrder(x)&&reportIsOpen(x)).length}</b>Bakım Açık</div><div><b>${us.filter(x=>x.status==='Planlandı').length}</b>Planlı</div><div><b>${us.filter(reportIsCompleted).length}</b>Biten</div></div></button>`}).join('')}</div></div>
    <div class="two-col" style="margin-top:12px"><div class="panel"><div class="panel-h">Son Günlük Servis İş Emirleri</div><div class="panel-b">${workTable(service.slice(0,10))}</div></div><div class="panel"><div class="panel-h">Operasyon Notu</div><div class="panel-b"><div class="notice">Günlük servis iş yükü ile yıllık planlı bakım yükü ayrı izlenir. Ayrıntılı yönetim raporu için <b>Raporlar</b> menüsünü kullanın.</div><div class="actions"><button class="btn soft" data-nav-report="1">Raporlara git ↗</button></div></div></div></div>`;
}

// V1.8: KPI sayi kutulari tıklanınca kayıtlar kategori/birim/durum bazında acilir.
// Salt-okunur istemci filtresidir; yetkiler API tarafinda korunur.
function metricWorkRows(kind){
  const w=state.workOrders.filter(x=>unitAllowed(x.unitCode));
  const isMaint=isMaintenanceOrder;
  const planned=planningFilteredRows();
  const monday=mondayOf(dateFromIso(todayIso())); const weekEnd=addLocalDays(monday,6);
  const conflictIds=planningConflictIds(planned);
  switch(kind){
    case 'open': return w.filter(reportIsOpen);
    case 'serviceOpen': return w.filter(x=>!isMaint(x)&&reportIsOpen(x));
    case 'serviceDone': return w.filter(x=>!isMaint(x)&&reportIsCompleted(x));
    case 'maintenancePlanned': return w.filter(x=>isMaint(x)&&x.status==='Planlandı');
    case 'maintenanceWaiting': return w.filter(x=>isMaint(x)&&reportIsOpen(x)&&!x.planDate);
    case 'request': return w.filter(x=>!isMaint(x)&&x.status==='Müşteri Talebi');
    case 'planned': return w.filter(x=>!isMaint(x)&&x.status==='Planlandı');
    case 'field': return w.filter(x=>!isMaint(x)&&x.status==='Sahada');
    case 'workshop': return w.filter(x=>!isMaint(x)&&x.status==='Atölyede');
    case 'waiting': return w.filter(x=>!isMaint(x)&&x.status==='Beklemede');
    case 'complete': return w.filter(x=>!isMaint(x)&&x.status==='Tamamlandı');
    case 'critical': return w.filter(x=>!isMaint(x)&&reportIsOpen(x)&&x.priority==='Kritik');
    case 'maintenanceOpen': return w.filter(x=>isMaint(x)&&isOpen(x));
    case 'maintenanceDone': return w.filter(x=>isMaint(x)&&['Tamamlandı','Kapatıldı'].includes(x.status));
    case 'planToday': return planned.filter(x=>x.planDate===todayIso());
    case 'planWeek': return planned.filter(x=>{const d=dateFromIso(x.planDate);return d&&d>=monday&&d<=weekEnd;});
    case 'planTotal': return planned.filter(x=>!!x.planDate);
    case 'planConflict': return planned.filter(x=>conflictIds.has(String(x.workOrderId)));
    case 'planWaiting': return planned.filter(x=>!x.planDate&&!['Tamamlandı','Kapatıldı','İptal'].includes(x.status));
    default: return [];
  }
}
function openMetricDetails(kind){
  const titles={serviceOpen:'Açık Günlük Servis',serviceDone:'Tamamlanan Günlük Servis',maintenancePlanned:'Planlanan Bakım',maintenanceWaiting:'Plan Bekleyen Bakım',open:'Açık İş',request:'Müşteri Talebi',planned:'Planlandı',field:'Sahada',workshop:'Atölyede',waiting:'Beklemede',complete:'Tamamlandı',critical:'Kritik',maintenanceOpen:'Açık PB İş Emri',maintenanceDone:'Tamamlanan PB Cihazı',planToday:'Bugün Planlı',planWeek:'Bu Hafta Planlı',planTotal:'Toplam Planlı',planConflict:'Çakışmalı İş',planWaiting:'Plan Bekleyen'};
  const source=metricWorkRows(kind);
  const select=(items,label)=>`<option value="all">Tüm ${label}</option>${items.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('')}`;
  const uniques=key=>[...new Set(source.map(x=>x[key]).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b),'tr'));
  modal(`<div class="modal-h"><div><b>${esc(titles[kind]||'İş Emirleri')} • ${source.length} kayıt</b><div class="subtle">Sayı kutusuna bağlı arıza / servis işleri, birim ve iş türüne göre kategorilendirilir.</div></div><button class="iconbtn" id="metricModalX" aria-label="Kapat">×</button></div>
  <div class="modal-b metric-modal-body"><div class="metric-filters">
    <select id="metricUnit" aria-label="Birim filtresi">${select(uniques('unitCode'),'Birimler')}</select>
    <select id="metricType" aria-label="İş türü filtresi">${select(uniques('workType'),'İş Türleri')}</select>
    <select id="metricStatus" aria-label="Durum filtresi">${select(uniques('status'),'Durumlar')}</select>
    <input id="metricSearch" type="search" placeholder="Firma, iş emri, arıza açıklaması veya teknisyen ara..." aria-label="İş emri ara">
  </div><div id="metricResults"></div></div><div class="modal-f"><button class="btn" id="metricClose">Kapat</button></div>`);
  $('#metricModalX').onclick=$('#metricClose').onclick=closeModal;
  const draw=()=>{
    const unit=$('#metricUnit').value,type=$('#metricType').value,status=$('#metricStatus').value;
    const q=$('#metricSearch').value.trim().toLocaleLowerCase('tr-TR');
    const rows=source.filter(x=>(unit==='all'||x.unitCode===unit)&&(type==='all'||x.workType===type)&&(status==='all'||x.status===status)
      &&(!q||[x.workOrderNo,x.customerName,x.location,x.subject,x.description,x.assignedStaff,x.chiefName,x.serialNumbers].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(q))));
    const groups=new Map();
    for(const x of rows){const group=x.unitCode||'Birim belirtilmemiş';if(!groups.has(group))groups.set(group,[]);groups.get(group).push(x);}
    $('#metricResults').innerHTML=`<div class="metric-result-summary"><b>${rows.length} kayıt gösteriliyor</b><span>Birimi genişletin; iş emrine tıklayarak ayrıntıyı açın.</span></div>`+
      ([...groups].sort((a,b)=>a[0].localeCompare(b[0],'tr')).map(([group,items])=>{
        const counts=new Map();for(const x of items){const t=x.workType||'Diğer';counts.set(t,(counts.get(t)||0)+1);}
        const category=[...counts].sort((a,b)=>b[1]-a[1]).map(([name,count])=>`<span class="metric-category">${esc(name)} <b>${count}</b></span>`).join('');
        const table=`<div class="table-scroll"><table><thead><tr><th>İş Emri</th><th>Firma / Konu</th><th>Tür</th><th>Lokasyon</th><th>Personel</th><th>Durum</th></tr></thead><tbody>${items.map(x=>`<tr><td><button class="metric-wo-link" data-metricopen="${x.workOrderId}">${esc(x.workOrderNo)}</button></td><td><b>${esc(x.customerName)}</b><div class="subtle">${esc(x.subject||x.description||'-')}</div></td><td>${esc(x.workType)}</td><td>${esc(x.location||'-')}</td><td>${esc(x.assignedStaff||'Atanmadı')}</td><td>${statusBadge(x.status)}</td></tr>`).join('')}</tbody></table></div>`;
        return `<details class="metric-group" open><summary>${esc(group)} <b>${items.length} iş</b></summary><div class="metric-categories">${category}</div>${table}</details>`;
      }).join('')||'<div class="notice">Bu filtrelerde iş emri bulunamadı.</div>');
    $$('[data-metricopen]').forEach(x=>x.onclick=()=>openWorkOrder(x.dataset.metricopen));
  };
  ['metricUnit','metricType','metricStatus'].forEach(id=>$('#'+id).addEventListener('change',draw));
  $('#metricSearch').addEventListener('input',draw); draw();
}

function unitTabs(){ return `<div class="tabbar">${availableUnits().map(u=>`<button class="tabbtn ${state.unit===u?'active':''}" data-unit="${esc(u)}">${esc(u)}</button>`).join('')}</div>`; }
function createPage(){
  const types=workTypes[state.unit]||['Talep']; const type=types[0]; const r=ruleFor(state.unit,type);
  return `${unitTabs()}<form id="createForm">
  <div class="form-card"><div class="form-h">Müşteri / İş Bilgileri</div><div class="form-grid">
    <div class="field"><label>İş Türü *</label><select name="workType" id="createWorkType">${types.map(x=>`<option>${esc(x)}</option>`).join('')}</select></div>
    <div class="field"><label>Öncelik</label><select name="priority"><option>Normal</option><option>Yüksek</option><option>Kritik</option></select></div>
    <div class="field"><label>Müşteri *</label><input name="customer" required></div>
    <div class="field"><label>Müşteri E-posta</label><input name="customerEmail" type="email"></div>
    <div class="field"><label>Proje</label><input name="project"></div>
    <div class="field"><label>Lokasyon</label><input name="location"></div>
    <div class="field"><label>Sistem / Ürün</label><select name="systemName">${(systems[state.unit]||['Genel']).map(x=>`<option>${esc(x)}</option>`).join('')}</select></div>
    <div class="field"><label>Seri No / Seri Nolar</label><input name="serials" id="createSerials" placeholder="Birden fazlaysa virgülle ayırın"></div>
    <div class="field span4"><div id="serialRuleInfo" class="notice">${serialRuleText(r)}</div></div>
    <div class="field span2"><label>Kısa Konu *</label><input name="subject" required></div>
    <div class="field span2"><label>Talep / Arıza Açıklaması</label><textarea name="description"></textarea></div>
  </div></div>
  <div class="actions"><button class="btn primary action-main" type="submit">İş Kaydını Oluştur</button></div></form>`;
}
function serialRuleText(r){
  if(r.serialRequiredOnCreate) return '<b>Seri numarası kayıt açılışında zorunlu.</b> Atölye / cihaz teslimli işlem kuralı.';
  if(r.serialRequiredOnClose) return '<b>Seri numarası açılışta opsiyonel, iş tamamlanırken zorunlu.</b> Saha teknisyeni kapanıştan önce seri numarasını girmeli.';
  return 'Bu iş türünde seri numarası zorunlu değil.';
}

function filteredWorkOrders(){
  let a=[...state.workOrders];
  if(state.workFilter!=='all') a=a.filter(x=>x.unitCode===state.workFilter);
  if(state.workKind!=='all') a=a.filter(x=>reportKind(x)===state.workKind);
  if(state.workStatusGroup==='open') a=a.filter(reportIsOpen);
  else if(state.workStatusGroup==='done') a=a.filter(reportIsCompleted);
  return a;
}
function workTable(rows){
  if(!rows.length) return '<div class="subtle">Kayıt bulunamadı.</div>';
  const assignable=state.view==='workorders'&&can('workorders.assign');
  return `<div class="table-scroll"><table><thead><tr>${assignable?`<th><input type="checkbox" id="assignSelectAll" aria-label="Görünen işleri seç" title="Önce aynı birimi filtreleyin"></th>`:''}<th>İş Emri</th><th>Birim</th><th>İş Türü</th><th>Müşteri</th><th>Lokasyon</th><th>Seri No</th><th>Şef</th><th>Teknisyen</th><th>Durum</th><th>Plan</th></tr></thead>
  <tbody>${rows.map(w=>`<tr>${assignable?`<td><input type="checkbox" data-assignment-pick="${w.workOrderId}" ${state.assignmentSelectedIds.includes(Number(w.workOrderId))?'checked':''} ${['Tamamlandı','Kapatıldı','İptal'].includes(w.status)?'disabled title="Kapalı iş atanamaz"':''} aria-label="${esc(w.workOrderNo)} seç"></td>`:''}<td><a href="#" data-open="${w.workOrderId}"><b>${esc(w.workOrderNo)}</b></a></td><td>${esc(w.unitCode)}</td><td>${esc(w.workType)}</td><td>${esc(w.customerName)}</td><td>${esc(w.location||'-')}</td><td>${esc(w.serialNumbers||'-')}</td><td>${esc(w.chiefName||'-')}</td><td>${esc(w.assignedStaff||'Atanmadı')}</td><td>${statusBadge(w.status)}</td><td>${can('workorders.plan')?`<button class="btn soft" data-plan="${w.workOrderId}">Planla</button>`:fmtPlanDate(w.planDate)}</td></tr>`).join('')}</tbody></table></div>`;
}
function workOrdersPage(){
  const rows=filteredWorkOrders();
  const counts=state.workOrders.filter(x=>unitAllowed(x.unitCode));
  const service=counts.filter(x=>!isMaintenanceOrder(x)&&reportIsOpen(x)).length;
  const maintenance=counts.filter(x=>isMaintenanceOrder(x)&&reportIsOpen(x)).length;
  return `<div class="report-section-head"><div><b>İş Emirleri</b><span class="subtle">Günlük servis ve planlı bakım ayrı listelenir.</span></div><div class="report-tiny-counts"><span>Servis açık <b>${service}</b></span><span>Bakım açık <b>${maintenance}</b></span></div></div>
  <div class="toolbar report-category-tabs"><button class="tabbtn ${state.workKind==='service'?'active':''}" data-workkind="service">Günlük Servis / Arıza</button><button class="tabbtn ${state.workKind==='maintenance'?'active':''}" data-workkind="maintenance">Planlı / Yıllık Bakım</button><button class="tabbtn ${state.workKind==='all'?'active':''}" data-workkind="all">Tümü (isteğe bağlı)</button></div>
  <div class="toolbar"><button class="tabbtn ${state.workStatusGroup==='open'?'active':''}" data-workstatus="open">Açık İşler</button><button class="tabbtn ${state.workStatusGroup==='done'?'active':''}" data-workstatus="done">Tamamlananlar</button><button class="tabbtn ${state.workStatusGroup==='all'?'active':''}" data-workstatus="all">Tüm Durumlar</button><div class="spacer"></div></div>
  <div class="toolbar"><button class="tabbtn ${state.workFilter==='all'?'active':''}" data-filter="all">Tüm Birimler</button>${availableUnits().map(u=>`<button class="tabbtn ${state.workFilter===u?'active':''}" data-filter="${esc(u)}">${esc(u)}</button>`).join('')}<div class="spacer"></div><input class="role-select" id="workSearch" placeholder="Müşteri, iş emri, cihaz veya lokasyon ara..." style="min-width:280px"></div>
  ${can('workorders.assign')?`<div class="bulk-assign-bar"><span><b id="assignmentSelectedCount">${state.assignmentSelectedIds.length}</b> iş emri seçildi</span><span class="subtle">İşaretle → ekibi seç → toplu ata</span><button class="btn primary" id="bulkAssignButton" ${state.assignmentSelectedIds.length?'':'disabled'}>Seçilenlere Toplu Atama</button><button class="btn" id="clearAssignmentSelection">Temizle</button></div>`:''}
  <div class="panel"><div class="panel-h">${state.workKind==='service'?'Günlük Servis':state.workKind==='maintenance'?'Planlı Bakım':'Tüm İşler'} <span class="badge b-blue">${rows.length}</span></div><div class="panel-b" id="workTableHost">${workTable(rows)}</div></div>`;
}

function isoLocal(d){
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function dateFromIso(v){
  if(!v) return null;
  const m=String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if(!m) return null;
  return new Date(Number(m[1]),Number(m[2])-1,Number(m[3]),12,0,0,0);
}
function addLocalDays(d,n){ const x=new Date(d); x.setDate(x.getDate()+n); return x; }
function mondayOf(d){ const x=new Date(d); const day=x.getDay()||7; x.setDate(x.getDate()-day+1); x.setHours(12,0,0,0); return x; }
function monthTitle(d){ return d.toLocaleDateString('tr-TR',{month:'long',year:'numeric'}); }
function dayTitle(d){ return d.toLocaleDateString('tr-TR',{weekday:'short',day:'2-digit',month:'2-digit'}); }
function fullDayTitle(d){ return d.toLocaleDateString('tr-TR',{weekday:'long',day:'numeric',month:'long',year:'numeric'}); }
function planMinutes(w){
  const t=String(w.startTime||'09:00').slice(0,5).split(':').map(Number);
  return (t[0]||0)*60+(t[1]||0);
}
function planEndMinutes(w){ return planMinutes(w)+Number(w.estimatedMinutes||60); }
function assignedNames(w){ return String(w.assignedStaff||'').split(',').map(x=>x.trim()).filter(Boolean); }
function planningFilteredRows(){
  let rows=state.workOrders.filter(w=>isOpen(w) && unitAllowed(w.unitCode));
  if(state.planningUnit!=='all') rows=rows.filter(w=>w.unitCode===state.planningUnit);
  if(state.planningKind!=='all') rows=rows.filter(w=>reportKind(w)===state.planningKind);
  if(state.planningPerson!=='all') rows=rows.filter(w=>w.chiefName===state.planningPerson || assignedNames(w).includes(state.planningPerson));
  return rows;
}
// Aynı müşteri + aynı lokasyon + aynı birim: saha ziyaretini toplu planlayabiliriz.
function bulkLocationKey(w){
  if(!String(w.location||'').trim() || !String(w.customerName||'').trim()) return null;
  return [w.customerName,w.location,w.unitCode].map(v=>String(v).trim().toLocaleLowerCase('tr-TR')).join('\u001f');
}
function groupedWaitingJobs(rows){
  const byLocation=new Map();
  for(const w of rows){
    const key=bulkLocationKey(w);
    const actualKey=key||`tek-${w.workOrderId}`;
    if(!byLocation.has(actualKey))byLocation.set(actualKey,{key,customer:w.customerName,location:w.location,unit:w.unitCode,jobs:[]});
    byLocation.get(actualKey).jobs.push(w);
  }
  return [...byLocation.values()].sort((a,b)=>b.jobs.length-a.jobs.length || String(a.customer).localeCompare(String(b.customer),'tr'));
}
// Bir toplu ziyaretteki ayrı cihaz emirleri sahte teknisyen/araç çakışması sayılmamalı.
function isSameBulkVisit(a,b){
  const group=String(a.routeGroupNo||'');
  return group.startsWith('TPL-') && group===String(b.routeGroupNo||'') &&
    a.planDate===b.planDate && String(a.startTime||'')===String(b.startTime||'') &&
    bulkLocationKey(a)===bulkLocationKey(b) && bulkLocationKey(a)!==null;
}
function planningConflictIds(rows){
  const ids=new Set();
  const planned=rows.filter(w=>w.planDate);
  for(let i=0;i<planned.length;i++) for(let j=i+1;j<planned.length;j++){
    const a=planned[i], b=planned[j];
    if(a.planDate!==b.planDate || isSameBulkVisit(a,b)) continue;
    const overlap=planMinutes(a)<planEndMinutes(b) && planMinutes(b)<planEndMinutes(a);
    if(!overlap) continue;
    const vehicle=!!a.vehiclePlate && !!b.vehiclePlate && a.vehiclePlate===b.vehiclePlate;
    const aa=assignedNames(a), bb=assignedNames(b);
    const person=aa.some(x=>bb.includes(x)) || (!!a.chiefName && a.chiefName===b.chiefName);
    if(vehicle||person){ ids.add(String(a.workOrderId)); ids.add(String(b.workOrderId)); }
  }
  return ids;
}
function planningCard(w,conflicts,compact=false){
  const isMaint=String(w.workOrderNo||'').startsWith('PB-') || /planlı bakım/i.test(w.workType||'');
  const classes=['calendar-card',w.unitCode==='Haberleşme'?'comms':'',conflicts.has(String(w.workOrderId))?'conflict':'',compact?'compact':''].filter(Boolean).join(' ');
  const time=(w.startTime||'09:00').slice(0,5);
  const mins=Number(w.estimatedMinutes||0);
  const duration=mins?`${mins>=60?(mins/60)+' sa':mins+' dk'}`:'';
  return `<button class="${classes}" data-open="${w.workOrderId}" title="${esc(w.customerName)} • ${esc(w.location||'')}">
    <div class="calendar-card-top"><b>${esc(time)}</b>${isMaint?'<span class="badge b-purple">Bakım</span>':statusBadge(w.status)}</div>
    <div class="calendar-card-title">${esc(w.customerName)}</div>
    <div class="calendar-card-sub">${esc(w.location||'-')} • ${esc(w.workType||'-')}</div>
    ${compact?'':`<div class="calendar-card-meta">${esc(w.assignedStaff||'Atanmadı')}${w.vehiclePlate?` • ${esc(w.vehiclePlate)}`:''}${duration?` • ${esc(duration)}`:''}</div>`}
  </button>`;
}
function planningWaitingCard(w,canBulk){
  const checked=state.bulkSelectedIds.includes(Number(w.workOrderId));
  return `<div class="request-card bulk-request"><div class="request-top"><b>${esc(w.workOrderNo)}</b>${statusBadge(w.status)}</div>
    <div class="request-meta">${esc(w.workType||'-')} • ${esc(w.subject||'-')}</div>
    <div class="request-meta">${esc(w.serialNumbers||'Seri no girilecek')}</div>
    <div class="bulk-request-actions">${canBulk?`<label class="bulk-pick"><input type="checkbox" data-bulk-select="${w.workOrderId}" ${checked?'checked':''}> Seç</label>`:'<small class="subtle">Lokasyon girilmeli</small>'}
      <button class="btn soft request-plan-btn" data-plan="${w.workOrderId}">Tek Planla</button></div></div>`;
}
function planningWaitingGroupsHtml(waiting){
  const groups=groupedWaitingJobs(waiting);
  return groups.map(g=>{
    const ids=g.jobs.map(w=>Number(w.workOrderId));
    const selected=ids.every(id=>state.bulkSelectedIds.includes(id));
    const eligible=!!g.key;
    return `<div class="waiting-group"><label class="waiting-group-head">
      ${eligible?`<input type="checkbox" data-bulk-group="${ids[0]}" ${selected?'checked':''} aria-label="Bu lokasyondaki tüm işleri seç">`:''}
      <span class="waiting-group-title"><strong>${esc(g.customer)}</strong><span>${esc(g.location||'Lokasyon belirtilmemiş')} • ${esc(g.unit)}</span></span>
      <span class="badge b-blue">${g.jobs.length} iş</span></label>
      <details class="waiting-group-details"><summary>${g.jobs.length} cihaz / iş emrini göster</summary>
      <div class="waiting-group-items">${g.jobs.map(w=>planningWaitingCard(w,eligible)).join('')}</div></details></div>`;
  }).join('');
}
// V1.11: Bir saha/konum için aynı gündeki çoklu cihazları tek ziyaret kartında göster.
function calendarDayVisits(jobs,iso){
  const byPlace=new Map();
  for(const w of jobs){
    const city=String(w.siteCity||'').trim();
    const site=String(w.siteName||w.location||'Lokasyon belirtilmemiş').trim();
    const key=[w.unitCode,w.customerName,site,city].map(v=>String(v).toLocaleLowerCase('tr-TR')).join('\u001f');
    if(!byPlace.has(key))byPlace.set(key,{city,site,unit:w.unitCode,customer:w.customerName,jobs:[],date:iso});
    byPlace.get(key).jobs.push(w);
  }
  const visits=[...byPlace.values()].sort((a,b)=>Math.min(...a.jobs.map(planMinutes))-Math.min(...b.jobs.map(planMinutes)));
  for(let idx=0;idx<visits.length;idx++){
    visits[idx].id=`${iso}-${idx}`;
    state.planningVisitGroups[visits[idx].id]=visits[idx];
  }
  return visits;
}
function visitGroupCard(g,conflicts,compact=false){
  const starts=g.jobs.map(planMinutes),earliest=Math.min(...starts);
  const time=`${String(Math.floor(earliest/60)).padStart(2,'0')}:${String(earliest%60).padStart(2,'0')}`;
  const conflictsHere=g.jobs.some(w=>conflicts.has(String(w.workOrderId)));
  const isMaint=g.jobs.every(w=>reportKind(w)==='maintenance');
  const label=isMaint?'Bakım':g.jobs.every(w=>reportKind(w)==='service')?'Servis':'Karma';
  const city=g.city||'Şehir belirtilmemiş';
  const teams=[...new Set(g.jobs.map(w=>String(w.assignedStaff||'').trim()).filter(Boolean))];
  return `<button class="calendar-card calendar-visit ${compact?'compact':''} ${conflictsHere?'conflict':''}" data-calvisit="${esc(g.id)}" title="${esc(g.customer)} • ${esc(g.site)} • ${g.jobs.length} iş emri">
    <div class="calendar-card-top"><b>${esc(time)}</b><span class="badge ${isMaint?'b-purple':'b-blue'}">${label} · ${g.jobs.length}</span></div>
    <div class="calendar-card-title">${esc(g.customer)}</div>
    <div class="calendar-card-sub"><strong>${esc(city)}</strong> · ${esc(g.site)}</div>
    ${compact?'':`<div class="calendar-card-meta">${g.jobs.length} cihaz/iş · ${teams.length===1?esc(teams[0]):teams.length>1?teams.length+' ekip':'Atanmadı'}</div>`}
  </button>`;
}
function openCalendarVisit(id){
  const g=state.planningVisitGroups[id];if(!g)return;
  modal(`<div class="modal-h"><div><b>${esc(g.customer)} · ${esc(g.city||'Şehir girilmemiş')}</b><div class="subtle">${esc(g.site)} · ${g.jobs.length} ayrı iş emri · ${esc(g.date)}</div></div><button class="iconbtn" id="modalX">×</button></div>
    <div class="modal-b"><div class="notice">Takvimde tek ziyaret olarak gösterilir. Her cihazın iş emri, teknisyen kaydı ve bakım formu bağımsızdır.</div>
    <div class="visit-job-list">${g.jobs.sort((a,b)=>planMinutes(a)-planMinutes(b)).map(w=>`<div class="visit-job"><div><strong>${esc(w.workOrderNo)}</strong><div class="subtle">${esc((w.startTime||'09:00').slice(0,5))} · ${esc(w.workType)} · ${esc(w.serialNumbers||w.subject||'')}</div><div class="subtle">${esc(w.siteArea||w.location||'')} · ${esc(w.assignedStaff||'Atanmadı')}</div></div><button class="btn soft" data-visitopen="${w.workOrderId}">Aç</button></div>`).join('')}</div></div>
    <div class="modal-f"><button class="btn" id="visitClose">Kapat</button></div>`);
  $('#modalX').onclick=$('#visitClose').onclick=closeModal;
  $$('[data-visitopen]').forEach(btn=>btn.onclick=()=>openWorkOrder(btn.dataset.visitopen));
}
function planningWeekView(planned,conflicts,anchor){
  const monday=mondayOf(anchor);
  const days=Array.from({length:7},(_,i)=>addLocalDays(monday,i));
  return `<div class="calendar-week-grid">${days.map(d=>{
    const iso=isoLocal(d); const items=planned.filter(w=>w.planDate===iso);
    const visits=calendarDayVisits(items,iso);const isToday=iso===todayIso();
    return `<div class="calendar-day ${isToday?'today':''}"><div class="calendar-day-head"><b>${esc(dayTitle(d))}</b><span>${visits.length} lokasyon · ${items.length} iş</span></div><div class="calendar-day-body">${visits.length?visits.slice(0,4).map(g=>visitGroupCard(g,conflicts)).join(''):'<div class="calendar-empty">Planlı iş yok</div>'}${visits.length>4?`<button class="calendar-more" data-planday="${iso}">+${visits.length-4} lokasyon daha</button>`:''}</div></div>`;
  }).join('')}</div>`;
}
function planningDayView(planned,conflicts,anchor){
  const iso=isoLocal(anchor);const items=planned.filter(w=>w.planDate===iso);
  const visits=calendarDayVisits(items,iso);
  return `<div class="calendar-day-focus"><div class="calendar-focus-title">${esc(fullDayTitle(anchor))} <span class="badge b-blue">${visits.length} lokasyon / ${items.length} iş</span></div><div class="calendar-day-list">${visits.length?visits.map(g=>visitGroupCard(g,conflicts)).join(''):'<div class="calendar-empty large">Bu gün için planlı iş yok.</div>'}</div></div>`;
}
function planningMonthView(planned,conflicts,anchor){
  const first=new Date(anchor.getFullYear(),anchor.getMonth(),1,12); const start=mondayOf(first);
  const days=Array.from({length:42},(_,i)=>addLocalDays(start,i));
  return `<div class="calendar-month-weekdays">${['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'].map(x=>`<b>${x}</b>`).join('')}</div><div class="calendar-month-grid">${days.map(d=>{
    const iso=isoLocal(d);const items=planned.filter(w=>w.planDate===iso);
    const visits=calendarDayVisits(items,iso);
    const muted=d.getMonth()!==anchor.getMonth(),today=iso===todayIso();
    return `<div class="calendar-month-cell ${muted?'muted':''} ${today?'today':''}"><div class="calendar-month-date">${d.getDate()} · ${visits.length} yer</div>${visits.slice(0,3).map(g=>visitGroupCard(g,conflicts,true)).join('')}${visits.length>3?`<button class="calendar-more" data-planday="${iso}">+${visits.length-3} lokasyon</button>`:''}</div>`;
  }).join('')}</div>`;
}
function planningPage(){
  const rows=planningFilteredRows();
  const planned=rows.filter(w=>w.planDate);
  const waiting=rows.filter(w=>!w.planDate && !['Tamamlandı','Kapatıldı','İptal'].includes(w.status));
  const searchText=state.planningCustomerSearch.trim().toLocaleLowerCase('tr-TR');
  const visibleWaiting=searchText?waiting.filter(w=>[w.customerName,w.location,w.workOrderNo,w.subject,w.serialNumbers].some(x=>String(x||'').toLocaleLowerCase('tr-TR').includes(searchText))):waiting;
  const conflicts=planningConflictIds(rows);
  const anchor=dateFromIso(state.planningAnchor)||dateFromIso(todayIso());
  const people=[...new Set(rows.flatMap(w=>[w.chiefName,...assignedNames(w)]).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'tr'));
  const todayCount=planned.filter(w=>w.planDate===todayIso()).length;
  const weekStart=mondayOf(dateFromIso(todayIso())); const weekEnd=addLocalDays(weekStart,6);
  const weekCount=planned.filter(w=>{const d=dateFromIso(w.planDate);return d&&d>=weekStart&&d<=weekEnd;}).length;
  let label=state.planningMode==='month'?monthTitle(anchor):state.planningMode==='day'?fullDayTitle(anchor):`${fmtPlanDate(isoLocal(mondayOf(anchor)))} – ${fmtPlanDate(isoLocal(addLocalDays(mondayOf(anchor),6)))}`;
  state.planningVisitGroups={};
  const main=state.planningMode==='day'?planningDayView(planned,conflicts,anchor):state.planningMode==='month'?planningMonthView(planned,conflicts,anchor):planningWeekView(planned,conflicts,anchor);
  return `<div class="planner-kpis"><button class="mini-kpi kpi-button" data-kpidetail="planToday"><b>${todayCount}</b><span>Bugün planlı</span></button><button class="mini-kpi kpi-button" data-kpidetail="planWeek"><b>${weekCount}</b><span>Bu hafta</span></button><button class="mini-kpi kpi-button" data-kpidetail="planTotal"><b>${planned.length}</b><span>Toplam planlı</span></button><button class="mini-kpi kpi-button ${conflicts.size?'conflict':''}" data-kpidetail="planConflict"><b>${conflicts.size}</b><span>Çakışmalı iş</span></button><button class="mini-kpi kpi-button" data-kpidetail="planWaiting"><b>${waiting.length}</b><span>Plan bekleyen</span></button></div>
  <div class="toolbar report-category-tabs"><button class="tabbtn ${state.planningKind==='service'?'active':''}" data-plankind="service">Günlük Servis Planı</button><button class="tabbtn ${state.planningKind==='maintenance'?'active':''}" data-plankind="maintenance">Planlı Bakım Planı</button><button class="tabbtn ${state.planningKind==='all'?'active':''}" data-plankind="all">Tüm Planlar</button></div>
  <div class="planning-toolbar calendar-toolbar">
    <button class="btn soft" data-calnav="prev">←</button><button class="btn" data-calnav="today">Bugün</button><button class="btn soft" data-calnav="next">→</button>
    <div class="calendar-period-label">${esc(label)}</div><div class="spacer"></div>
    <select id="planningUnit"><option value="all">Tüm Birimler</option>${availableUnits().map(u=>`<option value="${esc(u)}" ${state.planningUnit===u?'selected':''}>${esc(u)}</option>`).join('')}</select>
    <select id="planningPerson"><option value="all">Tüm Personel</option>${people.map(x=>`<option ${state.planningPerson===x?'selected':''}>${esc(x)}</option>`).join('')}</select>
    <div class="tabbar compact-tabs"><button class="tabbtn ${state.planningMode==='day'?'active':''}" data-calmode="day">Gün</button><button class="tabbtn ${state.planningMode==='week'?'active':''}" data-calmode="week">Hafta</button><button class="tabbtn ${state.planningMode==='month'?'active':''}" data-calmode="month">Ay</button></div>
  </div>
  <div class="calendar-layout"><div class="panel"><div class="panel-h">Planlama Takvimi ${conflicts.size?'<span class="badge b-red">Çakışma var</span>':''}</div><div class="panel-b calendar-panel">${main}</div></div>
  <div class="panel waiting-panel"><div class="panel-h bulk-waiting-head"><span>Planlanmayı Bekleyenler</span><span class="badge b-amber">${waiting.length}</span></div>
    <div class="bulk-action-bar"><span><b id="bulkSelectedCount">${state.bulkSelectedIds.length}</b> iş seçildi</span>${can('workorders.assign')?`<button class="btn soft" id="bulkWaitingAssignButton" ${!state.bulkSelectedIds.length?'disabled':''}>Toplu Ekip Ata</button>`:''}${can('workorders.plan')&&can('workorders.assign')?`<button class="btn primary" id="bulkPlanButton" ${!state.bulkSelectedIds.length?'disabled':''}>Toplu Planla + Ata</button>`:''}</div>
    <div class="planning-search"><label for="planningCustomerSearch">Müşteri / Firma / Lokasyon Ara</label><input id="planningCustomerSearch" type="search" placeholder="Örn. AKYAKA, İstanbul, seri no..." value="${esc(state.planningCustomerSearch)}" autocomplete="off"><small>${visibleWaiting.length} / ${waiting.length} kayıt listeleniyor</small></div>
    <div class="panel-b waiting-list">${visibleWaiting.length?planningWaitingGroupsHtml(visibleWaiting):'<div class="calendar-empty">Aramayla eşleşen iş yok.</div>'}</div>
  </div></div>`;
}


function securityDevicesPage(){
  const all=state.securityDevices||[];
  const types=[...new Set(all.map(x=>x.deviceType).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'tr'));
  const brands=[...new Set(all.map(x=>x.brand).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'tr'));
  const models=[...new Set(all.filter(x=>state.securityBrand==='all'||x.brand===state.securityBrand).map(x=>x.model).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'tr'));
  const q=(state.securitySearch||'').toLocaleLowerCase('tr-TR');
  let rows=all.filter(x=>(state.securityType==='all'||x.deviceType===state.securityType) &&
                         (state.securityBrand==='all'||x.brand===state.securityBrand) &&
                         (state.securityModel==='all'||x.model===state.securityModel));
  if(q) rows=rows.filter(x=>[x.serialNo,x.customerName,x.location,x.model,x.contactName].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(q)));
  const xray=all.filter(x=>x.deviceType==='X-Ray').length;
  const door=all.filter(x=>x.deviceType==='Kapı Dedektörü').length;
  const withSerial=all.filter(x=>x.serialNo).length;
  return `<div class="kpis"><div class="kpi"><div class="label">Toplam Kütük</div><div class="num">${all.length}</div></div><div class="kpi"><div class="label">X-Ray</div><div class="num">${xray}</div></div><div class="kpi"><div class="label">Kapı Dedektörü</div><div class="num">${door}</div></div><div class="kpi"><div class="label">Seri No Mevcut</div><div class="num">${withSerial}</div></div></div>
  <div class="toolbar">
    <select id="secType"><option value="all">Tüm Cihaz Tipleri</option>${types.map(x=>`<option ${x===state.securityType?'selected':''}>${esc(x)}</option>`).join('')}</select>
    <select id="secBrand"><option value="all">Tüm Markalar</option>${brands.map(x=>`<option ${x===state.securityBrand?'selected':''}>${esc(x)}</option>`).join('')}</select>
    <select id="secModel"><option value="all">Tüm Modeller</option>${models.map(x=>`<option ${x===state.securityModel?'selected':''}>${esc(x)}</option>`).join('')}</select>
    <div class="spacer"></div><input id="secSearch" value="${esc(state.securitySearch)}" placeholder="Seri no, müşteri, lokasyon ara..." style="min-width:300px">
  </div>
  <div class="panel"><div class="panel-h">Güvenlik Cihaz Kütüğü <span class="badge b-blue">${rows.length}</span></div><div class="panel-b">
  <div class="notice">Kaynak X-Ray / güvenlik cihaz kütüğü sisteme aktarıldı. Marka ve model filtreleri kütükteki mevcut veriden otomatik oluşur.</div>
  <div class="table-scroll" style="margin-top:12px"><table><thead><tr><th>Tip</th><th>Marka</th><th>Model</th><th>Seri No</th><th>Müşteri</th><th>Lokasyon</th><th>İlgili Kişi</th><th>Kurulum</th></tr></thead><tbody>${rows.slice(0,1000).map(d=>`<tr><td>${esc(d.deviceType)}</td><td>${esc(d.brand)}</td><td>${esc(d.model)}</td><td><b>${esc(d.serialNo||'-')}</b></td><td>${esc(d.customerName||'-')}</td><td>${esc(d.location||'-')}</td><td>${esc(d.contactName||'-')}</td><td>${esc(d.installStatus||'-')}</td></tr>`).join('')}</tbody></table></div>
  ${rows.length>1000?`<div class="subtle" style="margin-top:8px">İlk 1000 kayıt gösteriliyor. Filtre veya arama ile daraltabilirsiniz.</div>`:''}
  </div></div>`;
}

async function openMaintenanceDevices(planId){
  try{
    let rows=await api(`/api/maintenance/plans/${planId}/devices`);
    const canManage=can('maintenance.manage');
    const wrap=document.createElement('div');
    wrap.className='modal-backdrop';wrap.id='maintenanceDeviceOverlay';
    wrap.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.58);z-index:10000;overflow:auto;padding:4vh 3vw;display:flex;justify-content:center;align-items:flex-start';
    const show=()=>{
      const completed=rows.filter(x=>x.status==='Tamamlandı').length;
      wrap.innerHTML=`<div style="background:white;color:#173456;border-radius:12px;padding:22px;width:min(1100px,100%);max-height:90vh;overflow:auto">
        <div style="display:flex;justify-content:space-between;gap:15px;align-items:center"><div><h2 style="margin:0">Cihaz İş Emirleri • ${completed}/${rows.length} Tamamlandı</h2><p class="subtle">Her cihazın ayrı PB iş emri vardır. Seri no, bulunduğu bölge ve kontrol listesi cihazın kendi formuna kaydedilir.</p></div><button class="btn" id="closeMaintenanceDevices">Kapat</button></div>
        ${rows.length?`<div class="table-scroll"><table><thead><tr><th>PB İş Emri</th><th>Cihaz</th><th>Seri No</th><th>Bölge</th><th>Durum</th><th>İşlem</th></tr></thead><tbody>
        ${rows.map(r=>`<tr><td><b>${esc(r.workOrderNo||'Atanmadı')}</b></td><td>${esc(r.deviceType)} #${r.ordinal}</td><td>${esc(r.serialNo||'Girilecek')}</td><td>${esc(r.zone||'-')}</td><td>${statusBadge(r.status)}</td><td>${r.workOrderId?`<button class="btn soft" data-maintform="${r.workOrderId}">${r.status==='Tamamlandı'?'Formu Gör':'Bakım Formu Aç'}</button>`:'-'}</td></tr>`).join('')}
        </tbody></table></div>`:'<div class="notice">Henüz cihaz iş emri üretilmemiş.</div>'}
        ${canManage?`<div class="actions"><button class="btn primary" id="initMaintenanceDevices">Eksik Cihaz İş Emirlerini Oluştur / Kontrol Et</button></div>`:''}
      </div>`;
      wrap.querySelector('#closeMaintenanceDevices').onclick=()=>wrap.remove();
      wrap.querySelector('#initMaintenanceDevices')?.addEventListener('click',async()=>{try{
        const r=await api(`/api/maintenance/plans/${planId}/devices/initialize`,{method:'POST'});
        rows=await api(`/api/maintenance/plans/${planId}/devices`);await reloadWork();
        if(can('maintenance.view'))state.maintenanceContracts=await api('/api/maintenance/contracts');
        show();alert(r.message);
      }catch(e){alert(e.message);}});
      wrap.querySelectorAll('[data-maintform]').forEach(btn=>btn.onclick=async()=>{
        wrap.remove();await openMaintenanceForm(btn.dataset.maintform);
      });
    };
    document.body.appendChild(wrap);show();
  }catch(e){alert(e.message);}
}

async function openMaintenanceForm(workOrderId){
  try{
    const detail=await api(`/api/maintenance/workorders/${workOrderId}/form`);
    const f=detail.form,checks=detail.checks||[];
    const readonly=f.workOrderStatus==='Kapatıldı' || !(can('workorders.close')||can('maintenance.manage'));
    const resultOpts=['','Tamamlandı','Tekrar Gidilecek','Teklif Sunulacak','Servise Alındı','Servis İptal'];
    modal(`<div class="modal-h"><div><b>${esc(f.workOrderNo)} • ${esc(f.deviceType)} #${f.deviceOrdinal}</b><div class="subtle">DENGE ELEKTRONİK | DİJİTAL TEKNİK SERVİS / PLANLI BAKIM FORMU</div></div><button class="iconbtn" id="modalX">×</button></div>
      <div class="modal-b">
      <div class="review-summary"><div><span>Firma / Kurum</span><b>${esc(f.customerName)}</b></div><div><span>Cihaz</span><b>${esc(f.deviceType)}</b></div><div><span>Marka / Model</span><b>${esc([f.brand,f.model].filter(Boolean).join(' / ')||'-')}</b></div><div><span>Durum</span>${statusBadge(f.workOrderStatus)}</div></div>
      <div class="form-card"><div class="form-h">Cihaz ve Servis Bilgileri</div><div class="form-grid">
        <div class="field span2"><label>Seri Numarası *</label><input id="maintSerial" type="text" inputmode="text" maxlength="200" value="${esc(f.serialNo||'')}" placeholder="Cihaz etiketindeki seri numarası" ${readonly?'readonly':''}></div>
        <div class="field span2"><label>Bulunduğu Bölge / Konum *</label><input id="maintZone" maxlength="250" value="${esc(f.zone||'')}" placeholder="Örnek: A kapısı / Giriş 2 / B1" ${readonly?'readonly':''}></div>
        <div class="field span4"><label>Firma adresi (bilgi)</label><input readonly value="${esc(f.customerAddress||'-')}"></div>
      </div></div>
      <div class="form-card"><div class="form-h">${f.deviceType==='X-Ray'?'X-Ray':'Kapı Tipi Metal Dedektörü'} • Teknik Bakım Kontrol Listesi</div>
        <p class="subtle">Yalnızca gerçekten kontrol ettiğin maddeyi işaretle. Uygunsuz veya test edilemeyen kontroller açıkça kaydedilmeli.</p>
        ${!readonly?'<div class="actions"><button class="btn soft" type="button" id="maintAllOk">Kontrol Edilenlerin Tümünü Uygun İşaretle</button></div>':''}
        <div class="table-scroll"><table><thead><tr><th>Kontrol</th><th>Değerlendirme</th></tr></thead><tbody>
        ${checks.map(c=>`<tr><td>${esc(c.label)}</td><td><div class="maintenance-check-control"><label class="maintenance-ok-label"><input type="checkbox" data-maintok="${esc(c.code)}" ${c.result==='Uygun'?'checked':''} ${readonly?'disabled':''}> Uygun ✓</label><select data-maintcheck="${esc(c.code)}" ${readonly?'disabled':''} aria-label="${esc(c.label)} değerlendirme">
          ${['Bekliyor','Uygun','Uygunsuz','Kontrol Edilemedi'].map(o=>`<option value="${esc(o)}" ${c.result===o?'selected':''}>${esc(o)}</option>`).join('')}
        </select></div></td></tr>`).join('')}
        </tbody></table></div>
      </div>
      <div class="form-card"><div class="form-h">Şirket Teknik Servis Formu • Yapılan İşlem ve Sonuç</div><div class="form-grid">
        <div class="field span4"><label>Yapılan İşlem / Bakım Detayı</label><textarea id="maintPerformed" ${readonly?'readonly':''} placeholder="Yapılan kontrol, temizlik, test veya müdahaleler">${esc(f.performedWork||'')}</textarea></div>
        <div class="field span4"><label>Kullanılan Yedek Parçalar (varsa)</label><textarea id="maintParts" ${readonly?'readonly':''} placeholder="Parça adı ve adet">${esc(f.spareParts||'')}</textarea></div>
        <div class="field span4"><label>Teknisyen Notu / Tespitler *</label><textarea id="maintNotes" maxlength="1000" ${readonly?'readonly':''} placeholder="Cihazın durumu, uygunsuzluklar ve açıklamalar">${esc(f.notes||'')}</textarea></div>
        <div class="field span2"><label>Servis Sonucu *</label><select id="maintResult" ${readonly?'disabled':''}>${resultOpts.map(o=>`<option value="${esc(o)}" ${f.serviceResult===o?'selected':''}>${esc(o||'Seçiniz')}</option>`).join('')}</select></div>
        <div class="field span2"><label>Kapatma Kaydı</label><input readonly value="${esc(f.completedBy||'Henüz kapanmadı')} ${f.completedAt?fmtDate(f.completedAt):''}"></div>
      </div></div>
      <div class="notice">Tamamlandı sonucuyla kapatmak için seri numarası, bölge, not ve bütün teknik maddeler doldurulmalıdır. Uygunsuzluk varsa iş emri takip için açık kalır.</div>
      </div>
      <div class="modal-f"><button class="btn" id="closeMaintenanceForm">Kapat</button>${readonly?'':`<button class="btn soft" id="maintDraft">Taslak Kaydet</button><button class="btn primary" id="maintFinish">Formu Tamamla / İş Emrini Kapat</button>`}</div>`);
    $('#modalX').onclick=$('#closeMaintenanceForm').onclick=closeModal;
    if(readonly)return;
    // Hızlı işaretleme, kontrol gerçekten yapıldıysa kullanılmalı.
    $$('[data-maintok]').forEach(cb=>cb.addEventListener('change',()=>{
      const select=$$('[data-maintcheck]').find(x=>x.dataset.maintcheck===cb.dataset.maintok);
      if(select)select.value=cb.checked?'Uygun':'Bekliyor';
    }));
    $$('[data-maintcheck]').forEach(sel=>sel.addEventListener('change',()=>{
      const cb=$$('[data-maintok]').find(x=>x.dataset.maintok===sel.dataset.maintcheck);
      if(cb)cb.checked=sel.value==='Uygun';
    }));
    $('#maintAllOk').onclick=()=>{if(confirm('Yalnızca tüm maddeleri GERÇEKTEN kontrol edip uygun bulduysanız onaylayın.'))
      $$('[data-maintcheck]').forEach(el=>{if(el.value==='Bekliyor')el.value='Uygun';});
      $$('[data-maintok]').forEach(el=>{const sel=$$('[data-maintcheck]').find(x=>x.dataset.maintcheck===el.dataset.maintok);el.checked=sel?.value==='Uygun';});};
    const save=async complete=>{
      const payload={serialNo:$('#maintSerial').value.trim(),zone:$('#maintZone').value.trim(),notes:$('#maintNotes').value.trim(),
        performedWork:$('#maintPerformed').value.trim(),spareParts:$('#maintParts').value.trim(),serviceResult:$('#maintResult').value,complete,
        checks:$$('[data-maintcheck]').map(x=>({code:x.dataset.maintcheck,result:x.value}))};
      try{
        const r=await api(`/api/maintenance/workorders/${workOrderId}/form`,{method:'POST',body:JSON.stringify(payload)});
        await reloadWork();if(can('maintenance.view'))state.maintenanceContracts=await api('/api/maintenance/contracts');
        closeModal();render();alert(r.message);
      }catch(e){alert(e.message);}
    };
    $('#maintDraft').onclick=()=>save(false);
    $('#maintFinish').onclick=()=>save(true);
  }catch(e){alert(e.message);}
}

function maintenancePage(){
  const contracts=state.maintenanceContracts||[];
  const openRows=state.workOrders.filter(w=>String(w.workOrderNo||'').startsWith('PB-') || w.workType==='Planlı Bakım');
  const overdue=contracts.filter(c=>c.nextTargetDate && new Date(c.nextTargetDate+'T00:00:00')<=new Date() && !c.nextCompleted).length;
  return `<div class="toolbar">${can('maintenance.manage')?'<button class="btn primary" id="generateMaintenance">Vadesi Gelen Cihaz İş Emirlerini Oluştur</button>':''}<div class="spacer"></div><span class="badge b-blue">${contracts.length} bakım sözleşmesi</span></div>
  <div class="kpis"><div class="kpi"><div class="label">Bakım Sözleşmesi</div><div class="num">${contracts.length}</div></div><div class="kpi"><div class="label">Vadesi Gelen</div><div class="num">${overdue}</div></div><button class="kpi kpi-button" data-kpidetail="maintenanceOpen"><span class="label">Açık PB İş Emri</span><span class="num">${openRows.filter(isOpen).length}</span><span class="kpi-action">Cihaz işleri ↗</span></button><button class="kpi kpi-button" data-kpidetail="maintenanceDone"><span class="label">Tamamlanan PB Cihazı</span><span class="num">${openRows.filter(x=>['Tamamlandı','Kapatıldı'].includes(x.status)).length}</span><span class="kpi-action">Cihaz işleri ↗</span></button></div>
  <div class="panel"><div class="panel-h">2026 Cihaz Bazlı Bakım Planı</div><div class="panel-b"><div class="notice"><b>Her cihaz için tek, bağımsız PB iş emri.</b> Bakım sıklığı ve yapılan bakım adedi esas alınır; sözleşme tarihleri bilgi amaçlıdır. Tamamlanan cihazlar seri numarasıyla izlenir.</div>
  <div class="table-scroll" style="margin-top:12px"><table><thead><tr><th>Firma</th><th>Ürünler</th><th>Sıklık</th><th>Yapılan Dönem</th><th>Sonraki Bakım</th><th>Cihaz İş Emirleri</th>${can('finance.prices.view')?'<th>Ücret</th>':''}</tr></thead><tbody>${contracts.map(c=>`<tr><td><b>${esc(c.customerName)}</b><div class="subtle">${esc(c.currentAddress||'')}</div></td><td>${esc(c.productsText||'-')}</td><td>${esc(c.frequencyText||'-')}</td><td>${c.completedCount}/${c.annualFrequency||'-'}</td><td>${c.nextTargetDate?fmtPlanDate(c.nextTargetDate):'Plan tamamlandı'}</td><td>${c.nextPlanId?`<div><b>${c.deviceCount||0} cihaz iş emri</b> • ${c.deviceCompleted||0} tamamlandı</div><button class="btn soft" data-maintdevices="${c.nextPlanId}">Cihaz İş Emirleri / Bakım Formları</button>`:'-'}</td>${can('finance.prices.view')?`<td>${esc(c.maintenanceFeeText||'-')}</td>`:''}</tr>`).join('')}</tbody></table></div>
  </div></div>`;
}

const workshopBrands=["HYTERA","HYT","HQT","MOTOROLA","KIRISUN","ASELSAN"];
const workshopServiceTypes=["Arıza Onarımı","Garanti Onarımı","Dış Servis","Yazılım / Frekans Güncelleme","Setra - Kiralama Takip"];
const workshopStatuses=["Yeni Kayıt","Onarımda","Beklemede","Test / Kontrol","Tamamlandı","Teslim Edildi","İptal"];
const workshopAccessories=["","ADAPTÖR","ANTEN","ASKI İPİ","BATARYA","KAPAK","KLİPS","KULAKLIK","TAŞIMA ÇANTASI","ŞARJ CİHAZI"];
function accessoryOptions(selected=''){ return workshopAccessories.map(x=>`<option ${x===selected?'selected':''}>${esc(x)}</option>`).join(''); }
function workshopPage(){
  const rows=state.workshopTickets||[];
  return `<div class="toolbar">${can('workshop.manage')?'<button class="btn primary" id="newWorkshopBtn">＋ Yeni Atölye Servis Kaydı</button>':''}<div class="spacer"></div><span class="badge b-blue">${rows.length} kayıt</span></div>
  <div class="panel"><div class="panel-h">Haberleşme Teknik Servis Atölye</div><div class="panel-b"><div class="notice"><b>Logo CRM servis kaydı alanlarıyla uyumlu yapı.</b> Sonraki aşamada Logo CRM'ye otomatik yazma entegrasyonu bu alanlar üzerinden yapılabilir.</div>
  <div class="table-scroll" style="margin-top:12px"><table><thead><tr><th>Atölye No</th><th>İş Emri</th><th>Firma</th><th>Servis Türü</th><th>Marka / Model</th><th>Seri No</th><th>Durum</th><th>Atanan</th><th>Giriş</th><th>İşlem</th></tr></thead><tbody>${rows.map(t=>`<tr><td><b>${esc(t.workshopNo)}</b></td><td>${t.workOrderId?`<a href="#" data-open="${t.workOrderId}">İş Emri</a>`:'-'}</td><td>${esc(t.companyName)}</td><td>${esc(t.serviceType)}</td><td>${esc(t.brand)} ${esc(t.model||'')}</td><td><b>${esc(t.serialNo)}</b></td><td>${statusBadge(t.status)}</td><td>${esc(t.assignedTo||'-')}</td><td>${fmtDate(t.entryDate)}</td><td><button class="btn soft" data-workshopopen="${t.workshopTicketId}">${can('workshop.manage')?'Düzenle':'Görüntüle'}</button></td></tr>`).join('')}</tbody></table></div>
  </div></div>`;
}
function workshopFieldValue(v){ return esc(v??''); }
function openWorkshopModal(id=null){
  const t=id?state.workshopTickets.find(x=>Number(x.workshopTicketId)===Number(id)):null;
  const readonly=!can('workshop.manage');
  const personnel=[...new Set(state.personnel.filter(p=>p.isActive&&(p.unitCode==='Haberleşme'||/Haberleşme/i.test(p.departmentName||''))).map(p=>p.fullName))];
  const brand=t?.brand||'HYTERA', status=t?.status||'Yeni Kayıt', service=t?.serviceType||'Arıza Onarımı';
  modal(`<div class="modal-h"><div><b>${t?esc(t.workshopNo):'Yeni Haberleşme Atölye Servis Kaydı'}</b><div class="subtle">Logo CRM alan yapısına göre</div></div><button class="iconbtn" id="modalX">×</button></div>
  <div class="modal-b"><form id="workshopForm">
  <div class="form-card"><div class="form-h">Firma / Temel Bilgi</div><div class="form-grid">
    <div class="field span2"><label>Firma *</label><input name="companyName" value="${workshopFieldValue(t?.companyName)}" ${readonly?'readonly':''} required></div>
    <div class="field span2"><label>Firma Adresi</label><input name="companyAddress" value="${workshopFieldValue(t?.companyAddress)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Kişi</label><input name="contactName" value="${workshopFieldValue(t?.contactName)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Müşteri E-posta</label><input type="email" name="customerEmail" value="${workshopFieldValue(t?.customerEmail)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Müşteri Telefon</label><input name="customerPhone" value="${workshopFieldValue(t?.customerPhone)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Giriş Tarihi</label><input type="datetime-local" name="entryDate" value="${t?.entryDate?String(t.entryDate).slice(0,16):new Date().toISOString().slice(0,16)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Tahmini Bitiş Tarihi</label><input type="date" name="estimatedFinishDate" value="${workshopFieldValue(t?.estimatedFinishDate)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Logo Form No</label><input name="logoFormNo" value="${workshopFieldValue(t?.logoFormNo)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Ana Servis Kaydı</label><input name="logoMainServiceNo" value="${workshopFieldValue(t?.logoMainServiceNo)}" ${readonly?'readonly':''}></div>
  </div></div>
  <div class="form-card"><div class="form-h">Kategori / Atama / Durum</div><div class="form-grid">
    <div class="field"><label>Entegrasyon Firması</label><input name="integrationCompany" value="${workshopFieldValue(t?.integrationCompany||'Denge Telekom')}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Servis Türü *</label><select name="serviceType" ${readonly?'disabled':''}>${workshopServiceTypes.map(x=>`<option ${x===service?'selected':''}>${esc(x)}</option>`).join('')}</select></div>
    <div class="field"><label>Durum</label><select name="status" ${readonly?'disabled':''}>${workshopStatuses.map(x=>`<option ${x===status?'selected':''}>${esc(x)}</option>`).join('')}</select></div>
    <div class="field"><label>Tamir Bedeli</label><input type="number" step="0.01" name="repairAmount" value="${t?.repairAmount??''}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Teslim Alma Tipi</label><input name="receiveType" value="${workshopFieldValue(t?.receiveType)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Teslim Alan</label><input name="receivedBy" value="${workshopFieldValue(t?.receivedBy)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Teslim Eden</label><input name="deliveredBy" value="${workshopFieldValue(t?.deliveredBy)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Teslim Etme Tipi</label><input name="deliveryType" value="${workshopFieldValue(t?.deliveryType)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Kargo Takip No</label><input name="cargoTrackingNo" value="${workshopFieldValue(t?.cargoTrackingNo)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Atanan</label><select name="assignedTo" ${readonly?'disabled':''}><option value="">Atanmadı</option>${personnel.map(x=>`<option ${x===t?.assignedTo?'selected':''}>${esc(x)}</option>`).join('')}</select></div>
  </div></div>
  <div class="form-card"><div class="form-h">Cihaz / Garanti / Aksesuar</div><div class="form-grid">
    <div class="field"><label>Marka *</label><select name="brand" ${readonly?'disabled':''}>${workshopBrands.map(x=>`<option ${x===brand?'selected':''}>${x}</option>`).join('')}</select></div>
    <div class="field"><label>Model</label><input name="model" value="${workshopFieldValue(t?.model)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Seri No *</label><input name="serialNo" value="${workshopFieldValue(t?.serialNo)}" ${readonly?'readonly':''} required></div>
    <div class="field"><label>Proje Adı</label><input name="projectName" value="${workshopFieldValue(t?.projectName)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Garanti Başlangıç Tarihi</label><input type="date" name="warrantyStartDate" value="${workshopFieldValue(t?.warrantyStartDate)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Garanti Bitiş Tarihi</label><input type="date" name="warrantyEndDate" value="${workshopFieldValue(t?.warrantyEndDate)}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Garanti Durumu</label><input name="warrantyStatus" value="${workshopFieldValue(t?.warrantyStatus||'Garanti Değil')}" ${readonly?'readonly':''}></div>
    ${[1,2,3,4,5].map(n=>`<div class="field"><label>Aksesuar${n===1?'':' '+n}</label><select name="accessory${n}" ${readonly?'disabled':''}>${accessoryOptions(t?.['accessory'+n]||'')}</select></div>`).join('')}
  </div></div>
  <div class="form-card"><div class="form-h">Diğer</div><div class="form-grid">
    <div class="field span2"><label>Notlar</label><textarea name="notes" ${readonly?'readonly':''}>${workshopFieldValue(t?.notes)}</textarea></div>
    <div class="field span2"><label>Müşteri Şikayeti</label><textarea name="customerComplaint" ${readonly?'readonly':''}>${workshopFieldValue(t?.customerComplaint)}</textarea></div>
    <div class="field span2"><label>Cihaz Durumu</label><textarea name="deviceCondition" ${readonly?'readonly':''}>${workshopFieldValue(t?.deviceCondition)}</textarea></div>
    <div class="field span2"><label>Onarım Bilgisi</label><textarea name="repairInfo" ${readonly?'readonly':''}>${workshopFieldValue(t?.repairInfo)}</textarea></div>
  </div></div>
  ${readonly?'':`<div class="actions"><button class="btn primary" type="submit">${t?'Kaydet':'Servis Kaydını Oluştur'}</button></div>`}
  </form></div>`);
  $('#modalX').onclick=closeModal;
  const f=$('#workshopForm'); if(!readonly) f.onsubmit=async e=>{
    e.preventDefault(); const fd=new FormData(f);
    const body={};
    for(const [k,v] of fd.entries()) body[k]=v||null;
    body.repairAmount=fd.get('repairAmount')?Number(fd.get('repairAmount')):null;
    body.entryDate=fd.get('entryDate')||null;
    body.completionDate=(body.status==='Tamamlandı'||body.status==='Teslim Edildi')?new Date().toISOString():t?.completionDate||null;
    try{
      if(t) await api(`/api/workshop/tickets/${t.workshopTicketId}`,{method:'PUT',body:JSON.stringify(body)});
      else await api('/api/workshop/tickets',{method:'POST',body:JSON.stringify(body)});
      state.workshopTickets=await api('/api/workshop/tickets'); await reloadWork(); closeModal(); render();
    }catch(err){alert(err.message);}
  };
}

function rentalCatalogForUnit(unit){
  return state.rentalCatalog.filter(x=>x.unitCode===unit);
}
function rentalProductOptions(unit,selectedId=null){
  const rows=rentalCatalogForUnit(unit);
  const groups=[...new Set(rows.map(x=>x.category))];
  if(!rows.length) return '<option value="">Ürün bulunamadı</option>';
  return groups.map(g=>`<optgroup label="${esc(g)}">${rows.filter(x=>x.category===g).map(x=>`<option value="${x.rentalProductId}" ${Number(x.rentalProductId)===Number(selectedId)?'selected':''}>${esc(x.productCode)} • ${esc(x.productName)}</option>`).join('')}</optgroup>`).join('');
}
function rentalResponsibleOptions(selected=''){
  const active=state.personnel.filter(p=>p.isActive && (p.departmentName==='Kiralama & Operasyon Yönetimi' || /Kiralama/i.test(p.title||'')));
  const names=[...new Set(active.map(x=>x.fullName))];
  return `<option value="">Atanmadı</option>${names.map(n=>`<option ${n===selected?'selected':''}>${esc(n)}</option>`).join('')}`;
}
function rentalLineEditor(line={}, unit='Güvenlik Sistemleri', readonly=false){
  const id=line.rentalOrderItemId||'';
  const productId=line.rentalProductId||rentalCatalogForUnit(unit)[0]?.rentalProductId;
  return `<div class="rental-line form-card" data-id="${esc(id)}">
    <div class="form-grid">
      <div class="field span2"><label>Ürün / Marka-Model *</label><select class="rental-line-product" ${readonly?'disabled':''}>${rentalProductOptions(unit,productId)}</select></div>
      <div class="field"><label>Adet *</label><input class="rental-line-quantity" type="number" min="1" value="${Number(line.quantity||1)}" ${readonly?'readonly':''}></div>
      <div class="field"><label>İşlem</label>${readonly?'<span class="subtle">Kayıtlı ürün</span>':'<button type="button" class="btn rental-row-delete">Kalemi Sil</button>'}</div>
      <div class="field span2"><label>Seri Numaraları (harf, tire, nokta ve / desteklenir)</label><textarea class="rental-line-serial" rows="2" placeholder="Her cihazın seri numarasını ayrı satıra girin" ${readonly?'readonly':''}>${esc(line.serialNumbers||'')}</textarea></div>
      <div class="field span2"><label>Ürün notu</label><textarea class="rental-line-note" rows="2" ${readonly?'readonly':''}>${esc(line.notes||'')}</textarea></div>
    </div></div>`;
}
function rentalContactEditor(c={},readonly=false){
  return `<div class="rental-contact form-card" data-id="${esc(c.rentalOrderContactId||'')}"><div class="form-grid">
    <div class="field"><label>İrtibat türü</label><select class="contact-type" ${readonly?'disabled':''}>${['Satın Alma','Saha Operasyon','Teknik Sorumlu','Diğer'].map(t=>`<option ${t===(c.contactType||'Saha Operasyon')?'selected':''}>${esc(t)}</option>`).join('')}</select></div>
    <div class="field"><label>Ad Soyad *</label><input class="contact-name" maxlength="180" value="${esc(c.fullName||'')}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Organizasyondaki Görevi / Ünvanı</label><input class="contact-title" maxlength="180" value="${esc(c.jobTitle||'')}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Telefon</label><input class="contact-phone" type="tel" maxlength="80" value="${esc(c.phone||'')}" ${readonly?'readonly':''}></div>
    <div class="field span2"><label>E-posta</label><input class="contact-email" type="email" maxlength="250" value="${esc(c.email||'')}" ${readonly?'readonly':''}></div>
    <div class="field"><label>Kişi Notu</label><input class="contact-note" maxlength="500" value="${esc(c.notes||'')}" ${readonly?'readonly':''}></div>
    <div class="field"><label>İşlem</label>${readonly?'<span class="subtle">Kayıtlı irtibat</span>':'<button type="button" class="btn rental-contact-delete">Kişiyi Sil</button>'}</div>
  </div></div>`;
}
function rentalComposerMarkup(lines,contacts,unit,readonly=false){
  return `<div class="form-card"><div class="form-h" style="display:flex;align-items:center;gap:10px">Ürün Kalemleri <span class="subtle">Her model için ayrı satır</span><span class="spacer"></span>${readonly?'':'<button type="button" class="btn primary" id="addRentalProduct">＋ Ürün Ekle</button>'}</div>
    <div id="rentalLines" class="rental-repeat-area">${(lines||[]).map(l=>rentalLineEditor(l,unit,readonly)).join('')}</div></div>
    <div class="form-card"><div class="form-h" style="display:flex;align-items:center;gap:10px">Müşteri / Saha İrtibat Kişileri <span class="spacer"></span>${readonly?'':'<button type="button" class="btn primary" id="addRentalContact">＋ Kişi Ekle</button>'}</div>
    <div id="rentalContacts" class="rental-repeat-area">${(contacts||[]).map(c=>rentalContactEditor(c,readonly)).join('')}</div></div>`;
}
function wireRentalComposer(unit,readonly=false){
  if(readonly)return;
  $('#addRentalProduct')?.addEventListener('click',()=>$('#rentalLines').insertAdjacentHTML('beforeend',rentalLineEditor({},$('#rentalUnit')?.value||unit)));
  $('#addRentalContact')?.addEventListener('click',()=>$('#rentalContacts').insertAdjacentHTML('beforeend',rentalContactEditor({})));
  $('#rentalLines')?.addEventListener('click',e=>{if(e.target.closest('.rental-row-delete')){if($$('.rental-line').length<=1){alert('En az bir ürün kalemi olmalı.');return;}e.target.closest('.rental-line').remove();}});
  $('#rentalContacts')?.addEventListener('click',e=>{if(e.target.closest('.rental-contact-delete'))e.target.closest('.rental-contact').remove();});
}
function collectRentalComposition(){
  const items=$$('.rental-line').map(el=>({
    rentalOrderItemId:Number(el.dataset.id)||null,
    rentalProductId:Number(el.querySelector('.rental-line-product').value),
    quantity:Number(el.querySelector('.rental-line-quantity').value),
    serialNumbers:String(el.querySelector('.rental-line-serial').value||'').split(/[,;\n]+/).map(s=>s.trim()).filter(Boolean),
    notes:el.querySelector('.rental-line-note').value||null
  }));
  const contacts=$$('.rental-contact').map(el=>({
    rentalOrderContactId:Number(el.dataset.id)||null,
    contactType:el.querySelector('.contact-type').value,
    fullName:el.querySelector('.contact-name').value.trim(),
    jobTitle:el.querySelector('.contact-title').value||null,
    phone:el.querySelector('.contact-phone').value||null,
    email:el.querySelector('.contact-email').value||null,
    notes:el.querySelector('.contact-note').value||null
  }));
  if(!items.length||items.some(x=>!x.rentalProductId||x.quantity<1||!Number.isInteger(x.quantity)))throw Error('Her ürün için model ve geçerli adet girin.');
  if(contacts.some(x=>!x.fullName))throw Error('Eklenen irtibat kişilerinin adını doldurun veya boş satırı silin.');
  return {items,contacts};
}
async function refreshRentalData(){
  state.rentals=await api('/api/rentals');
  state.rentalInventory=await api('/api/rentals/inventory');
}
function rentalTable(rows){
 return `<div class="table-scroll"><table><thead><tr><th>Kiralama No</th><th>Birim</th><th>Ürün / Kalem</th><th>Toplam Adet</th><th>Müşteri / Lokasyon</th><th>Tarih</th><th>Durum</th><th>İşlem</th></tr></thead><tbody>${rows.length?rows.map(r=>`<tr>
 <td><b>${esc(r.rentalNo)}</b></td><td>${esc(r.unitCode)}</td>
 <td><b>${Number(r.itemCount||1)} ürün kalemi</b><div class="subtle">${esc(r.productName)}</div></td><td>${Number(r.totalQuantity||r.quantity)}</td>
 <td><b>${esc(r.customerName)}</b><div class="subtle">${esc(r.location||'-')}</div></td>
 <td>${fmtPlanDate(r.startDate)} → ${fmtPlanDate(r.endDate)}</td><td>${statusBadge(r.status)}</td>
 <td><button class="btn soft" data-rentalopen="${r.rentalOrderId}">${can('rentals.edit')?'Düzenle / Operasyon':'Görüntüle'}</button></td></tr>`).join(''):'<tr><td colspan="8">Henüz kiralama yok.</td></tr>'}</tbody></table></div>`;
}
function rentalInventoryView(){
 const inv=state.rentalInventory||{warehouses:[],assets:[]};
 const {warehouses=[],assets=[]}=inv;
 const available=assets.filter(a=>a.conditionStatus==='Hazır'&&!a.rentalOrderItemId);
 const waiting=assets.filter(a=>a.conditionStatus==='Hazır Değil'||a.conditionStatus==='Kontrolde');
 const rented=assets.filter(a=>a.conditionStatus==='Kirada');
 const search=String(state.rentalInventorySearch||'').toLocaleLowerCase('tr-TR');
 const visibleAssets=assets.filter(a=>
    (state.rentalInventoryWarehouse==='all'||String(a.rentalWarehouseId)===String(state.rentalInventoryWarehouse)) &&
    (state.rentalInventoryStatus==='all'||a.conditionStatus===state.rentalInventoryStatus) &&
    (!search||[a.productName,a.serialNo,a.warehouseName,a.missingNotes,a.rentalNo].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(search)))
 );
 return `<div class="panel"><div class="panel-h">Kiralama Depo / Envanter <span class="spacer"></span>${can('rentals.edit')?'<button class="btn primary" id="newRentalAsset">＋ Cihaz / Stok Ekle</button>':''}</div>
 <div class="panel-b"><div class="notice">Seri takipli cihazlar tek tek kaydedilir. Depoya dönen cihazlar kontrol edilmeden “Hazır” sayılmaz. Hazır olmayan cihazların eksikleri açıklanır.</div>
 <div class="rental-summary-grid">
  <div class="rental-summary-cell"><b>${available.reduce((s,x)=>s+x.quantity,0)}</b><span>Hazır / Boşta</span></div>
  <div class="rental-summary-cell"><b>${waiting.reduce((s,x)=>s+x.quantity,0)}</b><span>Eksik / Kontrolde</span></div>
  <div class="rental-summary-cell"><b>${rented.reduce((s,x)=>s+x.quantity,0)}</b><span>Kirada</span></div>
 </div>
 <div class="rental-warehouse-grid">${warehouses.map(w=>{const list=assets.filter(a=>a.rentalWarehouseId===w.rentalWarehouseId);const free=list.filter(a=>a.conditionStatus==='Hazır'&&!a.rentalOrderItemId);return `<div class="rental-warehouse-card"><div><b>${esc(w.name)}</b> <small>${esc(w.code)}</small></div><p><strong>${free.reduce((n,a)=>n+a.quantity,0)}</strong> hazır / <strong>${list.reduce((n,a)=>n+a.quantity,0)}</strong> kayıtlı</p>${can('rentals.edit')?`<button class="btn soft" data-whrename="${w.rentalWarehouseId}">Depo Adını Düzenle</button>`:''}</div>`;}).join('')}</div>
 <div class="toolbar"><input id="rentalInvSearch" style="min-width:240px" type="search" placeholder="Marka, model, seri no, kiralama ara" value="${esc(state.rentalInventorySearch||'')}">
 <select id="rentalInvWarehouse"><option value="all">Tüm Depolar</option>${warehouses.map(w=>`<option value="${w.rentalWarehouseId}" ${String(state.rentalInventoryWarehouse)===String(w.rentalWarehouseId)?'selected':''}>${esc(w.name)}</option>`).join('')}</select>
 <select id="rentalInvStatus">${['all','Hazır','Hazır Değil','Kontrolde','Kirada'].map(st=>`<option value="${st}" ${state.rentalInventoryStatus===st?'selected':''}>${st==='all'?'Tüm Durumlar':st}</option>`).join('')}</select></div>
 <div class="table-scroll"><table><thead><tr><th>Depo</th><th>Ürün / Model</th><th>Seri No</th><th>Adet</th><th>Durum</th><th>Eksik / Not</th><th>Kiralama</th><th>İşlem</th></tr></thead><tbody>${visibleAssets.length?visibleAssets.map(a=>`<tr><td>${esc(a.warehouseName)}</td><td>${esc(a.productName)}</td><td><b>${esc(a.serialNo||'-')}</b></td><td>${a.quantity}</td><td>${statusBadge(a.conditionStatus)}</td><td>${esc(a.missingNotes||a.notes||'-')}</td><td>${esc(a.rentalNo||'-')}</td><td>${can('rentals.edit')?`<button class="btn soft" data-invedit="${a.rentalInventoryId}">Düzenle</button>`:''}</td></tr>`).join(''):'<tr><td colspan="8">Stok girişi henüz yapılmadı.</td></tr>'}</tbody></table></div>
 </div></div>`;
}
function rentalsPage(){
  const allowedUnits=[...new Set(state.rentalCatalog.map(x=>x.unitCode))];
  let rows=[...state.rentals];
  if(state.rentalFilter!=='all')rows=rows.filter(x=>x.unitCode===state.rentalFilter);
  const tab=state.rentalTab||'orders';
  return `<div class="toolbar"><button class="tabbtn ${tab==='orders'?'active':''}" data-rentaltab="orders">Kiralama Kayıtları</button><button class="tabbtn ${tab==='inventory'?'active':''}" data-rentaltab="inventory">Depo / Envanter</button><span class="spacer"></span>${tab==='orders'&&can('rentals.create')?'<button class="btn primary" id="newRentalBtn">＋ Yeni Kiralama Kaydı</button>':''}</div>
 ${tab==='inventory'?rentalInventoryView():`<div class="toolbar"><button class="tabbtn ${state.rentalFilter==='all'?'active':''}" data-rentalfilter="all">Tümü</button>${allowedUnits.map(u=>`<button class="tabbtn ${state.rentalFilter===u?'active':''}" data-rentalfilter="${esc(u)}">${esc(u)}</button>`).join('')}</div>
 <div class="kpis rental-kpis"><div class="kpi"><div class="label">Kiralama Kaydı</div><div class="num">${rows.length}</div></div><div class="kpi"><div class="label">Kirada</div><div class="num">${rows.filter(x=>x.status==='Kirada').length}</div></div><div class="kpi"><div class="label">İade / Kontrol</div><div class="num">${rows.filter(x=>['İade Bekliyor','İade Alındı','Test / Kontrol'].includes(x.status)).length}</div></div><div class="kpi"><div class="label">Toplam Ürün Kalemi</div><div class="num">${rows.reduce((n,r)=>n+Number(r.itemCount||1),0)}</div></div></div>
 <div class="panel"><div class="panel-h">Kiralama Kayıtları <span class="badge b-blue">${rows.length}</span></div><div class="panel-b">${rentalTable(rows)}</div></div>`}`;
}
function openRentalCreateModal(){
  const units=[...new Set(state.rentalCatalog.map(x=>x.unitCode))];
  const unit=units[0]||'Güvenlik Sistemleri';
  const tomorrow=new Date(Date.now()+86400000).toISOString().slice(0,10);
  modal(`<div class="modal-h"><b>Yeni Kiralama • Çoklu Ürün / İrtibat</b><span class="spacer"></span><button class="iconbtn" id="modalX">×</button></div><div class="modal-b"><form id="rentalForm">
   <div class="form-card"><div class="form-h">Kiralama / Müşteri Bilgileri</div><div class="form-grid">
    <div class="field"><label>Birim *</label><select name="unitCode" id="rentalUnit">${units.map(u=>`<option>${esc(u)}</option>`).join('')}</select></div>
    <div class="field"><label>Müşteri *</label><input name="customerName" required maxlength="250"></div>
    <div class="field"><label>Müşteri E-posta</label><input name="customerEmail" type="email"></div>
    <div class="field"><label>Proje / Organizasyon</label><input name="projectName"></div>
    <div class="field span2"><label>Lokasyon / Etkinlik Adresi</label><input name="location"></div>
    <div class="field"><label>Başlangıç *</label><input type="date" name="startDate" value="${todayIso()}" required></div>
    <div class="field"><label>Bitiş *</label><input type="date" name="endDate" value="${tomorrow}" required></div>
    <div class="field"><label>ERP Sorumlusu</label><select name="responsibleName">${rentalResponsibleOptions()}</select></div>
    <div class="field span2"><label>Genel Not</label><textarea name="notes"></textarea></div>
   </div></div>
   ${rentalComposerMarkup([{}],[],unit)}
   <div class="actions"><button type="button" class="btn" id="cancelRental">Vazgeç</button><button class="btn primary">Kiralama Kaydını Oluştur</button></div>
   </form></div>`);
  $('#modalX').onclick=$('#cancelRental').onclick=closeModal;
  wireRentalComposer(unit);
  $('#rentalUnit').onchange=()=>{
    const newUnit=$('#rentalUnit').value;
    $('#rentalLines').innerHTML=rentalLineEditor({},newUnit);
  };
  $('#rentalForm').onsubmit=async e=>{
    e.preventDefault();
    const f=e.target;if(!f.reportValidity())return;
    const fd=new FormData(f);
    try{
      const {items,contacts}=collectRentalComposition();
      const first=items[0],firstContact=contacts[0];
      const r=await api('/api/rentals',{method:'POST',body:JSON.stringify({
        rentalProductId:first.rentalProductId,unitCode:fd.get('unitCode'),customerName:fd.get('customerName'),
        customerEmail:fd.get('customerEmail')||null,projectName:fd.get('projectName')||null,location:fd.get('location')||null,
        contactName:firstContact?.fullName||null,contactPhone:firstContact?.phone||null,
        quantity:items.reduce((sum,item)=>sum+item.quantity,0),serialNumbers:first.serialNumbers,
        startDate:fd.get('startDate'),endDate:fd.get('endDate'),responsibleName:fd.get('responsibleName')||null,notes:fd.get('notes')||null,
        items,contacts
      })});
      await refreshRentalData();closeModal();render();alert(`${r.rentalNo} kaydı ${items.length} ürün kalemi ile oluşturuldu.`);
    }catch(err){alert(err.message);}
  };
}
async function openRentalModal(id){
 const r=state.rentals.find(x=>Number(x.rentalOrderId)===Number(id));if(!r)return;
 const readonly=!can('rentals.edit');
 try{
 const details=await api(`/api/rentals/${id}/details`);
 const items=details.items||[],contacts=details.contacts||[],stages=details.stages||[];
 const wh=state.rentalInventory?.warehouses||[];
 modal(`<div class="modal-h"><div><b>${esc(r.rentalNo)} • Kiralama / Operasyon</b><div class="subtle">${esc(r.customerName)} • ${esc(r.unitCode)}</div></div><span class="spacer"></span><button class="iconbtn" id="modalX">×</button></div><div class="modal-b">
 <form id="editRentalForm"><div class="form-card"><div class="form-h">Kiralama Bilgileri</div><div class="form-grid">
 <div class="field"><label>Durum</label><select name="status" ${readonly?'disabled':''}>${rentalStatuses.map(s=>`<option ${s===r.status?'selected':''}>${esc(s)}</option>`).join('')}</select></div>
 <div class="field"><label>Başlangıç</label><input type="date" name="startDate" value="${esc(r.startDate)}" ${readonly?'readonly':''}></div>
 <div class="field"><label>Bitiş</label><input type="date" name="endDate" value="${esc(r.endDate)}" ${readonly?'readonly':''}></div>
 <div class="field"><label>Müşteri *</label><input name="customerName" value="${esc(r.customerName)}" required ${readonly?'readonly':''}></div>
 <div class="field"><label>E-posta</label><input name="customerEmail" value="${esc(r.customerEmail||'')}" type="email" ${readonly?'readonly':''}></div>
 <div class="field"><label>Proje / Etkinlik</label><input name="projectName" value="${esc(r.projectName||'')}" ${readonly?'readonly':''}></div>
 <div class="field span2"><label>Lokasyon / Adres</label><input name="location" value="${esc(r.location||'')}" ${readonly?'readonly':''}></div>
 <div class="field"><label>Sorumlu</label><select name="responsibleName" ${readonly?'disabled':''}>${rentalResponsibleOptions(r.responsibleName||'')}</select></div>
 <div class="field span2"><label>Notlar</label><textarea name="notes" ${readonly?'readonly':''}>${esc(r.notes||'')}</textarea></div>
 </div></div>
 ${rentalComposerMarkup(items,contacts,r.unitCode,readonly)}
 ${readonly?'':'<div class="actions"><button class="btn primary" type="submit">Değişiklikleri Kaydet</button></div>'}
 </form>
 <div class="form-card"><div class="form-h">Depodan Cihaz / Seri Numarası Atama</div><div class="panel-b"><div class="notice">Hazır envanter cihazlarını ürün kalemlerine bağlayın. Bir cihaz iki farklı kiralamaya atanamaz.</div>
 ${items.map(i=>`<div class="rental-assign-row"><span><b>${esc(i.productName)}</b> — ${i.quantity} adet<br><small>${esc(i.serialNumbers||'Seri numarası girilmedi')} | Envanterde atanmış ${i.assignedCount||0}</small></span>${readonly?'':`<button class="btn soft" type="button" data-rentalallocate="${i.rentalOrderItemId}">Depodan Seç / Ata</button>`}</div>`).join('')}
 </div></div>
 <div class="form-card"><div class="form-h">Operasyon Süreci: Sevk → Kurulum → Devreye Alma → Toplama → Depo</div><div class="panel-b">
 ${stages.length?`<div class="rental-stage-list">${stages.map(e=>`<div class="rental-stage"><b>${esc(e.stageName)}</b> <span>${new Date(e.eventAt).toLocaleString('tr-TR')}</span><p>${esc(e.teamName||'-')} | ${esc(e.warehouseName||'')} ${esc(e.notes||'')}${e.serialSnapshot?`<br><b>İşlemdeki seri nolar:</b> ${esc(e.serialSnapshot)}`:''}</p><small>Kaydeden: ${esc(e.createdBy||'-')}</small></div>`).join('')}</div>`:'<p class="subtle">Henüz operasyon aşaması kaydedilmedi.</p>'}
 ${readonly?'':`<div class="rental-stage-shortcuts">${['Sevk Edildi','Kurulum Yapıldı','Devreye Alındı','Toplandı','Depoya Alındı'].map(s=>`<button type="button" class="btn soft" data-stagepick="${esc(s)}">${esc(s)}</button>`).join('')}</div><form id="rentalStageForm" class="rental-stage-entry"><div class="form-grid">
  <div class="field"><label>Aşama *</label><select name="stageName">${['Sevk Edildi','Kurulum Yapıldı','Devreye Alındı','Toplandı','Depoya Alındı'].map(s=>`<option>${esc(s)}</option>`).join('')}</select></div>
  <div class="field"><label>Tarih / Saat *</label><input type="datetime-local" name="eventAt" value="${localDatetimeValue()}" required></div>
  <div class="field"><label>İşlemi Yapan Teknik Ekip</label><input name="teamName" placeholder="Teknisyenler / ekip adı"></div>
  <div class="field"><label>Depo (depo dönüşte zorunlu)</label><select name="rentalWarehouseId"><option value="">Depo Seç</option>${wh.map(w=>`<option value="${w.rentalWarehouseId}">${esc(w.name)}</option>`).join('')}</select></div>
  <div class="field span4"><label>İşlem Notu</label><textarea name="notes" rows="2" placeholder="Kurulum, arıza, sevk veya teslim bilgisi"></textarea></div>
 </div><button class="btn primary">Aşamayı Kaydet</button></form>`}
 </div></div>
 </div><div class="modal-f"><button class="btn" id="closeRentalDetail">Kapat</button></div>`);
 $('#modalX').onclick=$('#closeRentalDetail').onclick=closeModal;
 if(!readonly){
   wireRentalComposer(r.unitCode);
   $('#editRentalForm').onsubmit=async e=>{
     e.preventDefault();const f=e.target;if(!f.reportValidity())return;
     const fd=new FormData(f);
     try{
       const {items,contacts}=collectRentalComposition();
       // Önce ürün ve irtibatları tek SQL transaction ile kaydet, sonra üst bilgileri güncelle.
       await api(`/api/rentals/${id}/composition`,{method:'PUT',body:JSON.stringify({items,contacts})});
       const primary=items[0];
       await api(`/api/rentals/${id}`,{method:'PUT',body:JSON.stringify({
         customerName:fd.get('customerName'),customerEmail:fd.get('customerEmail')||null,projectName:fd.get('projectName')||null,
         location:fd.get('location')||null,contactName:contacts[0]?.fullName||null,contactPhone:contacts[0]?.phone||null,
         quantity:items.reduce((sum,i)=>sum+i.quantity,0),serialNumbers:primary.serialNumbers,
         startDate:fd.get('startDate'),endDate:fd.get('endDate'),status:fd.get('status'),
         responsibleName:fd.get('responsibleName')||null,notes:fd.get('notes')||null
       })});
       await refreshRentalData();closeModal();render();alert('Kiralama, ürünler ve irtibatlar kaydedildi.');
     }catch(err){alert(err.message);}
   };
   $$('[data-rentalallocate]').forEach(btn=>btn.onclick=()=>openRentalAllocation(id,Number(btn.dataset.rentalallocate),items.find(i=>i.rentalOrderItemId===Number(btn.dataset.rentalallocate))));
   $$('[data-stagepick]').forEach(b=>b.onclick=()=>{const form=$('#rentalStageForm');form.elements.stageName.value=b.dataset.stagepick;form.scrollIntoView({behavior:'smooth',block:'center'});});
   $('#rentalStageForm').onsubmit=async e=>{
     e.preventDefault();const fd=new FormData(e.target);
     try{
       await api(`/api/rentals/${id}/stage`,{method:'POST',body:JSON.stringify({
         stageName:fd.get('stageName'),eventAt:fd.get('eventAt'),teamName:fd.get('teamName')||null,
         rentalWarehouseId:Number(fd.get('rentalWarehouseId'))||null,notes:fd.get('notes')||null
       })});
       await refreshRentalData();await openRentalModal(id);
     }catch(err){alert(err.message);}
   };
 }
 }catch(err){alert(err.message);}
}
function localDatetimeValue(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;}
function openRentalAllocation(orderId,itemId,item){
 const inv=state.rentalInventory?.assets||[];
 const candidate=inv.filter(a=>a.rentalProductId===item.rentalProductId && ((a.conditionStatus==='Hazır'&&!a.rentalOrderItemId) || a.rentalOrderItemId===itemId));
 modal(`<div class="modal-h"><b>${esc(item.productName)} — Envanter Seçimi</b><span class="spacer"></span><button class="iconbtn" id="modalX">×</button></div><div class="modal-b">
 <div class="notice">Kiralama miktarı: ${item.quantity} adet. Yalnızca hazır veya bu işe atanmış cihazlar seçilebilir. Seri numarası ve depo bilgileri envanter kayıtlarından gelir.</div>
 <form id="rentalAllocationForm"><div class="table-scroll"><table><thead><tr><th>Seç</th><th>Depo</th><th>Seri No</th><th>Adet</th><th>Durum</th></tr></thead><tbody>
 ${candidate.length?candidate.map(a=>`<tr><td><input type="checkbox" name="asset" value="${a.rentalInventoryId}" ${a.rentalOrderItemId===itemId?'checked':''}></td><td>${esc(a.warehouseName)}</td><td>${esc(a.serialNo||'-')}</td><td>${a.quantity}</td><td>${esc(a.conditionStatus)}</td></tr>`).join(''):'<tr><td colspan="5">Bu modele ait hazır depo envanteri yok. Önce Depo / Envanter sekmesinden kaydet.</td></tr>'}
 </tbody></table></div><div class="actions"><button type="button" id="cancelAllocate" class="btn">Geri</button><button class="btn primary">Seçilenleri Ata</button></div></form></div>`);
 $('#modalX').onclick=$('#cancelAllocate').onclick=()=>openRentalModal(orderId);
 $('#rentalAllocationForm').onsubmit=async e=>{
   e.preventDefault();const ids=[...e.target.querySelectorAll('input[name=asset]:checked')].map(x=>Number(x.value));
   try{
     await api(`/api/rentals/${orderId}/allocate`,{method:'POST',body:JSON.stringify({rentalOrderItemId:itemId,rentalInventoryIds:ids})});
     await refreshRentalData();await openRentalModal(orderId);
   }catch(err){alert(err.message);}
 };
}
function openRentalInventoryModal(id=null){
 const inv=state.rentalInventory||{warehouses:[],assets:[]};
 const a=inv.assets.find(x=>x.rentalInventoryId===Number(id))||{};
 const firstProduct=state.rentalCatalog.find(p=>p.unitCode===a.unitCode)||state.rentalCatalog[0];
 modal(`<div class="modal-h"><b>${id?'Envanter Cihazını Düzenle':'Depoya Yeni Cihaz / Stok Ekle'}</b><span class="spacer"></span><button class="iconbtn" id="modalX">×</button></div><div class="modal-b">
 <form id="inventoryForm"><div class="form-grid">
 <div class="field span2"><label>Ürün / Marka / Model *</label><select name="rentalProductId">${state.rentalCatalog.map(p=>`<option value="${p.rentalProductId}" ${p.rentalProductId===(a.rentalProductId||firstProduct?.rentalProductId)?'selected':''}>${esc(p.unitCode)} • ${esc(p.productName)}</option>`).join('')}</select></div>
 <div class="field"><label>Depo *</label><select name="rentalWarehouseId">${inv.warehouses.map(w=>`<option value="${w.rentalWarehouseId}" ${w.rentalWarehouseId===(a.rentalWarehouseId||inv.warehouses[0]?.rentalWarehouseId)?'selected':''}>${esc(w.name)}</option>`).join('')}</select></div>
 <div class="field"><label>Seri Numarası</label><input type="text" name="serialNo" maxlength="200" value="${esc(a.serialNo||'')}" placeholder="Örn. PG-5030/2026.01"></div>
 <div class="field"><label>Adet *</label><input type="number" name="quantity" min="1" value="${a.quantity||1}" required></div>
 <div class="field"><label>Hazırlık Durumu</label><select name="conditionStatus">${['Hazır','Hazır Değil','Kontrolde','Kirada'].map(s=>`<option ${s===(a.conditionStatus||'Hazır')?'selected':''}>${esc(s)}</option>`).join('')}</select></div>
 <div class="field span2"><label>Hazır Değilse Ne Eksik?</label><textarea name="missingNotes" rows="2">${esc(a.missingNotes||'')}</textarea></div>
 <div class="field span4"><label>Envanter Notu</label><textarea name="notes" rows="2">${esc(a.notes||'')}</textarea></div>
 </div><div class="actions"><button type="button" class="btn" id="cancelInventory">Vazgeç</button><button class="btn primary">Envanteri Kaydet</button></div></form></div>`);
 $('#modalX').onclick=$('#cancelInventory').onclick=closeModal;
 $('#inventoryForm').onsubmit=async e=>{
  e.preventDefault();const fd=new FormData(e.target);
  try{
    await api('/api/rentals/inventory',{method:'POST',body:JSON.stringify({
      rentalInventoryId:id?Number(id):null,rentalProductId:Number(fd.get('rentalProductId')),
      rentalWarehouseId:Number(fd.get('rentalWarehouseId')),serialNo:fd.get('serialNo')||null,
      quantity:Number(fd.get('quantity')),conditionStatus:fd.get('conditionStatus'),
      missingNotes:fd.get('missingNotes')||null,notes:fd.get('notes')||null
    })});
    state.rentalInventory=await api('/api/rentals/inventory');closeModal();render();
  }catch(err){alert(err.message);}
 };
}
async function renameRentalWarehouse(id){
 const wh=state.rentalInventory?.warehouses.find(w=>w.rentalWarehouseId===Number(id));if(!wh)return;
 const name=prompt('Yeni depo adı:',wh.name);if(name===null||!name.trim())return;
 try{await api(`/api/rentals/warehouses/${id}`,{method:'PUT',body:JSON.stringify({name:name.trim()})});state.rentalInventory=await api('/api/rentals/inventory');render();}catch(err){alert(err.message);}
}

function personnelTable(rows){
  if(!rows.length) return '<div class="subtle">Personel bulunamadı.</div>';
  return `<div class="table-scroll"><table><thead><tr><th>Ad Soyad</th><th>Departman</th><th>Ünvan</th><th>Birim</th><th>Yönetici</th><th>ERP</th><th>Durum</th><th>İşlem</th></tr></thead><tbody>${rows.map(p=>`<tr><td><b>${esc(p.fullName)}</b></td><td>${esc(p.departmentName)}${(p.additionalDepartments||[]).length?`<div class="subtle">+ ${(p.additionalDepartments||[]).map(esc).join(', ')}</div>`:''}</td><td>${esc(p.title||'-')}</td><td>${esc(p.unitCode||'-')}</td><td>${esc(p.managerName||'-')}</td><td>${p.username?`<b>${esc(p.username)}</b><div class="subtle">${esc(p.roleName||'')}</div>`:'-'}</td><td>${p.isActive?'<span class="badge b-green">Aktif</span>':'<span class="badge b-red">Ayrıldı</span>'}</td><td class="user-actions">${can('personnel.manage')?`<button class="btn soft" data-personedit="${p.personnelId}">Düzenle</button><button class="btn" data-personstatus="${p.personnelId}" data-active="${p.isActive?'0':'1'}">${p.isActive?'İşten Çıkış':'Aktif Yap'}</button>`:''}${p.erpUserId&&can('users.manage')?`<button class="btn primary" data-personuser="${p.erpUserId}">Yetkiler</button>`:''}</td></tr>`).join('')}</tbody></table></div>`;
}
function personnelPage(){
  const active=state.personnel.filter(p=>p.isActive);
  const departments=[...new Set(state.personnel.map(p=>p.departmentName))].sort((a,b)=>a.localeCompare(b,'tr'));
  let rows=[...state.personnel];
  if(state.personnelDepartment!=='all') rows=rows.filter(p=>p.departmentName===state.personnelDepartment || (p.additionalDepartments||[]).includes(state.personnelDepartment));
  const managers=active.map(x=>x.fullName);
  const roles=state.meta?.roles||[];
  const canManage=can('personnel.manage');
  const canCreateUser=can('users.manage');
  const form=canManage?`<div class="panel"><div class="panel-h">Yeni Personel</div><div class="panel-b"><form id="personnelForm"><div class="form-grid">
    <div class="field"><label>Ad Soyad *</label><input name="fullName" required></div>
    <div class="field"><label>Departman *</label><select name="departmentName">${(state.meta?.departments||departments).map(d=>`<option>${esc(d)}</option>`).join('')}</select></div>
    <div class="field"><label>Ünvan</label><input name="title"></div>
    <div class="field"><label>Operasyon Birimi</label><select name="unitCode"><option value="">Genel / Birimsiz</option>${allUnits.map(u=>`<option>${esc(u)}</option>`).join('')}</select></div>
    <div class="field"><label>Yönetici</label><select name="managerName"><option value="">-</option>${managers.map(n=>`<option>${esc(n)}</option>`).join('')}</select></div>
    <div class="field"><label>İşe Giriş</label><input name="startDate" type="date" value="${todayIso()}"></div>
    <div class="field span2"><label>Ek Departmanlar</label><input name="additionalDepartments" placeholder="Virgülle ayırabilirsiniz"></div>
    <div class="field span2"><label>Not</label><textarea name="notes"></textarea></div>
    ${canCreateUser?`<div class="field span4"><label class="check-line"><input type="checkbox" name="createUser" id="personCreateUser"> Aynı anda ERP kullanıcı hesabı oluştur</label></div><div id="personUserFields" class="field span4 hidden"><div class="form-grid embedded-grid">
      <div class="field"><label>Kullanıcı Adı</label><input name="username"></div><div class="field"><label>Rol</label><select name="roleName" id="personRole">${roles.map(r=>`<option>${esc(r)}</option>`).join('')}</select></div><div class="field"><label>Geçici Şifre</label><input name="password" type="password" placeholder="Geçici şifre girin" autocomplete="new-password"></div><div class="field"><label>İlk girişte değiştir</label><select name="mustChange"><option value="1">Evet</option><option value="0">Hayır</option></select></div>
      <div class="field span4"><label>Yetkili Birimler</label><div class="multi-box">${allUnits.map(u=>`<label class="multi-option"><input type="checkbox" name="p_units" value="${esc(u)}"> ${esc(u)}</label>`).join('')}</div></div>
      <div class="field span4"><label>Modül / İşlem Yetkileri</label><div id="personPermissionHost">${permissionChecks(state.meta?.roleDefaults?.[roles[0]]||[],'p_permissions')}</div></div>
    </div></div>`:''}
  </div><div class="actions"><button class="btn primary">Personeli Kaydet</button></div></form></div></div>`:'';
  return `<div class="kpis personnel-kpis"><div class="kpi"><div class="label">Aktif Personel</div><div class="num">${active.length}</div></div><div class="kpi"><div class="label">Pasif / Ayrılan</div><div class="num">${state.personnel.length-active.length}</div></div><div class="kpi"><div class="label">Departman</div><div class="num">${departments.length}</div></div><div class="kpi"><div class="label">ERP Hesabı</div><div class="num">${state.personnel.filter(x=>x.erpUserId).length}</div></div></div>
  <div class="department-grid">${departments.map(d=>{const ps=state.personnel.filter(p=>p.isActive&&(p.departmentName===d||(p.additionalDepartments||[]).includes(d)));return `<button class="department-card ${state.personnelDepartment===d?'active':''}" data-deptfilter="${esc(d)}"><b>${esc(d)}</b><span>${ps.length} kişi</span><small>${ps.slice(0,4).map(p=>esc(p.fullName)).join(' • ')}${ps.length>4?' • …':''}</small></button>`}).join('')}</div>
  <div class="${canManage?'two-col personnel-admin-layout':''}" style="margin-top:12px">${form}<div class="panel"><div class="panel-h">Personel Listesi <span class="badge b-blue">${rows.length}</span><div class="spacer"></div><button class="btn soft ${state.personnelDepartment==='all'?'hidden':''}" data-deptfilter="all">Tüm Departmanlar</button></div><div class="panel-b">${personnelTable(rows)}</div></div></div>`;
}
function openPersonnelEditModal(id){
  const p=state.personnel.find(x=>Number(x.personnelId)===Number(id)); if(!p)return;
  const departments=state.meta?.departments||[];
  const managers=state.personnel.filter(x=>x.isActive&&x.personnelId!==p.personnelId).map(x=>x.fullName);
  modal(`<div class="modal-h"><div><b>Personel Düzenle • ${esc(p.fullName)}</b><div class="subtle">Departman, ünvan ve organizasyon bilgileri</div></div><button class="iconbtn" id="modalX">×</button></div><div class="modal-b"><form id="editPersonnelForm"><div class="form-card"><div class="form-grid">
    <div class="field"><label>Ad Soyad *</label><input name="fullName" value="${esc(p.fullName)}" required></div>
    <div class="field"><label>Departman *</label><select name="departmentName">${departments.map(d=>`<option ${d===p.departmentName?'selected':''}>${esc(d)}</option>`).join('')}</select></div>
    <div class="field"><label>Ünvan</label><input name="title" value="${esc(p.title||'')}"></div>
    <div class="field"><label>Operasyon Birimi</label><select name="unitCode"><option value="">Genel / Birimsiz</option>${allUnits.map(u=>`<option ${u===p.unitCode?'selected':''}>${esc(u)}</option>`).join('')}</select></div>
    <div class="field"><label>Yönetici</label><select name="managerName"><option value="">-</option>${managers.map(n=>`<option ${n===p.managerName?'selected':''}>${esc(n)}</option>`).join('')}</select></div>
    <div class="field"><label>İşe Giriş</label><input name="startDate" type="date" value="${esc(p.startDate||'')}"></div>
    <div class="field span2"><label>Ek Departmanlar</label><input name="additionalDepartments" value="${esc((p.additionalDepartments||[]).join(', '))}"></div>
    <div class="field span2"><label>Not</label><textarea name="notes">${esc(p.notes||'')}</textarea></div>
  </div></div></form></div><div class="modal-f"><button class="btn" id="cancelEditPersonnel">Vazgeç</button><button class="btn primary" id="saveEditPersonnel">Kaydet</button></div>`);
  $('#modalX').onclick=$('#cancelEditPersonnel').onclick=closeModal;
  $('#saveEditPersonnel').onclick=async()=>{
    const f=$('#editPersonnelForm');if(!f.reportValidity())return;const fd=new FormData(f);const add=String(fd.get('additionalDepartments')||'').split(/[,;\n]+/).map(x=>x.trim()).filter(Boolean);
    try{await api(`/api/personnel/${p.personnelId}`,{method:'PUT',body:JSON.stringify({fullName:fd.get('fullName'),departmentName:fd.get('departmentName'),additionalDepartments:add,title:fd.get('title')||null,unitCode:fd.get('unitCode')||null,managerName:fd.get('managerName')||null,startDate:fd.get('startDate')||null,notes:fd.get('notes')||null})});state.personnel=await api('/api/personnel');closeModal();render();}catch(err){alert(err.message);}
  };
}

function pocMobilityPage(){
  const rows=state.workOrders.filter(w=>['POC','Mobilite','Araç Takip'].includes(w.unitCode));
  return `<div class="panel"><div class="panel-h">POC / Mobilite / Araç Takip <span class="badge b-blue">${rows.length}</span></div><div class="panel-b">${workTable(rows)}</div></div>`;
}
// V1.10 - Günlük servis ve cihaz bazlı yıllık bakımı ayrı raporlayan, salt okunur canlı yönetim özeti.
function reportWorkDate(w,field){
  const value=field==='plan'?w.planDate:field==='closed'?w.closedAt:w.createdAt;
  return value?String(value).slice(0,10):'';
}
function reportFilteredRows(){
  const f=state.reportFilters;
  return state.workOrders.filter(w=>unitAllowed(w.unitCode))
    .filter(w=>f.kind==='all'||reportKind(w)===f.kind)
    .filter(w=>f.unit==='Tümü'||w.unitCode===f.unit)
    .filter(w=>f.status==='Tümü'||w.status===f.status)
    .filter(w=>f.workType==='Tümü'||w.workType===f.workType)
    .filter(w=>{const d=reportWorkDate(w,f.dateField);return (!f.start||d>=f.start)&&(!f.end||d<=f.end)&&(!!d||(!f.start&&!f.end));})
    .filter(w=>!f.person||String(w.assignedStaff||'').toLocaleLowerCase('tr-TR').includes(f.person.toLocaleLowerCase('tr-TR')))
    .filter(w=>!f.chief||String(w.chiefName||'').toLocaleLowerCase('tr-TR').includes(f.chief.toLocaleLowerCase('tr-TR')))
    .filter(w=>!f.customer||[w.customerName,w.location,w.workOrderNo,w.subject,w.serialNumbers].some(a=>String(a||'').toLocaleLowerCase('tr-TR').includes(f.customer.toLocaleLowerCase('tr-TR'))));
}
function reportBucket(w){
  if(w.status==='İptal')return 'İptal';
  if(reportIsCompleted(w))return 'Tamamlandı';
  if(w.status==='Beklemede'||w.status==='Kargoda')return 'Beklemede';
  if(w.status==='Planlandı')return 'Planlandı';
  if(['Sahada','İşlemde','Yola Çıkıldı','Atölyede','Test / Kontrol'].includes(w.status))return 'İşlemde';
  return 'Talep / Planlama';
}
function reportFilteredTimeLogs(){
  const f=state.reportFilters;
  // Zaman filtreleri gerçek faaliyet tarihine göre hesaplanır. Açılış/plan tarihleri çalışma süresi sayılmaz.
  const work=new Map(state.workOrders.filter(w=>unitAllowed(w.unitCode)).map(w=>[Number(w.workOrderId),w]));
  return state.workLogs.map(t=>({...t,work:work.get(Number(t.workOrderId))})).filter(t=>t.work)
    .filter(t=>f.kind==='all'||reportKind(t.work)===f.kind)
    .filter(t=>f.unit==='Tümü'||t.work.unitCode===f.unit)
    .filter(t=>f.status==='Tümü'||t.work.status===f.status)
    .filter(t=>f.workType==='Tümü'||t.work.workType===f.workType)
    .filter(t=>{const d=String(t.startedAt||'').slice(0,10);return (!f.start||d>=f.start)&&(!f.end||d<=f.end);})
    .filter(t=>!f.person||String(t.technicianName||'').toLocaleLowerCase('tr-TR').includes(f.person.toLocaleLowerCase('tr-TR')))
    .filter(t=>!f.chief||String(t.work.chiefName||'').toLocaleLowerCase('tr-TR').includes(f.chief.toLocaleLowerCase('tr-TR')))
    .filter(t=>!f.customer||[t.work.customerName,t.work.location,t.work.workOrderNo,t.work.subject,t.work.serialNumbers,t.locationNote].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(f.customer.toLocaleLowerCase('tr-TR'))));
}
function hoursLabel(minutes){return (minutes/60).toLocaleString('tr-TR',{maximumFractionDigits:2})+' saat';}
function reportTimePivot(logs,groupBy,heading){
  const groups=new Map();for(const t of logs){const key=groupBy(t)||'Belirtilmedi';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(t);}
  const activities=['Saha Çalışması','Yol / Ulaşım','Bekleme','Uzaktan Destek','Atölye','Test / Kontrol','Diğer'];
  const tr=(name,ls,total=false)=>`<tr${total?' class="report-total-row"':''}><td>${esc(name)}</td><td>${new Set(ls.map(t=>t.workOrderId)).size}</td><td>${ls.length}</td><td class="numcell"><b>${esc(hoursLabel(ls.reduce((a,t)=>a+t.minutes,0)))}</b></td>${activities.map(a=>`<td>${esc(hoursLabel(ls.filter(t=>t.activityType===a).reduce((n,t)=>n+t.minutes,0)))}</td>`).join('')}</tr>`;
  return `<div class="table-scroll"><table class="report-pivot-table"><thead><tr><th>${esc(heading)}</th><th>Farklı İş</th><th>Faaliyet</th><th>Toplam Kişi-Saat</th>${activities.map(a=>`<th>${esc(a)}</th>`).join('')}</tr></thead><tbody>${[...groups].sort((a,b)=>b[1].reduce((n,t)=>n+t.minutes,0)-a[1].reduce((n,t)=>n+t.minutes,0)).map(([k,l])=>tr(k,l)).join('')||'<tr><td colspan="11">Gerçek süre kaydı bulunamadı.</td></tr>'}${tr('TOPLAM',logs,true)}</tbody></table></div>`;
}
function reportCrossTable(rows,field,label){
  const buckets=['Talep / Planlama','Planlandı','İşlemde','Beklemede','Tamamlandı','İptal'];
  const groups=new Map();
  for(const w of rows){const k=field(w)||'Belirtilmemiş';if(!groups.has(k))groups.set(k,[]);groups.get(k).push(w);}
  const sums=(list)=>[list.length,...buckets.map(b=>list.filter(w=>reportBucket(w)===b).length)];
  const tableRow=(key,list,em=false)=>`<tr${em?' class="report-total-row"':''}><td>${esc(key)}</td>${sums(list).map(n=>`<td class="numcell">${n}</td>`).join('')}</tr>`;
  return `<div class="table-scroll"><table class="report-pivot-table"><thead><tr><th>${esc(label)}</th><th>Toplam</th>${buckets.map(b=>`<th>${esc(b)}</th>`).join('')}</tr></thead><tbody>${[...groups].sort((a,b)=>b[1].length-a[1].length).map(([k,list])=>tableRow(k,list)).join('')||'<tr><td colspan="8">Kayıt bulunamadı.</td></tr>'}${tableRow('GENEL TOPLAM',rows,true)}</tbody></table></div>`;
}
function reportPersonnelTable(rows){
  const people=new Map();
  for(const w of rows){
    const names=[...new Set(String(w.assignedStaff||'').split(',').map(x=>x.trim()).filter(Boolean))];
    for(const name of names){if(!people.has(name))people.set(name,[]);people.get(name).push(w);}
  }
  const sorted=[...people].sort((a,b)=>b[1].length-a[1].length);
  return `<div class="table-scroll"><table class="report-pivot-table"><thead><tr><th>Teknisyen</th><th>Toplam Atanan</th><th>Günlük Servis</th><th>Planlı Bakım</th><th>Tamamlanan</th></tr></thead><tbody>${sorted.map(([name,list])=>`<tr><td>${esc(name)}</td><td>${list.length}</td><td>${list.filter(x=>!isMaintenanceOrder(x)).length}</td><td>${list.filter(isMaintenanceOrder).length}</td><td>${list.filter(reportIsCompleted).length}</td></tr>`).join('')||'<tr><td colspan="5">Atanmış teknisyen yok.</td></tr>'}</tbody></table></div><div class="subtle report-hint">Bir işte birden fazla teknisyen varsa iş her teknisyenin satırında bir kez sayılır; personel toplamları benzersiz iş emri toplamını aşabilir.</div>`;
}
function reportTableRows(rows){
  return `<div class="table-scroll"><table class="report-pivot-table"><thead><tr><th>İş Emri</th><th>Kategori</th><th>Birim</th><th>Müşteri / Lokasyon</th><th>İş Türü</th><th>Şef / Teknisyen</th><th>Durum</th><th>Plan</th></tr></thead><tbody>${rows.slice(0,150).map(w=>`<tr><td><button class="metric-wo-link" data-reportopen="${Number(w.workOrderId)}">${esc(w.workOrderNo)}</button></td><td>${isMaintenanceOrder(w)?'<span class="badge b-purple">Planlı Bakım</span>':'<span class="badge b-blue">Günlük Servis</span>'}</td><td>${esc(w.unitCode)}</td><td><b>${esc(w.customerName)}</b><div class="subtle">${esc(w.location||'-')}</div></td><td>${esc(w.workType)}</td><td><b>${esc(w.chiefName||'-')}</b><div class="subtle">${esc(w.assignedStaff||'Atanmadı')}</div></td><td>${statusBadge(w.status)}</td><td>${esc(fmtPlanDate(w.planDate))}</td></tr>`).join('')||'<tr><td colspan="8">Bu filtrelerde kayıt yok.</td></tr>'}</tbody></table></div>${rows.length>150?`<div class="report-hint">İlk 150 kayıt gösteriliyor. Excel çıktısı filtreye uyan ${rows.length} kaydın tamamını içerir.</div>`:''}`;
}
function renderReportResults(){
  const host=$('#reportResults');if(!host)return;
  const rows=reportFilteredRows();const service=rows.filter(w=>!isMaintenanceOrder(w));const upkeep=rows.filter(isMaintenanceOrder);
  const active=rows.filter(reportIsOpen),done=rows.filter(reportIsCompleted),waiting=rows.filter(w=>reportIsOpen(w)&&!w.planDate);
  const metrics=[['Toplam İş',rows.length],['Açık Günlük Servis',service.filter(reportIsOpen).length],['Açık Planlı Bakım',upkeep.filter(reportIsOpen).length],['Tamamlanan',done.length],['Plan Bekleyen',waiting.length],['Kritik Açık',active.filter(w=>w.priority==='Kritik').length]];
  const realLogs=reportFilteredTimeLogs();
  const totalHours=realLogs.reduce((n,t)=>n+t.minutes,0);
  const activePeople=new Set(realLogs.map(t=>t.technicianName)).size;
  const loggedIds=new Set(realLogs.map(t=>Number(t.workOrderId)));
  const loggedOrders=loggedIds.size;
  const onsiteMinutes=realLogs.filter(t=>t.activityType==='Saha Çalışması').reduce((n,t)=>n+t.minutes,0);
  const journeyMinutes=realLogs.filter(t=>t.activityType==='Yol / Ulaşım').reduce((n,t)=>n+t.minutes,0);
  const monthly=(w)=>{const d=reportWorkDate(w,state.reportFilters.dateField);return d?d.slice(0,7):'Tarih belirtilmemiş';};
  host.innerHTML=`<div class="report-summary-title"><b>Yönetim Özeti</b><span>Filtrelenen ${rows.length} iş emri • Canlı SQL kayıtlarından</span></div>
  <div class="report-summary-kpis">${metrics.map(([label,n])=>`<div class="report-summary-kpi"><span>${esc(label)}</span><b>${n}</b></div>`).join('')}</div>
  <div class="report-dual-summary"><div><div class="report-dual-title">Günlük Servis</div><b>${service.length} iş</b><span>${service.filter(reportIsOpen).length} açık · ${service.filter(reportIsCompleted).length} tamamlanan</span></div><div><div class="report-dual-title">Planlı / Yıllık Bakım</div><b>${upkeep.length} cihaz işi</b><span>${upkeep.filter(reportIsOpen).length} açık · ${upkeep.filter(reportIsCompleted).length} tamamlanan</span></div></div>
  <div class="report-summary-title"><b>Gerçek Personel Mesaisi • Sahada Kim, Nerede, Kaç Saat?</b><span>İş emri zaman kayıtlarından; plan süresi dahil edilmez</span></div>
  <div class="report-summary-kpis">${[['Kayıtlı Kişi-Saat',hoursLabel(totalHours)],['Süresi Girilen İş',loggedOrders],['Aktif Teknisyen',activePeople],['Sahada Çalışma',hoursLabel(onsiteMinutes)],['Yol Süresi',hoursLabel(journeyMinutes)],['Süre Kaydı Olmayan',rows.filter(w=>!loggedIds.has(Number(w.workOrderId))).length]].map(([label,value])=>`<div class="report-summary-kpi"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('')}</div>
  <div class="notice report-info">Personel-saat toplamı birden fazla teknisyenin ayrı ayrı süresini içerir. Örneğin iki kişi iki saat çalışırsa 4 kişi-saat hesaplanır. Tarih filtresi süre kayıtlarında <b>faaliyetin başlangıç tarihine</b> uygulanır. Süre girişi yapılmamış işlere 0 saat tahmin edilmez.</div>
  <div class="report-pivots"><div class="panel"><div class="panel-h">Gerçek Süre • Teknisyen / Faaliyet</div><div class="panel-b">${reportTimePivot(realLogs,t=>t.technicianName,'Teknisyen')}</div></div>
  <div class="panel"><div class="panel-h">Gerçek Süre • Müşteri / Lokasyon</div><div class="panel-b">${reportTimePivot(realLogs,t=>`${t.work.customerName} • ${t.locationNote||t.work.location||'Lokasyon yok'}`,'Müşteri / Bölge')}</div></div>
  <div class="panel"><div class="panel-h">Gerçek Süre • Ay / Birim</div><div class="panel-b">${reportTimePivot(realLogs,t=>`${String(t.startedAt).slice(0,7)} • ${t.work.unitCode}`,'Dönem / Birim')}</div></div></div>
  <div class="panel"><div class="panel-h">Kim, Nerede, Kaç Saat? • Gerçek Süre Hareketleri <span class="badge b-blue">${realLogs.length}</span></div><div class="panel-b"><div class="table-scroll"><table class="report-pivot-table"><thead><tr><th>Teknisyen</th><th>İş Emri</th><th>Firma</th><th>Lokasyon / Bölge</th><th>Faaliyet</th><th>Başlangıç</th><th>Bitiş</th><th>Süre</th><th>Açıklama</th></tr></thead><tbody>${realLogs.slice(0,200).map(t=>`<tr><td><b>${esc(t.technicianName)}</b></td><td><button class="metric-wo-link" data-reportopen="${Number(t.workOrderId)}">${esc(t.work.workOrderNo)}</button></td><td>${esc(t.work.customerName)}</td><td>${esc(t.locationNote||t.work.location||'-')}</td><td>${esc(t.activityType)}</td><td>${esc(fmtDate(t.startedAt))}</td><td>${esc(fmtDate(t.endedAt))}</td><td>${esc(hoursLabel(t.minutes))}</td><td>${esc(t.workNote||'-')}</td></tr>`).join('')||'<tr><td colspan="9">Gerçek süre kaydı bulunamadı. Teknisyen iş emrinden faaliyet başlangıç/bitişini girmelidir.</td></tr>'}</tbody></table></div>${realLogs.length>200?'<div class="report-hint">İlk 200 süre kaydı gösteriliyor; Excel çıktısında tüm kayıtlar bulunur.</div>':''}</div></div>
  <div class="report-pivots"><div class="panel"><div class="panel-h">Otomatik Çapraz Özet • Birim / İş Türü / Durum</div><div class="panel-b">${reportCrossTable(rows,w=>`${w.unitCode} • ${isMaintenanceOrder(w)?'Planlı Bakım':'Günlük Servis'}`,'Birim / Kategori')}</div></div>
  <div class="panel"><div class="panel-h">Otomatik Çapraz Özet • Ay / Durum</div><div class="panel-b">${reportCrossTable(rows,monthly,'Yıl - Ay')}</div></div>
  <div class="panel"><div class="panel-h">Personel İş Yükü</div><div class="panel-b">${reportPersonnelTable(rows)}</div></div></div>
  <div class="panel"><div class="panel-h">Filtrelenmiş İş Emirleri <span class="badge b-blue">${rows.length}</span></div><div class="panel-b">${reportTableRows(rows)}</div></div>`;
  $$('[data-reportopen]').forEach(el=>el.onclick=()=>openWorkOrder(el.dataset.reportopen));
}
function reportsPage(){
  const f=state.reportFilters;
  const option=(value,title,selected)=>`<option value="${esc(value)}" ${selected===value?'selected':''}>${esc(title||value)}</option>`;
  const types=[...new Set(state.workOrders.filter(x=>unitAllowed(x.unitCode)).map(x=>x.workType).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'tr'));
  return `<div class="panel"><div class="panel-h">Yönetim Raporlama • Otomatik Özet / Excel</div><div class="panel-b">
  <div class="toolbar report-preset-bar"><button class="btn" id="reportReload">↻ Güncelle</button><button class="btn soft" data-reportpreset="day">Bugün</button><button class="btn soft" data-reportpreset="week">Bu Hafta</button><button class="btn soft" data-reportpreset="month">Bu Ay</button><button class="btn soft" data-reportpreset="all">Tüm Tarihler</button><div class="spacer"></div>${can('reports.export')?'<button class="btn primary" id="exportExcel">Excel’e Aktar (8 Sayfa)</button>':''}</div>
  <div class="form-grid report-grid">
    <div class="field"><label>Tarih Esası</label><select id="reportDateField">${option('created','İş Açılış Tarihi',f.dateField)}${option('plan','Plan Tarihi',f.dateField)}${option('closed','Kapanış Tarihi',f.dateField)}</select></div>
    <div class="field"><label>Başlangıç</label><input type="date" id="reportStart" value="${esc(f.start)}"></div>
    <div class="field"><label>Bitiş</label><input type="date" id="reportEnd" value="${esc(f.end)}"></div>
    <div class="field"><label>İş Kategorisi</label><select id="reportKind">${option('all','Tüm İşler',f.kind)}${option('service','Günlük Servis',f.kind)}${option('maintenance','Planlı / Yıllık Bakım',f.kind)}</select></div>
    <div class="field"><label>Birim</label><select id="reportUnit">${option('Tümü','Tüm Birimler',f.unit)}${availableUnits().map(x=>option(x,x,f.unit)).join('')}</select></div>
    <div class="field"><label>Durum</label><select id="reportStatus">${option('Tümü','Tüm Durumlar',f.status)}${statuses.map(x=>option(x,x,f.status)).join('')}</select></div>
    <div class="field"><label>İş Türü</label><select id="reportWorkType">${option('Tümü','Tüm Türler',f.workType)}${types.map(x=>option(x,x,f.workType)).join('')}</select></div>
    <div class="field"><label>Teknisyen</label><input id="reportPerson" placeholder="Personel ara" value="${esc(f.person)}"></div>
    <div class="field"><label>Şef</label><input id="reportChief" placeholder="Şef ara" value="${esc(f.chief)}"></div>
    <div class="field"><label>Müşteri / Lokasyon / Seri No</label><input id="reportCustomer" placeholder="Müşteri veya cihaz ara" value="${esc(f.customer)}"></div>
  </div><div class="notice report-info">Rapor ilk açılışta <b>tüm tarihlerden</b> beslenir. İstersen tarih ve kategori seç. Birim / durum / ay / personel çapraz özetleri filtreye göre otomatik hesaplanır. Excel çıktısında günlük servis, planlı bakım ve gerçek kişi bazlı çalışma saatleri ayrı sayfalardadır. Süre kaydı olmayan işler tahmini süre ile doldurulmaz.</div>
  </div></div><div id="reportResults"></div>`;
}

function offersPage(){
  return `<div class="toolbar">${can('offers.create')?'<button class="btn primary" id="newOfferBtn">＋ Yeni Teklif</button>':''}<div class="spacer"></div><span class="subtle">Güvenlik • Haberleşme • POC • Mobilite • Araç Takip ortak teklif altyapısı</span></div>
  <div class="panel"><div class="panel-h">Teklifler <span class="badge b-blue">${state.offers.length}</span></div><div class="panel-b">${offerTable()}</div></div>`;
}
function offerTable(){
  if(!state.offers.length) return '<div class="subtle">Henüz teklif kaydı yok.</div>';
  return `<div class="table-scroll"><table><thead><tr><th>Teklif No</th><th>İş Emri</th><th>Birim</th><th>Müşteri</th><th>Durum</th><th>Toplam</th><th>Tarih</th><th>İşlem</th></tr></thead><tbody>${state.offers.map(o=>`<tr><td><b>${esc(o.offerNo)}</b></td><td>${esc(o.workOrderNo||'-')}</td><td>${esc(o.unitCode)}</td><td>${esc(o.customerName)}</td><td>${statusBadge(o.status)}</td><td><b>${money(o.grandTotal)} TL</b></td><td>${fmtDate(o.createdAt)}</td><td class="user-actions"><button class="btn soft" data-offerpdf="${o.offerId}">PDF</button>${can('offers.approve') && ['Taslak','Onay Bekliyor'].includes(o.status)?`<button class="btn" data-offerapprove="${o.offerId}">Onayla</button>`:''}${can('offers.send') && o.status==='Onaylandı'?`<button class="btn primary" data-offersend="${o.offerId}" data-email="${esc(o.customerEmail||'')}">Mail Gönder</button>`:''}</td></tr>`).join('')}</tbody></table></div>`;
}

function permissionChecks(selected=[], fieldName='permissions'){
  const catalog=state.meta?.permissions||{};
  return `<div class="permission-grid">${Object.entries(catalog).map(([k,v])=>`<label class="permission-item"><input type="checkbox" name="${esc(fieldName)}" value="${esc(k)}" ${selected.includes('*')||selected.includes(k)?'checked':''}> <span>${esc(v)}</span><small>${esc(k)}</small></label>`).join('')}</div>`;
}
function usersPage(){
  if(!can('users.manage')) return '<div class="notice conflict">Yetkiniz yok.</div>';
  const roles=state.meta?.roles||[];
  return `<div class="two-col user-admin-layout"><div class="panel"><div class="panel-h">Yeni Kullanıcı</div><div class="panel-b"><form id="userForm"><div class="form-grid"><div class="field"><label>Ad Soyad *</label><input name="fullName" required></div><div class="field"><label>Kullanıcı Adı *</label><input name="username" required></div><div class="field"><label>Rol *</label><select name="role" id="newUserRole">${roles.map(r=>`<option>${esc(r)}</option>`).join('')}</select></div><div class="field"><label>Geçici Şifre *</label><input name="password" type="password" minlength="8" required placeholder="Geçici şifre girin" autocomplete="new-password"></div><div class="field span4"><label>Yetkili Birimler</label><div class="multi-box">${allUnits.map(u=>`<label class="multi-option"><input type="checkbox" name="units" value="${esc(u)}" checked> ${esc(u)}</label>`).join('')}</div></div><div class="field span4"><label>Modül / İşlem Yetkileri</label><div id="permissionHost">${permissionChecks(state.meta?.roleDefaults?.[roles[0]]||[])}</div></div><div class="field span4"><label class="check-line"><input type="checkbox" name="mustChange" checked> İlk girişte şifre değişikliği zorunlu</label></div></div><div class="actions"><button class="btn primary">Kullanıcı Oluştur</button></div></form></div></div>
  <div class="panel"><div class="panel-h">Kullanıcılar <span class="badge b-blue">${state.users.length}</span></div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Ad Soyad</th><th>Kullanıcı</th><th>Rol</th><th>Birim</th><th>Durum</th><th>İşlem</th></tr></thead><tbody>${state.users.map(u=>`<tr><td><b>${esc(u.fullName)}</b></td><td>${esc(u.username)}</td><td>${esc(u.roleName)}</td><td>${esc((u.allowedUnits||[]).join(', '))}</td><td>${u.isActive?'<span class="badge b-green">Aktif</span>':'<span class="badge b-red">Pasif</span>'}</td><td class="user-actions"><button class="btn primary" data-useredit="${u.userId}">Düzenle</button>${u.username!=='admin'?`<button class="btn" data-userstatus="${u.userId}" data-active="${u.isActive?'0':'1'}">${u.isActive?'Pasif Yap':'Aktif Yap'}</button>`:''}<button class="btn soft" data-resetpassword="${u.userId}">Şifre Sıfırla</button></td></tr>`).join('')}</tbody></table></div></div></div></div>`;
}

function openUserEditModal(userId){
  const u=state.users.find(x=>Number(x.userId)===Number(userId));
  if(!u) return alert('Kullanıcı bulunamadı.');
  const roles=state.meta?.roles||[];
  const selectedUnits=u.allowedUnits||[];
  modal(`<div class="modal-h"><div><b>Kullanıcı Düzenle • ${esc(u.fullName)}</b><div class="subtle">Birim, rol ve işlem yetkilerini sonradan değiştirebilirsiniz.</div></div><button class="iconbtn" id="modalX">×</button></div>
  <div class="modal-b"><form id="editUserForm"><div class="form-card"><div class="form-h">Kullanıcı Bilgileri</div><div class="form-grid">
    <div class="field"><label>Ad Soyad *</label><input name="fullName" required value="${esc(u.fullName)}"></div>
    <div class="field"><label>Kullanıcı Adı *</label><input name="username" required value="${esc(u.username)}" ${u.username==='admin'?'readonly':''}></div>
    <div class="field"><label>Rol *</label><select name="role" id="editUserRole">${roles.map(r=>`<option ${r===u.roleName?'selected':''}>${esc(r)}</option>`).join('')}</select></div>
    <div class="field"><label>Durum</label><input value="${u.isActive?'Aktif':'Pasif'}" readonly></div>
    <div class="field span4"><label>Yetkili Birimler</label><div class="multi-box">${allUnits.map(unit=>`<label class="multi-option"><input type="checkbox" name="units" value="${esc(unit)}" ${selectedUnits.includes(unit)?'checked':''}> ${esc(unit)}</label>`).join('')}</div></div>
    <div class="field span4"><label>Modül / İşlem Yetkileri</label><div id="editPermissionHost">${permissionChecks(u.permissions||[])}</div></div>
    <div class="field span4"><label class="check-line"><input type="checkbox" name="mustChange" ${u.mustChangePassword?'checked':''}> Sonraki girişte şifre değişikliği zorunlu</label></div>
  </div></div></form></div>
  <div class="modal-f"><button class="btn" id="cancelEditUser">Vazgeç</button><button class="btn primary" id="saveEditUser">Değişiklikleri Kaydet</button></div>`);

  $('#modalX').onclick=$('#cancelEditUser').onclick=closeModal;
  const role=$('#editUserRole');
  if(role) role.onchange=()=>{ $('#editPermissionHost').innerHTML=permissionChecks(state.meta?.roleDefaults?.[role.value]||[]); };
  $('#saveEditUser').onclick=async()=>{
    const form=$('#editUserForm');
    if(!form.reportValidity()) return;
    const fd=new FormData(form);
    try{
      const result=await api(`/api/users/${u.userId}`,{method:'PUT',body:JSON.stringify({
        username:fd.get('username'),
        fullName:fd.get('fullName'),
        roleName:fd.get('role'),
        allowedUnits:fd.getAll('units'),
        permissions:fd.getAll('permissions'),
        mustChangePassword:fd.get('mustChange')==='on'
      })});
      if(state.user?.userId===u.userId && result?.user) state.user=result.user;
      state.users=await api('/api/users');
      closeModal();
      render();
      alert('Kullanıcı ve yetkileri güncellendi.');
    }catch(err){ alert(err.message); }
  };
}

function warehousePage(){
  const rows=state.workOrders.filter(w=>['Atölyede','Kargoda','Beklemede'].includes(w.status));
  const original=`<div class="panel"><div class="panel-h">Depo / Lojistik — Servis İş Emirleri</div><div class="panel-b"><div class="notice">Atölyede, kargoda veya beklemede olan mevcut servis kayıtları.</div><div style="margin-top:12px">${workTable(rows)}</div></div></div>`;
  return `${can('rentals.view')?rentalInventoryView():''}${original}`;
}
function accountingPage(){
  const offers=state.offers.filter(o=>['Onay Bekliyor','Onaylandı','Müşteriye Gönderildi','Kabul Edildi'].includes(o.status));
  return `<div class="panel"><div class="panel-h">Muhasebe / Teklif Görünümü</div><div class="panel-b"><div class="notice">Teklif ve faturalama yönlendirmeleri için ayrılmış görünüm. Pilot aşamada tekliflerin finansal özeti gösterilir.</div><div style="margin-top:12px">${offers.length?`<table><thead><tr><th>Teklif</th><th>Müşteri</th><th>Durum</th><th>Toplam</th></tr></thead><tbody>${offers.map(o=>`<tr><td>${esc(o.offerNo)}</td><td>${esc(o.customerName)}</td><td>${statusBadge(o.status)}</td><td>${money(o.grandTotal)} TL</td></tr>`).join('')}</tbody></table>`:'<div class="subtle">Kayıt yok.</div>'}</div></div></div>`;
}

// V1.13 - Egitim, Yetkinlik ve Saha Gelisim yonetim modulu.
function trainingData(){return state.trainingData||{people:[],courses:[],criteria:[],plans:[],sessions:[],attendance:[],competencies:[],levels:[],observations:[]};}
function trainingIso(d){return d?String(d).slice(0,10):'';}
function trainingDate(d){return d?fmtPlanDate(trainingIso(d)):'—';}
function trainingPersonName(id){return trainingData().people.find(p=>Number(p.personnelId)===Number(id))?.fullName||`Personel #${id}`;}
function trainingCourseTitle(id){return trainingData().courses.find(c=>Number(c.courseId)===Number(id))?.title||`Eğitim #${id}`;}
function trainingPeople(){return trainingData().people.filter(p=>state.trainingUnit==='all'||p.unitCode===state.trainingUnit);}
function trainingSelectedPlans(){return trainingData().plans.filter(p=>trainingPeople().some(x=>Number(x.personnelId)===Number(p.personnelId)));}
function trainingCourseOptions(selected=null){return trainingData().courses.filter(c=>c.isActive).map(c=>`<option value="${c.courseId}" ${Number(selected)===Number(c.courseId)?'selected':''}>${esc(c.title)}${c.unitCode?' • '+esc(c.unitCode):''}</option>`).join('');}
function trainingPersonOptions(selected=null){return trainingPeople().map(p=>`<option value="${p.personnelId}" ${Number(selected)===Number(p.personnelId)?'selected':''}>${esc(p.fullName)}${p.unitCode?' • '+esc(p.unitCode):''}</option>`).join('');}
function trainingTab(id,label){return `<button class="tabbtn ${state.trainingTab===id?'active':''}" data-trainingtab="${id}">${label}</button>`;}
function trainingScoreLabel(score,critical=false){return `<span class="badge ${critical?'b-red':Number(score)>=85?'b-green':Number(score)>=65?'b-amber':'b-red'}">${Number(score).toFixed(0)}%${critical?' · Kritik':''}</span>`;}
function trainingProgress(value,total){let pct=total?Math.round(100*value/total):0;return `<div class="training-progress"><div style="width:${Math.max(0,Math.min(100,pct))}%"></div></div><small>${pct}% (${value}/${total})</small>`;}
function trainingFollowUps(){
  const t=trainingData();const result=[];const today=todayIso();
  const followPlans=[...trainingSelectedPlans(),...(t.carryoverPlans||[]).filter(x=>trainingPeople().some(p=>Number(p.personnelId)===Number(x.personnelId)))];
  for(const p of followPlans.filter(x=>x.status==='Tamamlandı'&&x.completedAt)){
    for(const days of [30,60,90]){
      const date=new Date(trainingIso(p.completedAt)+'T12:00:00');date.setDate(date.getDate()+days);
      const due=[date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
      const done=t.observations.some(o=>Number(o.personnelId)===Number(p.personnelId)&&Number(o.courseId)===Number(p.courseId)&&Number(o.phaseDays)===days);
      if(!done)result.push({...p,phaseDays:days,due,overdue:due<today,upcoming:due<=today});
    }
  }
  return result.sort((a,b)=>a.due.localeCompare(b.due));
}
function trainingOverview(){
  const t=trainingData(),people=trainingPeople(),plans=trainingSelectedPlans(),ids=new Set(people.map(p=>Number(p.personnelId)));
  const completed=plans.filter(p=>p.status==='Tamamlandı').length;
  const observations=t.observations.filter(o=>ids.has(Number(o.personnelId))&&trainingIso(o.observedOn).startsWith(String(state.trainingYear)));
  const scores=observations.map(o=>Number(o.score));const avg=scores.length?Math.round(scores.reduce((a,b)=>a+b,0)/scores.length):null;
  const levels=t.levels.filter(x=>ids.has(Number(x.personnelId)));
  const goals=levels.filter(x=>Number(x.currentLevel)>=Number(x.targetLevel)).length;
  const followUps=trainingFollowUps();
  const units=[...new Set(people.map(p=>p.unitCode||'Genel'))];
  const byUnit=units.map(unit=>{const pids=new Set(people.filter(p=>(p.unitCode||'Genel')===unit).map(p=>Number(p.personnelId)));const list=plans.filter(p=>pids.has(Number(p.personnelId)));return {unit,total:list.length,done:list.filter(p=>p.status==='Tamamlandı').length,people:pids.size};});
  return `<div class="training-kpis">
   <div class="training-stat"><span>Yıllık Eğitim Gerçekleşme</span><strong>${plans.length?Math.round(100*completed/plans.length):0}%</strong><small>${completed} / ${plans.length} hedef</small></div>
   <div class="training-stat"><span>Saha Gözlem Uygunluğu</span><strong>${avg===null?'—':avg+'%'}</strong><small>${observations.length} gözlem kaydı</small></div>
   <div class="training-stat"><span>Hedef Yetkinlik</span><strong>${levels.length?Math.round(100*goals/levels.length)+'%':'—'}</strong><small>${goals} / ${levels.length} değerlendirme</small></div>
   <div class="training-stat"><span>30/60/90 Gün Takip</span><strong>${followUps.filter(x=>x.upcoming).length}</strong><small>Geciken / zamanı gelen</small></div>
  </div>
  <div class="two-col training-columns">
  <div class="panel"><div class="panel-h">Birim Bazlı Eğitim Tamamlama</div><div class="panel-b training-unit-bars">${byUnit.length?byUnit.map(u=>`<div><div class="training-bar-head"><b>${esc(u.unit)}</b><small>${u.people} personel</small></div>${trainingProgress(u.done,u.total)}</div>`).join(''):'<span class="subtle">Aktif personel bulunmadı.</span>'}</div></div>
  <div class="panel"><div class="panel-h">Eğitim Sonrası Saha Takibi <span class="badge b-blue">30 / 60 / 90 gün</span></div>
  <div class="panel-b"><div class="training-queue">${followUps.length?followUps.slice(0,16).map(x=>`<div class="training-queue-row"><div><b>${esc(trainingPersonName(x.personnelId))}</b><small>${esc(trainingCourseTitle(x.courseId))} • ${x.phaseDays}. gün • ${trainingDate(x.due)}</small></div><div>${x.overdue?'<span class="badge b-red">Gecikti</span>':x.upcoming?'<span class="badge b-amber">Zamanı geldi</span>':'<span class="badge b-blue">Yaklaşan</span>'}<button class="btn soft" data-trainfollow="${x.personnelId}:${x.courseId}:${x.phaseDays}">Gözlem</button></div></div>`).join(''):'<div class="subtle">Şu anda açık takip yok. Tamamlanan eğitimlere göre otomatik oluşur.</div>'}</div></div></div></div>
  <div class="panel"><div class="panel-h">Kişi Bazlı Yıllık Eğitim Durumu <span class="badge b-blue">${state.trainingYear}</span></div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Personel</th><th>Birim</th><th>Plan</th><th>Tamamlanan</th><th>İlerleme</th><th>İşlem</th></tr></thead><tbody>${people.map(p=>{const pp=plans.filter(x=>Number(x.personnelId)===Number(p.personnelId));const done=pp.filter(x=>x.status==='Tamamlandı').length;return `<tr><td><b>${esc(p.fullName)}</b></td><td>${esc(p.unitCode||p.departmentName||'Genel')}</td><td>${pp.length}</td><td>${done}</td><td style="min-width:140px">${trainingProgress(done,pp.length)}</td><td><button class="btn soft" data-trainingperson="${p.personnelId}">Gelişim Kartı</button></td></tr>`}).join('')}</tbody></table></div></div></div>`;
}
function trainingPlanPage(){
 const t=trainingData(),plans=trainingSelectedPlans();
 return `${can('training.manage')?`<div class="panel"><div class="panel-h">Yıllık Eğitim Planına Toplu Atama</div><div class="panel-b"><form id="trainingBulkPlanForm"><div class="form-grid">
 <div class="field span2"><label>Eğitim *</label><select name="courseId" required>${trainingCourseOptions()}</select></div>
 <div class="field"><label>Plan yılı</label><input name="planYear" type="number" min="2020" max="2100" value="${state.trainingYear}" readonly></div>
 <div class="field"><label>Hedef tarih *</label><input name="dueDate" type="date" value="${state.trainingYear}-12-15" required></div>
 <div class="field span4"><label>Gelişim hedefi / Beklenen saha davranışı</label><textarea name="personalGoal" rows="2" placeholder="Eğitim sonrası gözlenecek davranış ve hedef"></textarea></div>
 </div><div class="training-people-title"><b>Personel Seçimi</b><button type="button" class="btn soft" id="trainingCheckAll">Görünenleri Seç</button><button type="button" class="btn soft" id="trainingUncheckAll">Seçimi Temizle</button></div>
 <div class="training-check-grid">${trainingPeople().map(p=>`<label><input type="checkbox" name="trainingPerson" value="${p.personnelId}"> <span>${esc(p.fullName)} <small>${esc(p.unitCode||'Genel')}</small></span></label>`).join('')}</div>
 <div class="actions"><button class="btn primary">Seçilenlere Yıllık Eğitim Ata</button></div></form></div></div>`:''}
 <div class="panel"><div class="panel-h">${state.trainingYear} Yılı Eğitim Planı <span class="badge b-blue">${plans.length} atama</span></div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Personel</th><th>Eğitim</th><th>Hedef Tarih</th><th>Durum</th><th>Gelişim Hedefi</th></tr></thead><tbody>${plans.map(p=>`<tr><td>${esc(trainingPersonName(p.personnelId))}</td><td><b>${esc(trainingCourseTitle(p.courseId))}</b></td><td>${trainingDate(p.dueDate)}</td><td><span class="badge ${p.status==='Tamamlandı'?'b-green':trainingIso(p.dueDate)<todayIso()?'b-red':'b-blue'}">${esc(p.status)}</span></td><td>${esc(p.personalGoal||'—')}</td></tr>`).join('')||'<tr><td colspan="5">Henüz bu yıla ait eğitim planı yok.</td></tr>'}</tbody></table></div></div></div>`;
}
function trainingCatalogPage(){
 const t=trainingData();
 return `<div class="panel"><div class="panel-h">Eğitim Kataloğu ve Beklenen Saha Davranışı</div><div class="panel-b"><div class="training-course-grid">${t.courses.map(c=>{const cs=t.criteria.filter(x=>Number(x.courseId)===Number(c.courseId));return `<div class="training-course-card"><div class="training-course-top"><b>${esc(c.title)}</b><span class="badge ${c.mandatory?'b-amber':'b-blue'}">${c.mandatory?'Zorunlu':'Gelişim'}</span></div><small>${esc(c.courseCode)} • ${esc(c.category)} • ${Number(c.durationHours)} saat ${c.unitCode?'• '+esc(c.unitCode):'• Tüm Birimler'}</small><div><strong>Neden?</strong> ${esc(c.reason||'Belirlenmedi')}</div><div><strong>Beklenen davranış:</strong> ${esc(c.targetBehavior||'Belirlenmedi')}</div><div><strong>Başarı ölçütü:</strong> ${esc(c.successMetric||'Belirlenmedi')}</div><details><summary>${cs.length} saha kontrol maddesi</summary><ol>${cs.map(i=>`<li>${i.isCritical?'⚠️ ':''}${esc(i.criterionText)}</li>`).join('')}</ol></details></div>`}).join('')}</div></div></div>
 ${can('training.manage')?`<div class="panel"><div class="panel-h">Yeni Eğitim ve Saha Kontrol Listesi Tanımla</div><div class="panel-b"><form id="trainingCourseForm"><div class="form-grid">
 <div class="field"><label>Eğitim Kodu *</label><input name="code" required placeholder="TEKNIK-2027-01"></div>
 <div class="field span2"><label>Eğitim Başlığı *</label><input name="title" required></div>
 <div class="field"><label>Kategori</label><select name="category"><option>Teknik</option><option>İSG</option><option>Kişisel Gelişim</option><option>İş Süreci</option></select></div>
 <div class="field"><label>Birim</label><select name="unitCode"><option value="">Tüm Birimler</option>${allUnits.map(u=>`<option>${esc(u)}</option>`).join('')}</select></div>
 <div class="field"><label>Süre (saat)</label><input name="durationHours" type="number" min="0.5" max="24" step="0.5" value="2" required></div>
 <div class="field"><label>Zorunlu</label><select name="mandatory"><option value="0">Hayır</option><option value="1">Evet</option></select></div>
 <div class="field span2"><label>Neden bu eğitimi veriyoruz?</label><textarea name="reason" rows="2"></textarea></div>
 <div class="field span2"><label>Hangi davranış değişsin?</label><textarea name="targetBehavior" rows="2"></textarea></div>
 <div class="field span2"><label>Nasıl ölçeceğiz?</label><textarea name="successMetric" rows="2"></textarea></div>
 <div class="field span4"><label>Saha gözlem kontrol maddeleri (her satıra bir madde, kritik maddelerin başına ! koy)</label><textarea name="checklist" rows="4" required placeholder="! Sahada gerekli İSG önlemlerini aldı\nSeri numarasını doğruladı\nYapılan işi doğru kaydetti"></textarea></div>
 </div><div class="actions"><button class="btn primary">Eğitimi ve Kontrol Listesini Kaydet</button></div></form></div></div>`:''}`;
}
function trainingSessionPage(){
 const t=trainingData(), s=t.sessions; const visibleIds=new Set(trainingPeople().map(p=>Number(p.personnelId)));
 const att=t.attendance.filter(a=>visibleIds.has(Number(a.personnelId)));
 return `${can('training.manage')?`<div class="two-col training-columns"><div class="panel"><div class="panel-h">Gerçekleşen Eğitim Kaydı</div><div class="panel-b"><form id="trainingSessionForm" class="training-form"><div class="field"><label>Eğitim</label><select name="courseId">${trainingCourseOptions()}</select></div><div class="field"><label>Tarih</label><input name="sessionDate" type="date" value="${todayIso()}" required></div><div class="field"><label>Eğitmen</label><input name="trainerName" value="${esc(state.user?.fullName||'')}" required></div><div class="field"><label>Gerçekleşen süre (saat)</label><input name="durationHours" type="number" min="0.5" max="24" step="0.5" value="2" required></div><div class="field"><label>Yer</label><input name="location" placeholder="Eğitim salonu / Saha"></div><div class="field"><label>Eğitim notu</label><textarea name="notes" rows="2"></textarea></div><button class="btn primary">Eğitimi Kaydet</button></form></div></div>
 <div class="panel"><div class="panel-h">Katılım ve Ön/Son Değerlendirme</div><div class="panel-b"><form id="trainingAttendanceForm" class="training-form"><div class="field"><label>Eğitim Oturumu</label><select name="trainingSessionId" required>${s.map(x=>`<option value="${x.trainingSessionId}">${esc(trainingCourseTitle(x.courseId))} · ${trainingDate(x.sessionDate)}</option>`).join('')}</select></div><div class="field"><label>Personel</label><select name="personnelId">${trainingPersonOptions()}</select></div><div class="field"><label>Katılım</label><select name="attended"><option value="1">Katıldı (tamamlandı)</option><option value="0">Katılmadı</option></select></div><div class="form-grid"><div class="field"><label>Eğitim öncesi puan /100</label><input name="scoreBefore" type="number" min="0" max="100" placeholder="Opsiyonel"></div><div class="field"><label>Eğitim sonrası puan /100</label><input name="scoreAfter" type="number" min="0" max="100" placeholder="Opsiyonel"></div></div><div class="field"><label>Değerlendirme notu</label><textarea name="notes" rows="2"></textarea></div><button class="btn primary" ${s.length?'':'disabled'}>Katılım / Ölçüm Kaydet</button></form></div></div></div>`:''}
 <div class="panel"><div class="panel-h">Gerçekleşen Eğitimler ve Katılımcılar</div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Tarih</th><th>Eğitim</th><th>Eğitmen</th><th>Süre</th><th>Katılan</th><th>Ön / Son Puan</th></tr></thead><tbody>${s.map(x=>{const a=att.filter(a=>Number(a.trainingSessionId)===Number(x.trainingSessionId));let scored=a.filter(x=>x.scoreBefore!==null&&x.scoreAfter!==null);let before=scored.length?Math.round(scored.reduce((sum,a)=>sum+Number(a.scoreBefore),0)/scored.length):null,after=scored.length?Math.round(scored.reduce((sum,a)=>sum+Number(a.scoreAfter),0)/scored.length):null;return `<tr><td>${trainingDate(x.sessionDate)}</td><td><b>${esc(trainingCourseTitle(x.courseId))}</b></td><td>${esc(x.trainerName)}</td><td>${x.durationHours} sa.</td><td>${a.filter(x=>x.attended).length}</td><td>${before===null?'—':before+' → '+after}</td></tr>`}).join('')||'<tr><td colspan="6">Henüz gerçekleşen eğitim girilmedi.</td></tr>'}</tbody></table></div></div></div>`;
}
function trainingChecks(courseId){const cs=trainingData().criteria.filter(x=>Number(x.courseId)===Number(courseId));return `<div class="training-checks">${cs.map(c=>`<div class="training-check"><div><b>${esc(c.criterionText)}</b>${c.isCritical?'<small class="training-critical">Kritik İSG / güvenlik maddesi</small>':''}</div><select class="training-rating" data-criterion="${c.criterionId}"><option value="-1">Gözlenmedi</option><option value="2">Uygun (2)</option><option value="1">Geliştirilmeli (1)</option><option value="0">Uygun değil (0)</option></select></div>`).join('')}</div>`;}
function trainingObservationPage(){
 const t=trainingData(), p=state.trainingDraft||{};const defaultCourse=p.courseId||t.courses[0]?.courseId;
 const obs=t.observations.filter(o=>trainingIso(o.observedOn).startsWith(String(state.trainingYear))&&trainingPeople().some(x=>Number(x.personnelId)===Number(o.personnelId)));
 return `${can('training.observe')||can('training.manage')?`<div class="panel"><div class="panel-h">Saha Gözlem Formu • İş Emriyle Bağlantılı</div><div class="panel-b"><form id="trainingObservationForm"><div class="form-grid">
 <div class="field"><label>Personel *</label><select name="personnelId" required>${trainingPersonOptions(p.personnelId)}</select></div>
 <div class="field span2"><label>Gözlemlenen Eğitim *</label><select id="trainingObserveCourse" name="courseId" required>${trainingCourseOptions(defaultCourse)}</select></div>
 <div class="field"><label>Gözlem Aşaması</label><select name="phaseDays">${[[0,'İlk Gözlem'],[30,'30. Gün'],[60,'60. Gün'],[90,'90. Gün']].map(([v,l])=>`<option value="${v}" ${Number(p.phaseDays)===v?'selected':''}>${l}</option>`).join('')}</select></div>
 <div class="field"><label>Gözlem Tarihi</label><input name="observedOn" type="date" value="${todayIso()}" required></div>
 <div class="field span2"><label>İlgili İş Emri (varsa)</label><select name="workOrderId"><option value="">Bağımsız saha gözlemi</option>${state.workOrders.slice(0,400).map(w=>`<option value="${w.workOrderId}">${esc(w.workOrderNo)} • ${esc(w.customerName||'')}</option>`).join('')}</select></div>
 <div class="field span4"><label>Uygulama ve Davranış Kontrol Listesi</label><div id="trainingCriteriaHost">${trainingChecks(defaultCourse)}</div></div>
 <div class="field span2"><label>Gözlemci Notu</label><textarea name="notes" rows="3" placeholder="Somut olay, kanıt, güçlü yönler"></textarea></div>
 <div class="field span2"><label>Gelişim / Düzeltici Faaliyet Hedefi</label><textarea name="actionPlan" rows="3" placeholder="Geliştirilecek davranış, sorumlu, hedef"></textarea></div>
 <div class="field"><label>Sonraki İzleme Tarihi</label><input name="nextReviewDate" type="date"></div>
 </div><div class="actions"><button class="btn primary">Saha Gözlemini Kaydet</button></div></form></div></div>`:''}
 <div class="panel"><div class="panel-h">Kayıtlı Saha Gözlemleri <span class="badge b-blue">${obs.length}</span></div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Tarih</th><th>Personel</th><th>Eğitim</th><th>Aşama</th><th>Puan</th><th>Gelişim / Not</th></tr></thead><tbody>${obs.slice(0,100).map(x=>`<tr><td>${trainingDate(x.observedOn)}</td><td><b>${esc(trainingPersonName(x.personnelId))}</b></td><td>${esc(trainingCourseTitle(x.courseId))}</td><td>${x.phaseDays===0?'İlk gözlem':x.phaseDays+'. gün'}</td><td>${trainingScoreLabel(x.score,x.criticalFailure)}</td><td>${esc(x.actionPlan||x.notes||'—')}</td></tr>`).join('')||'<tr><td colspan="6">Henüz saha gözlemi yok.</td></tr>'}</tbody></table></div></div></div>`;
}
function trainingCompetenciesPage(){
 const t=trainingData(),levels=t.levels.filter(l=>trainingPeople().some(p=>Number(p.personnelId)===Number(l.personnelId)));
 return `<div class="notice">Yetkinlik seviyesi: <b>1</b> Başlangıç · <b>2</b> Gözetimle çalışır · <b>3</b> Bağımsız yapar · <b>4</b> Uzman / Eğitici. Kritik yetkinliklerde puanın yanında uygulama kanıtı değerlendirilmelidir.</div>
 ${can('training.observe')||can('training.manage')?`<div class="panel"><div class="panel-h">Personel Yetkinlik Değerlendirmesi</div><div class="panel-b"><form id="trainingCompetencyForm"><div class="form-grid">
 <div class="field"><label>Personel</label><select name="personnelId">${trainingPersonOptions()}</select></div>
 <div class="field span2"><label>Yetkinlik</label><select name="competencyId">${t.competencies.map(c=>`<option value="${c.competencyId}">${esc(c.name)}${c.unitCode?' • '+esc(c.unitCode):''}</option>`).join('')}</select></div>
 <div class="field"><label>Mevcut seviye</label><select name="currentLevel">${[1,2,3,4].map(i=>`<option value="${i}" ${i===2?'selected':''}>${i}</option>`).join('')}</select></div>
 <div class="field"><label>Hedef seviye</label><select name="targetLevel">${[1,2,3,4].map(i=>`<option value="${i}" ${i===3?'selected':''}>${i}</option>`).join('')}</select></div>
 <div class="field"><label>Değerlendirme tarihi</label><input name="assessedAt" type="date" value="${todayIso()}" required></div>
 <div class="field"><label>Sonraki gözden geçirme</label><input name="nextReviewDate" type="date"></div>
 <div class="field span4"><label>Kanıt / gözlem / uygulama sınavı notu</label><textarea name="evidence" rows="2"></textarea></div>
 </div><div class="actions"><button class="btn primary">Yetkinliği Kaydet</button></div></form></div></div>`:''}
 <div class="panel"><div class="panel-h">Yetkinlik Matrisi</div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Personel</th><th>Yetkinlik</th><th>Mevcut</th><th>Hedef</th><th>Durum</th><th>Gözlem / Kanıt</th><th>Sonraki</th></tr></thead><tbody>${levels.map(l=>{const c=t.competencies.find(x=>Number(x.competencyId)===Number(l.competencyId));return `<tr><td><b>${esc(trainingPersonName(l.personnelId))}</b></td><td>${esc(c?.name||'—')}${c?.isCritical?' ⚠️':''}</td><td><b>${l.currentLevel}/4</b></td><td>${l.targetLevel}/4</td><td><span class="badge ${l.currentLevel>=l.targetLevel?'b-green':'b-amber'}">${l.currentLevel>=l.targetLevel?'Hedefte':'Gelişim gerekli'}</span></td><td>${esc(l.evidence||'—')}</td><td>${trainingDate(l.nextReviewDate)}</td></tr>`}).join('')||'<tr><td colspan="7">Henüz yetkinlik değerlendirmesi yapılmadı.</td></tr>'}</tbody></table></div></div></div>`;
}
function trainingPersonCardPage(){
 const t=trainingData(),people=trainingPeople();
 const person=people.find(p=>Number(p.personnelId)===Number(state.trainingPerson))||people[0];
 if(!person)return '<div class="notice">Görünür personel bulunmadı.</div>';
 const id=Number(person.personnelId),plans=t.plans.filter(x=>Number(x.personnelId)===id),levels=t.levels.filter(x=>Number(x.personnelId)===id),obs=t.observations.filter(x=>Number(x.personnelId)===id);
 const completed=plans.filter(x=>x.status==='Tamamlandı').length;
 return `<div class="panel"><div class="panel-h">Bireysel Gelişim Kartı <span class="spacer"></span><select id="trainingPersonCardSelect">${trainingPersonOptions(id)}</select></div><div class="panel-b"><h3>${esc(person.fullName)}</h3><div class="subtle">${esc(person.title||'')} • ${esc(person.departmentName||person.unitCode||'')}</div><div class="training-person-summary"><div><b>${completed}/${plans.length}</b><small>Yıllık eğitim</small></div><div><b>${levels.filter(x=>Number(x.currentLevel)>=Number(x.targetLevel)).length}/${levels.length}</b><small>Hedef yetkinlik</small></div><div><b>${obs.length}</b><small>Saha gözlemi</small></div></div>
 <h4>Yıllık Eğitim Planı</h4><div class="table-scroll"><table><thead><tr><th>Eğitim</th><th>Hedef</th><th>Durum</th></tr></thead><tbody>${plans.map(x=>`<tr><td>${esc(trainingCourseTitle(x.courseId))}</td><td>${trainingDate(x.dueDate)}</td><td>${statusBadge(x.status)}</td></tr>`).join('')||'<tr><td colspan="3">Plan yok</td></tr>'}</tbody></table></div>
 <h4>Yetkinlikler</h4><div class="table-scroll"><table><thead><tr><th>Yetkinlik</th><th>Mevcut / Hedef</th><th>Kanıt</th></tr></thead><tbody>${levels.map(x=>`<tr><td>${esc(t.competencies.find(c=>Number(c.competencyId)===Number(x.competencyId))?.name||'')}</td><td>${x.currentLevel} / ${x.targetLevel}</td><td>${esc(x.evidence||'—')}</td></tr>`).join('')||'<tr><td colspan="3">Değerlendirme yok</td></tr>'}</tbody></table></div>
 <h4>Saha Gelişim Geçmişi</h4>${obs.length?`<div class="training-observation-cards">${obs.map(x=>`<div><small>${trainingDate(x.observedOn)} · ${x.phaseDays===0?'İlk':x.phaseDays+'. gün'} · ${esc(trainingCourseTitle(x.courseId))}</small><b>${trainingScoreLabel(x.score,x.criticalFailure)}</b><p>${esc(x.actionPlan||x.notes||'—')}</p></div>`).join('')}</div>`:'<p class="subtle">Henüz saha gözlemi yok.</p>'}</div></div>`;
}
function trainingPage(){
 if(!state.trainingData)return '<div class="panel"><div class="panel-b">Eğitim verileri yükleniyor...</div></div>';
 const units=[...new Set(trainingData().people.map(p=>p.unitCode).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'tr'));
 const tab=state.trainingTab||'overview';
 return `<div class="training-head"><div><h2>Eğitim, Yetkinlik ve Personel Gelişimi</h2><p class="subtle">Eğitim → uygulama → 30/60/90 gün saha gözlemi → ölçülebilir gelişim</p></div>
 <div class="training-filters"><label>Yıl <input id="trainingYear" type="number" min="2020" max="2100" value="${state.trainingYear}"></label><label>Birim <select id="trainingUnit"><option value="all">Tüm Birimler</option>${units.map(u=>`<option value="${esc(u)}" ${state.trainingUnit===u?'selected':''}>${esc(u)}</option>`).join('')}</select></label>
 ${can('training.export')?'<button class="btn soft" id="trainingExport">Excel için CSV ↧</button>':''}</div></div>
 <div class="training-tabs">${trainingTab('overview','Yönetim Özeti')}${trainingTab('plans','Yıllık Plan')}${trainingTab('courses','Eğitim Kataloğu')}${trainingTab('sessions','Katılım ve Sınav')}${trainingTab('observations','Saha Gözlemi')}${trainingTab('competencies','Yetkinlik Matrisi')}${trainingTab('person','Bireysel Gelişim')}</div>
 ${tab==='overview'?trainingOverview():tab==='plans'?trainingPlanPage():tab==='courses'?trainingCatalogPage():tab==='sessions'?trainingSessionPage():tab==='observations'?trainingObservationPage():tab==='competencies'?trainingCompetenciesPage():trainingPersonCardPage()}`;
}
async function trainingRefresh(){state.trainingData=await api(`/api/training/overview?year=${state.trainingYear}`);}
async function trainingSubmit(url,obj,success){try{await api(url,{method:'POST',body:JSON.stringify(obj)});await trainingRefresh();render();alert(success||'Kaydedildi.');}catch(e){alert(e.message);}}
function bindTraining(){
 $$('[data-trainingtab]').forEach(b=>b.onclick=()=>{state.trainingTab=b.dataset.trainingtab;render();});
 $('#trainingUnit')?.addEventListener('change',e=>{state.trainingUnit=e.target.value;render();});
 $('#trainingYear')?.addEventListener('change',async e=>{const y=Number(e.target.value);if(y<2020||y>2100)return;state.trainingYear=y;try{await trainingRefresh();render();}catch(e){alert(e.message);}});
 $('#trainingExport')?.addEventListener('click',()=>downloadBlob(`/api/training/export.csv?year=${state.trainingYear}`,`Egitim_${state.trainingYear}.csv`).catch(e=>alert(e.message)));
 $$('[data-trainingperson]').forEach(b=>b.onclick=()=>{state.trainingPerson=b.dataset.trainingperson;state.trainingTab='person';render();});
 $('#trainingPersonCardSelect')?.addEventListener('change',e=>{state.trainingPerson=e.target.value;render();});
 $$('[data-trainfollow]').forEach(b=>b.onclick=()=>{const [personnelId,courseId,phaseDays]=b.dataset.trainfollow.split(':');state.trainingDraft={personnelId,courseId,phaseDays:Number(phaseDays)};state.trainingTab='observations';render();});
 $('#trainingCheckAll')?.addEventListener('click',()=>$$('[name="trainingPerson"]').forEach(el=>el.checked=true));
 $('#trainingUncheckAll')?.addEventListener('click',()=>$$('[name="trainingPerson"]').forEach(el=>el.checked=false));
 $('#trainingBulkPlanForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.target);const personnelIds=f.getAll('trainingPerson').map(Number);if(!personnelIds.length){alert('En az bir personel seç.');return;}trainingSubmit('/api/training/plans/bulk',{personnelIds,courseId:Number(f.get('courseId')),planYear:Number(f.get('planYear')),dueDate:f.get('dueDate'),personalGoal:f.get('personalGoal')},'Yıllık eğitim planı kaydedildi.');});
 $('#trainingCourseForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.target);trainingSubmit('/api/training/courses',{code:f.get('code'),title:f.get('title'),category:f.get('category'),unitCode:f.get('unitCode')||null,reason:f.get('reason'),targetBehavior:f.get('targetBehavior'),successMetric:f.get('successMetric'),durationHours:Number(f.get('durationHours')),mandatory:f.get('mandatory')==='1',checklist:f.get('checklist')},'Eğitim ve saha kontrol listesi oluşturuldu.');});
 $('#trainingSessionForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.target);trainingSubmit('/api/training/sessions',{courseId:Number(f.get('courseId')),sessionDate:f.get('sessionDate'),trainerName:f.get('trainerName'),durationHours:Number(f.get('durationHours')),location:f.get('location'),notes:f.get('notes')},'Gerçekleşen eğitim kaydedildi.');});
 $('#trainingAttendanceForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.target);const n=v=>v===''?null:Number(v);trainingSubmit('/api/training/attendance',{trainingSessionId:Number(f.get('trainingSessionId')),personnelId:Number(f.get('personnelId')),attended:f.get('attended')==='1',scoreBefore:n(f.get('scoreBefore')),scoreAfter:n(f.get('scoreAfter')),notes:f.get('notes')},'Katılım ve değerlendirme kaydedildi.');});
 $('#trainingCompetencyForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.target);trainingSubmit('/api/training/competencies',{personnelId:Number(f.get('personnelId')),competencyId:Number(f.get('competencyId')),currentLevel:Number(f.get('currentLevel')),targetLevel:Number(f.get('targetLevel')),assessedAt:f.get('assessedAt'),nextReviewDate:f.get('nextReviewDate')||null,evidence:f.get('evidence')},'Yetkinlik kaydedildi.');});
 $('#trainingObserveCourse')?.addEventListener('change',e=>{$('#trainingCriteriaHost').innerHTML=trainingChecks(e.target.value);});
 $('#trainingObservationForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.target),ratings=$$('.training-rating').map(el=>({criterionId:Number(el.dataset.criterion),rating:Number(el.value)}));if(!ratings.some(r=>r.rating>=0)){alert('En az bir gözlem maddesini değerlendir.');return;}const critical=ratings.some(r=>r.rating===0&&trainingData().criteria.some(c=>Number(c.criterionId)===r.criterionId&&c.isCritical));if(critical&&!confirm('Kritik uygunsuzluk tespit edildi. Gözlem kritik olarak kaydedilecek. Devam edilsin mi?'))return;trainingSubmit('/api/training/observations',{personnelId:Number(f.get('personnelId')),courseId:Number(f.get('courseId')),workOrderId:f.get('workOrderId')?Number(f.get('workOrderId')):null,observedOn:f.get('observedOn'),phaseDays:Number(f.get('phaseDays')),ratings,notes:f.get('notes'),actionPlan:f.get('actionPlan'),nextReviewDate:f.get('nextReviewDate')||null},'Saha gözlemi ve puanlaması kaydedildi.');state.trainingDraft=null;});
}

// V1.14 - Canli faaliyet takibi. Mevcut manuel sure kayitlarini degistirmez.
const liveActivities=['Yol / Ulaşım','Saha Çalışması','Bekleme','Uzaktan Destek','Atölye','Test / Kontrol','Mola / Ara'];
function liveActiveMine(){return (state.liveTracking?.active||[]).find(x=>Number(x.technicianUserId)===Number(state.user?.userId));}
function liveMinutesSince(start){return Math.max(0,Math.floor((Date.now()-new Date(start).getTime())/60000));}
function liveClock(minutes){const m=Math.max(0,Number(minutes)||0);return `${Math.floor(m/60)} sa ${String(m%60).padStart(2,'0')} dk`;}
function liveActivityOptions(selected){return liveActivities.map(a=>`<option ${a===selected?'selected':''}>${esc(a)}</option>`).join('');}
async function reloadLiveTracking(){state.liveTracking=await api('/api/timetracking/summary');}
async function submitLiveAction(id,action,activityType,locationNote,workNote){
  const route=action==='start'?'start':action==='finish'?'finish':'change';
  const result=await api(`/api/workorders/${id}/live-timer/${route}`,{
    method:'POST',body:JSON.stringify({activityType,locationNote,workNote})
  });
  await reloadLiveTracking();
  if(can('reports.view'))state.workLogs=await api('/api/reports/worklogs');
  return result;
}
function liveWorkOrderControls(w){
  if(!can('workorders.edit')&&!can('workorders.close'))return '';
  const assigned=String(w.assignedStaff||'').split(',').map(x=>x.trim()).some(x=>x.toLocaleLowerCase('tr-TR')===String(state.user.fullName||'').toLocaleLowerCase('tr-TR'));
  const active=liveActiveMine(),mine=active&&Number(active.workOrderId)===Number(w.workOrderId);
  const other=active&&!mine;
  return `<div class="form-card live-time-card"><div class="form-h">V1.14 • Canlı Personel Zaman Sayacı</div>
    <div class="notice">Süre yalnızca <b>kendi ERP hesabınızla</b> ve size atanmış işte ölçülür. Yol, saha, bekleme ayrı kaydedilir. Mola kişi-saat hesabına dahil edilmez.</div>
    ${active?`<div class="live-running"><b>${esc(active.activityType)}</b> • ${esc(active.technicianName)} • <span data-live-elapsed="${esc(active.startedAt)}">${esc(liveClock(liveMinutesSince(active.startedAt)))}</span>${other?`<div class="subtle">Aktif sayaç başka işte. Önce o işi açıp bitirin: ${esc((state.workOrders.find(x=>Number(x.workOrderId)===Number(active.workOrderId))||{}).workOrderNo||'')}</div>`:''}</div>`:'<div class="subtle">Aktif zaman sayacınız yok.</div>'}
    ${!assigned?'<div class="notice">Bu işte kendi adınıza teknisyen ataması yok. Sayaç başlatmak için önce atama yapılmalı.</div>':other?'<div class="subtle">Bir personel aynı anda yalnızca bir işi süreye alabilir.</div>':`
    <div class="form-grid"><div class="field span2"><label>Faaliyet türü</label><select id="woLiveActivity">${liveActivityOptions(mine?active.activityType:'Yol / Ulaşım')}</select></div>
    <div class="field span2"><label>Bulunduğu bölge</label><input id="woLiveLocation" maxlength="250" placeholder="Bina / kat / cihaz bölgesi" value="${esc(active?.locationNote||w.siteArea||'')}"></div>
    <div class="field span4"><label>Yapılan işlem / not</label><input id="woLiveNote" maxlength="1000" placeholder="İşlem ya da bekleme nedeni"></div></div>
    <div class="actions">${mine?`<button class="btn primary" data-liveaction="change" data-livework="${Number(w.workOrderId)}" data-livesource="wo">Faaliyeti Değiştir</button><button class="btn soft" data-liveaction="finish" data-livework="${Number(w.workOrderId)}" data-livesource="wo">Süreyi Bitir</button>`:`<button class="btn primary" data-liveaction="start" data-livework="${Number(w.workOrderId)}" data-livesource="wo">Sayacı Başlat</button>`}</div>`}
    <div class="subtle report-hint">Süreyi bitirmek iş emrini otomatik kapatmaz; mevcut iş kapatma adımı ayrıca uygulanır.</div>
  </div>`;
}
function timeTrackingPage(){
  const d=state.liveTracking||{active:[],logs:[],isManager:false};
  const me=liveActiveMine();
  const orders=state.workOrders.filter(x=>unitAllowed(x.unitCode)&&reportIsOpen(x)&&String(x.assignedStaff||'').split(',').map(z=>z.trim().toLocaleLowerCase('tr-TR')).includes(String(state.user.fullName).toLocaleLowerCase('tr-TR')));
  const picked=orders.find(w=>Number(w.workOrderId)===Number(state.timeWorkOrder))||orders[0];
  const f=state.timeFilters;
  const all=(d.logs||[]).filter(x=>{
    const w=state.workOrders.find(y=>Number(y.workOrderId)===Number(x.workOrderId));
    if(!w)return false;
    const date=String(x.startedAt||'').slice(0,10);
    const search=`${x.technicianName} ${w.customerName} ${w.location} ${x.locationNote||''} ${w.workOrderNo}`.toLocaleLowerCase('tr-TR');
    return (!f.start||date>=f.start)&&(!f.end||date<=f.end)&&(f.unit==='Tümü'||w.unitCode===f.unit)&&(!f.person||x.technicianName.toLocaleLowerCase('tr-TR').includes(f.person.toLocaleLowerCase('tr-TR')))&&(!f.search||search.includes(f.search.toLocaleLowerCase('tr-TR')));
  });
  const breaks=(d.breaks||[]).filter(t=>{
    const w=state.workOrders.find(y=>Number(y.workOrderId)===Number(t.workOrderId));if(!w)return false;
    const date=String(t.startedAt||'').slice(0,10);
    const searchable=`${t.technicianName} ${w.customerName} ${w.location} ${t.locationNote||''} ${w.workOrderNo}`.toLocaleLowerCase('tr-TR');
    return (!f.start||date>=f.start)&&(!f.end||date<=f.end)&&(f.unit==='Tümü'||w.unitCode===f.unit)&&(!f.person||t.technicianName.toLocaleLowerCase('tr-TR').includes(f.person.toLocaleLowerCase('tr-TR')))&&(!f.search||searchable.includes(f.search.toLocaleLowerCase('tr-TR')));
  });
  const breakMinutes=breaks.reduce((sum,t)=>sum+Math.max(0,Math.floor((new Date(t.endedAt).getTime()-new Date(t.startedAt).getTime())/60000)),0);
  const mins=all.reduce((n,t)=>n+Number(t.minutes||0),0);
  const sumActivity=type=>all.filter(x=>x.activityType===type).reduce((n,x)=>n+Number(x.minutes||0),0);
  const unique=new Set(all.map(x=>Number(x.workOrderId))).size;
  const active=(d.active||[]).filter(x=>{
    const w=state.workOrders.find(y=>Number(y.workOrderId)===Number(x.workOrderId));return w&&(f.unit==='Tümü'||w.unitCode===f.unit);
  });
  const pivot=new Map();
  for(const t of all){const p=t.technicianName; if(!pivot.has(p))pivot.set(p,{logs:[],mins:0});const r=pivot.get(p);r.logs.push(t);r.mins+=Number(t.minutes||0);}
  const pivots=[...pivot.entries()].sort((a,b)=>b[1].mins-a[1].mins);
  const lookup=id=>state.workOrders.find(w=>Number(w.workOrderId)===Number(id))||{};
  const action=me?`<div class="live-running"><b>Aktif: ${esc(me.activityType)}</b><span data-live-elapsed="${esc(me.startedAt)}">${esc(liveClock(liveMinutesSince(me.startedAt)))}</span><div class="subtle">${esc(lookup(me.workOrderId).workOrderNo||'')} • ${esc(lookup(me.workOrderId).customerName||'')}</div></div>`:'<div class="subtle">Şu anda aktif faaliyet kaydınız yok.</div>';
  return `<div class="report-section-head"><div><b>Saha Zaman Takibi • V1.14</b><span class="subtle">Gerçek başlangıç/bitiş • iş emri bazında • SQL kalıcı kayıt</span></div><button class="btn soft" id="liveRefresh">↻ Güncelle</button></div>
  <div class="two-col live-tracker-layout"><div class="panel"><div class="panel-h">Benim Canlı Faaliyetim</div><div class="panel-b">${action}
  <div class="notice" style="margin-top:10px">Yol → saha → mola → devam → bitir. Faaliyet değişiminde önceki bölüm otomatik kaydedilir. Her bölüm en az 1 dakika olmalıdır.</div>
  ${!me?`<div class="field"><label>Atandığım açık iş emri</label><select id="timeWorkOrder">${orders.map(w=>`<option value="${w.workOrderId}" ${w===picked?'selected':''}>${esc(w.workOrderNo)} • ${esc(w.customerName)} • ${esc(w.location||'')}</option>`).join('')}</select></div>`:''}
  ${me&&lookup(me.workOrderId).workOrderId?`<div class="actions"><button class="btn soft" id="liveOpenWork" data-open-id="${Number(me.workOrderId)}">İş emrini aç ↗</button></div>`:''}
  ${!me&&!orders.length?'<div class="notice">Size atanmış açık iş emri bulunamadı. Önce İş Emirleri ekranından atama yapılmalı.</div>':`<div class="form-grid" style="margin-top:12px"><div class="field span2"><label>Faaliyet</label><select id="timeActivity">${liveActivityOptions(me?.activityType||'Yol / Ulaşım')}</select></div><div class="field span2"><label>Lokasyon / cihazın bölgesi</label><input id="timeLocation" maxlength="250" value="${esc(me?.locationNote||picked?.siteArea||'')}" placeholder="Örnek: A blok / kat 1"></div><div class="field span4"><label>Not / bekleme nedeni</label><textarea id="timeNote" maxlength="1000" rows="2" placeholder="Sahada yapılan işlem veya yol notu"></textarea></div></div><div class="actions">${me?`<button class="btn primary" data-liveaction="change" data-livework="${Number(me.workOrderId)}" data-livesource="page">Faaliyeti Değiştir</button><button class="btn soft" data-liveaction="finish" data-livework="${Number(me.workOrderId)}" data-livesource="page">Süreyi Bitir</button>`:`<button class="btn primary" ${picked?'':'disabled'} data-liveaction="start" data-livework="${Number(picked?.workOrderId||0)}" data-livesource="page">Sayacı Başlat</button>`}</div>`}
  <div class="subtle report-hint">İş emri kapatma işlemi süreyi bitirmekten ayrıdır. 18 saatten uzun açık sayaçlar yetkili yönetici tarafından iptal edilmelidir.</div></div></div>
  <div class="panel"><div class="panel-h">Sürelerin Yönetim Özeti</div><div class="panel-b">
  <div class="form-grid"><div class="field"><label>Başlangıç</label><input type="date" id="timeFrom" value="${esc(f.start)}"></div><div class="field"><label>Bitiş</label><input type="date" id="timeTo" value="${esc(f.end)}"></div><div class="field"><label>Birim</label><select id="timeUnit"><option>Tümü</option>${availableUnits().map(u=>`<option ${f.unit===u?'selected':''}>${esc(u)}</option>`).join('')}</select></div><div class="field"><label>Teknisyen</label><input id="timePerson" value="${esc(f.person)}" placeholder="İsim ara"></div><div class="field span4"><label>Müşteri / Bölge / İş Emri</label><input id="timeSearch" value="${esc(f.search)}" placeholder="Müşteri veya lokasyon ara"></div></div>
  <div class="live-kpis">${[['Toplam kişi-saat',liveClock(mins)],['Sahada',liveClock(sumActivity('Saha Çalışması'))],['Yol',liveClock(sumActivity('Yol / Ulaşım'))],['Bekleme',liveClock(sumActivity('Bekleme'))],['Mola (hariç)',liveClock(breakMinutes)],['Farklı iş',unique],['Aktif sayaç',active.length]].map(([k,v])=>`<div class="live-kpi"><small>${esc(k)}</small><b>${esc(v)}</b></div>`).join('')}</div>
  <div class="subtle report-hint">Veriler tamamlanmış gerçek faaliyet kayıtlarıdır. Mola, kayıtlı çalışma süresine dahil edilmez. Başlatılıp henüz bitmemiş faaliyetler toplamı artırmaz.</div>
  ${d.isManager?'<div class="actions"><button class="btn soft" id="timeExport">CSV / Excel Dışa Aktar</button><button class="btn soft" id="timeToReports">Tam Raporlara Git ↗</button></div>':''}</div></div></div>
  ${d.isManager?`<div class="panel"><div class="panel-h">Şu Anda Çalışan Ekipler <span class="badge b-blue">${active.length}</span></div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Teknisyen</th><th>Birim / Firma</th><th>İş Emri</th><th>Faaliyet</th><th>Başlangıç</th><th>Süre</th><th>İşlem</th></tr></thead><tbody>${active.map(t=>{const w=lookup(t.workOrderId);return `<tr><td>${esc(t.technicianName)}</td><td>${esc(w.unitCode||'')}<div class="subtle">${esc(w.customerName||'')}</div></td><td><button class="metric-wo-link" data-timeopen="${Number(t.workOrderId)}">${esc(w.workOrderNo||'')}</button></td><td>${esc(t.activityType)}</td><td>${esc(fmtDate(t.startedAt))}</td><td data-live-elapsed="${esc(t.startedAt)}">${esc(liveClock(liveMinutesSince(t.startedAt)))}</td><td>${can('workorders.assign')||can('users.manage')?`<button class="btn soft" data-livecancel="${Number(t.sessionId)}">İptal Et</button>`:''}</td></tr>`;}).join('')||'<tr><td colspan="7">Şu anda aktif sayaç yok.</td></tr>'}</tbody></table></div></div></div>`:''}
  <div class="panel"><div class="panel-h">Personel / Kişi-Saat Dağılımı</div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Teknisyen</th><th>İş</th><th>Faaliyet</th><th>Toplam</th><th>Saha</th><th>Yol</th><th>Bekleme</th><th>Mola (hariç)</th></tr></thead><tbody>${pivots.map(([p,r])=>`<tr><td><b>${esc(p)}</b></td><td>${new Set(r.logs.map(x=>x.workOrderId)).size}</td><td>${r.logs.length}</td><td><b>${esc(liveClock(r.mins))}</b></td>${['Saha Çalışması','Yol / Ulaşım','Bekleme'].map(a=>`<td>${esc(liveClock(r.logs.filter(x=>x.activityType===a).reduce((n,x)=>n+Number(x.minutes||0),0)))}</td>`).join('')}<td>${esc(liveClock(breaks.filter(t=>t.technicianName===p).reduce((n,t)=>n+Math.max(0,Math.floor((new Date(t.endedAt)-new Date(t.startedAt))/60000)),0)))}</td></tr>`).join('')||'<tr><td colspan="8">Seçilen aralıkta gerçekleşen süre kaydı yok.</td></tr>'}</tbody></table></div></div></div>
  <div class="panel"><div class="panel-h">Kim, Nerede, Ne Kadar Çalıştı? <span class="badge b-blue">${all.length}</span></div><div class="panel-b"><div class="table-scroll"><table><thead><tr><th>Teknisyen</th><th>İş Emri</th><th>Müşteri / Konum</th><th>Faaliyet</th><th>Başlangıç</th><th>Bitiş</th><th>Süre</th><th>Not</th></tr></thead><tbody>${all.slice(0,300).map(t=>{const w=lookup(t.workOrderId);return `<tr><td>${esc(t.technicianName)}</td><td><button class="metric-wo-link" data-timeopen="${Number(t.workOrderId)}">${esc(w.workOrderNo||'')}</button></td><td>${esc(w.customerName||'')}<div class="subtle">${esc(t.locationNote||w.location||'')}</div></td><td>${esc(t.activityType)}</td><td>${esc(fmtDate(t.startedAt))}</td><td>${esc(fmtDate(t.endedAt))}</td><td>${esc(liveClock(t.minutes))}</td><td>${esc(t.workNote||'-')}</td></tr>`;}).join('')||'<tr><td colspan="8">Bu filtrelere uygun kayıt yok.</td></tr>'}</tbody></table></div>${all.length>300?'<div class="subtle">İlk 300 satır gösteriliyor. Dışa aktarma tüm satırları içerir.</div>':''}</div></div>`;
}
let liveTickerHandle=null;
function startVisibleTimeTick(){
  if(liveTickerHandle)clearInterval(liveTickerHandle);
  const update=()=>$$('[data-live-elapsed]').forEach(el=>{el.textContent=liveClock(liveMinutesSince(el.dataset.liveElapsed));});
  update();liveTickerHandle=setInterval(update,15000);
}
function bindLiveTimerButtons(){
  startVisibleTimeTick();
  $$('[data-liveaction]').forEach(b=>b.onclick=async()=>{
    const id=Number(b.dataset.livework),source=b.dataset.livesource;
    const activity=$(`#${source==='wo'?'woLiveActivity':'timeActivity'}`)?.value||'Yol / Ulaşım';
    const location=$(`#${source==='wo'?'woLiveLocation':'timeLocation'}`)?.value||'';
    const note=$(`#${source==='wo'?'woLiveNote':'timeNote'}`)?.value||'';
    if(!id){alert('Önce iş emri seçmelisiniz.');return;}
    if(b.dataset.liveaction==='finish'&&!confirm('Aktif faaliyetin süresini bitirmek istiyor musunuz?'))return;
    b.disabled=true;
    try{const answer=await submitLiveAction(id,b.dataset.liveaction,activity,location,note);
      if(source==='wo') await openWorkOrder(id); else render();
      if(answer?.message)alert(answer.message);
    }catch(e){b.disabled=false;alert(e.message);}
  });
}
function bindTimeTracking(){
  $('#liveRefresh')?.addEventListener('click',async()=>{try{await reloadLiveTracking();render();}catch(err){alert(err.message);}});
  $('#liveOpenWork')?.addEventListener('click',e=>openWorkOrder(e.currentTarget.dataset.openId));
  $$('[data-timeopen]').forEach(el=>el.onclick=()=>openWorkOrder(el.dataset.timeopen));
  $('#timeWorkOrder')?.addEventListener('change',e=>{state.timeWorkOrder=Number(e.target.value);render();});
  const filters={timeFrom:'start',timeTo:'end',timeUnit:'unit',timePerson:'person',timeSearch:'search'};
  for(const [id,key] of Object.entries(filters)){
    const el=$(`#${id}`);
    if(el)el.addEventListener('change',e=>{state.timeFilters[key]=e.target.value;render();});
  }
  $('#timeToReports')?.addEventListener('click',()=>{state.view='reports';render();});
  $('#timeExport')?.addEventListener('click',()=>{
    if(!can('reports.export'))return alert('Rapor dışa aktarma yetkiniz yok.');
    const f=state.timeFilters,lines=[['Teknisyen','İş Emri','Birim','Müşteri','Lokasyon','Faaliyet','Başlangıç','Bitiş','Dakika','Not']];
    (state.liveTracking?.logs||[]).forEach(t=>{
      const w=state.workOrders.find(x=>Number(x.workOrderId)===Number(t.workOrderId));if(!w)return;
      const d=String(t.startedAt||'').slice(0,10);
      const str=`${t.technicianName} ${w.customerName} ${w.location} ${t.locationNote||''} ${w.workOrderNo}`.toLocaleLowerCase('tr-TR');
      if((f.start&&d<f.start)||(f.end&&d>f.end)||(f.unit!=='Tümü'&&w.unitCode!==f.unit)||(f.person&&!t.technicianName.toLocaleLowerCase('tr-TR').includes(f.person.toLocaleLowerCase('tr-TR')))||(f.search&&!str.includes(f.search.toLocaleLowerCase('tr-TR'))))return;
      lines.push([t.technicianName,w.workOrderNo,w.unitCode,w.customerName,t.locationNote||w.location,t.activityType,t.startedAt,t.endedAt,t.minutes,t.workNote||'']);
    });
    const csv=lines.map(row=>row.map(v=>{let s=String(v??'');if(/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';}).join(';')).join('\r\n');
    const blob=new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob);
    const link=document.createElement('a');link.href=url;link.download='DengeERP_V114_Personel_Sureleri.csv';document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
  });
  $$('[data-livecancel]').forEach(el=>el.onclick=async()=>{
    const reason=prompt('Bu açık zaman sayacını neden iptal ediyorsunuz? Denetim kaydında saklanacaktır.');if(!reason?.trim())return;
    try{await api(`/api/timetracking/sessions/${Number(el.dataset.livecancel)}/cancel`,{method:'POST',body:JSON.stringify({reason:reason.trim()})});await reloadLiveTracking();render();}catch(e){alert(e.message);}
  });
  bindLiveTimerButtons();
}

function currentPage(){
  if(['operations120','mobile120','stock120','finance120'].includes(state.view))return ops120Page(state.view);
  if(state.view==='dashboard') return dashboard();
  if(state.view==='create') return createPage();
  if(state.view==='workorders') return workOrdersPage();
  if(state.view==='planning') return planningPage();
  if(state.view==='securitydevices') return securityDevicesPage();
  if(state.view==='maintenance') return maintenancePage();
  if(state.view==='workshop') return workshopPage();
  if(state.view==='rentals') return rentalsPage();
  if(state.view==='pocmobility') return pocMobilityPage();
  if(state.view==='offers') return offersPage();
  if(state.view==='reports') return reportsPage();
  if(state.view==='timetracking') return timeTrackingPage();
  if(state.view==='training') return trainingPage();
  if(state.view==='personnel') return personnelPage();
  if(state.view==='users') return usersPage();
  if(state.view==='warehouse') return warehousePage();
  if(state.view==='accounting') return accountingPage();
  return dashboard();
}

function modal(html){ $('#modalHost').innerHTML=`<div class="modal-backdrop"><div class="modal">${html}</div></div>`; }
function closeModal(){ const h=$('#modalHost'); if(h) h.innerHTML=''; }
function selectedPersonnel(unit){
  const actual=state.users.filter(u=>u.isActive && (u.allowedUnits||[]).includes(unit));
  const org=state.personnel.filter(p=>p.isActive && p.unitCode===unit);
  const chiefs=[
    ...actual.filter(u=>u.roleName==='Şef').map(u=>u.fullName),
    ...org.filter(p=>/takım lideri|yönetici|müdür/i.test(p.title||'')).map(p=>p.fullName)
  ];
  const techs=[
    ...actual.filter(u=>u.roleName==='Teknisyen').map(u=>u.fullName),
    ...org.filter(p=>/teknisyen|mühendis|operasyon uzmanı|destek uzmanı/i.test(p.title||'')).map(p=>p.fullName)
  ];
  const fb=personnelFallback[unit]||{chiefs:[],technicians:[]};
  return {chiefs:[...new Set([...chiefs,...fb.chiefs])],technicians:[...new Set([...techs,...fb.technicians])]};
}

async function openWorkOrder(id){
  const w=state.workOrders.find(x=>String(x.workOrderId)===String(id)); if(!w) return;
  let hist=[]; try{ hist=await api(`/api/workorders/${id}/history`); }catch{}
  let workLogs=[]; try{workLogs=await api(`/api/workorders/${id}/time-logs`);}catch{}
  try{if(can('workorders.view'))state.liveTracking=await api('/api/timetracking/summary');}catch{}
  const people=selectedPersonnel(w.unitCode);
  const statusList=w.unitCode==='POC'?pocStatuses:statuses;
  const serialRule=ruleFor(w.unitCode,w.workType);
  const assignedTechs=[...new Set(String(w.assignedStaff||'').split(',').map(x=>x.trim()).filter(Boolean))];
  const mayLog=can('workorders.edit')||can('workorders.close');
  const canSerialUpdate=w.workType!=='Planlı Bakım' && (can('workorders.create')||can('workorders.edit')||can('workorders.close'));
  modal(`<div class="modal-h"><div><b>${esc(w.workOrderNo)} • ${esc(w.customerName)}</b><div class="subtle">${esc(w.unitCode)} • ${esc(w.workType)} • ${esc(w.location||'-')}</div></div><button class="iconbtn" id="modalX">×</button></div>
  <div class="modal-b">
    <div class="review-summary"><div><span>Durum</span>${statusBadge(w.status)}</div><div><span>Şef</span><b>${esc(w.chiefName||'-')}</b></div><div><span>Teknisyen</span><b>${esc(w.assignedStaff||'Atanmadı')}</b></div><div><span>Araç</span><b>${esc(w.vehiclePlate||'-')}</b></div></div>
    ${w.workType==='Planlı Bakım'?`<div class="form-card"><div class="form-h">Cihaz Bazlı Bakım</div><div class="notice">Bu cihazın teknik bakım kontrol listesini, seri numarasını ve lokasyonunu kendi iş emrinde doldurun.</div><div class="actions"><button class="btn primary" id="openMaintFromWork">Cihaz Bakım Formu Aç</button></div></div>`:''}
    <div class="form-card" style="margin-top:12px"><div class="form-h">İş / Cihaz Bilgileri</div><div class="form-grid"><div class="field"><label>Sistem</label><input readonly value="${esc(w.systemName||'-')}"></div><div class="field span2"><label>Seri No / Seri Nolar</label><input id="woSerials" value="${esc(w.serialNumbers||'')}" ${canSerialUpdate?'':'readonly'} placeholder="Virgülle ayırın"></div><div class="field"><label>Seri No Kuralı</label><input readonly value="${serialRule.serialRequiredOnCreate?'Açılışta zorunlu':serialRule.serialRequiredOnClose?'Kapanışta zorunlu':'Opsiyonel'}"></div><div class="field span4"><label>Konu</label><input readonly value="${esc(w.subject)}"></div><div class="field span4"><label>Açıklama</label><textarea readonly>${esc(w.description||'')}</textarea></div></div>${canSerialUpdate?'<div class="actions"><button class="btn soft" id="saveSerials">Seri No Kaydet</button></div>':''}</div>
    <div class="form-card"><div class="form-h">Planlama</div><div class="form-grid"><div class="field"><label>Plan Tarihi</label><input readonly value="${esc(fmtPlanDate(w.planDate))}"></div><div class="field"><label>Saat</label><input readonly value="${esc((w.startTime||'').slice(0,5)||'-')}"></div><div class="field"><label>Tahmini Süre</label><input readonly value="${w.estimatedMinutes?esc(w.estimatedMinutes+' dk'):'-'}"></div><div class="field"><label>Araç</label><input readonly value="${esc(w.vehiclePlate||'-')}"></div><div class="field span4"><label>Plan Notu</label><textarea readonly>${esc(w.planNote||'-')}</textarea></div></div>
      <div class="form-grid" style="margin-top:10px"><div class="field"><label>Şehir / İlçe</label><input readonly value="${esc([w.siteCity,w.siteDistrict].filter(Boolean).join(' / ')||'-')}"></div><div class="field"><label>Lokasyon / Tesis</label><input readonly value="${esc(w.siteName||w.location||'-')}"></div><div class="field span2"><label>Bina / Kat / Bölge</label><input readonly value="${esc(w.siteArea||'-')}"></div><div class="field span4"><label>Açık Adres</label><textarea readonly>${esc(w.siteAddress||'-')}</textarea></div><div class="field"><label>Saha Yetkilisi</label><input readonly value="${esc(w.siteContact||'-')}"></div><div class="field"><label>İrtibat</label><input readonly value="${esc(w.sitePhone||'-')}"></div><div class="field span4"><label>Ulaşım / Giriş Notu</label><textarea readonly>${esc(w.siteDirections||'-')}</textarea></div></div>${can('workorders.plan')?`<div class="actions"><button class="btn primary" id="detailPlan">Planı Aç / Düzenle</button></div>`:''}</div>
    ${can('workorders.assign')||can('workorders.edit')?`<div class="form-card"><div class="form-h">Atama / Durum</div><div class="form-grid">${can('workorders.assign')?`<div class="field"><label>Şef</label><select id="editChief"><option value="">-</option>${people.chiefs.map(x=>`<option ${x===w.chiefName?'selected':''}>${esc(x)}</option>`).join('')}</select></div><div class="field span2"><label>Teknisyenler</label><div class="multi-box">${people.technicians.map(x=>`<label class="multi-option"><input type="checkbox" name="editTech" value="${esc(x)}" ${(w.assignedStaff||'').split(',').map(z=>z.trim()).includes(x)?'checked':''}> ${esc(x)}</label>`).join('')}</div></div>`:''}<div class="field"><label>Durum</label><select id="editStatus">${statusList.filter(x=>w.workType!=='Planlı Bakım'||!['Tamamlandı','Kapatıldı'].includes(x)||x===w.status).map(x=>`<option ${x===w.status?'selected':''}>${esc(x)}</option>`).join('')}</select></div><div class="field span4"><label>İşlem Notu</label><textarea id="editNote" placeholder="Durum değişikliği / işlem açıklaması"></textarea></div></div><div class="actions"><button class="btn primary" id="saveWorkChanges">Değişiklikleri Kaydet</button></div></div>`:''}
    ${can('offers.create')?`<div class="actions"><button class="btn soft" id="offerFromWork">Bu İş İçin Teklif Oluştur</button></div>`:''}
    ${liveWorkOrderControls(w)}
    <div class="form-card" style="margin-top:12px"><div class="form-h">Gerçek Çalışma Süresi • Personel Bazında</div>
    <div class="notice">Tahmini süre bu hesaba dahil edilmez. Her teknisyen için yol, sahada çalışma ve bekleme gibi faaliyetleri ayrı kaydedin. Birden fazla teknisyen varsa herkesin süresi ayrı tutulur.</div>
    ${mayLog?`<form id="actualTimeForm"><div class="form-grid">
      <div class="field"><label>Teknisyen</label><select name="technicianName" ${state.user.roleName==='Teknisyen'?'disabled':''}>${(state.user.roleName==='Teknisyen'?[state.user.fullName]:assignedTechs).map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('')}</select></div>
      <div class="field"><label>Faaliyet</label><select name="activityType"><option>Saha Çalışması</option><option>Yol / Ulaşım</option><option>Bekleme</option><option>Uzaktan Destek</option><option>Atölye</option><option>Test / Kontrol</option><option>Diğer</option></select></div>
      <div class="field"><label>Başlangıç</label><input name="startedAt" type="datetime-local" required></div>
      <div class="field"><label>Bitiş</label><input name="endedAt" type="datetime-local" required></div>
      <div class="field span2"><label>Cihazın Bulunduğu Bölge / Saha</label><input name="locationNote" maxlength="250" placeholder="Örnek: A Blok / Zemin Kat / Giriş 2"></div>
      <div class="field span2"><label>Çalışma Notu</label><input name="workNote" maxlength="1000" placeholder="Yapılan işlem veya bekleme nedeni"></div></div>
      <div class="actions"><button class="btn primary" type="submit">Gerçek Süre Kaydet</button></div></form>`:'<div class="subtle">Bu kullanıcı çalışma süresi ekleme yetkisine sahip değil.</div>'}
    <div class="table-scroll"><table><thead><tr><th>Personel</th><th>Faaliyet</th><th>Başlangıç</th><th>Bitiş</th><th>Toplam</th><th>Bölge / Not</th><th>İşlem</th></tr></thead><tbody>${workLogs.map(t=>`<tr><td><b>${esc(t.technicianName)}</b></td><td>${esc(t.activityType)}</td><td>${esc(fmtDate(t.startedAt))}</td><td>${esc(fmtDate(t.endedAt))}</td><td>${(t.minutes/60).toLocaleString('tr-TR',{maximumFractionDigits:2})} saat</td><td>${esc(t.locationNote||'-')}<div class="subtle">${esc(t.workNote||'')}</div></td><td>${can('workorders.assign')?`<button class="btn soft" data-timevoid="${t.timeLogId}">İptal</button>`:''}</td></tr>`).join('')||'<tr><td colspan="7">Bu iş için henüz gerçek süre kaydı girilmedi.</td></tr>'}</tbody></table></div>
    <div class="subtle report-hint">Toplam ${workLogs.reduce((n,x)=>n+x.minutes,0)/60} kişi-saat kayıtlıdır. Çakışan personel faaliyetleri kaydedilemez.</div></div>
    <div class="panel"><div class="panel-h">Durum Geçmişi</div><div class="panel-b">${hist.length?`<table><thead><tr><th>Tarih</th><th>Eski</th><th>Yeni</th><th>Kullanıcı</th><th>Not</th></tr></thead><tbody>${hist.map(h=>`<tr><td>${fmtDate(h.changedAt)}</td><td>${esc(h.oldStatus||'-')}</td><td>${esc(h.newStatus)}</td><td>${esc(h.changedByName||'-')}</td><td>${esc(h.note||'')}</td></tr>`).join('')}</tbody></table>`:'<div class="subtle">Henüz durum geçmişi yok.</div>'}</div></div>
  </div><div class="modal-f"><button class="btn" id="closeModalBtn">Kapat</button></div>`);
  $('#modalX').onclick=$('#closeModalBtn').onclick=closeModal;
  bindLiveTimerButtons();
  $('#actualTimeForm')?.addEventListener('submit',async e=>{
    e.preventDefault();const f=e.currentTarget;if(!f.reportValidity())return;
    const data=new FormData(f);
    const startedAt=String(data.get('startedAt')||'');const endedAt=String(data.get('endedAt')||'');
    const technicianName=state.user.roleName==='Teknisyen'?state.user.fullName:String(data.get('technicianName')||'');
    if(!technicianName){alert('Önce teknisyen atayın.');return;}
    if(new Date(endedAt)<=new Date(startedAt)){alert('Bitiş saati başlangıçtan sonra olmalı.');return;}
    const btn=f.querySelector('button[type="submit"]');btn.disabled=true;
    try{await api(`/api/workorders/${id}/time-logs`,{method:'POST',body:JSON.stringify({technicianName,activityType:data.get('activityType'),startedAt,endedAt,locationNote:data.get('locationNote'),workNote:data.get('workNote')})});
      if(can('reports.view'))state.workLogs=await api('/api/reports/worklogs');
      await openWorkOrder(id);
    }catch(err){alert(err.message);btn.disabled=false;}
  });
  $$('[data-timevoid]').forEach(btn=>btn.onclick=async()=>{
    if(!confirm('Bu çalışma süresi kaydı hatalı mı? Kayıt silinmez, iptal olarak işaretlenir.'))return;
    try{await api(`/api/workorders/${id}/time-logs/${btn.dataset.timevoid}`,{method:'DELETE'});
      if(can('reports.view'))state.workLogs=await api('/api/reports/worklogs');
      await openWorkOrder(id);
    }catch(err){alert(err.message);}
  });
  $('#openMaintFromWork')?.addEventListener('click',()=>openMaintenanceForm(id));
  if($('#saveSerials')) $('#saveSerials').onclick=async()=>{ try{await api(`/api/workorders/${id}/serials`,{method:'PUT',body:JSON.stringify({serialNumbers:$('#woSerials').value.split(/[,;\n]+/).map(x=>x.trim()).filter(Boolean)})}); await reloadWork(); alert('Seri numarası SQL’e kaydedildi.'); await openWorkOrder(id);}catch(e){alert(e.message);} };
  if($('#detailPlan')) $('#detailPlan').onclick=()=>openPlan(id);
  if($('#saveWorkChanges')) $('#saveWorkChanges').onclick=async()=>{
    try{
      if(can('workorders.assign') && $('#editChief')) await api(`/api/workorders/${id}/assignments`,{method:'PUT',body:JSON.stringify({chief:$('#editChief').value||null,technicians:$$('input[name="editTech"]:checked').map(x=>x.value)})});
      await api(`/api/workorders/${id}/status`,{method:'PATCH',body:JSON.stringify({status:$('#editStatus').value,note:$('#editNote').value.trim()||null})});
      await reloadWork(); alert('İş emri güncellendi.'); await openWorkOrder(id);
    }catch(e){alert(e.message);}
  };
  if($('#offerFromWork')) $('#offerFromWork').onclick=()=>openOfferModal(w);
}

// İş Emirleri tablosunda seçilenleri farklı müşterilere ait olsalar da, aynı birimdeyken toplu atayabiliriz.
function updateAssignmentSelectionUI(){
  const assignableIds=new Set(state.workOrders.filter(w=>unitAllowed(w.unitCode)&&!['Tamamlandı','Kapatıldı','İptal'].includes(w.status)).map(w=>Number(w.workOrderId)));
  state.assignmentSelectedIds=state.assignmentSelectedIds.filter(id=>assignableIds.has(id));
  $$('[data-assignment-pick]').forEach(cb=>{cb.checked=state.assignmentSelectedIds.includes(Number(cb.dataset.assignmentPick));});
  const visible=$$('[data-assignment-pick]:not(:disabled)');
  const selectAll=$('#assignSelectAll');
  if(selectAll){
    selectAll.checked=visible.length>0 && visible.every(cb=>cb.checked);
    selectAll.indeterminate=visible.some(cb=>cb.checked)&&!selectAll.checked;
  }
  const cnt=$('#assignmentSelectedCount');if(cnt)cnt.textContent=state.assignmentSelectedIds.length;
  const action=$('#bulkAssignButton');if(action)action.disabled=state.assignmentSelectedIds.length===0;
}
function setAssignmentSelection(ids,checked){
  const byId=new Map(state.workOrders.map(w=>[Number(w.workOrderId),w]));
  const desired=ids.map(id=>Number(id)).filter(id=>byId.has(id));
  if(checked){
    const selectedUnit=byId.get(desired[0])?.unitCode;
    if(!selectedUnit)return;
    const existingUnit=byId.get(state.assignmentSelectedIds[0])?.unitCode;
    if(existingUnit && existingUnit!==selectedUnit){
      // Yeni birim seçimi eski birim seçimini sıfırlar; farklı ekipleri karıştırmayız.
      state.assignmentSelectedIds=[];
    }
    state.assignmentSelectedIds=[...new Set([...state.assignmentSelectedIds,...desired.filter(id=>byId.get(id)?.unitCode===selectedUnit)])];
  }else{
    state.assignmentSelectedIds=state.assignmentSelectedIds.filter(id=>!desired.includes(id));
  }
  updateAssignmentSelectionUI();
}
function bindAssignmentRows(){
  $$('[data-assignment-pick]').forEach(cb=>cb.onchange=()=>setAssignmentSelection([cb.dataset.assignmentPick],cb.checked));
  const selectAll=$('#assignSelectAll');
  if(selectAll)selectAll.onchange=()=>{
    const visible=$$('[data-assignment-pick]:not(:disabled)').map(x=>Number(x.dataset.assignmentPick));
    const units=new Set(state.workOrders.filter(w=>visible.includes(Number(w.workOrderId))).map(w=>w.unitCode));
    if(units.size>1){alert('Önce üstte bir birim seçin; farklı birimler aynı ekibe toplu atanamaz.');selectAll.checked=false;return;}
    setAssignmentSelection(visible,selectAll.checked);
  };
  updateAssignmentSelectionUI();
}
function openBulkAssign(ids){
  const selected=new Set(ids.map(Number));
  const jobs=state.workOrders.filter(w=>selected.has(Number(w.workOrderId)));
  if(jobs.length!==selected.size||!jobs.length){alert('İş emri seçimi güncel değil, listeyi yenileyin.');return;}
  const unit=jobs[0].unitCode;
  if(jobs.some(w=>w.unitCode!==unit||['Tamamlandı','Kapatıldı','İptal'].includes(w.status))){
    alert('Seçilenlerin tamamı aynı birimde ve açık durumda olmalıdır.');return;
  }
  const people=selectedPersonnel(unit);
  modal(`<div class="modal-h"><div><b>Toplu Şef / Teknisyen Ataması • ${jobs.length} İş</b><div class="subtle">${esc(unit)} • Her iş emri ve bakım formu ayrı kalır</div></div><button class="iconbtn" id="modalX">×</button></div>
    <div class="modal-b"><div class="notice">Seçtiğiniz ekip <b>${jobs.length} iş emrine tek işlemle</b> atanır. Önceki aktif ekip atamaları bu iş emirleri için güncellenir; mevcut plan tarihleri ve cihaz kayıtları değişmez.</div>
    <div class="bulk-modal-orders">${jobs.map(w=>`<div><b>${esc(w.workOrderNo)}</b> • ${esc(w.customerName)} • ${esc(w.location||'-')} • ${esc(w.subject||w.workType)}</div>`).join('')}</div>
    <div class="form-card"><div class="form-grid"><div class="field"><label>Şef</label><select id="bulkAssignChief"><option value="">Şef seçiniz (isteğe bağlı)</option>${people.chiefs.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('')}</select></div>
    <div class="field span2"><label>Teknisyen / Ekip (çoklu seçim)</label><div class="multi-box">${people.technicians.map(x=>`<label class="multi-option"><input type="checkbox" name="bulkAssignTech" value="${esc(x)}"> ${esc(x)}</label>`).join('')}</div></div></div></div></div>
    <div class="modal-f"><button class="btn" id="bulkAssignCancel">Vazgeç</button><button class="btn primary" id="bulkAssignSave">${jobs.length} İşe Ekibi Ata</button></div>`);
  $('#modalX').onclick=$('#bulkAssignCancel').onclick=closeModal;
  $('#bulkAssignSave').onclick=async()=>{
    const chief=$('#bulkAssignChief').value||null;
    const tech=$$('input[name="bulkAssignTech"]:checked').map(x=>x.value);
    if(!chief&&!tech.length){alert('En az bir şef veya teknisyen seçin.');return;}
    const save=$('#bulkAssignSave');save.disabled=true;save.textContent='SQL’e kaydediliyor...';
    try{
      const r=await api('/api/workorders/bulk-assign',{method:'PUT',body:JSON.stringify({workOrderIds:jobs.map(w=>Number(w.workOrderId)),chief,technicians:tech})});
      state.assignmentSelectedIds=[];state.bulkSelectedIds=[];
      await reloadWork();closeModal();render();
      alert(`${r.assignedCount} iş emrine ekip atandı. Her iş emri bağımsız kaldı.`);
    }catch(e){alert(e.message);save.disabled=false;save.textContent='Tekrar Dene';}
  };
}

function syncBulkPlanningSelection(){
  const waiting=planningFilteredRows().filter(w=>!w.planDate && !['Tamamlandı','Kapatıldı','İptal'].includes(w.status));
  const validIds=new Set(waiting.map(w=>Number(w.workOrderId)));
  state.bulkSelectedIds=state.bulkSelectedIds.filter(id=>validIds.has(id));
  const chosen=state.bulkSelectedIds;
  const q=state.planningCustomerSearch.trim().toLocaleLowerCase('tr-TR');
  const visible=q?waiting.filter(w=>[w.customerName,w.location,w.workOrderNo,w.subject,w.serialNumbers].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(q))):waiting;
  $$('[data-bulk-select]').forEach(cb=>{cb.checked=chosen.includes(Number(cb.dataset.bulkSelect));});
  $$('[data-bulk-group]').forEach(cb=>{
    const first=waiting.find(w=>Number(w.workOrderId)===Number(cb.dataset.bulkGroup));
    const key=first?bulkLocationKey(first):null;
    const ids=visible.filter(w=>bulkLocationKey(w)===key).map(w=>Number(w.workOrderId));
    cb.checked=!!ids.length && ids.every(id=>chosen.includes(id));
    cb.indeterminate=ids.some(id=>chosen.includes(id)) && !cb.checked;
  });
  const count=$('#bulkSelectedCount');if(count)count.textContent=chosen.length;
  const btn=$('#bulkPlanButton');if(btn)btn.disabled=chosen.length===0;
  const assign=$('#bulkWaitingAssignButton');if(assign)assign.disabled=chosen.length===0;
}
function changeBulkSelection(id,checked,wholeGroup=false){
  const waiting=planningFilteredRows().filter(w=>!w.planDate && !['Tamamlandı','Kapatıldı','İptal'].includes(w.status));
  const work=waiting.find(w=>Number(w.workOrderId)===Number(id));
  const key=work?bulkLocationKey(work):null;
  if(!key)return;
  const q=state.planningCustomerSearch.trim().toLocaleLowerCase('tr-TR');
  const visible=q?waiting.filter(w=>[w.customerName,w.location,w.workOrderNo,w.subject,w.serialNumbers].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(q))):waiting;
  const ids=wholeGroup?visible.filter(w=>bulkLocationKey(w)===key).map(w=>Number(w.workOrderId)):[Number(id)];
  const ownGroup=waiting.filter(w=>bulkLocationKey(w)===key).map(w=>Number(w.workOrderId));
  if(checked){
    // Tek işlemde yalnızca aynı müşteri/lokasyon/birim işleri seçilebilir.
    state.bulkSelectedIds=state.bulkSelectedIds.filter(x=>ownGroup.includes(x));
    state.bulkSelectedIds=[...new Set([...state.bulkSelectedIds,...ids])];
  }else{
    state.bulkSelectedIds=state.bulkSelectedIds.filter(x=>!ids.includes(x));
  }
  syncBulkPlanningSelection();
}
// Planlama saha bilgisi: kütükten bilinenler otomatik önerilir, planı kaydederken değiştirilebilir.
const siteFormFields=[
  ['siteName','Müşteri Lokasyonu / Tesis',250,'Örn. AKYAKA AVM - Ana Giriş'],
  ['siteCity','Şehir / İl',100,'Örn. İstanbul'],
  ['siteDistrict','İlçe',120,'Örn. Üsküdar'],
  ['siteAddress','Açık Adres',600,'Mahalle, cadde, sokak, bina no'],
  ['siteArea','Bina / Kat / Cihaz Bölgesi',250,'Örn. B giriş / X-Ray 2'],
  ['siteContact','Saha Yetkilisi',180,'Ad Soyad'],
  ['sitePhone','İrtibat Telefonu',80,'Telefon'],
  ['siteDirections','Ulaşım / Giriş / Otopark Notu',1000,'Güvenlik giriş kapısı, araç giriş bilgisi vb.']
];
function planSiteFormHTML(work,prefix){
  return `<div class="form-card site-fields"><div class="form-h">Saha / Lokasyon Bilgileri <span class="subtle">Kütükten öneri • Düzenlenebilir</span></div>
  <div class="form-grid">${siteFormFields.map(([key,label,max,place])=>`<div class="field ${['siteAddress','siteDirections'].includes(key)?'span4':''}"><label>${esc(label)}</label>${['siteAddress','siteDirections'].includes(key)?`<textarea id="${prefix}_${key}" maxlength="${max}" placeholder="${esc(place)}">${esc(work?.[key]||(key==='siteName'?work?.location:'')||'')}</textarea>`:`<input id="${prefix}_${key}" maxlength="${max}" placeholder="${esc(place)}" value="${esc(work?.[key]||(key==='siteName'?work?.location:'')||'')}">`}</div>`).join('')}</div>
  <div class="subtle site-hint" id="${prefix}_source">Kayıtlı bilgiler varsa önerilir; her alan değiştirilebilir. Şehir boşsa tahmin yapılmaz.</div></div>`;
}
function readPlanSite(prefix){return Object.fromEntries(siteFormFields.map(([key])=>[key,document.getElementById(`${prefix}_${key}`)?.value.trim()||null]));}
async function fillPlanSiteFromInventory(work,prefix){
  if(!work) return;
  // Önceden kaydedilmiş plan bilgilerini asla öneriyle değiştirme.
  try{
    const suggestion=await api(`/api/workorders/${Number(work.workOrderId)}/site-suggestion`);
    let updated=0;
    siteFormFields.forEach(([key])=>{
      const el=document.getElementById(`${prefix}_${key}`);
      if(el&&!String(el.value||'').trim()&&String(suggestion[key]||'').trim()){el.value=suggestion[key];updated++;}
    });
    const badge=document.getElementById(`${prefix}_source`);
    if(badge)badge.textContent=updated?`Kütük/sözleşmeden ${updated} alan önerildi; istersen düzenle.`:'Kütükte ek saha bilgisi bulunamadı; alanları elle doldurabilirsin.';
  }catch(e){const badge=document.getElementById(`${prefix}_source`);if(badge)badge.textContent='Kütük önerisine ulaşılamadı; saha bilgilerini elle doldurabilirsin.';}
}

function openBulkPlan(){
  const waiting=planningFilteredRows().filter(w=>!w.planDate && !['Tamamlandı','Kapatıldı','İptal'].includes(w.status));
  const jobs=waiting.filter(w=>state.bulkSelectedIds.includes(Number(w.workOrderId)));
  if(!jobs.length){alert('Planlamak için en az bir iş emri seçin.');return;}
  const key=bulkLocationKey(jobs[0]);
  if(!key || jobs.some(w=>bulkLocationKey(w)!==key)){
    alert('Yalnızca aynı müşteri, lokasyon ve birimin iş emirleri toplu planlanabilir.');return;
  }
  const people=selectedPersonnel(jobs[0].unitCode);
  modal(`<div class="modal-h"><div><b>Toplu Planlama • ${jobs.length} Ayrı İş Emri</b><div class="subtle">${esc(jobs[0].customerName)} • ${esc(jobs[0].location)} • ${esc(jobs[0].unitCode)}</div></div><button class="iconbtn" id="modalX">×</button></div>
    <div class="modal-b"><div class="notice">Tek tarih, ekip ve araç seçilecek; <b>her cihazın iş emri ayrı ayrı korunacak.</b> Bu işlem sadece planlar, bakım formlarını kapatmaz.</div>
    <div class="bulk-modal-orders">${jobs.map(w=>`<div><strong>${esc(w.workOrderNo)}</strong> • ${esc(w.workType)} • ${esc(w.serialNumbers||w.subject||'-')}</div>`).join('')}</div>
    <div class="form-card"><div class="form-h">Ortak Saha Ziyareti</div><div class="form-grid">
      <div class="field"><label>Plan Tarihi *</label><input type="date" id="bulkPlanDate" value="${esc(state.planningAnchor||todayIso())}"></div>
      <div class="field"><label>Başlangıç Saati *</label><input type="time" id="bulkPlanTime" value="09:00"></div>
      <div class="field"><label>Saha Ziyareti Süresi</label><select id="bulkPlanDuration">${[60,120,180,240,360,480].map(n=>`<option value="${n}" ${n===240?'selected':''}>${n===480?'Tam gün':n/60+' saat'}</option>`).join('')}</select></div>
      <div class="field"><label>Araç</label><input id="bulkPlanVehicle" maxlength="30" placeholder="Plaka"></div>
      <div class="field"><label>Şef</label><select id="bulkPlanChief"><option value="">Seçiniz</option>${people.chiefs.map(x=>`<option>${esc(x)}</option>`).join('')}</select></div>
      <div class="field span2"><label>Teknisyen / Ekip</label><div class="multi-box">${people.technicians.map(x=>`<label class="multi-option"><input type="checkbox" name="bulkPlanTech" value="${esc(x)}"> ${esc(x)}</label>`).join('')}</div></div>
      <div class="field span4"><label>Plan Notu</label><textarea id="bulkPlanNote" maxlength="1000" placeholder="Bu lokasyondaki cihazlar aynı ziyarette kontrol edilecek"></textarea></div>
    </div></div>${planSiteFormHTML(jobs[0],'bulkSite')}</div>
    <div class="modal-f"><button class="btn" id="bulkPlanCancel">Vazgeç</button><button class="btn primary" id="bulkPlanSave">${jobs.length} İş Emrini Planla</button></div>`);
  $('#modalX').onclick=$('#bulkPlanCancel').onclick=closeModal;
  fillPlanSiteFromInventory(jobs[0],'bulkSite');
  $('#bulkPlanSave').onclick=async()=>{
    const date=$('#bulkPlanDate').value,time=$('#bulkPlanTime').value;
    if(!date||!time){alert('Plan tarihi ve saati zorunludur.');return;}
    if(!$('#bulkPlanChief').value && !$$('input[name="bulkPlanTech"]:checked').length){alert('En az bir şef veya teknisyen seçin.');return;}
    const save=$('#bulkPlanSave');save.disabled=true;save.textContent='SQL’e kaydediliyor...';
    try{
      const result=await api('/api/workorders/bulk-plan',{method:'PUT',body:JSON.stringify({
        workOrderIds:jobs.map(w=>Number(w.workOrderId)),
        chief:$('#bulkPlanChief').value||null,
        technicians:$$('input[name="bulkPlanTech"]:checked').map(x=>x.value),
        planDate:date,startTime:time+':00',estimatedMinutes:Number($('#bulkPlanDuration').value),
        vehiclePlate:$('#bulkPlanVehicle').value.trim()||null,planNote:$('#bulkPlanNote').value.trim()||null,
        ...readPlanSite('bulkSite')
      })});
      state.bulkSelectedIds=[];
      await reloadWork();closeModal();state.planningAnchor=date;render();
      alert(`${result.plannedCount} ayrı iş emri aynı saha ziyareti için planlandı. Cihaz bakım formları bağımsız kaldı.`);
    }catch(e){alert(e.message);save.disabled=false;save.textContent='Tekrar Dene';}
  };
}

function openPlan(id){
  const w=state.workOrders.find(x=>String(x.workOrderId)===String(id)); if(!w) return;
  const people=selectedPersonnel(w.unitCode);
  const selected=(w.assignedStaff||'').split(',').map(x=>x.trim()).filter(Boolean);
  modal(`<div class="modal-h"><div><b>Planlama • ${esc(w.workOrderNo)}</b><div class="subtle">${esc(w.customerName)} • ${esc(w.location||'-')}</div></div><button class="iconbtn" id="modalX">×</button></div><div class="modal-b"><div class="form-card"><div class="form-h">Planlama Bilgileri</div><div class="form-grid"><div class="field"><label>Şef</label><select id="planChief"><option value="">-</option>${people.chiefs.map(x=>`<option ${x===w.chiefName?'selected':''}>${esc(x)}</option>`).join('')}</select></div><div class="field span2"><label>Teknisyen / Ekip</label><div class="multi-box">${people.technicians.map(x=>`<label class="multi-option"><input name="planTech" type="checkbox" value="${esc(x)}" ${selected.includes(x)?'checked':''}> ${esc(x)}</label>`).join('')}</div></div><div></div><div class="field"><label>Plan Tarihi *</label><input type="date" id="planDate" value="${esc(w.planDate||todayIso())}"></div><div class="field"><label>Başlangıç Saati</label><input type="time" id="planTime" value="${esc((w.startTime||'09:00').slice(0,5))}"></div><div class="field"><label>Tahmini Süre</label><select id="planDuration">${[60,120,180,240,480].map(n=>`<option value="${n}" ${Number(w.estimatedMinutes||120)===n?'selected':''}>${n===480?'Tam Gün':n/60+' Saat'}</option>`).join('')}</select></div><div class="field"><label>Araç</label><input id="planVehicle" value="${esc(w.vehiclePlate||'')}"></div><div class="field"><label>Rota Grubu</label><input id="routeGroup" value="${esc(w.routeGroupNo||'')}" placeholder="Örn. RTE-0001"></div><div class="field span2"><label>Plan Notu</label><textarea id="planNote">${esc(w.planNote||'')}</textarea></div></div></div>${planSiteFormHTML(w,'singleSite')}</div><div class="modal-f"><button class="btn" id="cancelPlan">Vazgeç</button><button class="btn primary" id="savePlan">Planı SQL’e Kaydet</button></div>`);
  $('#modalX').onclick=$('#cancelPlan').onclick=closeModal;
  fillPlanSiteFromInventory(w,'singleSite');
  $('#savePlan').onclick=async()=>{
    try{
      await api(`/api/workorders/${id}/assignments`,{method:'PUT',body:JSON.stringify({chief:$('#planChief').value||null,technicians:$$('input[name="planTech"]:checked').map(x=>x.value)})});
      await api(`/api/workorders/${id}/plan`,{method:'PUT',body:JSON.stringify({planDate:$('#planDate').value,startTime:$('#planTime').value?$('#planTime').value+':00':null,estimatedMinutes:Number($('#planDuration').value),vehiclePlate:$('#planVehicle').value.trim()||null,routeGroupNo:$('#routeGroup').value.trim()||null,planNote:$('#planNote').value.trim()||null,...readPlanSite('singleSite')})});
      await reloadWork(); closeModal(); alert('Plan SQL’e başarıyla kaydedildi.'); render();
    }catch(e){alert(e.message);}
  };
}

function addOfferItemRow(values={}){
  const host=$('#offerItems'); if(!host) return;
  const div=document.createElement('div'); div.className='offer-item-row';
  div.innerHTML=`<input class="oi-code" placeholder="Kod" value="${esc(values.itemCode||'')}"><input class="oi-desc" placeholder="Ürün / hizmet açıklaması" value="${esc(values.description||'')}"><input class="oi-qty" type="number" step="0.01" min="0" value="${values.quantity??1}"><input class="oi-price" type="number" step="0.01" min="0" value="${values.unitPrice??0}"><input class="oi-disc" type="number" step="0.01" min="0" value="${values.discountPercent??0}"><input class="oi-vat" type="number" step="0.01" min="0" value="${values.vatPercent??20}"><button type="button" class="btn danger oi-remove">×</button>`;
  host.appendChild(div); div.querySelector('.oi-remove').onclick=()=>div.remove();
}
function openOfferModal(work=null){
  const units=availableUnits();
  modal(`<div class="modal-h"><div><b>Yeni Teklif</b><div class="subtle">Ürün / hizmet bazlı teknik servis teklifi</div></div><button class="iconbtn" id="modalX">×</button></div><div class="modal-b"><form id="offerForm"><div class="form-card"><div class="form-h">Müşteri / Teklif</div><div class="form-grid"><div class="field"><label>İlgili İş Emri</label><select name="workOrderId"><option value="">Bağımsız Teklif</option>${state.workOrders.map(w=>`<option value="${w.workOrderId}" ${work&&w.workOrderId===work.workOrderId?'selected':''}>${esc(w.workOrderNo)} • ${esc(w.customerName)}</option>`).join('')}</select></div><div class="field"><label>Birim *</label><select name="unitCode">${units.map(u=>`<option ${u===(work?.unitCode||state.unit)?'selected':''}>${esc(u)}</option>`).join('')}</select></div><div class="field"><label>Müşteri *</label><input name="customerName" required value="${esc(work?.customerName||'')}"></div><div class="field"><label>E-posta</label><input name="customerEmail" type="email" value="${esc(work?.customerEmail||'')}"></div><div class="field"><label>Geçerlilik</label><input name="validUntil" type="date" value="${new Date(Date.now()+15*86400000).toISOString().slice(0,10)}"></div><div class="field span2"><label>Not</label><textarea name="notes"></textarea></div></div></div><div class="form-card"><div class="form-h">Teklif Kalemleri <div class="spacer"></div><button type="button" class="btn soft" id="addOfferItem">＋ Kalem Ekle</button></div><div class="offer-item-head"><span>Kod</span><span>Açıklama</span><span>Adet</span><span>Birim Fiyat</span><span>İsk. %</span><span>KDV %</span><span></span></div><div id="offerItems"></div></div><div class="actions"><button type="button" class="btn" id="cancelOffer">Vazgeç</button><button class="btn primary">Teklifi Oluştur</button></div></form></div>`);
  $('#modalX').onclick=$('#cancelOffer').onclick=closeModal; $('#addOfferItem').onclick=()=>addOfferItemRow(); addOfferItemRow({description:work?.subject||'',quantity:1,vatPercent:20});
  $('#offerForm').onsubmit=async e=>{
    e.preventDefault(); const fd=new FormData(e.target); const items=$$('.offer-item-row').map(r=>({itemCode:r.querySelector('.oi-code').value.trim()||null,description:r.querySelector('.oi-desc').value.trim(),quantity:Number(r.querySelector('.oi-qty').value||0),unitPrice:Number(r.querySelector('.oi-price').value||0),discountPercent:Number(r.querySelector('.oi-disc').value||0),vatPercent:Number(r.querySelector('.oi-vat').value||0)})).filter(x=>x.description);
    try{ await api('/api/offers',{method:'POST',body:JSON.stringify({workOrderId:fd.get('workOrderId')?Number(fd.get('workOrderId')):null,unitCode:fd.get('unitCode'),customerName:fd.get('customerName'),customerEmail:fd.get('customerEmail')||null,validUntil:fd.get('validUntil')||null,notes:fd.get('notes')||null,items})}); state.offers=await api('/api/offers'); closeModal(); state.view='offers'; render(); alert('Teklif oluşturuldu.'); }catch(err){alert(err.message);}
  };
}

async function reloadWork(){ state.workOrders=await api('/api/workorders'); }
async function downloadBlob(url, filenameFallback){
  const headers={}; if(state.token) headers.Authorization=`Bearer ${state.token}`;
  const r=await fetch(url,{headers,cache:'no-store'});
  if(r.status===401){logoutLocal();render();throw new Error('Oturum süresi doldu. Tekrar giriş yapın.');}
  if(!r.ok){const raw=await r.text();let msg=`İndirme başarısız (${r.status})`;try{const j=JSON.parse(raw);msg=j.message||j.detail||j.title||msg;}catch{if(raw)msg=raw;}throw new Error(msg);}
  const blob=await r.blob(); const cd=r.headers.get('content-disposition')||''; const m=cd.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i); const name=m?decodeURIComponent(m[1].replace(/\"/g,'')):filenameFallback; const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; document.body.appendChild(a); a.click(); setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);
}

function bind(){
  if(['operations120','mobile120','stock120','finance120'].includes(state.view))ops120Bind();
  if(state.view==='timetracking')bindTimeTracking();
  if(state.view==='training')bindTraining();
  $$('[data-nav]').forEach(x=>x.onclick=async e=>{e.preventDefault();state.view=x.dataset.nav;render();if(['operations120','mobile120','stock120','finance120'].includes(state.view)){await ops120Refresh();render();}if(state.view==='timetracking'){try{await reloadLiveTracking();render();}catch(err){alert(err.message);}}if(state.view==='training'){try{await trainingRefresh();render();}catch(err){alert(err.message);}}if(state.view==='reports'){try{state.workOrders=await api('/api/workorders');state.workLogs=await api('/api/reports/worklogs');renderReportResults();}catch(err){alert(err.message);}}});
  $$('[data-unit]').forEach(x=>x.onclick=()=>{state.unit=x.dataset.unit;render();});
  $$('[data-filter]').forEach(x=>x.onclick=()=>{state.workFilter=x.dataset.filter;state.assignmentSelectedIds=[];render();});
  $$('[data-workkind]').forEach(x=>x.onclick=()=>{state.workKind=x.dataset.workkind;state.assignmentSelectedIds=[];render();});
  $$('[data-workstatus]').forEach(x=>x.onclick=()=>{state.workStatusGroup=x.dataset.workstatus;state.assignmentSelectedIds=[];render();});
  $$('[data-plankind]').forEach(x=>x.onclick=()=>{state.planningKind=x.dataset.plankind;state.bulkSelectedIds=[];render();});
  $('#planningCustomerSearch')?.addEventListener('input',e=>{const pos=e.target.selectionStart;state.planningCustomerSearch=e.target.value;state.bulkSelectedIds=[];render();
    const fresh=$('#planningCustomerSearch');if(fresh){fresh.focus();try{fresh.setSelectionRange(pos,pos);}catch{}}});
  $$('[data-dashcategory]').forEach(x=>x.onclick=()=>{state.workKind=x.dataset.dashcategory;state.workStatusGroup='open';state.assignmentSelectedIds=[];state.view='workorders';render();});
  $$('[data-nav-report]').forEach(x=>x.onclick=()=>{state.view='reports';render();});
  $$('[data-unitfilter]').forEach(x=>x.onclick=()=>{state.workFilter=x.dataset.unitfilter;state.workKind='service';state.workStatusGroup='open';state.view='workorders';render();});
  $$('[data-kpidetail]').forEach(x=>x.onclick=()=>openMetricDetails(x.dataset.kpidetail));
  $$('[data-rentalfilter]').forEach(x=>x.onclick=()=>{state.rentalFilter=x.dataset.rentalfilter;render();});
  $$('[data-deptfilter]').forEach(x=>x.onclick=()=>{state.personnelDepartment=x.dataset.deptfilter;render();});
  $('#secType')?.addEventListener('change',e=>{state.securityType=e.target.value;render();});
  $('#secBrand')?.addEventListener('change',e=>{state.securityBrand=e.target.value;state.securityModel='all';render();});
  $('#secModel')?.addEventListener('change',e=>{state.securityModel=e.target.value;render();});
  $('#secSearch')?.addEventListener('input',e=>{state.securitySearch=e.target.value;render();});
  $$('[data-open]').forEach(x=>x.onclick=e=>{e.preventDefault();openWorkOrder(x.dataset.open);});
  if(state.view==='workorders') bindAssignmentRows();
  $('#bulkAssignButton')?.addEventListener('click',()=>openBulkAssign(state.assignmentSelectedIds,'workorders'));
  $('#clearAssignmentSelection')?.addEventListener('click',()=>{state.assignmentSelectedIds=[];updateAssignmentSelectionUI();});
  $$('[data-bulk-select]').forEach(cb=>cb.onchange=()=>changeBulkSelection(cb.dataset.bulkSelect,cb.checked));
  $$('[data-bulk-group]').forEach(cb=>cb.onchange=()=>changeBulkSelection(cb.dataset.bulkGroup,cb.checked,true));
  $('#bulkPlanButton')?.addEventListener('click',openBulkPlan);
  $('#bulkWaitingAssignButton')?.addEventListener('click',()=>openBulkAssign(state.bulkSelectedIds,'planning'));
  if(state.view==='planning')syncBulkPlanningSelection();
  $$('[data-plan]').forEach(x=>x.onclick=e=>{e.preventDefault();openPlan(x.dataset.plan);});
  $$('[data-calmode]').forEach(x=>x.onclick=()=>{state.planningMode=x.dataset.calmode;render();});
  $$('[data-calnav]').forEach(x=>x.onclick=()=>{
    const d=dateFromIso(state.planningAnchor)||dateFromIso(todayIso());
    if(x.dataset.calnav==='today') state.planningAnchor=todayIso();
    else { const step=state.planningMode==='month'?1:state.planningMode==='week'?7:1; if(state.planningMode==='month'){d.setMonth(d.getMonth()+(x.dataset.calnav==='next'?1:-1));} else d.setDate(d.getDate()+(x.dataset.calnav==='next'?step:-step)); state.planningAnchor=isoLocal(d);}
    render();
  });
  $('#planningUnit')?.addEventListener('change',e=>{state.planningUnit=e.target.value;render();});
  $('#planningPerson')?.addEventListener('change',e=>{state.planningPerson=e.target.value;render();});
  $$('[data-planday]').forEach(x=>x.onclick=()=>{state.planningAnchor=x.dataset.planday;state.planningMode='day';render();});
  $$('[data-calvisit]').forEach(x=>x.onclick=()=>openCalendarVisit(x.dataset.calvisit));
  $('#logoutBtn')?.addEventListener('click',async()=>{try{await api('/api/auth/logout',{method:'POST'});}catch{} logoutLocal();render();});

  const cwt=$('#createWorkType'); if(cwt)cwt.onchange=()=>{$('#serialRuleInfo').innerHTML=serialRuleText(ruleFor(state.unit,cwt.value));};
  const cf=$('#createForm'); if(cf) cf.onsubmit=async e=>{e.preventDefault(); const fd=new FormData(cf); const serials=String(fd.get('serials')||'').split(/[,;\n]+/).map(x=>x.trim()).filter(Boolean); try{const r=await api('/api/workorders',{method:'POST',body:JSON.stringify({unitCode:state.unit,workType:fd.get('workType'),customerName:fd.get('customer'),customerEmail:fd.get('customerEmail')||null,projectName:fd.get('project')||null,location:fd.get('location')||null,systemName:fd.get('systemName')||null,serialNumbers:serials,subject:fd.get('subject'),description:fd.get('description')||null,priority:fd.get('priority')})}); await reloadWork(); alert(`${r.workOrderNo} oluşturuldu.`); state.view='workorders'; state.workFilter=state.unit; render();}catch(err){alert(err.message);}};

  const search=$('#workSearch'); if(search) search.oninput=()=>{const q=search.value.toLocaleLowerCase('tr-TR'); const rows=filteredWorkOrders().filter(w=>[w.workOrderNo,w.customerName,w.projectName,w.location,w.serialNumbers,w.subject,w.assignedStaff,w.chiefName].some(v=>String(v||'').toLocaleLowerCase('tr-TR').includes(q))); $('#workTableHost').innerHTML=workTable(rows); $$('[data-open]').forEach(x=>x.onclick=e=>{e.preventDefault();openWorkOrder(x.dataset.open);}); $$('[data-plan]').forEach(x=>x.onclick=e=>{e.preventDefault();openPlan(x.dataset.plan);});bindAssignmentRows();};

  $$('[data-maintdevices]').forEach(x=>x.onclick=()=>openMaintenanceDevices(x.dataset.maintdevices));
  $('#generateMaintenance')?.addEventListener('click',async()=>{
    try{
      const r=await api('/api/maintenance/generate-due',{method:'POST'});
      state.maintenanceContracts=await api('/api/maintenance/contracts');
      await reloadWork();
      render();
      alert(r.message);
    }catch(err){alert(err.message);}
  });
  $('#newWorkshopBtn')?.addEventListener('click',()=>openWorkshopModal());
  $$('[data-workshopopen]').forEach(x=>x.onclick=()=>openWorkshopModal(x.dataset.workshopopen));

  $$('[data-rentaltab]').forEach(b=>b.onclick=()=>{state.rentalTab=b.dataset.rentaltab;render();});
  $('#rentalInvSearch')?.addEventListener('change',e=>{state.rentalInventorySearch=e.target.value;render();});
  $('#rentalInvWarehouse')?.addEventListener('change',e=>{state.rentalInventoryWarehouse=e.target.value;render();});
  $('#rentalInvStatus')?.addEventListener('change',e=>{state.rentalInventoryStatus=e.target.value;render();});
  $('#newRentalAsset')?.addEventListener('click',()=>openRentalInventoryModal());
  $$('[data-invedit]').forEach(b=>b.onclick=()=>openRentalInventoryModal(b.dataset.invedit));
  $$('[data-whrename]').forEach(b=>b.onclick=()=>renameRentalWarehouse(b.dataset.whrename));
  $('#newRentalBtn')?.addEventListener('click',()=>openRentalCreateModal());
  $$('[data-rentalopen]').forEach(x=>x.onclick=()=>openRentalModal(x.dataset.rentalopen));
  $$('[data-rentaloffer]').forEach(x=>x.onclick=()=>{const r=state.rentals.find(a=>Number(a.rentalOrderId)===Number(x.dataset.rentaloffer));if(r)openOfferModal({unitCode:r.unitCode,customerName:r.customerName,customerEmail:r.customerEmail,subject:`Kiralama • ${r.productName}`});});

  $('#newOfferBtn')?.addEventListener('click',()=>openOfferModal());
  $$('[data-offerpdf]').forEach(x=>x.onclick=async()=>{try{await downloadBlob(`/api/offers/${x.dataset.offerpdf}/pdf`,`Teklif_${x.dataset.offerpdf}.pdf`);}catch(e){alert(e.message);}});
  $$('[data-offerapprove]').forEach(x=>x.onclick=async()=>{try{await api(`/api/offers/${x.dataset.offerapprove}/status`,{method:'PATCH',body:JSON.stringify({status:'Onaylandı'})}); state.offers=await api('/api/offers');render();}catch(e){alert(e.message);}});
  $$('[data-offersend]').forEach(x=>x.onclick=async()=>{const recipient=prompt('Müşteri e-posta adresi:',x.dataset.email||''); if(recipient===null)return; try{await api(`/api/offers/${x.dataset.offersend}/send`,{method:'POST',body:JSON.stringify({recipient})}); state.offers=await api('/api/offers');render();alert('Teklif e-posta ile gönderildi.');}catch(e){alert(e.message);}});

  // Rapor filtreleri ekran yenilendiğinde korunur, sonuçlar girilen kriterlere göre anında hesaplanır.
  $('#reportReload')?.addEventListener('click',async()=>{try{state.workOrders=await api('/api/workorders');state.workLogs=await api('/api/reports/worklogs');renderReportResults();}catch(err){alert(err.message);}});
  const reportFields={reportDateField:'dateField',reportStart:'start',reportEnd:'end',reportKind:'kind',reportUnit:'unit',reportStatus:'status',reportWorkType:'workType',reportPerson:'person',reportChief:'chief',reportCustomer:'customer'};
  Object.entries(reportFields).forEach(([id,key])=>{$('#'+id)?.addEventListener(['person','chief','customer'].includes(key)?'input':'change',e=>{state.reportFilters[key]=e.target.value;renderReportResults();});});
  $$('[data-reportpreset]').forEach(x=>x.onclick=()=>{
    const f=state.reportFilters;
    const now=new Date();let start=new Date(now);
    if(x.dataset.reportpreset==='week'){const day=(now.getDay()+6)%7;start.setDate(now.getDate()-day);}
    if(x.dataset.reportpreset==='month') start=new Date(now.getFullYear(),now.getMonth(),1);
    if(x.dataset.reportpreset==='all'){f.start='';f.end='';}
    else{f.start=isoLocal(start);f.end=isoLocal(now);}
    $('#reportStart').value=f.start;$('#reportEnd').value=f.end;renderReportResults();
  });
  $('#exportExcel')?.addEventListener('click',async()=>{
    const f=state.reportFilters;if(f.start&&f.end&&f.start>f.end){alert('Başlangıç tarihi bitişten büyük olamaz.');return;}
    const q=new URLSearchParams({start:f.start,end:f.end,dateField:f.dateField,kind:f.kind,unit:f.unit,status:f.status,workType:f.workType,person:f.person.trim(),chief:f.chief.trim(),customer:f.customer.trim()});if(!f.start)q.delete('start');if(!f.end)q.delete('end');
    try{await downloadBlob('/api/reports/workorders.xlsx?'+q.toString(),`DengeERP_Rapor_${isoLocal(new Date())}.xlsx`);}catch(e){alert(e.message);}
  });
  if(state.view==='reports')renderReportResults();

  const createUserToggle=$('#personCreateUser');
  if(createUserToggle) createUserToggle.onchange=()=>{$('#personUserFields').classList.toggle('hidden',!createUserToggle.checked);};
  const personRole=$('#personRole');
  if(personRole) personRole.onchange=()=>{$('#personPermissionHost').innerHTML=permissionChecks(state.meta?.roleDefaults?.[personRole.value]||[],'p_permissions');};
  const pf=$('#personnelForm');
  if(pf) pf.onsubmit=async e=>{
    e.preventDefault();const fd=new FormData(pf);const add=String(fd.get('additionalDepartments')||'').split(/[,;\n]+/).map(x=>x.trim()).filter(Boolean);const createUser=fd.get('createUser')==='on';
    try{
      await api('/api/personnel',{method:'POST',body:JSON.stringify({fullName:fd.get('fullName'),departmentName:fd.get('departmentName'),additionalDepartments:add,title:fd.get('title')||null,unitCode:fd.get('unitCode')||null,managerName:fd.get('managerName')||null,startDate:fd.get('startDate')||null,notes:fd.get('notes')||null,createUser,username:createUser?(fd.get('username')||null):null,password:createUser?(fd.get('password')||null):null,roleName:createUser?(fd.get('roleName')||null):null,allowedUnits:createUser?fd.getAll('p_units'):[],permissions:createUser?fd.getAll('p_permissions'):[],mustChangePassword:createUser?fd.get('mustChange')==='1':true})});
      state.personnel=await api('/api/personnel');if(can('users.manage'))state.users=await api('/api/users');render();alert('Personel kaydı oluşturuldu.');
    }catch(err){alert(err.message);}
  };
  $$('[data-personedit]').forEach(x=>x.onclick=()=>openPersonnelEditModal(x.dataset.personedit));
  $$('[data-personstatus]').forEach(x=>x.onclick=async()=>{
    const active=x.dataset.active==='1';const msg=active?'Personel tekrar aktif edilsin mi?':'Personel işten ayrıldı olarak işaretlensin mi? Bağlı ERP hesabı varsa erişimi de kapatılır.';
    if(!confirm(msg))return;
    try{await api(`/api/personnel/${x.dataset.personstatus}/status`,{method:'PATCH',body:JSON.stringify({isActive:active,endDate:active?null:todayIso()})});state.personnel=await api('/api/personnel');if(can('users.manage'))state.users=await api('/api/users');render();}catch(err){alert(err.message);}
  });
  $$('[data-personuser]').forEach(x=>x.onclick=()=>{const u=state.users.find(a=>Number(a.userId)===Number(x.dataset.personuser));if(u)openUserEditModal(u.userId);else alert('Bağlı kullanıcı hesabı listede bulunamadı.');});

  const role=$('#newUserRole'); if(role) role.onchange=()=>{$('#permissionHost').innerHTML=permissionChecks(state.meta?.roleDefaults?.[role.value]||[]);};
  const uf=$('#userForm'); if(uf) uf.onsubmit=async e=>{e.preventDefault();const fd=new FormData(uf);try{await api('/api/users',{method:'POST',body:JSON.stringify({username:fd.get('username'),password:fd.get('password'),fullName:fd.get('fullName'),roleName:fd.get('role'),allowedUnits:fd.getAll('units'),permissions:fd.getAll('permissions'),mustChangePassword:fd.get('mustChange')==='on'})});state.users=await api('/api/users');render();alert('Kullanıcı oluşturuldu.');}catch(err){alert(err.message);}};
  $$('[data-useredit]').forEach(x=>x.onclick=()=>openUserEditModal(x.dataset.useredit));
  $$('[data-userstatus]').forEach(x=>x.onclick=async()=>{try{await api(`/api/users/${x.dataset.userstatus}/status`,{method:'PATCH',body:JSON.stringify({isActive:x.dataset.active==='1'})});state.users=await api('/api/users');render();}catch(e){alert(e.message);}});
  $$('[data-resetpassword]').forEach(x=>x.onclick=async()=>{const p=prompt('Yeni geçici şifre (en az 8 karakter):');if(p===null)return;try{await api(`/api/users/${x.dataset.resetpassword}/reset-password`,{method:'POST',body:JSON.stringify({tempPassword:p})});alert('Geçici şifre oluşturuldu.');}catch(e){alert(e.message);}});
}

function bindLogin(){
  $('#loginForm').onsubmit=async e=>{e.preventDefault(); const fd=new FormData(e.target); try{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:fd.get('username'),password:fd.get('password')})}); if(!r.ok)throw new Error('Kullanıcı adı veya şifre hatalı.'); const j=await r.json(); state.token=j.token; state.user=j.user; localStorage.setItem('denge_token',state.token); await loadCore(); state.view=can('dashboard.view')?'dashboard':can('workorders.view')?'workorders':'offers'; render();}catch(err){const d=$('#loginError');d.textContent=err.message;d.classList.remove('hidden');}};
}
function bindPassword(){
  $('#passwordForm').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target);const p1=fd.get('p1'),p2=fd.get('p2');const d=$('#passwordError');if(p1!==p2){d.textContent='Şifreler aynı değil.';d.classList.remove('hidden');return;}try{const r=await api('/api/auth/change-password',{method:'POST',body:JSON.stringify({newPassword:p1})});state.user=r.user;await loadCore();render();}catch(err){d.textContent=err.message;d.classList.remove('hidden');}};
}

function render(){
  if(!state.user){document.getElementById('app').innerHTML=loginPage();bindLogin();return;}
  if(state.user.mustChangePassword){document.getElementById('app').innerHTML=passwordPage();bindPassword();return;}
  document.getElementById('app').innerHTML=layout(currentPage());bind();
}

(async function bootstrap(){
  if(state.token){try{state.user=await api('/api/auth/me');await loadCore();}catch{logoutLocal();}}
  render();
})();
