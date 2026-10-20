const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.attributes={};this.textContent='';this.hidden=false;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(){}
  get lastChild(){return this.children.at(-1);}
}
function app(fetcher=async()=>({ok:true,json:async()=>({items:[]})})) {
  const nodes=new Map();
  const context={document:{createElement:tag=>new Element(tag),getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}},
    location:{href:'https://example.com/stream-radar/'},navigator:{onLine:true},fetch:fetcher,URL,Date,console};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('app.js','utf8'),context);
  return {run:code=>vm.runInContext(code,context),nodes};
}
test('Search ignores accents and audio-only excludes unknown and subtitles', async()=>{
  const a=app();await new Promise(setImmediate);
  a.run(`state.items=[{title:'Città',platform:'Netflix',date:'2026-10-20',audio_italiano:'yes'}, {title:'Citta',platform:'Netflix',date:'2026-10-19',audio_italiano:'unknown'}];state.search='citta';`);
  assert.equal(a.run('getShown().length'),2);
  a.run('state.audioOnly=true');assert.equal(a.run('getShown().length'),1);
  a.run("state.platform='Disney+';");assert.equal(a.run('getShown().length'),0);
});
test('Cards use text nodes, safe links, poster fallback and expandable details',()=>{
  const a=app();
  const card=a.run(`itemCard({title:'<img onerror=alert(1)>',date:'2026-10-20',rating:8,rating_count:123,audio_italiano:'unknown',link:'javascript:alert(1)',poster:'javascript:alert(1)'})`);
  const [button,panel]=card.children;
  assert.equal(button.children[0].src,'./icons/icon.svg');
  assert.equal(button.children[1].children[1].textContent,'<img onerror=alert(1)>');
  assert.equal(panel.children.some(n=>n.tag==='a'),false);
  button.onclick();assert.equal(panel.hidden,false);assert.equal(button.attributes['aria-expanded'],'true');
  button.onclick();assert.equal(panel.hidden,true);
});
test('Failed refresh preserves loaded items and restores refresh button',async()=>{
  let fail=false;
  const a=app(async()=>{if(fail)throw Error('offline');return {ok:true,json:async()=>({updated_at:new Date().toISOString(),items:[{title:'Test',platform:'Netflix',date:'2026-10-20'}]})};});
  await new Promise(setImmediate);assert.equal(a.run('state.items.length'),1);
  fail=true;await a.run('load()');assert.equal(a.run('state.items.length'),1);
  assert.match(a.nodes.get('notice').textContent,/ultimi dati/);assert.equal(a.nodes.get('refresh').disabled,false);
});
test('Episode grouping counts titles and never extends audio evidence to unknown episodes',()=>{
  const a=app();
  a.run(`state.items=[{title:'Serie',tmdb_id:1,media_type:'tv',platform:'Netflix',date:'2026-10-20',season:1,episode:2,audio_italiano:'yes',audio_source:'https://example.com/e2'},{title:'Serie',tmdb_id:1,media_type:'tv',platform:'Netflix',date:'2026-10-19',season:1,episode:1,audio_italiano:'unknown'}];`);
  assert.equal(a.run('groupedItems(state.items).length'),1);
  assert.equal(a.run('groupedItems(state.items)[0].audio_italiano'),'unknown');
  assert.equal(a.run('groupedItems(state.items)[0].audio_source'),null);
  assert.equal(a.run('groupedItems(state.items)[0].recent_episodes.length'),2);
  a.run("state.audioOnly=true");assert.equal(a.run('groupedItems(getShown())[0].audio_italiano'),'yes');
});
