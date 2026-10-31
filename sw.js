// 錦江町 森林管理システム：オフラインでも開けるようにするための仕組み
const VER='v42';
// この仕組みが置かれたフォルダ（例：/my-first-repo/app/）。町ごとのフォルダで同じファイルを使う
const BASE=new URL(self.registration.scope).pathname;
const PFX=BASE.endsWith('/app/')?'forest':BASE.split('/').filter(Boolean).pop(); // 錦江町は今までどおり「forest」
const SHELL=PFX+'-shell-'+VER, DATA=PFX+'-data-v1', TILES=PFX+'-tiles-v1';
const SHELL_FILES=['./','./index.html','./config.js','./manifest.webmanifest','./icon-192.png','./icon-512.png',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js'];
const TILE_MAX=6000;            // 一度見た地図の画像を覚えておく枚数
const SAVED='gsi-saved-v1';      // 「地図を端末に保存」で保存した画像（自動では消さない。どのアプリからも使う）

self.addEventListener('install',e=>{
  e.waitUntil(caches.open(SHELL).then(c=>Promise.all(SHELL_FILES.map(u=>c.add(u).catch(()=>{})))).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',e=>{
  e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k.startsWith(PFX+'-shell-')&&k!==SHELL).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});

async function networkFirst(req,cacheName,fresh){
  const c=await caches.open(cacheName);
  // fresh: ブラウザの一時保存を使わず、毎回GitHubに最新版を確認する
  try{const r=await fetch(fresh?req.url:req,fresh?{cache:'no-cache',credentials:'same-origin'}:undefined);if(r&&(r.ok||r.type==='opaque'))c.put(req,r.clone()).catch(()=>{});return r}
  catch(e){const m=await c.match(req,{ignoreSearch:true});if(m)return m;throw e}
}
async function cacheFirst(req,cacheName,trim){
  const c=await caches.open(cacheName);
  const m=(await c.match(req))||(await (await caches.open(SAVED)).match(req.url));if(m)return m;
  const r=await fetch(req);
  if(r&&(r.ok||r.type==='opaque')){c.put(req,r.clone()).then(()=>{if(trim)trimCache(c,trim)}).catch(()=>{})}
  return r;
}
// 地番データ：同じURL（版番号つき）なら保存分を使い、新しい版を取ったら古い版を消す
async function dataCache(req){
  const c=await caches.open(DATA);
  const m=await c.match(req);if(m)return m;
  const r=await fetch(req);
  if(r&&r.ok){
    await c.put(req,r.clone()).catch(()=>{});
    const path=new URL(req.url).pathname;
    for(const k of await c.keys()){const ku=new URL(k.url);if(ku.pathname===path&&k.url!==req.url)await c.delete(k)}
  }
  return r;
}
let trimming=false;
async function trimCache(c,max){
  if(trimming)return;trimming=true;
  try{const keys=await c.keys();if(keys.length>max){for(const k of keys.slice(0,keys.length-max))await c.delete(k)}}finally{trimming=false}
}

self.addEventListener('fetch',e=>{
  const req=e.request;if(req.method!=='GET')return;
  const u=new URL(req.url);
  if(req.mode==='navigate'||(u.origin===location.origin&&(u.pathname===BASE+'index.html'||u.pathname===BASE))){e.respondWith(networkFirst(req,SHELL,true));return}
  // 目録（小さい）は毎回最新を確認、地番データ本体は版番号が同じ間は端末の保存分を使う
  if(u.origin===location.origin&&u.pathname===BASE+'data/index.json'){e.respondWith(networkFirst(req,DATA,true));return}
  // 地番データ本体（まとめた版は、町ごとの版のフォルダにある地番データも使う）
  if(u.origin===location.origin&&(u.pathname.startsWith(BASE+'data/')||(u.pathname.includes('/data/')&&u.pathname.endsWith('.geojson')))){e.respondWith(dataCache(req));return}
  if(u.origin===location.origin&&u.pathname===BASE+'kokuyu/index.json'){e.respondWith(networkFirst(req,DATA,true));return}
  if(u.origin===location.origin&&u.pathname.startsWith(BASE+'kokuyu/')){e.respondWith(dataCache(req));return}
  // 地図の画像は保存分を先に使う（画面から直接読むもの＝保存処理や標高の計算は、そのまま通す）
  if(u.hostname==='cyberjapandata.gsi.go.jp'){if(req.destination==='image')e.respondWith(cacheFirst(req,TILES,TILE_MAX));return}
  if(u.hostname==='cdnjs.cloudflare.com'||u.hostname==='fonts.googleapis.com'||u.hostname==='fonts.gstatic.com'){e.respondWith(cacheFirst(req,SHELL));return}
  if(u.origin===location.origin){e.respondWith(networkFirst(req,SHELL))}
});
