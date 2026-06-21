"""
IMMUNE -- live demo UI server
Run from your project root:  uv run dashboard/server.py
Then open:  http://localhost:5000
"""
import subprocess
import os
import sys
from flask import Flask, Response, render_template_string
from pathlib import Path

app = Flask(__name__)
PROJECT_ROOT = Path(__file__).parent.parent

# Find uv executable — works even when PATH is missing it
UV = os.path.join(os.path.expanduser("~"), ".local", "bin", "uv")
if not os.path.exists(UV):
    # Windows path
    UV = os.path.join(os.path.expanduser("~"), ".cargo", "bin", "uv.exe")
if not os.path.exists(UV):
    # Try AppData (Windows uv installer default)
    UV = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "uv", "bin", "uv.exe")
if not os.path.exists(UV):
    UV = "uv"  # fallback to PATH

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IMMUNE -- Live Demo</title>
<style>
  :root {
    --bg:        #2e3339;
    --surface:   #424b54;
    --border:    #4f5a63;
    --steel:     #93a8ac;
    --blossom:   #e2b4bd;
    --rose:      #9b6a6c;
    --white:     #ffffff;
    --dim:       #93a8ac;
    --text:      #ffffff;
    --green:     #7ec8a0;
    --red:       #e2b4bd;
    --yellow:    #d4b896;
    --cyan:      #93a8ac;
    --font-mono: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace;
    --font-sans: 'Inter', system-ui, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font-sans); min-height: 100vh; display: flex; flex-direction: column; }
  header { border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; align-items: center; justify-content: space-between; background: var(--surface); }
  .logo { display: flex; align-items: center; gap: 12px; }
  .logo-icon { width: 36px; height: 36px; border-radius: 8px; background: var(--rose); display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; color: white; flex-shrink: 0; }
  .logo-text { font-size: 16px; font-weight: 600; letter-spacing: -0.01em; color: var(--white); }
  .logo-sub  { font-size: 12px; color: var(--steel); margin-top: 1px; }
  .status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--steel); }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--border); }
  .status-dot.running { background: var(--green); animation: pulse 1.5s ease-in-out infinite; }
  .status-dot.done    { background: var(--steel); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  main { flex: 1; display: grid; grid-template-columns: 1fr 300px; max-height: calc(100vh - 65px); }
  .terminal-wrap { display: flex; flex-direction: column; border-right: 1px solid var(--border); }
  .terminal-head { padding: 0.6rem 1.25rem; border-bottom: 1px solid var(--border); font-size: 10px; font-weight: 600; color: var(--steel); text-transform: uppercase; letter-spacing: 0.08em; display: flex; align-items: center; justify-content: space-between; background: var(--surface); }
  #terminal { flex: 1; overflow-y: auto; padding: 1.25rem 1.5rem; font-family: var(--font-mono); font-size: 12.5px; line-height: 1.8; white-space: pre-wrap; word-break: break-word; background: var(--bg); }
  #terminal::-webkit-scrollbar { width: 4px; }
  #terminal::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  .ansi-red    { color: var(--blossom); }
  .ansi-green  { color: var(--green); }
  .ansi-yellow { color: var(--yellow); }
  .ansi-cyan   { color: var(--steel); }
  .ansi-bold   { font-weight: 700; color: var(--white); }
  .ansi-dim    { color: var(--steel); opacity: 0.7; }
  .sidebar { display: flex; flex-direction: column; overflow-y: auto; background: var(--surface); }
  .sidebar-section { padding: 1.1rem 1.25rem; border-bottom: 1px solid var(--border); }
  .sidebar-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--steel); margin-bottom: 0.85rem; }
  .score-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .score-card { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 0.85rem 0.75rem; text-align: center; }
  .score-value { font-size: 26px; font-weight: 700; font-family: var(--font-mono); color: var(--steel); }
  .score-value.bad  { color: var(--blossom); }
  .score-value.good { color: var(--green); }
  .score-label { font-size: 11px; color: var(--steel); margin-top: 3px; }
  .trust-rows { display: flex; flex-direction: column; gap: 10px; }
  .trust-row { display: flex; align-items: center; gap: 8px; }
  .trust-label { font-size: 10px; color: var(--steel); width: 68px; flex-shrink: 0; font-family: var(--font-mono); }
  .trust-bar-wrap { flex: 1; height: 5px; background: var(--border); border-radius: 99px; overflow: hidden; }
  .trust-bar { height: 100%; border-radius: 99px; }
  .trust-score { font-size: 10px; font-family: var(--font-mono); width: 28px; text-align: right; flex-shrink: 0; }
  .events { display: flex; flex-direction: column; gap: 6px; }
  .event { background: var(--bg); border: 1px solid var(--border); border-left: 3px solid var(--border); border-radius: 6px; padding: 0.55rem 0.75rem; font-size: 11.5px; line-height: 1.5; opacity: 0; transform: translateY(4px); animation: fadeIn 0.3s ease forwards; }
  @keyframes fadeIn { to { opacity:1; transform:none; } }
  .event-text { color: var(--steel); }
  .event-text strong { color: var(--white); }
  .event.quarantine { border-left-color: var(--blossom); }
  .event.healed     { border-left-color: var(--green); }
  .event.parole     { border-left-color: var(--yellow); }
  .run-btn { display: block; width: calc(100% - 2.5rem); margin: 1.1rem 1.25rem; padding: 0.75rem; background: var(--rose); color: var(--white); border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; font-family: var(--font-sans); }
  .run-btn:hover { opacity: 0.85; }
  .run-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .empty-state { font-size: 11px; color: var(--steel); text-align: center; padding: 0.75rem 0; }
  #error-box { display:none; background:#5a2a2a; border:1px solid var(--blossom); border-radius:6px; padding:0.75rem 1rem; margin:0 1.25rem 1rem; font-size:11px; color:var(--blossom); font-family:var(--font-mono); white-space:pre-wrap; word-break:break-all; }
</style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">IMM</div>
    <div>
      <div class="logo-text">IMMUNE</div>
      <div class="logo-sub">Self-healing memory for AI agents</div>
    </div>
  </div>
  <div class="status">
    <div class="status-dot" id="status-dot"></div>
    <span id="status-text">Ready</span>
  </div>
</header>
<main>
  <div class="terminal-wrap">
    <div class="terminal-head">
      <span>Live output</span>
      <span id="line-count">0 lines</span>
    </div>
    <div id="terminal"><span style="color:var(--steel)">Click Run demo to start...</span></div>
  </div>
  <div class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-label">Accuracy</div>
      <div class="score-cards">
        <div class="score-card">
          <div class="score-value" id="naive-score">--</div>
          <div class="score-label">Naive agent</div>
        </div>
        <div class="score-card">
          <div class="score-value" id="immune-score">--</div>
          <div class="score-label">IMMUNE agent</div>
        </div>
      </div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-label">Trust score decay</div>
      <div class="trust-rows">
        <div class="trust-row">
          <span class="trust-label">planted</span>
          <div class="trust-bar-wrap"><div class="trust-bar" style="width:62%;background:#7ec8a0"></div></div>
          <span class="trust-score" style="color:#7ec8a0">0.62</span>
        </div>
        <div class="trust-row">
          <span class="trust-label">1st fail</span>
          <div class="trust-bar-wrap"><div class="trust-bar" style="width:41%;background:#d4b896"></div></div>
          <span class="trust-score" style="color:#d4b896">0.41</span>
        </div>
        <div class="trust-row">
          <span class="trust-label">2nd fail</span>
          <div class="trust-bar-wrap"><div class="trust-bar" style="width:21%;background:#e2b4bd"></div></div>
          <span class="trust-score" style="color:#e2b4bd">0.21</span>
        </div>
        <div class="trust-row">
          <span class="trust-label">quarantine</span>
          <div class="trust-bar-wrap"><div class="trust-bar" style="width:4%;background:#9b6a6c"></div></div>
          <span class="trust-score" style="color:#9b6a6c">LOCK</span>
        </div>
      </div>
    </div>
    <div class="sidebar-section" style="flex:1">
      <div class="sidebar-label">Events</div>
      <div class="events" id="events">
        <div class="empty-state">Events appear here during the demo</div>
      </div>
    </div>
    <div id="error-box"></div>
    <button class="run-btn" id="run-btn" onclick="runDemo()">Run demo</button>
  </div>
</main>
<script>
const terminal  = document.getElementById('terminal');
const runBtn    = document.getElementById('run-btn');
const statusDot = document.getElementById('status-dot');
const statusTxt = document.getElementById('status-text');
const lineCount = document.getElementById('line-count');
const events    = document.getElementById('events');
const errorBox  = document.getElementById('error-box');
let lines = 0;
let evtSource = null;

function ansiToHtml(text) {
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\x1b\[1m/g,  '<span class="ansi-bold">')
    .replace(/\x1b\[2m/g,  '<span class="ansi-dim">')
    .replace(/\x1b\[91m/g, '<span class="ansi-red">')
    .replace(/\x1b\[92m/g, '<span class="ansi-green">')
    .replace(/\x1b\[93m/g, '<span class="ansi-yellow">')
    .replace(/\x1b\[96m/g, '<span class="ansi-cyan">')
    .replace(/\x1b\[0m/g,  '</span>')
    .replace(/\x1b\[\d+m/g, '');
}

function addEvent(text, cls) {
  if (events.querySelector('.empty-state')) events.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'event ' + cls;
  el.innerHTML = '<span class="event-text">' + text + '</span>';
  events.appendChild(el);
  events.scrollTop = events.scrollHeight;
}

function parseEvents(raw) {
  if (raw.includes('ACCURACY: 1/')) {
    document.getElementById('naive-score').textContent = '1/2';
    document.getElementById('naive-score').className = 'score-value bad';
    addEvent('<strong>Naive agent:</strong> 1/2 -- poison won', '');
  }
  if (raw.includes('ACCURACY: 2/')) {
    document.getElementById('immune-score').textContent = '2/2';
    document.getElementById('immune-score').className = 'score-value good';
    addEvent('<strong>IMMUNE agent:</strong> 2/2 -- culprit quarantined', 'healed');
  }
  if (raw.includes('healed')) {
    addEvent('<strong>Healed</strong> -- counterfactual replay attribution', 'healed');
  }
  if (raw.includes('quarantined') || raw.includes('QUARANTINED')) {
    addEvent('<strong>Quarantined</strong> -- poisoned memory locked out', 'quarantine');
  }
  if (raw.includes('PAROLED')) {
    addEvent('<strong>Paroled</strong> -- offline re-trial passed, released', 'parole');
  }
}

function runDemo() {
  if (evtSource) { evtSource.close(); evtSource = null; }
  terminal.innerHTML = '';
  events.innerHTML = '<div class="empty-state">Running...</div>';
  errorBox.style.display = 'none';
  lines = 0;
  lineCount.textContent = '0 lines';
  document.getElementById('naive-score').textContent = '--';
  document.getElementById('naive-score').className = 'score-value';
  document.getElementById('immune-score').textContent = '--';
  document.getElementById('immune-score').className = 'score-value';
  runBtn.disabled = true;
  runBtn.textContent = 'Running...';
  statusDot.className = 'status-dot running';
  statusTxt.textContent = 'Running...';

  evtSource = new EventSource('/stream');

  evtSource.onmessage = (e) => {
    if (e.data === '__DONE__') {
      evtSource.close(); evtSource = null;
      runBtn.disabled = false;
      runBtn.textContent = 'Run again';
      statusDot.className = 'status-dot done';
      statusTxt.textContent = 'Complete';
      return;
    }
    if (e.data.startsWith('__ERROR__')) {
      errorBox.textContent = e.data.replace('__ERROR__','').trim();
      errorBox.style.display = 'block';
    }
    const html = ansiToHtml(e.data) + '\n';
    terminal.innerHTML += html;
    terminal.scrollTop = terminal.scrollHeight;
    lines++;
    lineCount.textContent = lines + ' lines';
    parseEvents(e.data);
  };

  evtSource.onerror = () => {
    evtSource.close(); evtSource = null;
    runBtn.disabled = false;
    runBtn.textContent = 'Run again';
    statusDot.className = 'status-dot';
    statusTxt.textContent = 'Connection error -- check terminal';
  };
}
</script>
</body>
</html>"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/stream')
def stream():
    def generate():
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        # Add common uv locations to PATH so subprocess can find it
        extra = os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming', 'uv', 'bin')
        env['PATH'] = extra + os.pathsep + env.get('PATH', '')

        try:
            proc = subprocess.Popen(
                [UV, 'run', 'demo.py'],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                bufsize=1,
                encoding='utf-8',
                errors='replace',
            )
        except FileNotFoundError as e:
            yield 'data: __ERROR__ Could not find uv: ' + str(e) + '\n\n'
            yield 'data: __DONE__\n\n'
            return

        for line in proc.stdout:
            stripped = line.rstrip('\n')
            if 'press enter' in stripped.lower():
                continue
            yield 'data: ' + stripped + '\n\n'

        proc.wait()
        if proc.returncode != 0:
            yield 'data: __ERROR__ demo.py exited with code ' + str(proc.returncode) + '\n\n'
        yield 'data: __DONE__\n\n'

    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    print('\n  IMMUNE dashboard')
    print('  UV path: ' + UV)
    print('  Project: ' + str(PROJECT_ROOT))
    print('  Open:    http://localhost:5000\n')
    app.run(debug=False, threaded=True, port=5000)
# this line intentionally blank
