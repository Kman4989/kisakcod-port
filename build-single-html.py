#!/usr/bin/env python3
"""
Build a single-file HTML that combines SP + MP into one page.
Produces two outputs:
  - kisakcod-combined.html : inlines CSS/JS/font, keeps wasm external (lightweight, ~600KB)
  - kisakcod-single.html   : fully inlines CSS/JS/font/WASM (single-file offline, ~16MB)
"""
import base64
import pathlib
import re

ROOT = pathlib.Path(__file__).parent
assets_font = ROOT / "assets" / "conduit-itc-regular.otf"
sp_js = ROOT / "kisakcod-sp.js"
sp_wasm = ROOT / "kisakcod-sp.wasm"
mp_js = ROOT / "mp" / "kisakcod-mp.js"
mp_wasm = ROOT / "mp" / "kisakcod-mp.wasm"
index_html = ROOT / "index.html"

def b64(path, binary=True):
    data = path.read_bytes()
    return base64.b64encode(data).decode('ascii')

def b64_text(path):
    data = path.read_text(encoding='utf-8')
    return base64.b64encode(data.encode('utf-8')).decode('ascii')

# Read original index.html to extract style and inline script
orig = index_html.read_text(encoding='utf-8')
# Extract <style>...</style>
style_m = re.search(r'<style>(.*?)</style>', orig, re.DOTALL)
orig_style = style_m.group(1) if style_m else ""
# Extract the large inline <script> after template (second script block)
# There are two script blocks: template script is inside <template>, then the main inline logic.
# We want the main logic: it's the <script> after </template>
scripts = re.findall(r'<script>(.*?)</script>', orig, re.DOTALL)
# The last script is the main logic
orig_main_js = scripts[-1] if scripts else ""
# For new file, we will reuse orig_main_js but modify startGame logic

font_b64 = b64(assets_font)
# Replace font URL in CSS
new_style = orig_style.replace('url("assets/conduit-itc-regular.otf")', f'url(data:font/opentype;base64,{font_b64})')
# Keep same CSS, but append extra for mode selector
extra_style = """
#mode-selector{margin:10px auto 14px}
#mode-selector button{background:#2a2a3a;color:#bbb;border:1px solid #444}
#mode-selector button.active{background:#6ec26e;color:#183318;border-color:#6ec26e}
#single-file-note{color:#777;font-size:13px;margin:10px auto 0;max-width:48em}
#single-file-note a{color:#8ab}
"""
new_style_full = new_style + extra_style

# Prepare base64 for JS (text)
sp_js_b64 = b64_text(sp_js)
mp_js_b64 = b64_text(mp_js)
sp_wasm_b64 = b64(sp_wasm)
mp_wasm_b64 = b64(mp_wasm)

# For lightweight version we still inline JS text via base64 -> blob url, but wasm stays external
# For full version we also inline wasm

# The original inline script contains:
# - canvas setup, relay logic, Module definition, kisakNet, input install, startGame
# We will create a patched version that supports mode switching and embedded resources.

# Generate the patched main js for single file.
# We'll keep orig_main_js verbatim for most, but replace the last part that handles gameScript template + startGame.
# Let's extract parts to modify:
# Original tail after __kisakInstallInput is:
#   const gameScript=document.getElementById("module-script-template").content.querySelector("script");
#   if(null!==joinCode){...}
#   function startGame(){if(document.body.contains(gameScript))return; const e=new URL(gameScript.src,location.href); if(e.searchParams.set("kisakLan",Module.kisakLanUrl),Module.kisakBots){...} for(const t of[...])... gameScript.src=e.href,document.body.appendChild(gameScript)} startGame()

# We'll replace that with mode-aware logic.

# For patching, we will remove the template handling and inject our own.

patched_js_template = r'''
// --- Embedded resources (base64) ---
const SP_JS_B64 = "__SP_JS_B64__";
const MP_JS_B64 = "__MP_JS_B64__";
const SP_WASM_B64 = "__SP_WASM_B64__";
const MP_WASM_B64 = "__MP_WASM_B64__";
const EMBED_WASM = __EMBED_WASM__; // true for single-file, false for combined (external wasm)

function b64ToBytes(b64){
  const bin = atob(b64);
  const len = bin.length;
  const bytes = new Uint8Array(len);
  for(let i=0;i<len;i++) bytes[i]=bin.charCodeAt(i);
  return bytes;
}
function b64ToBlobUrl(b64, mime){
  const bytes = b64ToBytes(b64);
  const blob = new Blob([bytes], {type: mime});
  return URL.createObjectURL(blob);
}
function jsB64ToBlobUrl(b64){
  // JS is UTF-8 bytes -> decode
  const bytes = b64ToBytes(b64);
  const text = new TextDecoder().decode(bytes);
  const blob = new Blob([text], {type: "text/javascript"});
  return URL.createObjectURL(blob);
}

// Create blob URLs (only if embedded wasm, else we still create JS blob urls for inlining JS)
const SP_WASM_URL = EMBED_WASM ? b64ToBlobUrl(SP_WASM_B64, "application/wasm") : null;
const MP_WASM_URL = EMBED_WASM ? b64ToBlobUrl(MP_WASM_B64, "application/wasm") : null;
const SP_JS_URL = jsB64ToBlobUrl(SP_JS_B64);
const MP_JS_URL = jsB64ToBlobUrl(MP_JS_B64);

'''

# Now build the full inline script that includes original logic + mode handling
# orig_main_js already defines canvas, fullscreenButton, blockedShortcuts, relayStore, Module, kisakNet, __kisakInstallInput
# We need to keep it, but we will inject our patched template at top and override the end.

# For simplicity, we will create final script as:
# 1. orig_main_js with its ending truncated (remove gameScript/template/startGame)
# 2. plus our mode logic

# Find where to truncate: locate "const gameScript="
trunc_idx = orig_main_js.find('const gameScript=')
if trunc_idx == -1:
    # fallback: keep whole and just override
    orig_prefix = orig_main_js
else:
    orig_prefix = orig_main_js[:trunc_idx]

# Build final script
def build_final_js(embed_wasm=True):
    # For lightweight combined we omit wasm b64 to keep file small
    wasm_sp = sp_wasm_b64 if embed_wasm else ""
    wasm_mp = mp_wasm_b64 if embed_wasm else ""
    patched_header = patched_js_template.replace("__SP_JS_B64__", sp_js_b64).replace("__MP_JS_B64__", mp_js_b64).replace("__SP_WASM_B64__", wasm_sp).replace("__MP_WASM_B64__", wasm_mp).replace("__EMBED_WASM__", "true" if embed_wasm else "false")
    # Mode handling JS
    mode_js = r'''
// === Mode selector (SP / MP) ===
let currentMode = null;
try { currentMode = localStorage.getItem("kisak_mode"); } catch(e){}
if(currentMode !== "sp" && currentMode !== "mp") currentMode = "sp";

// UI helpers - elements exist after DOM, so bind on DOMContentLoaded if needed
function updateModeButtons(){
  const spBtn = document.getElementById("mode-sp");
  const mpBtn = document.getElementById("mode-mp");
  if(!spBtn || !mpBtn) return;
  if(currentMode==="sp"){ spBtn.classList.add("active"); mpBtn.classList.remove("active"); }
  else { mpBtn.classList.add("active"); spBtn.classList.remove("active"); }
  // Update hint text slightly
  const hint = document.querySelector("#installer-panel p.hint");
  if(hint){
    if(currentMode==="mp") hint.textContent = "Multiplayer — pick your Call of Duty 4 folder (same as SP, plus bots).";
    else hint.textContent = "Singleplayer — pick your Call of Duty 4 folder.";
  }
}
function setMode(m){
  if(m!== "sp" && m!== "mp") return;
  if(m===currentMode) return;
  currentMode = m;
  try{ localStorage.setItem("kisak_mode", m); }catch(e){}
  updateModeButtons();
  // If game already injected, require reload
  if(window.__kisakGameInjected){
    const msg = "Mode changed to " + (m==="mp" ? "Multiplayer" : "Singleplayer") + ". Reload to apply?";
    if(confirm(msg)) location.reload();
  }
}

// Hook buttons after DOM ready
(function bindModeUI(){
  function bind(){
    const spBtn=document.getElementById("mode-sp");
    const mpBtn=document.getElementById("mode-mp");
    if(spBtn) spBtn.addEventListener("click", ()=>setMode("sp"));
    if(mpBtn) mpBtn.addEventListener("click", ()=>setMode("mp"));
    updateModeButtons();
  }
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})();

// Allow ?mode=sp/mp in URL to override (useful for direct links)
try{
  const urlMode = new URLSearchParams(location.search).get("mode");
  if(urlMode==="sp" || urlMode==="mp"){
    currentMode = urlMode;
    try{ localStorage.setItem("kisak_mode", currentMode);}catch(e){}
  }
}catch(e){}

// --- Override Module.locateFile to handle embedded WASM ---
(function patchModuleLocateFile(){
  const origLocate = Module.locateFile;
  Module.locateFile = function(path, prefix){
    // If embedded wasm mode, return blob URL for wasm files
    if(EMBED_WASM && path.endsWith(".wasm")){
      if(path.includes("kisakcod-mp.wasm") || currentMode==="mp") return MP_WASM_URL;
      if(path.includes("kisakcod-sp.wasm") || currentMode==="sp") return SP_WASM_URL;
      return currentMode==="mp" ? MP_WASM_URL : SP_WASM_URL;
    }
    // External (non-embedded) - need correct relative paths from root
    // SP wasm is at root, MP wasm is in mp/ subfolder
    if(path==="kisakcod-sp.wasm") return "kisakcod-sp.wasm";
    if(path==="kisakcod-mp.wasm") return "mp/kisakcod-mp.wasm";
    // Handle pthreads worker script? It may request the .js file itself via locateFile?
    // Fallback to original
    if(origLocate) return origLocate(path, prefix);
    return (prefix||"")+path;
  };
  // Also ensure Module.mainScriptUrlOrBlob is not needed; workers will inherit blob URL.
})();

// --- Fetch interceptor for embedded mods (optional) ---
// For single-file we keep external fetch for mods; if unavailable bots will still work without mods.
// We keep original fetch behavior, but we could add embedded manifest if needed.
// (No interceptor needed for basic operation)

// --- Dynamic game script injection (replaces template) ---
let gameScriptEl = null;
window.__kisakGameInjected = false;

function getSelectedJsUrl(){
  return currentMode==="mp" ? MP_JS_URL : SP_JS_URL;
}

function startGame(){
  if(window.__kisakGameInjected) return;
  window.__kisakGameInjected = true;
  const jsUrl = getSelectedJsUrl();
  const url = new URL(jsUrl, location.href);
  // Preserve original query param handling (kisakLan, bots, etc.)
  if(Module.kisakLanUrl) url.searchParams.set("kisakLan", Module.kisakLanUrl);
  if(Module.kisakBots){
    url.searchParams.set("fs_game","mods/mp_bots");
    const t=0|Module.kisakBotsAdd;
    if(t>0) url.searchParams.set("addbots", String(t));
  }
  for(const k of ["devmap","ben","bench","benchcmd","benchdelay","addbots"]){
    const v = relayParams.get(k);
    if(v!==null) url.searchParams.set(k, v);
  }
  if(joinCode!==null) url.searchParams.set("joinCode", joinCode);
  // Also set mode param for workers to know
  url.searchParams.set("mode", currentMode);

  const s = document.createElement("script");
  s.async = true;
  s.src = url.href;
  // For Emscripten pthreads, workers will use this script URL; blob URL is okay.
  s.onerror = function(e){ console.error("Failed to load game script", e); alert("Failed to load "+currentMode+" script. Check console."); };
  // Store for debugging
  window.__kisakCurrentGameScript = s;
  document.body.appendChild(s);
}

// Expose for manual reload
window.kisakSwitchMode = setMode;

// Original code had auto-start; we keep it but allow mode selector to show before game loads.
// The original installer logic inside the embedded JS (the !function(){...} block) will handle panel.
// We start game after a tick to let Mode UI bind first.
setTimeout(startGame, 50);

// Also handle COOP/COEP warning for single-file file:// usage
(function checkHeaders(){
  // SharedArrayBuffer requires crossOriginIsolated
  if(typeof SharedArrayBuffer === "undefined"){
    console.warn("SharedArrayBuffer not available - threading disabled. Serve via HTTP with COOP/COEP headers.");
    // Show note in installer log if possible
    setTimeout(()=>{
      const log=document.getElementById("install-log");
      if(log && !window.crossOriginIsolated){
        log.textContent += "\n[Note] SharedArrayBuffer unavailable (not crossOriginIsolated). Multiplayer threading may fail. Serve this file via a server with COOP/COEP headers for full functionality. Single-file file:// may still work for SP with degraded performance.\n";
      }
    }, 500);
  }
})();

// Keep original input install logic already defined in orig_prefix (window.__kisakInstallInput etc.)

'''
    # Replace EMBED_WASM placeholder inside mode_js (it was in patched_header)
    final = patched_header + "\n" + orig_prefix + "\n" + mode_js
    return final

# Build HTML skeletons
html_template = '''<!doctype html>
<html lang="en-us">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>kisakcod webport - single file</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>__STYLE__</style>
</head>
<body>
<div id="installer-panel">
  <h1>KisakCOD</h1>
  <p class="hint">Pick your Call of Duty 4 folder.</p>
  <div class="row" id="mode-selector">
    <button id="mode-sp" type="button" class="active">Singleplayer</button>
    <button id="mode-mp" type="button">Multiplayer</button>
  </div>
  <div class="row">
    <button id="select-folder-button" type="button">Pick game folder</button>
    <button id="play-button" type="button" disabled>Play</button>
    <button id="wipe-data-button" type="button" class="danger">Wipe data</button>
  </div>
  <div id="install-options" hidden>
    <div class="row">
      <label class="opt"><input id="include-audio" type="checkbox" checked> Audio <span class="opt-size" id="audio-size"></span></label>
      <label class="opt"><input id="include-video" type="checkbox"> Video <span class="opt-size" id="video-size"></span></label>
    </div>
    <div class="row map-options">
      <div class="row-title">Maps (choose campaign, multiplayer, or both)</div>
      <div id="map-selection"></div>
    </div>
    <div id="install-copy-size"></div>
  </div>
  <div id="install-log"></div>
  <div id="single-file-note">__NOTE__</div>
</div>
<canvas id="canvas" width="1280" height="720" tabindex="-1"></canvas>
<button id="fullscreen-button" type="button">Fullscreen</button>
<script>__SCRIPT__</script>
</body>
</html>
'''

note_combined = 'Combined build — SP + MP in one HTML. <b>WASM stays external</b> (needs <code>kisakcod-sp.wasm</code> + <code>mp/kisakcod-mp.wasm</code> next to this file). Font &amp; game JS are inlined. Open via HTTP with <code>Cross-Origin-Opener-Policy: same-origin</code> &amp; <code>Cross-Origin-Embedder-Policy: require-corp</code> for threading. | <a href="?mode=sp">SP</a> · <a href="?mode=mp">MP</a> · Mode stored in localStorage.'
note_single = 'Fully self-contained — WASM, JS &amp; font inlined (no external files). Large file (~16MB). Still needs game data via “Pick game folder” (OPFS). Serve via HTTP with COOP/COEP headers for threading; file:// will warn but may run SP. | <a href="?mode=sp">SP</a> · <a href="?mode=mp">MP</a>'

for embed, out_name, note in [
    (False, "kisakcod-combined.html", note_combined),
    (True,  "kisakcod-single.html",    note_single),
]:
    script = build_final_js(embed_wasm=embed)
    html = html_template.replace("__STYLE__", new_style_full).replace("__SCRIPT__", script).replace("__NOTE__", note)
    out_path = ROOT / out_name
    out_path.write_text(html, encoding='utf-8')
    print(f"Wrote {out_path}  ({len(html)/1024/1024:.2f} MB)  embedWasm={embed}")

# Also write a tiny README for the builds
readme = ROOT / "SINGLE_FILE_README.md"
readme.write_text("# Single-file builds\n\n- `kisakcod-combined.html` — lightweight combined SP+MP, inlines JS+font, WASM stays external. Needs `kisakcod-sp.wasm` and `mp/kisakcod-mp.wasm` alongside. ~0.6 MB.\n- `kisakcod-single.html` — fully self-contained, inlines JS+font+WASM. No external files except the game folder you pick. ~16 MB.\n\nBoth have a toggle for Singleplayer / Multiplayer (persisted in localStorage, overridable via `?mode=sp` or `?mode=mp`).\n\nServe with COOP/COEP headers for threading:\n```\nCross-Origin-Opener-Policy: same-origin\nCross-Origin-Embedder-Policy: require-corp\n```\n\nOtherwise SharedArrayBuffer is disabled and MP may fail.\n", encoding='utf-8')
print("Done")

