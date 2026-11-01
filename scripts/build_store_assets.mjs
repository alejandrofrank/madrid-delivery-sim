/** Reproducible, offline-after-download browser derivatives. No runtime CDN. */
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {NodeIO} from '@gltf-transform/core';
import {ALL_EXTENSIONS} from '@gltf-transform/extensions';
import {dedup, flatten, join, weld, simplify, prune, textureCompress, meshopt} from '@gltf-transform/functions';
import {MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier} from 'meshoptimizer';
import sharp from 'sharp';
await Promise.all([MeshoptDecoder.ready, MeshoptEncoder.ready, MeshoptSimplifier.ready]);
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  'meshopt.decoder': MeshoptDecoder, 'meshopt.encoder': MeshoptEncoder
});
const revision = '5888c2bede350ab39719834f58c2714e531c6851';
const assets = {shelving:'storage_shelf_basic_b01',pallet:'pallet_a01',cart:'cart_mobile_b01',
  forklift:'vehicle_forklift_orange_a01',robot:'robotics_small_bot_a01',
  produce:'food_produce_apple_f01',packaged:'food_processed_boxedCereal_l01'};
const output = 'web/vendor/simready';
await mkdir(output, {recursive:true});
await mkdir('artifacts/dark-store/source-assets', {recursive:true});
const manifest = {dataset:'https://huggingface.co/datasets/codepawl/simready-glb', revision,
  author:'NVIDIA', conversion:'codepawl', license:'CC-BY-4.0',
  license_url:'https://creativecommons.org/licenses/by/4.0/',
  modifications:'glTF Transform 4.5.1: simplified geometry, 256px WebP textures, Meshopt compression; visual assets only, not physics.',
  assets:[]};
for (const [role,name] of Object.entries(assets)) {
  const source = 'artifacts/dark-store/source-assets/'+role+'.glb';
  const url = manifest.dataset+'/resolve/'+revision+'/glb/'+name+'.glb';
  let bytes;
  try { bytes = await readFile(source); } catch {
    const response = await fetch(url); if (!response.ok) throw new Error(role+': '+response.status);
    bytes = Buffer.from(await response.arrayBuffer()); await writeFile(source, bytes);
  }
  const document = await io.read(source);
  await document.transform(dedup(), flatten(), join(), weld(),
    simplify({simplifier:MeshoptSimplifier,ratio:0.035,error:0.015}), prune(),
    textureCompress({encoder:sharp,targetFormat:'webp',resize:[256,256]}),
    meshopt({encoder:MeshoptEncoder,level:'medium'}));
  await io.write(output+'/'+role+'.glb',document);
  const reduced = await readFile(output+'/'+role+'.glb');
  manifest.assets.push({role,name,url,source_sha256:createHash('sha256').update(bytes).digest('hex'),
    path:'/static/vendor/simready/'+role+'.glb',bytes:reduced.length,
    sha256:createHash('sha256').update(reduced).digest('hex')});
  console.log(role+': '+bytes.length+' -> '+reduced.length+' bytes');
}
manifest.total_bytes = manifest.assets.reduce((sum,a)=>sum+a.bytes,0);
if (manifest.total_bytes > 3_000_000) throw new Error('Asset set exceeds 3 MB budget');
await writeFile(output+'/manifest.json', JSON.stringify(manifest,null,2)+'\n');
await writeFile(output+'/NOTICE.txt', 'NVIDIA SimReady models, converted by codepawl. CC BY 4.0.\n'+manifest.dataset+'\n'+manifest.license_url+'\n'+manifest.modifications+'\nSee manifest.json for pinned originals and SHA-256 checksums.\n');
const copies = {'build/three.module.js':'three.module.js','build/three.core.js':'three.core.js',
  'examples/jsm/loaders/GLTFLoader.js':'GLTFLoader.js','examples/jsm/controls/OrbitControls.js':'OrbitControls.js',
  'examples/jsm/utils/BufferGeometryUtils.js':'BufferGeometryUtils.js','examples/jsm/libs/meshopt_decoder.module.js':'meshopt_decoder.module.js','LICENSE':'LICENSE'};
await mkdir('web/vendor/three',{recursive:true});
for(const [from,to] of Object.entries(copies)) {
  let content=await readFile('node_modules/three/'+from,'utf8');
  content=content.replaceAll("from 'three'", "from './three.module.js'")
    .replaceAll("from '../utils/BufferGeometryUtils.js'", "from './BufferGeometryUtils.js'");
  await writeFile('web/vendor/three/'+to,content);
}
await writeFile('web/vendor/three/version.json',JSON.stringify({version:'0.187.0',license:'MIT',source:'https://github.com/mrdoob/three.js/tree/r187'},null,2)+'\n');
console.log('Total models: '+manifest.total_bytes+' bytes');
