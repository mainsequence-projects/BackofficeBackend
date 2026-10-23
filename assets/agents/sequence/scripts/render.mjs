import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import sharp from 'sharp';

const root=path.resolve(import.meta.dirname,'..');
const framesRoot=path.join(root,'build','frames');
await fs.mkdir(framesRoot,{recursive:true});
const agents=JSON.parse(await fs.readFile(path.join(root,'inputs.json'),'utf8'));
for (const agent of agents) {
  agent.file = path.join(root, agent.file);
  const bytes = await fs.readFile(agent.file);
  if (crypto.createHash('sha256').update(bytes).digest('hex') !== agent.sha256) throw Error(`Source changed: ${agent.key}`);
  agent.sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
  if (agent.file.endsWith('.svg')) {
    const source = bytes.toString();
    agent.box = source.match(/viewBox="([^"]+)"/)[1];
    agent.logo = source.replace(/^[\s\S]*?<svg[^>]*>/,'').replace(/<\/svg>[\s\S]*$/,'');
    // Preserve source paths, widths and joins; only make solid ink theme-adaptive.
    let inherited = source.match(/<svg([^>]*)>/)[1].replace(/(?:xmlns|viewBox)="[^"]*"/g,'');
    agent.logo = `<g ${inherited}>${agent.logo}</g>`.replace(/(fill|stroke)="#(?:000000|000)"/g,'$1="currentColor"');
  } else {
    // Embed original pixels; transparent source padding is excluded by the viewBox.
    agent.logo = `<g class="raster" filter="url(#sequence-ink-dark)"><image width="512" height="512" href="data:image/png;base64,${bytes.toString('base64')}"/></g>`;
  }
}

function logo(agent) {
  const wide = false;
  return `<svg x="${wide?5:7}" y="7" width="${wide?30:26}" height="26" viewBox="${agent.box}" overflow="visible">${agent.logo}</svg>`;
}

const inkFilters = `<defs><filter id="sequence-ink-dark" color-interpolation-filters="sRGB"><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncR type="linear" slope=".16" intercept=".40"/><feFuncG type="linear" slope=".16" intercept=".40"/><feFuncB type="linear" slope=".16" intercept=".40"/></feComponentTransfer></filter><filter id="sequence-ink-light" color-interpolation-filters="sRGB"><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncR type="linear" slope=".7" intercept="0"/><feFuncG type="linear" slope=".7" intercept="0"/><feFuncB type="linear" slope=".7" intercept="0"/></feComponentTransfer></filter></defs>`;

function motion(key, mode, phase) {
  const tau = Math.PI * 2;
  const wave = (1-Math.cos(phase*tau))/2;
  const t = (phase*2)%1;
  const dot = (x,y,r=1,opacity=1)=>`<circle cx="${x}" cy="${y}" r="${r}" fill="currentColor" opacity="${opacity}"/>`;
  const line = (d,opacity=1,width=1.2)=>`<path d="${d}" fill="none" stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" opacity="${opacity}"/>`;
  let out = line('M4.5 35.5l3-3',1,2.5);
  if (mode==='idle') return out+dot(35.5,4.5,1.9+.2*wave,.65+.35*wave);
  if (mode==='thinking') {
    for(let i=0;i<3;i++){const a=phase*tau*2+i*tau/3;out+=dot(35.3+2.1*Math.cos(a),4.5+2.1*Math.sin(a),i===0?1.3:.8,1-i*.25);}
    return out;
  }
  if (mode==='attention') return out+line('m35.5 1.2 3.3 3.3-3.3 3.3-3.3-3.3Z',.4+.6*wave,1.55);
  out += dot(35.5,4.5,2.1);

    for(let i=0;i<3;i++) out+=line(`M14 ${34.4+i*2.1}h6`,.16+.84*(1-Math.cos(t*tau-i*1.8))/2,1.1);
    out+=line('m24 36 2 2 4-4',.25+.75*(1-Math.cos(t*tau))/2,1.6);

  return out;
}
const frames=path.join(framesRoot,'neutral',agents[0].key);
await fs.mkdir(frames,{recursive:true});
function svg(inside) {return `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 40 40" color="#808080">${inkFilters}${inside}</svg>`;}
const agent=agents[0];
await sharp(Buffer.from(svg(logo(agent)))).png().toFile(path.join(frames,'identity.png'));
for(const state of ['idle','thinking','working','error']) {
  for(let frame=0;frame<60;frame++) {
    const source=svg(logo(agent)+motion(agent.key,state==='error'?'attention':state,frame/60));
    await sharp(Buffer.from(source)).png().toFile(path.join(frames,`${state}-${String(frame).padStart(2,'0')}.png`));
  }
}
console.log(`Rendered ${agent.name}: four animated states.`);
