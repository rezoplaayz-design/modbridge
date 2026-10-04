from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import os
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
import json, zipfile, uuid, shutil, tempfile, mimetypes, re, os, webbrowser, threading, time

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
JOBS = RUNTIME / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = 200 * 1024 * 1024
MAX_UNCOMPRESSED = 1024 * 1024 * 1024
MAX_FILES = 50000
JOBS_STATE = {}

MIME = {
    '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
    '.mcaddon': 'application/octet-stream', '.mcpack': 'application/octet-stream', '.zip': 'application/zip'
}

def json_response(handler, status, data):
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(raw)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(raw)

def safe_json(raw, fallback=None):
    try:
        return json.loads(raw.decode('utf-8-sig'))
    except Exception:
        return fallback

def safe_text(raw):
    try: return raw.decode('utf-8-sig', errors='replace')
    except Exception: return ''

def parse_multipart(handler):
    length = int(handler.headers.get('Content-Length', '0') or '0')
    if length <= 0 or length > MAX_UPLOAD + 1024 * 1024:
        raise ValueError('Invalid or oversized upload.')
    ctype = handler.headers.get('Content-Type', '')
    if 'multipart/form-data' not in ctype:
        raise ValueError('Expected multipart/form-data.')
    body = handler.rfile.read(length)
    msg = BytesParser(policy=default).parsebytes(
        b'Content-Type: ' + ctype.encode('utf-8') + b'\r\nMIME-Version: 1.0\r\n\r\n' + body
    )
    fields = {}
    files = {}
    for part in msg.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if not name: continue
        payload = part.get_payload(decode=True) or b''
        filename = part.get_filename()
        if filename:
            files[name] = {'filename': Path(filename).name, 'data': payload, 'content_type': part.get_content_type()}
        else:
            fields[name] = safe_text(payload)
    return fields, files

def zip_safety(zf):
    infos = zf.infolist()
    if len(infos) > MAX_FILES:
        raise ValueError('Archive contains too many files.')
    total = sum(max(0, i.file_size) for i in infos)
    if total > MAX_UNCOMPRESSED:
        raise ValueError('Archive expands beyond the safety limit.')
    for i in infos:
        p = PurePosixPath(i.filename)
        if p.is_absolute() or '..' in p.parts:
            raise ValueError('Unsafe archive path detected.')

def detect_loader_and_meta(zf, names):
    loader = 'Unknown'
    mod_id = None
    mod_name = None
    mod_version = None
    mc_version = None
    metadata = {}
    if 'fabric.mod.json' in names:
        loader = 'Fabric'
        obj = safe_json(zf.read('fabric.mod.json'), {}) or {}
        metadata['fabric'] = obj
        mod_id = obj.get('id')
        mod_name = obj.get('name') or mod_id
        mod_version = obj.get('version')
        depends = obj.get('depends') or {}
        mc_version = depends.get('minecraft') if isinstance(depends, dict) else None
        if isinstance(mc_version, list): mc_version = ', '.join(map(str, mc_version))
    elif 'META-INF/neoforge.mods.toml' in names:
        loader = 'NeoForge'
        txt = safe_text(zf.read('META-INF/neoforge.mods.toml'))
        mod_id = first_toml_value(txt, 'modId')
        mod_name = first_toml_value(txt, 'displayName') or mod_id
        mod_version = first_toml_value(txt, 'version')
        mc_version = find_version_range(txt)
    elif 'META-INF/mods.toml' in names:
        loader = 'Forge'
        txt = safe_text(zf.read('META-INF/mods.toml'))
        mod_id = first_toml_value(txt, 'modId')
        mod_name = first_toml_value(txt, 'displayName') or mod_id
        mod_version = first_toml_value(txt, 'version')
        mc_version = find_version_range(txt)
    else:
        for candidate in ('META-INF/MANIFEST.MF', 'quilt.mod.json'):
            if candidate in names:
                if candidate == 'quilt.mod.json': loader = 'Quilt'
                break
    return loader, mod_id, mod_name, mod_version, mc_version, metadata

def first_toml_value(text, key):
    m = re.search(r'(?m)^\s*' + re.escape(key) + r'\s*=\s*["\']([^"\']+)', text)
    return m.group(1).strip() if m else None

def find_version_range(text):
    vals = re.findall(r'(?m)^\s*versionRange\s*=\s*["\']([^"\']+)', text)
    # Prefer a minecraft dependency-looking range rather than loader range if present.
    return vals[-1] if vals else None

def analyze_jar(path):
    with zipfile.ZipFile(path, 'r') as zf:
        zip_safety(zf)
        names = set(zf.namelist())
        files = [n for n in names if not n.endswith('/')]
        loader, mod_id, mod_name, mod_version, mc_version, metadata = detect_loader_and_meta(zf, names)
        namespaces = sorted(({m.group(1) for n in files if (m := re.match(r'^(?:assets|data)/([^/]+)/', n))} - {'minecraft'}))
        primary_ns = mod_id if mod_id and re.match(r'^[a-z0-9_.-]+$', str(mod_id)) else (namespaces[0] if namespaces else 'modbridge')
        item_textures = [n for n in files if re.match(r'^assets/[^/]+/textures/(?:item|items)/.+\.png$', n, re.I)]
        block_textures = [n for n in files if re.match(r'^assets/[^/]+/textures/(?:block|blocks)/.+\.png$', n, re.I)]
        other_textures = [n for n in files if re.match(r'^assets/[^/]+/textures/.+\.png$', n, re.I) and n not in item_textures and n not in block_textures]
        recipes = [n for n in files if re.match(r'^data/[^/]+/recipes/.+\.json$', n, re.I)]
        lang = [n for n in files if re.match(r'^assets/[^/]+/lang/.+\.json$', n, re.I)]
        sounds = [n for n in files if re.match(r'^assets/[^/]+/sounds/.+\.ogg$', n, re.I)]
        models = [n for n in files if re.match(r'^assets/[^/]+/models/.+\.json$', n, re.I)]
        loot = [n for n in files if re.match(r'^data/[^/]+/(?:loot_table|loot_tables)/.+\.json$', n, re.I)]
        tags = [n for n in files if re.match(r'^data/[^/]+/tags/.+\.json$', n, re.I)]
        classes = [n for n in files if n.endswith('.class')]
        mixin_json = [n for n in files if n.lower().endswith('.json') and 'mixin' in n.lower()]
        render_classes = [n for n in classes if re.search(r'(render|renderer|shader)', n, re.I)]
        network_classes = [n for n in classes if re.search(r'(packet|network|payload)', n, re.I)]
        entity_classes = [n for n in classes if re.search(r'Entity[^/]*\.class$|/entity/', n, re.I)]
        # Count basic convertibility from observable resources; penalties for deep hooks.
        resource_signal = len(item_textures) + len(block_textures) + len(recipes) + len(lang) + len(sounds)
        penalty = min(22, len(mixin_json) * 4 + min(8, len(render_classes)) + min(6, len(network_classes)))
        support = max(48, min(96, 72 + min(20, resource_signal // 3) - penalty))
        if loader == 'Unknown': support = max(45, support - 5)
        warnings = []
        if mixin_json: warnings.append(f'{len(mixin_json)} mixin configuration file(s) need manual review.')
        if render_classes: warnings.append('Custom rendering classes detected; Bedrock rendering is not directly portable.')
        if network_classes: warnings.append('Custom networking code detected; requires a Bedrock-side redesign.')
        if not item_textures and not recipes and not block_textures: warnings.append('Few static resources were found; this mod may rely heavily on Java code.')
        if loader == 'Quilt': warnings.append('Quilt is detected, but the prototype conversion path is optimized for Fabric/Forge/NeoForge metadata.')
        return {
            'loader': loader, 'mod_id': mod_id, 'mod_name': mod_name or path.stem, 'mod_version': mod_version,
            'minecraft_version': mc_version or 'Unknown', 'namespaces': namespaces, 'primary_namespace': primary_ns,
            'counts': {
                'item_textures': len(item_textures), 'block_textures': len(block_textures), 'other_textures': len(other_textures),
                'textures': len(item_textures)+len(block_textures)+len(other_textures), 'recipes': len(recipes), 'lang_files': len(lang),
                'sounds': len(sounds), 'models': len(models), 'loot_tables': len(loot), 'tags': len(tags), 'classes': len(classes),
                'mixins': len(mixin_json), 'render_classes': len(render_classes), 'network_classes': len(network_classes),
                'entity_class_hints': len(entity_classes)
            },
            'support_score': support, 'warnings': warnings,
            'files': {'item_textures': item_textures, 'block_textures': block_textures, 'recipes': recipes, 'lang': lang, 'sounds': sounds},
        }

def ensure_parent(path):
    path.parent.mkdir(parents=True, exist_ok=True)

def copy_zip_entry(zf, src, dst):
    ensure_parent(dst)
    with zf.open(src) as rf, open(dst, 'wb') as wf:
        shutil.copyfileobj(rf, wf)

def safe_identifier_piece(text):
    text = re.sub(r'[^a-z0-9_./-]+', '_', text.lower()).replace('..', '.')
    return text.strip('/._-') or 'item'

def convert_ingredient(x):
    if isinstance(x, str): return {'item': x}
    if not isinstance(x, dict): return None
    if 'item' in x: return {'item': x['item']}
    if 'tag' in x: return {'tag': x['tag']}
    return None

def convert_result(x):
    if isinstance(x, str): return {'item': x, 'count': 1}
    if not isinstance(x, dict): return None
    item = x.get('id') or x.get('item')
    if not item: return None
    out = {'item': item}
    count = x.get('count', 1)
    if isinstance(count, int) and count != 1: out['count'] = count
    return out

def generate_project(job_id, analysis):
    job = JOBS / job_id
    jar_path = job / 'input.jar'
    out = job / 'output'
    if out.exists(): shutil.rmtree(out)
    rp = out / 'ModBridge_Resource_Pack'
    bp = out / 'ModBridge_Behavior_Pack'
    rp.mkdir(parents=True); bp.mkdir(parents=True)
    rp_uuid, rp_mod_uuid, bp_uuid, bp_mod_uuid = [str(uuid.uuid4()) for _ in range(4)]
    namespace = safe_identifier_piece(analysis.get('primary_namespace') or 'modbridge').replace('/','_')
    report = {
        'job_id': job_id, 'input': analysis.get('mod_name'), 'loader': analysis.get('loader'),
        'support_score': analysis.get('support_score'), 'converted': [], 'warnings': list(analysis.get('warnings') or []), 'skipped': []
    }
    rp_manifest = {
        'format_version': 2,
        'header': {'name': f"{analysis.get('mod_name','Java Mod')} - ModBridge Resources", 'description': 'Generated by ModBridge prototype', 'uuid': rp_uuid, 'version': [1,0,0], 'min_engine_version': [1,21,0]},
        'modules': [{'type':'resources','uuid':rp_mod_uuid,'version':[1,0,0]}]
    }
    bp_manifest = {
        'format_version': 2,
        'header': {'name': f"{analysis.get('mod_name','Java Mod')} - ModBridge Behavior", 'description': 'Generated by ModBridge prototype', 'uuid': bp_uuid, 'version': [1,0,0], 'min_engine_version': [1,21,0]},
        'modules': [{'type':'data','uuid':bp_mod_uuid,'version':[1,0,0]}],
        'dependencies': [{'uuid':rp_uuid,'version':[1,0,0]}]
    }
    (rp/'manifest.json').write_text(json.dumps(rp_manifest, indent=2), encoding='utf-8')
    (bp/'manifest.json').write_text(json.dumps(bp_manifest, indent=2), encoding='utf-8')
    item_texture = {'resource_pack_name': 'modbridge_generated', 'texture_name': 'atlas.items', 'texture_data': {}}
    lang_map = {}
    recipe_count = 0
    item_count = 0
    copied_sounds = 0
    with zipfile.ZipFile(jar_path, 'r') as zf:
        zip_safety(zf)
        names = set(zf.namelist())
        # Item textures -> copy + generate simple custom items.
        for src in analysis['files']['item_textures']:
            m = re.match(r'^assets/([^/]+)/textures/(?:item|items)/(.+)\.png$', src, re.I)
            if not m: continue
            ns, rel = m.group(1).lower(), safe_identifier_piece(m.group(2))
            tex_dst = rp / 'textures' / 'items' / ns / (rel + '.png')
            copy_zip_entry(zf, src, tex_dst)
            key = safe_identifier_piece(f'{ns}_{rel}').replace('/','_')
            item_texture['texture_data'][key] = {'textures': f'textures/items/{ns}/{rel}'}
            identifier = f'{ns}:{rel.replace("/","_")}'
            item_json = {
                'format_version': '1.21.0',
                'minecraft:item': {
                    'description': {'identifier': identifier, 'menu_category': {'category': 'items'}},
                    'components': {'minecraft:icon': key, 'minecraft:display_name': {'value': f'item.{ns}.{rel.replace("/","_")}.name'}}
                }
            }
            item_path = bp / 'items' / ns / (rel.replace('/','_') + '.json')
            ensure_parent(item_path); item_path.write_text(json.dumps(item_json, indent=2), encoding='utf-8')
            lang_map.setdefault('en_US', {})[f'item.{ns}.{rel.replace("/","_")}.name'] = rel.split('/')[-1].replace('_',' ').title()
            item_count += 1
        if item_texture['texture_data']:
            p = rp / 'textures' / 'item_texture.json'; ensure_parent(p); p.write_text(json.dumps(item_texture, indent=2), encoding='utf-8')
            report['converted'].append(f'{item_count} item texture(s) copied and basic Bedrock item definitions generated.')
        # Block textures are copied for manual block mapping.
        block_copied = 0
        for src in analysis['files']['block_textures']:
            m = re.match(r'^assets/([^/]+)/textures/(?:block|blocks)/(.+)\.png$', src, re.I)
            if not m: continue
            ns, rel = m.group(1).lower(), safe_identifier_piece(m.group(2))
            dst = rp / 'textures' / 'blocks' / ns / (rel + '.png')
            copy_zip_entry(zf, src, dst); block_copied += 1
        if block_copied:
            report['converted'].append(f'{block_copied} block texture(s) copied to the Resource Pack.')
            report['warnings'].append('Block textures were copied, but Java block behavior cannot be inferred reliably from texture files alone.')
        # Lang conversion
        for src in analysis['files']['lang']:
            m = re.match(r'^assets/([^/]+)/lang/([a-z_]+)\.json$', src, re.I)
            if not m: continue
            locale = m.group(2).lower()
            target_locale = {'en_us':'en_US','en_gb':'en_GB'}.get(locale)
            if not target_locale: continue
            obj = safe_json(zf.read(src), {}) or {}
            if isinstance(obj, dict):
                lang_map.setdefault(target_locale, {}).update({str(k):str(v) for k,v in obj.items() if isinstance(v,(str,int,float))})
        if lang_map:
            texts = rp / 'texts'; texts.mkdir(parents=True, exist_ok=True)
            langs=[]
            for loc, mapping in lang_map.items():
                langs.append(loc)
                content='\n'.join(f'{k}={v}' for k,v in sorted(mapping.items()))+'\n'
                (texts/f'{loc}.lang').write_text(content, encoding='utf-8')
            (texts/'languages.json').write_text(json.dumps(langs, indent=2), encoding='utf-8')
            report['converted'].append(f'{len(lang_map)} language file(s) converted to Bedrock .lang format.')
        # Recipes: shaped/shapeless common vanilla recipe formats.
        for src in analysis['files']['recipes']:
            obj = safe_json(zf.read(src), None)
            if not isinstance(obj, dict): continue
            typ = obj.get('type','')
            m = re.match(r'^data/([^/]+)/recipes/(.+)\.json$', src, re.I)
            if not m: continue
            ns, rel = m.group(1).lower(), safe_identifier_piece(m.group(2))
            out_obj = None
            if typ in ('minecraft:crafting_shaped','crafting_shaped'):
                pattern = obj.get('pattern')
                key = obj.get('key')
                result = convert_result(obj.get('result'))
                if isinstance(pattern,list) and isinstance(key,dict) and result:
                    bkey={}
                    for k,v in key.items():
                        ing=convert_ingredient(v)
                        if ing: bkey[k]=ing
                    out_obj={'format_version':'1.20.10','minecraft:recipe_shaped':{'description':{'identifier':f'{ns}:{rel.replace("/","_")}'},'tags':['crafting_table'],'pattern':pattern,'key':bkey,'result':result}}
            elif typ in ('minecraft:crafting_shapeless','crafting_shapeless'):
                ings=[]
                for v in obj.get('ingredients',[]):
                    ing=convert_ingredient(v)
                    if ing: ings.append(ing)
                result=convert_result(obj.get('result'))
                if ings and result:
                    out_obj={'format_version':'1.20.10','minecraft:recipe_shapeless':{'description':{'identifier':f'{ns}:{rel.replace("/","_")}'},'tags':['crafting_table'],'ingredients':ings,'result':result}}
            if out_obj:
                dst=bp/'recipes'/ns/(rel.replace('/','_')+'.json'); ensure_parent(dst); dst.write_text(json.dumps(out_obj,indent=2),encoding='utf-8');recipe_count+=1
        if recipe_count: report['converted'].append(f'{recipe_count} shaped/shapeless crafting recipe(s) converted.')
        if analysis['counts']['recipes']>recipe_count:
            report['skipped'].append(f'{analysis["counts"]["recipes"]-recipe_count} recipe(s) use formats not handled by this prototype.')
        # Sounds: copy raw OGG assets. sound event mapping is not guaranteed.
        for src in analysis['files']['sounds']:
            m=re.match(r'^assets/([^/]+)/sounds/(.+\.ogg)$',src,re.I)
            if not m: continue
            ns,rel=m.group(1).lower(),m.group(2)
            dst=rp/'sounds'/ns/rel;copy_zip_entry(zf,src,dst);copied_sounds+=1
        if copied_sounds:
            report['converted'].append(f'{copied_sounds} sound asset(s) copied.')
            report['warnings'].append('Java sound event definitions may need Bedrock sound_definitions mapping.')
    if analysis['counts']['mixins']:
        report['skipped'].append('Mixins are Java bytecode hooks and are not automatically portable to Bedrock.')
    if analysis['counts']['render_classes']:
        report['skipped'].append('Custom Java renderers require a separate Bedrock rendering implementation.')
    if analysis['counts']['network_classes']:
        report['skipped'].append('Custom networking code requires a Bedrock-specific replacement.')
    report_path = out/'conversion-report.json'; report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    # Validate before pack.
    validation = validate_generated(out)
    report['validation'] = validation
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    # Build .mcpack files and .mcaddon
    rp_pack=job/'ModBridge_Resource_Pack.mcpack';bp_pack=job/'ModBridge_Behavior_Pack.mcpack'
    zip_folder(rp,rp_pack);zip_folder(bp,bp_pack)
    addon=job/f'{safe_identifier_piece(analysis.get("mod_name") or "converted-mod").replace("/","-")}-Bedrock.mcaddon'
    with zipfile.ZipFile(addon,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(rp_pack,rp_pack.name);z.write(bp_pack,bp_pack.name);z.write(report_path,'conversion-report.json')
    source_zip=job/'modbridge-source.zip'; zip_folder(out,source_zip)
    return {'addon':addon,'source':source_zip,'report':report_path,'validation':validation,'report_data':report}

def zip_folder(folder, target):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob('*'):
            if p.is_file(): z.write(p,p.relative_to(folder).as_posix())

def validate_generated(out):
    checks=[];warnings=[];fixed=0
    for packname in ('ModBridge_Resource_Pack','ModBridge_Behavior_Pack'):
        p=out/packname/'manifest.json'
        checks.append({'name':f'{packname} manifest exists','ok':p.exists()})
        if p.exists():
            try: json.loads(p.read_text(encoding='utf-8'));checks.append({'name':f'{packname} manifest JSON','ok':True})
            except Exception as e: checks.append({'name':f'{packname} manifest JSON','ok':False,'detail':str(e)})
    json_files=list(out.rglob('*.json'))
    bad=[]
    for p in json_files:
        try: json.loads(p.read_text(encoding='utf-8'))
        except Exception as e: bad.append({'file':p.relative_to(out).as_posix(),'error':str(e)})
    checks.append({'name':'Generated JSON syntax','ok':not bad,'detail':bad[:5]})
    rp=out/'ModBridge_Resource_Pack';bp=out/'ModBridge_Behavior_Pack'
    item_index=rp/'textures'/'item_texture.json'
    if item_index.exists():
        try:
            obj=json.loads(item_index.read_text(encoding='utf-8'));missing=[]
            for key,val in (obj.get('texture_data') or {}).items():
                tex=(val or {}).get('textures') if isinstance(val,dict) else None
                if tex and not (rp/(tex+'.png')).exists(): missing.append(tex)
            checks.append({'name':'Item texture references','ok':not missing,'detail':missing[:10]})
        except Exception as e: checks.append({'name':'Item texture references','ok':False,'detail':str(e)})
    else:
        warnings.append('No item texture index was generated because no Java item textures were detected.')
    return {'passed':sum(1 for c in checks if c.get('ok')),'total':len(checks),'checks':checks,'warnings':warnings,'fixed':fixed}

def rebuild_indexes(job_id):
    state=JOBS_STATE.get(job_id)
    if not state or not state.get('output'): raise ValueError('No generated project for this job.')
    out=Path(state['output'])
    # Rebuild item texture index by scanning copied item PNGs.
    rp=out/'ModBridge_Resource_Pack'
    texture_data={}
    items_root=rp/'textures'/'items'
    if items_root.exists():
        for p in items_root.rglob('*.png'):
            rel=p.relative_to(rp).with_suffix('').as_posix()
            key=safe_identifier_piece(p.relative_to(items_root).with_suffix('').as_posix()).replace('/','_')
            texture_data[key]={'textures':rel}
    if texture_data:
        idx=rp/'textures'/'item_texture.json';ensure_parent(idx);idx.write_text(json.dumps({'resource_pack_name':'modbridge_generated','texture_name':'atlas.items','texture_data':texture_data},indent=2),encoding='utf-8')
    # Regenerate only manifest UUID linkage if manifests are missing/bad.
    try:
        rp_m=json.loads((rp/'manifest.json').read_text(encoding='utf-8'))
        bp=out/'ModBridge_Behavior_Pack'; bp_m=json.loads((bp/'manifest.json').read_text(encoding='utf-8'))
    except Exception:
        analysis=state['analysis']
        # easiest reliable repair: regenerate full project
        res=generate_project(job_id,analysis)
        state.update({'output':str((JOBS/job_id/'output')),'addon':str(res['addon']),'source':str(res['source']),'report':str(res['report'])})
        return res
    # Repack after index repair
    job=JOBS/job_id
    rp_pack=job/'ModBridge_Resource_Pack.mcpack';bp_pack=job/'ModBridge_Behavior_Pack.mcpack'
    zip_folder(rp,rp_pack);zip_folder(out/'ModBridge_Behavior_Pack',bp_pack)
    addon=Path(state['addon'])
    with zipfile.ZipFile(addon,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(rp_pack,rp_pack.name);z.write(bp_pack,bp_pack.name);z.write(Path(state['report']),'conversion-report.json')
    return {'addon':addon,'source':Path(state['source']),'report':Path(state['report']),'validation':validate_generated(out)}

class Handler(BaseHTTPRequestHandler):
    server_version='ModBridge/0.8'
    def log_message(self, fmt, *args):
        print('[web]', fmt % args)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/health': return json_response(self,200,{'ok':True,'version':'0.8','mode':'local'})
        m=re.match(r'^/api/download/([a-f0-9-]+)/(?P<kind>addon|source|report|fixed)$',path)
        if m:
            job_id=m.group(1);kind=m.group('kind');state=JOBS_STATE.get(job_id)
            if not state: return json_response(self,404,{'error':'Job not found.'})
            key='addon' if kind in ('addon','fixed') else kind
            p=Path(state.get(key,''))
            if not p.exists(): return json_response(self,404,{'error':'File not available.'})
            return self.send_file(p, attachment=True)
        if path=='/': path='/index.html'
        target=(ROOT/path.lstrip('/')).resolve()
        if not str(target).startswith(str(ROOT)) or not target.exists() or not target.is_file():
            self.send_error(404);return
        return self.send_file(target, attachment=False)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            if path=='/api/analyze':
                fields,files=parse_multipart(self)
                up=files.get('file')
                if not up: return json_response(self,400,{'error':'Missing file.'})
                if not up['filename'].lower().endswith('.jar'): return json_response(self,400,{'error':'Only .jar files are accepted.'})
                job_id=str(uuid.uuid4());job=JOBS/job_id;job.mkdir(parents=True)
                jar=job/'input.jar';jar.write_bytes(up['data'])
                try: analysis=analyze_jar(jar)
                except zipfile.BadZipFile:
                    shutil.rmtree(job,ignore_errors=True);return json_response(self,400,{'error':'The uploaded file is not a valid JAR/ZIP archive.'})
                analysis['filename']=up['filename'];analysis['size']=len(up['data'])
                JOBS_STATE[job_id]={'jar':str(jar),'analysis':analysis}
                return json_response(self,200,{'job_id':job_id,'analysis':analysis})
            if path=='/api/convert':
                length=int(self.headers.get('Content-Length','0') or 0);body=json.loads(self.rfile.read(length) or b'{}')
                job_id=body.get('job_id');state=JOBS_STATE.get(job_id)
                if not state:return json_response(self,404,{'error':'Job not found. Analyze the mod again.'})
                res=generate_project(job_id,state['analysis'])
                state.update({'output':str(JOBS/job_id/'output'),'addon':str(res['addon']),'source':str(res['source']),'report':str(res['report'])})
                return json_response(self,200,{'job_id':job_id,'validation':res['validation'],'report':res['report_data'],'downloads':{'addon':f'/api/download/{job_id}/addon','source':f'/api/download/{job_id}/source','report':f'/api/download/{job_id}/report'}})
            if path=='/api/repair':
                length=int(self.headers.get('Content-Length','0') or 0);body=json.loads(self.rfile.read(length) or b'{}');job_id=body.get('job_id');log=str(body.get('content_log') or '')
                state=JOBS_STATE.get(job_id)
                if not state:return json_response(self,404,{'error':'Job not found.'})
                low=log.lower();can_fix=False;kind='diagnostic';issue='No known automatic repair matched.';action='Review the Content Log and generated conversion report.'
                if any(k in low for k in ('texture','manifest','uuid','dependency','item_texture')):
                    can_fix=True;kind='automatic';issue='Pack metadata or texture index issue';action='Regenerated pack indexes/manifests where needed and rebuilt the .mcaddon.'
                    res=rebuild_indexes(job_id)
                    state['addon']=str(res['addon'])
                elif any(k in low for k in ('script','api','mixin','renderer','network')):
                    issue='Java/Script behavior mismatch';action='This requires a feature-specific Bedrock implementation; the prototype will not fake an automatic repair.'
                return json_response(self,200,{'can_fix':can_fix,'type':kind,'issue':issue,'action':action,'download':f'/api/download/{job_id}/fixed' if can_fix else None})
            return json_response(self,404,{'error':'Unknown API endpoint.'})
        except ValueError as e:
            return json_response(self,400,{'error':str(e)})
        except Exception as e:
            import traceback; traceback.print_exc()
            return json_response(self,500,{'error':'Server error: '+str(e)})
    def send_file(self,p,attachment=False):
        p=Path(p);raw=p.read_bytes();ctype=MIME.get(p.suffix.lower()) or mimetypes.guess_type(str(p))[0] or 'application/octet-stream'
        self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)))
        if attachment:self.send_header('Content-Disposition',f'attachment; filename="{p.name}"')
        self.send_header('Cache-Control','no-store' if p.suffix in ('.html','.js','.css') else 'public, max-age=60');self.end_headers();self.wfile.write(raw)

def main():
    # Cloud-ready: bind to all interfaces and respect a hosting provider's PORT.
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '8765'))
    server = ThreadingHTTPServer((host, port), Handler)

    display_host = '127.0.0.1' if host == '0.0.0.0' else host
    url = f'http://{display_host}:{port}/'
    print('\nModBridge is running at', url)
    print(f'Listening on {host}:{port}')
    print('Press Ctrl+C to stop.\n')

    # Only auto-open a browser for local desktop use.
    if os.environ.get('OPEN_BROWSER', '0') == '1':
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__=='__main__': main()
