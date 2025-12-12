import os
import logging
import json
import traceback
import re
import time
import random
from datetime import datetime, timedelta
import asyncio
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import PicklePersistence
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram import BotCommand
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from PIL import Image
import io
import tempfile

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Version identifier for deployment verification
BOT_VERSION = "v2025.12.09-rate-limit-fix"

# Print startup banner
print("\n" + "="*60)
print("╔═══════════════════════════════════════════════════════════╗")
print("║       FINANCE BOT - Telegram Bot Keuangan v3.0          ║")
print(f"║       Version: {BOT_VERSION:40s}║")
print("╚═══════════════════════════════════════════════════════════╝")
print("="*60 + "\n")

logger.info(f"🚀 Finance Bot {BOT_VERSION} starting up...")
logger.info(f"📅 Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Configuration
load_dotenv()
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GOOGLE_SHEETS_CREDENTIALS = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv('GOOGLE_SHEETS_CREDENTIALS_JSON')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
AUTHORIZED_USER_IDS = os.getenv('AUTHORIZED_USER_ID', '').split(',')

def _mask(s):
    """Mask sensitive strings showing only first 4 and last 4 chars"""
    if not s:
        return "NOT SET"
    if len(s) <= 8:
        return "****"
    return s[:4] + '...' + s[-4:]

# Enhanced environment variable logging
print("\n🔧 CONFIGURATION CHECK:")
print("-" * 60)

# Check Telegram Token
if TELEGRAM_TOKEN:
    print(f"✅ Telegram Bot Token: {_mask(TELEGRAM_TOKEN)}")
    logger.info(f"✅ TELEGRAM_TOKEN loaded: {_mask(TELEGRAM_TOKEN)}")
else:
    print("❌ Telegram Bot Token: NOT SET")
    logger.error("❌ TELEGRAM_TOKEN not found in environment variables")

# Check Gemini API Key
if GEMINI_API_KEY:
    print(f"✅ Gemini API Key: {_mask(GEMINI_API_KEY)}")
    logger.info(f"✅ GEMINI_API_KEY loaded: {_mask(GEMINI_API_KEY)}")
else:
    print("❌ Gemini API Key: NOT SET")
    logger.error("❌ GEMINI_API_KEY not found in environment variables")

# Check Google Sheets Credentials
creds_method = None
if GOOGLE_SHEETS_CREDENTIALS_JSON:
    creds_method = "JSON from environment"
    print(f"✅ Google Sheets Credentials: {_mask(GOOGLE_SHEETS_CREDENTIALS_JSON[:50])} (JSON/Base64)")
    logger.info(f"✅ GOOGLE_SHEETS_CREDENTIALS_JSON loaded (length: {len(GOOGLE_SHEETS_CREDENTIALS_JSON)} chars)")
elif GOOGLE_SHEETS_CREDENTIALS:
    creds_method = "File path"
    print(f"✅ Google Sheets Credentials: {GOOGLE_SHEETS_CREDENTIALS} (File)")
    logger.info(f"✅ GOOGLE_SHEETS_CREDENTIALS (file): {GOOGLE_SHEETS_CREDENTIALS}")
else:
    print("❌ Google Sheets Credentials: NOT SET")
    logger.warning("⚠️  GOOGLE_SHEETS_CREDENTIALS not found - Google Sheets will be disabled")

# Check Spreadsheet ID
if SPREADSHEET_ID:
    print(f"✅ Spreadsheet ID: {_mask(SPREADSHEET_ID)}")
    logger.info(f"✅ SPREADSHEET_ID loaded: {_mask(SPREADSHEET_ID)}")
else:
    print("❌ Spreadsheet ID: NOT SET")
    logger.warning("⚠️  SPREADSHEET_ID not found")

# Check Authorized Users
if AUTHORIZED_USER_IDS and AUTHORIZED_USER_IDS != ['']:
    print(f"✅ Authorized Users: {len(AUTHORIZED_USER_IDS)} user(s) - {AUTHORIZED_USER_IDS}")
    logger.info(f"✅ AUTHORIZED_USER_IDS loaded: {AUTHORIZED_USER_IDS}")
else:
    print("❌ Authorized Users: NOT SET")
    logger.error("❌ AUTHORIZED_USER_ID not found in environment variables")
    raise ValueError("AUTHORIZED_USER_ID environment variable is not set or empty.")

print("-" * 60 + "\n")

# SPREADSHEET_ID validation - handles both URL and direct ID formats
def validate_spreadsheet_id(spreadsheet_id):
    """Validate and extract spreadsheet ID from URL or direct ID"""
    if not spreadsheet_id:
        return None
    
    # If it's already just an ID (44 characters), return it
    if len(spreadsheet_id) == 44 and not spreadsheet_id.startswith('http'):
        print(f"Using direct SPREADSHEET_ID: {spreadsheet_id}")
        return spreadsheet_id
    
    # If it's a URL, extract the ID
    if 'docs.google.com/spreadsheets/d/' in spreadsheet_id:
        import re
        try:
            spreadsheet_url_pattern = r"/d/([a-zA-Z0-9-_]+)"
            match = re.search(spreadsheet_url_pattern, spreadsheet_id)
            if match:
                extracted_id = match.group(1)
                print(f"Extracted SPREADSHEET_ID from URL: {extracted_id}")
                return extracted_id
        except Exception as e:
            print(f"Error extracting ID from URL: {e}")
    
    # If validation fails, return original (might be valid ID)
    print(f"Using SPREADSHEET_ID as-is: {spreadsheet_id}")
    return spreadsheet_id

# Process SPREADSHEET_ID with better validation
print(f"Using SPREADSHEET_ID: {SPREADSHEET_ID}")

validated_spreadsheet_id = validate_spreadsheet_id(SPREADSHEET_ID)

if not validated_spreadsheet_id:
    print("Warning: Invalid SPREADSHEET_ID. Google Sheets integration disabled.")
    USE_GOOGLE_SHEETS = False
else:
    SPREADSHEET_ID = validated_spreadsheet_id
    USE_GOOGLE_SHEETS = True
    print(f"Final SPREADSHEET_ID: {SPREADSHEET_ID}")

if not SPREADSHEET_ID:
    print("SPREADSHEET_ID not found, using JSON storage only")
    USE_GOOGLE_SHEETS = False


# Configure Gemini API
genai.configure(api_key=GEMINI_API_KEY)

# Model configuration - using gemini-2.0-flash-lite for cost efficiency
# Pricing: Input $0.075/1M tokens, Output $0.30/1M tokens (25% cheaper than flash)
# Supports: text, image, video, audio input
GEMINI_MODEL = 'gemini-2.0-flash-lite'

model = genai.GenerativeModel(GEMINI_MODEL)
# Model with vision capabilities for image analysis (same model, supports multimodal)
vision_model = genai.GenerativeModel(GEMINI_MODEL)

logger.info(f"🤖 Using Gemini model: {GEMINI_MODEL}")

# ============================================================
# RETRY LOGIC WITH EXPONENTIAL BACKOFF
# ============================================================
async def call_gemini_with_retry(generate_func, max_retries=3, base_delay=2):
    """
    Call Gemini API with retry logic and exponential backoff.

    Args:
        generate_func: A callable that returns the Gemini response
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (will be multiplied exponentially)

    Returns:
        The Gemini response or raises the last exception
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            # Call the generate function
            response = generate_func()
            return response
        except Exception as e:
            last_exception = e
            error_str = str(e).lower()

            # Check if it's a rate limit error (429)
            is_rate_limit = (
                '429' in error_str or
                'quota' in error_str or
                'rate' in error_str or
                'resource_exhausted' in error_str or
                'exceeded' in error_str
            )

            if is_rate_limit and attempt < max_retries:
                # Calculate delay with exponential backoff and jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Rate limit hit, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
            elif attempt < max_retries:
                # For other errors, still retry but with shorter delay
                delay = base_delay + random.uniform(0, 1)
                logger.warning(f"Gemini API error: {e}, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Gemini API failed after {max_retries + 1} attempts: {e}")
                raise last_exception

    raise last_exception

# ============================================================
# LOCAL FALLBACK PARSER (untuk format Indonesia: 70k, 50rb, dll)
# ============================================================
def parse_indonesian_amount(text):
    """
    Parse Indonesian number formats locally without AI.
    Supports: 70k, 70K, 50rb, 50ribu, 1jt, 1juta, 1.5jt, dll.

    Returns:
        float or None if no amount found
    """
    text = text.lower().strip()

    # Pattern untuk berbagai format angka Indonesia
    patterns = [
        # Format dengan suffix: 70k, 70K, 50rb, 50ribu, 1jt, 1juta
        (r'(\d+(?:[.,]\d+)?)\s*(?:juta|jt)', 1000000),      # 1jt, 1.5juta
        (r'(\d+(?:[.,]\d+)?)\s*(?:ribu|rb|k)', 1000),       # 50rb, 70k
        # Format dengan titik ribuan: 1.000.000 atau 1,000,000
        (r'(\d{1,3}(?:[.,]\d{3})+)', 1),                     # 1.000.000
        # Format angka biasa
        (r'(\d+)', 1),                                        # 50000
    ]

    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            num_str = match.group(1)
            # Normalize decimal separator
            # Jika ada titik ribuan (e.g., 1.000.000), hapus titik
            if '.' in num_str and num_str.count('.') > 1:
                num_str = num_str.replace('.', '')
            elif ',' in num_str and num_str.count(',') > 1:
                num_str = num_str.replace(',', '')
            # Jika ada satu titik/koma, anggap sebagai desimal
            elif '.' in num_str or ',' in num_str:
                num_str = num_str.replace(',', '.')

            try:
                amount = float(num_str) * multiplier
                return amount
            except ValueError:
                continue

    return None

def parse_transaction_locally(text):
    """
    Parse transaction data locally without AI.
    Fallback ketika Gemini API gagal.

    Returns:
        dict with amount, description, transaction_type, category, date
    """
    text_lower = text.lower()
    current_date = datetime.now()

    # Parse amount
    amount = parse_indonesian_amount(text)

    # Determine transaction type based on keywords
    income_keywords = [
        'terima', 'dapat', 'pemasukan', 'masuk', 'diterima',
        'gaji', 'bonus', 'komisi', 'dividen', 'bunga', 'hadiah',
        'warisan', 'penjualan', 'refund', 'kembalian', 'cashback',
        'dibayar oleh', 'transfer dari', 'kiriman dari', 'diberi', 'dikasih'
    ]

    expense_keywords = [
        'beli', 'bayar', 'belanja', 'pengeluaran', 'keluar', 'dibayar',
        'membeli', 'memesan', 'berlangganan', 'sewa', 'booking',
        'makanan', 'transportasi', 'bensin', 'pulsa', 'tagihan', 'biaya', 'iuran',
        'transfer ke', 'kirim ke', 'buat', 'untuk'
    ]

    is_income = any(kw in text_lower for kw in income_keywords)
    is_expense = any(kw in text_lower for kw in expense_keywords)

    # Default to expense if unclear
    if is_income and not is_expense:
        transaction_type = 'income'
    else:
        transaction_type = 'expense'

    # Determine category
    category_map = {
        'makanan': ['makan', 'food', 'resto', 'warung', 'cafe', 'kopi', 'snack', 'jajan'],
        'transportasi': ['bensin', 'parkir', 'tol', 'ojek', 'grab', 'gojek', 'taxi', 'bus', 'kereta'],
        'belanja': ['belanja', 'beli', 'shopping', 'toko', 'mart', 'alfamart', 'indomaret'],
        'tagihan': ['tagihan', 'listrik', 'air', 'pdam', 'internet', 'wifi', 'pulsa', 'paket data'],
        'kesehatan': ['obat', 'dokter', 'rumah sakit', 'klinik', 'apotek', 'vitamin'],
        'hiburan': ['film', 'bioskop', 'game', 'streaming', 'netflix', 'spotify'],
        'pendidikan': ['buku', 'kursus', 'les', 'sekolah', 'kuliah', 'spp'],
        'iuran': ['iuran', 'arisan', 'sumbangan', 'donasi', 'zakat', 'infaq'],
        'gaji': ['gaji', 'salary', 'upah'],
        'bonus': ['bonus', 'thr', 'insentif'],
    }

    category = 'Lainnya'
    for cat, keywords in category_map.items():
        if any(kw in text_lower for kw in keywords):
            category = cat.capitalize()
            break

    # Parse date from text
    date = current_date.strftime("%Y-%m-%d")
    if 'kemarin' in text_lower or 'yesterday' in text_lower:
        date = (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
    elif 'besok' in text_lower or 'tomorrow' in text_lower:
        date = (current_date + timedelta(days=1)).strftime("%Y-%m-%d")

    # Extract description (remove the amount part)
    description = text
    amount_str = parse_indonesian_amount(text)
    if amount_str:
        # Remove common amount patterns from description
        description = re.sub(r'\d+(?:[.,]\d+)?\s*(?:juta|jt|ribu|rb|k)?', '', text, flags=re.IGNORECASE)
        description = re.sub(r'rp\.?\s*', '', description, flags=re.IGNORECASE)
        description = description.strip()
        if not description:
            description = text

    # Apply sign based on transaction type
    if amount and transaction_type == 'expense':
        amount = -abs(amount)
    elif amount:
        amount = abs(amount)

    return {
        'amount': amount,
        'description': description.strip() if description else text,
        'transaction_type': transaction_type,
        'category': category,
        'date': date
    }

# ============================================================
# CONVERSATION STATE CONSTANTS
# ============================================================
STATE_WAITING_AMOUNT = 'waiting_amount'
STATE_WAITING_CONFIRMATION = 'waiting_confirmation'

# Configure Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Google Sheets credentials handling
def setup_google_sheets_credentials():
    """Setup Google Sheets credentials with proper error handling (supports JSON/Base64 in env, or file path)"""

    # METHOD 1: Try environment variable with JSON/Base64 encoded credentials
    raw = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if raw:
        try:
            credentials_info = json.loads(raw)  # try raw JSON
            creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_info, scope)
            print("✅ Using Google Sheets credentials from environment (JSON)")
            logger.info("✅ Loaded credentials from GOOGLE_SHEETS_CREDENTIALS_JSON (JSON format)")
            return creds
        except json.JSONDecodeError:
            # Try Base64 decoding
            import base64, binascii
            try:
                decoded = base64.b64decode(raw + "===")
                credentials_info = json.loads(decoded.decode("utf-8"))
                creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_info, scope)
                print("✅ Using Google Sheets credentials from environment (Base64)")
                logger.info("✅ Loaded credentials from GOOGLE_SHEETS_CREDENTIALS_JSON (Base64 format)")
                return creds
            except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as e:
                print(f"❌ Error parsing credentials (JSON/Base64): {e}")
                logger.error(f"❌ Error parsing GOOGLE_SHEETS_CREDENTIALS_JSON: {e}")
                # Continue to try other methods
        except Exception as e:
            print(f"❌ Error loading credentials from JSON data: {e}")
            logger.error(f"❌ Error loading credentials from JSON dict: {e}", exc_info=True)
            # Continue to try other methods

    # METHOD 2: Try environment variable with file path
    env_file_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
    if env_file_path and os.path.exists(env_file_path):
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(env_file_path, scope)
            print(f"✅ Using Google Sheets credentials from file: {env_file_path}")
            logger.info(f"✅ Loaded credentials from file (env): {env_file_path}")
            return creds
        except Exception as e:
            print(f"❌ Error loading credentials from file {env_file_path}: {e}")
            logger.error(f"❌ Error loading credentials from {env_file_path}: {e}", exc_info=True)
            # Continue to try other methods

    # METHOD 3: Try common hardcoded file paths (for Docker/GCP deployments)
    print("🔍 Checking common credential file locations...")
    common_paths = [
        "/app/service-account-key.json",          # Docker container path
        "./service-account-key.json",             # Current directory
        "../service-account-key.json",            # Parent directory
        "/root/service-account-key.json",         # Root home directory
        "service-account-key.json",               # Relative path
        os.path.expanduser("~/service-account-key.json")  # User home directory
    ]

    for path in common_paths:
        if os.path.exists(path):
            try:
                file_size = os.path.getsize(path)
                print(f"  ✅ Found: {path} ({file_size} bytes)")
                logger.info(f"  ✅ Found credential file: {path} ({file_size} bytes)")

                creds = ServiceAccountCredentials.from_json_keyfile_name(path, scope)
                print(f"✅ Successfully loaded Google Sheets credentials from: {path}")
                logger.info(f"✅ Successfully loaded credentials from: {path}")
                return creds
            except Exception as e:
                print(f"  ❌ Error loading {path}: {e}")
                logger.error(f"  ❌ Error loading credentials from {path}: {e}", exc_info=True)
                # Continue trying other paths
        else:
            print(f"  ⏭️  Not found: {path}")

    # No credentials found anywhere
    print("⚠️ No Google Sheets credentials found in any location.")
    logger.warning("⚠️ No Google Sheets credentials found - tried env vars and common file paths")
    return None
print("📊 GOOGLE SHEETS SETUP:")
print("-" * 60)
creds = setup_google_sheets_credentials()

if creds is not None:
    try:
        print("🔄 Attempting to authorize with Google Sheets...")
        logger.info("🔄 Authorizing Google Sheets client...")
        client = gspread.authorize(creds)

        print(f"🔄 Opening spreadsheet: {_mask(SPREADSHEET_ID)}...")
        logger.info(f"🔄 Opening spreadsheet ID: {_mask(SPREADSHEET_ID)}")
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1

        USE_GOOGLE_SHEETS = True
        print("✅ Google Sheets integration ENABLED")
        print(f"✅ Connected to spreadsheet: {sheet.title}")
        logger.info(f"✅ Google Sheets integration enabled - Sheet: {sheet.title}")
    except Exception as e:
        print(f"❌ Error connecting to Google Sheets: {e}")
        logger.error(f"❌ Error connecting to Google Sheets: {e}", exc_info=True)
        USE_GOOGLE_SHEETS = False
        sheet = None
        print("⚠️  Google Sheets integration DISABLED")
        logger.warning("⚠️  Google Sheets integration disabled due to connection error")
else:
    USE_GOOGLE_SHEETS = False
    sheet = None
    print("⚠️  Google Sheets integration DISABLED - no valid credentials")
    logger.warning("⚠️  Google Sheets integration disabled - no valid credentials found")

print("-" * 60 + "\n")

# Print final startup status
print("🎯 STARTUP STATUS SUMMARY:")
print("-" * 60)
status_items = [
    ("Telegram Bot", "✅ READY" if TELEGRAM_TOKEN else "❌ FAILED"),
    ("Gemini AI", "✅ READY" if GEMINI_API_KEY else "❌ FAILED"),
    ("Google Sheets", "✅ READY" if USE_GOOGLE_SHEETS else "⚠️  DISABLED"),
    ("Authorized Users", f"✅ {len(AUTHORIZED_USER_IDS)} user(s)" if AUTHORIZED_USER_IDS else "❌ FAILED")
]

for item, status in status_items:
    print(f"  {item:20s}: {status}")

print("-" * 60)

if USE_GOOGLE_SHEETS:
    print("✅ Bot will run in FULL MODE (all features enabled)")
    logger.info("✅ Bot starting in FULL MODE - all features enabled")
else:
    print("⚠️  Bot will run in LIMITED MODE (Google Sheets disabled)")
    logger.warning("⚠️  Bot starting in LIMITED MODE - Google Sheets features disabled")
    print("⚠️  Commands /laporan, /catat, photo receipt scanning will show error")

print("="*60 + "\n")

SPREADSHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"

def is_authorized(user_id):
    """Check if the user is authorized to use the bot."""
    return str(user_id) in AUTHORIZED_USER_IDS

async def sheet_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return
    
    user_name = update.effective_user.first_name
    
    # Create a message with the link
    message = (
        f"📊 *Link Google Sheet Keuangan Anda*\n\n"
        f"Halo {user_name}, berikut adalah link untuk melihat data keuangan Anda:\n\n"
        f"[Buka Google Sheet]({SPREADSHEET_URL})\n\n"
        "Anda dapat melihat semua transaksi dan mengunduh data dalam format Excel/CSV."
    )
    
    # Create button to open the link
    keyboard = [[InlineKeyboardButton("Buka Google Sheet", url=SPREADSHEET_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message, 
        parse_mode='Markdown',
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )

async def delete_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    # Create keyboard with deletion options
    keyboard = [
        [InlineKeyboardButton("Hapus Transaksi Terakhir", callback_data="delete_last")],
        [InlineKeyboardButton("Hapus Transaksi Tertentu", callback_data="delete_specific")],
        [InlineKeyboardButton("Hapus Berdasarkan Tanggal", callback_data="delete_date")],
        [InlineKeyboardButton("Hapus Semua Data", callback_data="delete_all")],
        [InlineKeyboardButton("❌ Batal", callback_data="delete_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🗑️ *Hapus Data Keuangan*\n\n"
        f"Halo {user_name}, pilih opsi penghapusan data:\n\n"
        "⚠️ *Perhatian:* Data yang dihapus tidak dapat dikembalikan!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
async def delete_transaction_messages(context: ContextTypes.DEFAULT_TYPE):
    """Delete transaction-related messages after a delay."""
    job_data = context.job.data
    chat_id = job_data['chat_id']
    user_id = job_data['user_id']
    
    # Get the user data
    user_data = context.application.user_data.get(user_id, {})
    
    # Check if message deletion is enabled
    if not user_data.get('delete_messages', True):
        return
    
    # Get the list of message IDs to delete
    messages_to_delete = user_data.get('messages_to_delete', [])
    
    if not messages_to_delete:
        return
    
    # Delete each message
    for message_id in messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.error(f"Error deleting message {message_id}: {e}")
    
    # Clear the list of messages to delete
    context.application.user_data[user_id]['messages_to_delete'] = []

async def toggle_delete_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return
    
    # Toggle the setting
    if 'delete_messages' not in context.user_data:
        context.user_data['delete_messages'] = True
    else:
        context.user_data['delete_messages'] = not context.user_data['delete_messages']
    
    # Inform the user of the current setting
    status = "AKTIF" if context.user_data['delete_messages'] else "NONAKTIF"
    
    await update.message.reply_text(
        f"🗑️ Penghapusan pesan otomatis: {status}\n\n"
        f"{'Pesan akan dihapus otomatis setelah transaksi dicatat.' if context.user_data['delete_messages'] else 'Pesan tidak akan dihapus otomatis.'}"
    )

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id

    # Check authorization
    if not is_authorized(user_id):
        await query.answer("Anda tidak memiliki akses untuk menggunakan bot ini.", show_alert=True)
        return

    await query.answer()
    action = query.data.split("_")[1]


    if action == "cancel":
        await query.edit_message_text("❌ Penghapusan data dibatalkan.")
        return

    # Check if Google Sheets is available (for all delete operations)
    if not sheet or not USE_GOOGLE_SHEETS:
        await query.edit_message_text(
            "❌ *Google Sheets Tidak Aktif*\n\n"
            "Fitur penghapusan data tidak tersedia karena Google Sheets tidak terhubung.\n\n"
            "📞 Hubungi administrator untuk setup credentials.",
            parse_mode='Markdown'
        )
        logger.error(f"Google Sheets not available - cannot delete records (USE_GOOGLE_SHEETS={USE_GOOGLE_SHEETS})")
        return

    elif action == "last":
        # Delete the last transaction for this user
        all_records = sheet.get_all_records()
        user_records = [record for record in all_records if str(record.get('User ID')) == str(user_id)]
        
        if not user_records:
            await query.edit_message_text("❌ Tidak ada transaksi untuk dihapus.")
            return
        
        # Find the last transaction's row
        last_record = user_records[-1]
        all_values = sheet.get_all_values()
        header = all_values[0]  # First row is header
        
        # Find the row index of the last transaction
        row_index = None
        for i, row in enumerate(all_values[1:], start=2):  # Start from 2 because row 1 is header
            record = dict(zip(header, row))
            if (str(record.get('User ID')) == str(user_id) and 
                record.get('Timestamp') == last_record.get('Timestamp')):
                row_index = i
                break
        
        if row_index:
            # Delete the row
            sheet.delete_rows(row_index)
            
            # Show confirmation with details of deleted transaction
            amount = float(last_record.get('Amount', 0))
            transaction_type = "Pemasukan" if amount > 0 else "Pengeluaran"
            
            await query.edit_message_text(
                "✅ Transaksi terakhir berhasil dihapus!\n\n"
                f"Jenis: {transaction_type}\n"
                f"Jumlah: Rp {abs(amount):,.0f}\n"
                f"Kategori: {last_record.get('Category', 'Lainnya')}\n"
                f"Deskripsi: {last_record.get('Description', '')}\n"
                f"Tanggal: {last_record.get('Date', '')}"
            )
        else:
            await query.edit_message_text("❌ Tidak dapat menemukan transaksi terakhir.")
    
    elif action == "specific":
        # Show recent transactions for selection
        all_records = sheet.get_all_records()
        user_records = [record for record in all_records if str(record.get('User ID')) == str(user_id)]
        
        if not user_records:
            await query.edit_message_text("❌ Tidak ada transaksi untuk dihapus.")
            return
        
        # Get the last 5 transactions (or fewer if there aren't 5)
        recent_transactions = user_records[-5:] if len(user_records) >= 5 else user_records
        
        # Create buttons for each transaction
        keyboard = []
        for i, transaction in enumerate(recent_transactions):
            amount = float(transaction.get('Amount', 0))
            transaction_type = "➕" if amount > 0 else "➖"
            date = transaction.get('Date', '')
            description = transaction.get('Description', '')
            # Truncate description if too long
            if len(description) > 20:
                description = description[:17] + "..."
            
            # Create a button with transaction info
            label = f"{date}: {transaction_type} Rp{abs(amount):,.0f} - {description}"
            # Truncate label if too long
            if len(label) > 64:  # Telegram button label limit
                label = label[:61] + "..."
            
            keyboard.append([InlineKeyboardButton(label, callback_data=f"del_specific_{i}")])
        
        # Add a cancel button
        keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="delete_cancel")])
        
        # Store the transactions in context for later reference
        context.user_data['recent_transactions'] = recent_transactions
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Pilih transaksi yang ingin dihapus:",
            reply_markup=reply_markup
        )
    
    elif action == "date":
        # Ask for date range
        context.user_data['delete_state'] = 'awaiting_start_date'
        
        await query.edit_message_text(
            "📅 *Hapus Berdasarkan Tanggal*\n\n"
            "Masukkan tanggal awal (format: YYYY-MM-DD):\n"
            "Contoh: 2023-05-01\n\n"
            "💡 Ketik 'batal' untuk membatalkan atau gunakan /hapus untuk command lain",
            parse_mode='Markdown'
        )
    
    elif action == "all":
        # Ask for confirmation before deleting all
        keyboard = [
            [InlineKeyboardButton("✅ Ya, Hapus Semua", callback_data="confirm_delete_all")],
            [InlineKeyboardButton("❌ Tidak, Batalkan", callback_data="delete_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⚠️ *PERINGATAN*\n\n"
            "Anda akan menghapus SEMUA data keuangan Anda.\n"
            "Tindakan ini TIDAK DAPAT DIBATALKAN.\n\n"
            "Apakah Anda yakin ingin melanjutkan?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
async def process_multiple_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE, transactions):
    """Process multiple transactions and ask for confirmation."""
    user_id = update.effective_user.id
    
    # Create a summary of the transactions
    confirmation_message = f"📝 *{len(transactions)} Transaksi Terdeteksi*\n\n"
    
    # Make a deep copy of the transactions to avoid reference issues
    processed_transactions = []
    
    for i, transaction in enumerate(transactions, 1):
        # Create a new dictionary for each transaction to avoid reference issues
        processed_transaction = {
            'amount': float(transaction.get('amount', 0)),  # Ensure amount is a float
            'category': str(transaction.get('category', 'Lainnya')),  # Ensure category is a string
            'description': str(transaction.get('description', f'Transaksi {i}')),  # Ensure description is a string
            'date': str(transaction.get('date', datetime.now().strftime("%Y-%m-%d")))  # Ensure date is a string
        }
        
        # Add to processed transactions
        processed_transactions.append(processed_transaction)
        
        # Transaction type for display
        transaction_type = "Pemasukan" if processed_transaction['amount'] > 0 else "Pengeluaran"
        
        # Format the date for display
        try:
            display_date = datetime.strptime(processed_transaction['date'], "%Y-%m-%d").strftime("%d/%m/%Y")
        except:
            display_date = processed_transaction['date']
        
        confirmation_message += f"*Transaksi {i}:*\n"
        confirmation_message += f"Tanggal: {display_date}\n"
        confirmation_message += f"Jenis: {transaction_type}\n"
        confirmation_message += f"Jumlah: Rp {abs(processed_transaction['amount']):,.0f}\n"
        confirmation_message += f"Kategori: {processed_transaction['category']}\n"
        confirmation_message += f"Deskripsi: {processed_transaction['description']}\n\n"
    
    confirmation_message += "Apakah semua transaksi ini benar?"
    
    # Print for debugging
    print(f"Storing {len(processed_transactions)} transactions in context")
    for i, t in enumerate(processed_transactions):
        print(f"Transaction {i+1}: {t}")
    
    # Save processed transactions in context with a clear key
    context.user_data['pending_multiple_transactions'] = processed_transactions.copy()
    
    # Create confirmation buttons
    keyboard = [
        [InlineKeyboardButton("✅ Benar Semua", callback_data="confirm_all_yes"),
         InlineKeyboardButton("❌ Batal", callback_data="confirm_all_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send confirmation message and store its ID
    conf_message = await update.message.reply_text(
        confirmation_message, 
        reply_markup=reply_markup, 
        parse_mode='Markdown'
    )
    
    # Add the confirmation message ID to the list for deletion
    if 'messages_to_delete' not in context.user_data:
        context.user_data['messages_to_delete'] = []
    context.user_data['messages_to_delete'].append(conf_message.message_id)
    
async def multiple_transactions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation for multiple transactions."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Check authorization
    if not is_authorized(user_id):
        await query.answer("Anda tidak memiliki akses untuk menggunakan bot ini.", show_alert=True)
        return
    
    await query.answer()
    
    if query.data == "confirm_all_yes":
        # Get the pending transactions
        transactions = context.user_data.get('pending_multiple_transactions', [])

        if not transactions:
            await query.edit_message_text("❌ Terjadi kesalahan. Tidak ada transaksi untuk disimpan.")
            return

        # Check if Google Sheets is available
        if not sheet or not USE_GOOGLE_SHEETS:
            await query.edit_message_text(
                "❌ *Google Sheets Tidak Aktif*\n\n"
                "Tidak dapat menyimpan transaksi karena Google Sheets tidak terhubung.\n\n"
                "📞 Hubungi administrator untuk setup credentials.",
                parse_mode='Markdown'
            )
            logger.error(f"Google Sheets not available - cannot save multiple transactions (USE_GOOGLE_SHEETS={USE_GOOGLE_SHEETS})")
            return

        # Show processing message
        processing_message = await query.edit_message_text(f"⏳ Menyimpan {len(transactions)} transaksi...")

        # Record all transactions to the sheet
        success_count = 0
        for transaction in transactions:
            try:
                # Prepare row data
                row_data = [
                    transaction.get('date', datetime.now().strftime("%Y-%m-%d")),
                    transaction.get('amount', 0),
                    transaction.get('category', 'Lainnya'),
                    transaction.get('description', ''),
                    user_id,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ]
                
                # Append to Google Sheet
                sheet.append_row(row_data)
                success_count += 1
                
                # Add a small delay between insertions
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error recording transaction: {e}", exc_info=True)
        
        # Generate category summary
        category_summary = generate_category_summary(transactions, "💰 RINGKASAN KATEGORI")

        # Clear the pending transactions
        context.user_data.pop('pending_multiple_transactions', None)

        # Send confirmation message with category summary
        confirmation_text = (
            f"✅ {success_count} dari {len(transactions)} transaksi berhasil dicatat!\n\n"
            f"{category_summary}\n\n"
            f"Gunakan /laporan untuk melihat ringkasan keuangan Anda."
        )

        await query.edit_message_text(
            confirmation_text,
            parse_mode='Markdown'
        )

        # Don't delete this message - keep category summary visible permanently
    
    elif query.data == "confirm_all_no":
        # Clear the pending transactions
        context.user_data.pop('pending_multiple_transactions', None)
        
        await query.edit_message_text(
            "❌ Pencatatan transaksi dibatalkan."
        )

async def delete_specific_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Check if Google Sheets is available
    if not sheet or not USE_GOOGLE_SHEETS:
        await query.edit_message_text(
            "❌ *Google Sheets Tidak Aktif*\n\n"
            "Fitur ini memerlukan Google Sheets yang tidak terhubung.\n\n"
            "📞 Hubungi administrator untuk setup credentials.",
            parse_mode='Markdown'
        )
        logger.error("Google Sheets not available - cannot delete specific transaction")
        return

    # Extract the index from the callback data
    index = int(query.data.split("_")[2])

    # Get the transaction from stored context
    if 'recent_transactions' not in context.user_data or index >= len(context.user_data['recent_transactions']):
        await query.edit_message_text("❌ Terjadi kesalahan. Silakan coba lagi.")
        return

    transaction = context.user_data['recent_transactions'][index]

    # Find the row to delete
    all_values = sheet.get_all_values()
    header = all_values[0]  # First row is header
    
    # Find the row index of the transaction
    row_index = None
    for i, row in enumerate(all_values[1:], start=2):  # Start from 2 because row 1 is header
        record = dict(zip(header, row))
        if (str(record.get('User ID')) == str(user_id) and 
            record.get('Timestamp') == transaction.get('Timestamp')):
            row_index = i
            break
    
    if row_index:
        # Delete the row
        sheet.delete_rows(row_index)
        
        # Show confirmation with details of deleted transaction
        amount = float(transaction.get('Amount', 0))
        transaction_type = "Pemasukan" if amount > 0 else "Pengeluaran"
        
        await query.edit_message_text(
            "✅ Transaksi berhasil dihapus!\n\n"
            f"Jenis: {transaction_type}\n"
            f"Jumlah: Rp {abs(amount):,.0f}\n"
            f"Kategori: {transaction.get('Category', 'Lainnya')}\n"
            f"Deskripsi: {transaction.get('Description', '')}\n"
            f"Tanggal: {transaction.get('Date', '')}"
        )
    else:
        await query.edit_message_text("❌ Tidak dapat menemukan transaksi yang dipilih.")

# Handle date input for deletion
async def handle_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Check if we're in the date deletion flow
    if 'delete_state' not in context.user_data:
        return
    
    delete_state = context.user_data['delete_state']

    # Check if user wants to cancel
    if message_text.lower() in ['batal', 'cancel', 'batalkan']:
        # Clear delete state
        context.user_data.pop('delete_state', None)
        context.user_data.pop('start_date', None)
        context.user_data.pop('records_to_delete', None)
        await update.message.reply_text("❌ Proses hapus berdasarkan tanggal dibatalkan.")
        return

    # Validate date format (YYYY-MM-DD)
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', message_text):
        await update.message.reply_text(
            "❌ Format tanggal tidak valid. Gunakan format YYYY-MM-DD.\n"
            "Contoh: 2023-05-01\n\n"
            "Silakan coba lagi atau ketik 'batal' untuk membatalkan:"
        )
        return
    
    if delete_state == 'awaiting_start_date':
        # Store start date and ask for end date
        context.user_data['start_date'] = message_text
        context.user_data['delete_state'] = 'awaiting_end_date'
        
        await update.message.reply_text(
            "📅 Masukkan tanggal akhir (format: YYYY-MM-DD):\n"
            "Contoh: 2023-05-31"
        )
    
    elif delete_state == 'awaiting_end_date':
        start_date = context.user_data['start_date']
        end_date = message_text

        # Validate that end date is after start date
        if end_date < start_date:
            await update.message.reply_text(
                "❌ Tanggal akhir harus setelah tanggal awal.\n"
                "Silakan masukkan tanggal akhir yang valid:"
            )
            return

        # Check if Google Sheets is available
        if not sheet or not USE_GOOGLE_SHEETS:
            await update.message.reply_text(
                "❌ Google Sheets tidak terhubung.\n"
                "Silakan hubungi administrator untuk mengaktifkan integrasi Google Sheets."
            )
            logger.error("Google Sheets not available - cannot delete by date")
            # Clear delete state
            context.user_data.pop('delete_state', None)
            context.user_data.pop('start_date', None)
            return

        # Get all records
        all_records = sheet.get_all_records()
        
        # Filter records by user ID and date range
        user_records_in_range = [
            record for record in all_records 
            if str(record.get('User ID')) == str(user_id) and 
               start_date <= record.get('Date', '') <= end_date
        ]
        
        if not user_records_in_range:
            await update.message.reply_text(
                "❌ Tidak ada transaksi dalam rentang tanggal tersebut."
            )
            # Clear delete state
            context.user_data.pop('delete_state', None)
            context.user_data.pop('start_date', None)
            return
        
        # Ask for confirmation
        context.user_data['records_to_delete'] = user_records_in_range
        
        # Create confirmation message
        confirmation_message = (
            f"🗑️ *Konfirmasi Penghapusan*\n\n"
            f"Anda akan menghapus {len(user_records_in_range)} transaksi "
            f"dari {start_date} hingga {end_date}.\n\n"
            "Apakah Anda yakin ingin melanjutkan?"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Ya, Hapus", callback_data="confirm_delete_date")],
            [InlineKeyboardButton("❌ Tidak, Batalkan", callback_data="delete_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            confirmation_message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    action = query.data.split("_")[2]  # confirm_delete_all or confirm_delete_date

    # Check if Google Sheets is available
    if not sheet or not USE_GOOGLE_SHEETS:
        await query.edit_message_text(
            "❌ *Google Sheets Tidak Aktif*\n\n"
            "Fitur ini memerlukan Google Sheets yang tidak terhubung.\n\n"
            "📞 Hubungi administrator untuk setup credentials.",
            parse_mode='Markdown'
        )
        logger.error("Google Sheets not available - cannot confirm delete")
        return

    if action == "all":
        # Delete all transactions for this user
        all_values = sheet.get_all_values()
        header = all_values[0]  # First row is header
        
        # Find all rows to delete (in reverse order to avoid index shifting)
        rows_to_delete = []
        for i, row in enumerate(all_values[1:], start=2):  # Start from 2 because row 1 is header
            record = dict(zip(header, row))
            if str(record.get('User ID')) == str(user_id):
                rows_to_delete.append(i)
        
        # Delete rows in reverse order
        for row_index in sorted(rows_to_delete, reverse=True):
            sheet.delete_rows(row_index)
        
        await query.edit_message_text(
            "✅ Semua transaksi Anda telah dihapus.\n\n"
            f"Total {len(rows_to_delete)} transaksi telah dihapus."
        )
    
    elif action == "date":
        if 'records_to_delete' not in context.user_data:
            await query.edit_message_text("❌ Terjadi kesalahan. Silakan coba lagi.")
            return
        
        records_to_delete = context.user_data['records_to_delete']
        
        # Find all rows to delete (in reverse order)
        all_values = sheet.get_all_values()
        header = all_values[0]  # First row is header
        
        # Find the row indices of the transactions to delete
        rows_to_delete = []
        for record_to_delete in records_to_delete:
            for i, row in enumerate(all_values[1:], start=2):  # Start from 2 because row 1 is header
                record = dict(zip(header, row))
                if (str(record.get('User ID')) == str(user_id) and 
                    record.get('Timestamp') == record_to_delete.get('Timestamp')):
                    rows_to_delete.append(i)
                    break
        
        # Delete rows in reverse order
        for row_index in sorted(rows_to_delete, reverse=True):
            sheet.delete_rows(row_index)
        
        # Clear delete state
        context.user_data.pop('delete_state', None)
        context.user_data.pop('start_date', None)
        context.user_data.pop('records_to_delete', None)
        
        await query.edit_message_text(
            "✅ Transaksi dalam rentang tanggal telah dihapus.\n\n"
            f"Total {len(rows_to_delete)} transaksi telah dihapus."
        )

from datetime import datetime, timedelta

# Category emoji mapping for better visual summary
CATEGORY_EMOJIS = {
    # Food categories
    'Makanan': '🍽️',
    'Protein': '🍗',
    'Sayur': '🥬',
    'Buah': '🍍',
    'Minuman': '🥤',
    'Snack': '🍿',
    'Bumbu': '🧄',
    'Roti': '🍞',
    'Nasi': '🍚',
    'Mie': '🍜',
    'Daging': '🥩',
    'Seafood': '🦐',
    'Susu': '🥛',

    # Transportation
    'Transportasi': '🚗',
    'Bensin': '⛽',
    'Parkir': '🅿️',
    'Ojek': '🏍️',
    'Bus': '🚌',
    'Kereta': '🚊',

    # Shopping
    'Belanja': '🛒',
    'Pakaian': '👕',
    'Elektronik': '📱',
    'Kosmetik': '💄',
    'Obat': '💊',
    'Vitamin': '💊',

    # Bills & Services
    'Tagihan': '🧾',
    'Listrik': '💡',
    'Air': '💧',
    'Internet': '📶',
    'Pulsa': '📞',
    'Gas': '🔥',

    # Entertainment
    'Hiburan': '🎬',
    'Bioskop': '🎭',
    'Game': '🎮',
    'Musik': '🎵',
    'Olahraga': '⚽',

    # Health
    'Kesehatan': '🏥',
    'Dokter': '👨‍⚕️',
    'Rumah Sakit': '🏥',

    # Education
    'Pendidikan': '📚',
    'Buku': '📖',
    'Kursus': '🎓',

    # Income categories
    'Gaji': '💰',
    'Bonus': '🎁',
    'Investasi': '📈',
    'Hadiah': '🎉',
    'Penjualan': '💸',
    'Bisnis': '💼',

    # Default
    'Lainnya': '🍜',
}

def get_category_emoji(category):
    """Get emoji for a category, with fallback to default"""
    return CATEGORY_EMOJIS.get(category, '🍜')

def format_rupiah(amount):
    """Format amount with dots as thousand separators (Indonesian style)"""
    return f"{amount:,.0f}".replace(',', '.')

def generate_category_summary(transactions, title="💰 RINGKASAN KATEGORI"):
    """
    Generate a beautiful category summary with emojis
    transactions: list of dict with 'category', 'amount', 'description' keys
    """
    if not transactions:
        return ""

    # Group transactions by category
    category_totals = {}
    category_items = {}

    for transaction in transactions:
        category = transaction.get('category', 'Lainnya')
        amount = abs(float(transaction.get('amount', 0)))
        description = transaction.get('description', 'Item')

        # Initialize category if not exists
        if category not in category_totals:
            category_totals[category] = 0
            category_items[category] = []

        # Add to totals and items
        category_totals[category] += amount
        category_items[category].append({
            'description': description,
            'amount': amount
        })

    # Build summary message
    summary_lines = [f"\n{title}\n"]

    # Sort categories by total amount (descending)
    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)

    grand_total = 0

    for category, total in sorted_categories:
        emoji = get_category_emoji(category)

        # Category header
        summary_lines.append(f"{emoji} *{category}*")

        # List items in this category
        items = category_items[category]

        # Sort items by amount (descending) and limit to prevent very long messages
        sorted_items = sorted(items, key=lambda x: x['amount'], reverse=True)[:10]  # Max 10 items per category

        for item in sorted_items:
            item_desc = item['description']
            # Clean up description (remove store name, category duplicates)
            if ' di ' in item_desc:
                item_desc = item_desc.split(' di ')[0]
            if category.lower() in item_desc.lower():
                item_desc = item_desc.replace(category, '').strip()
            if item_desc.startswith('Belanja '):
                item_desc = item_desc.replace('Belanja ', '')

            # Truncate if too long
            if len(item_desc) > 30:
                item_desc = item_desc[:27] + "..."

            summary_lines.append(f" • {item_desc} = {format_rupiah(item['amount'])}")

        # Show if there are more items
        if len(category_items[category]) > 10:
            remaining = len(category_items[category]) - 10
            summary_lines.append(f" • ... dan {remaining} item lainnya")

        # Category subtotal
        summary_lines.append(f"*Subtotal {category} = {format_rupiah(total)}*\n")
        grand_total += total

    # Grand total
    summary_lines.append("⸻\n")
    summary_lines.append("💰 *Total Keseluruhan*\n")
    summary_lines.append(f"*{format_rupiah(grand_total)} rupiah*")

    return "\n".join(summary_lines)

# Function to analyze receipt image using Gemini Vision
async def analyze_receipt_image(image_file):
    """Analyze receipt image using Gemini Vision API with retry logic."""
    # Current date for reference
    current_date = datetime.now()

    # Create prompt for receipt analysis
    prompt = f"""
    Analyze this receipt/invoice image and extract ALL financial transactions found.
    Today's date is {current_date.strftime("%Y-%m-%d")} ({current_date.strftime("%A, %d %B %Y")}).

    For each item/transaction found in the receipt, provide:
    1. The item name or description
    2. The amount/price
    3. The quantity (if applicable)
    4. The subtotal for that item

    Return a JSON object with:
    - "store_name": name of the store/merchant (if visible)
    - "receipt_date": date on the receipt in YYYY-MM-DD format (if visible, otherwise use today's date)
    - "receipt_time": time on the receipt (if visible)
    - "total_amount": the grand total amount on the receipt
    - "payment_method": cash/card/transfer/etc (if visible)
    - "items": array of items, each containing:
        - "description": item name/description
        - "quantity": quantity purchased (default 1 if not shown)
        - "unit_price": price per unit
        - "amount": total price for this item
        - "category": suggested category (Makanan/Minuman/Belanja/etc)
    - "tax": tax amount (if shown)
    - "discount": discount amount (if shown)
    - "transaction_type": always "expense" for receipts
    - "suggested_description": a brief summary of the purchase for record keeping

    Important instructions:
    - Extract ALL items listed on the receipt, not just the total
    - If the receipt is not clear, still try to extract what you can see
    - For Indonesian receipts, handle both "Rp" and numeric formats
    - Convert all amounts to numeric values only (no currency symbols)
    - If you cannot read the receipt clearly, return null for unclear fields
    - Common Indonesian store names: Indomaret, Alfamart, Transmart, Hypermart, etc.
    - Common categories: Makanan, Minuman, Snack, Kebutuhan Harian, Obat, etc.
    """

    try:
        # Use retry logic for Gemini API call
        response = await call_gemini_with_retry(
            lambda: vision_model.generate_content([prompt, image_file]),
            max_retries=3,
            base_delay=3
        )

        try:
            # Extract JSON from response
            response_text = response.text
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].strip()
            else:
                json_str = response_text.strip()

            receipt_data = json.loads(json_str)

            # Process the receipt data
            if receipt_data:
                # Ensure we have a date
                if not receipt_data.get('receipt_date'):
                    receipt_data['receipt_date'] = current_date.strftime("%Y-%m-%d")

                # Calculate total if not provided but items exist
                if not receipt_data.get('total_amount') and receipt_data.get('items'):
                    total = sum(float(item.get('amount', 0)) for item in receipt_data['items'])
                    if receipt_data.get('tax'):
                        total += float(receipt_data.get('tax', 0))
                    if receipt_data.get('discount'):
                        total -= float(receipt_data.get('discount', 0))
                    receipt_data['total_amount'] = total

                return receipt_data

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON from Gemini response: {e}")
            return {
                "error": "Tidak dapat memproses struk dengan benar. Coba lagi dengan foto yang lebih jelas.",
                "raw_response": response_text[:500]
            }

    except Exception as e:
        error_str = str(e).lower()
        logger.error(f"Error analyzing receipt image: {e}", exc_info=True)

        # Check if it's a rate limit error after all retries
        if '429' in error_str or 'quota' in error_str or 'exceeded' in error_str:
            return {
                "error": "⏳ Layanan AI sedang sibuk (rate limit). Silakan coba lagi dalam beberapa menit.\n\n💡 Tips: Anda juga bisa catat transaksi manual dengan format:\nContoh: 'Belanja Indomaret 150000'"
            }
        else:
            return {
                "error": f"Gagal menganalisis gambar: {str(e)}"
            }

# Enhanced helper function to parse financial data using Gemini with improved income/expense detection
async def parse_financial_data(text):
    """
    Parse financial data from text using Gemini AI with retry and local fallback.

    Flow:
    1. Try Gemini API with retry logic
    2. If Gemini fails, use local parser as fallback
    """
    # Current date for reference
    current_date = datetime.now()

    # First, try local parsing to get basic amount (for fallback and validation)
    local_result = parse_transaction_locally(text)

    # Try Gemini API with retry
    try:
        # Extract financial information using Gemini
        prompt = f"""
        Extract financial information from this Indonesian text: "{text}"
        Today's date is {current_date.strftime("%Y-%m-%d")} ({current_date.strftime("%A, %d %B %Y")}).

        Return a JSON object with these fields:
        - amount: the monetary amount (numeric value only, without currency symbols). For Indonesian formats like "70k" or "70rb" convert to 70000, "1jt" to 1000000.
        - category: the spending/income category
        - description: brief description of the transaction
        - transaction_type: "income" if this is money received, or "expense" if this is money spent
        - date: the date of the transaction in YYYY-MM-DD format
        - time_context: any time-related information found in the text (e.g., "yesterday", "last Monday", "2 days ago")

        For the date field, analyze time expressions carefully:

        1. Specific dates:
           - "5 Mei 2023", "05/05/2023", "5 May 2023" → use that exact date
           - "5 Mei", "05/05" → use that date in the current year

        2. Relative days:
           - "kemarin", "yesterday" → use yesterday's date ({(current_date - timedelta(days=1)).strftime("%Y-%m-%d")})
           - "hari ini", "today", "sekarang" → use today's date ({current_date.strftime("%Y-%m-%d")})
           - "besok", "tomorrow" → use tomorrow's date ({(current_date + timedelta(days=1)).strftime("%Y-%m-%d")})
           - "lusa", "day after tomorrow" → use the day after tomorrow ({(current_date + timedelta(days=2)).strftime("%Y-%m-%d")})
           - "2 hari yang lalu", "2 days ago" → subtract the specified number of days
           - "minggu lalu", "last week" → subtract 7 days
           - "bulan lalu", "last month" → use the same day in the previous month

         3. Day names:
           - "Senin", "Monday" → use the date of the most recent Monday
           - "Senin lalu", "last Monday" → use the date of the previous Monday (not today if today is Monday)
           - "Senin depan", "next Monday" → use the date of the next Monday (not today if today is Monday)

        4. Month references:
           - "awal bulan", "beginning of the month" → use the 1st day of the current month
           - "akhir bulan", "end of the month" → use the last day of the current month
           - "pertengahan bulan", "middle of the month" → use the 15th day of the current month
           - "awal bulan lalu", "beginning of last month" → use the 1st day of the previous month

        If no date is mentioned, use today's date ({current_date.strftime("%Y-%m-%d")}).

        For transaction_type, analyze the context carefully using these rules:

        INCOME indicators (set transaction_type to "income"):
        - Words about receiving money: "terima", "dapat", "pemasukan", "masuk", "diterima"
        - Income sources: "gaji", "bonus", "komisi", "dividen", "bunga", "hadiah", "warisan", "penjualan", "refund", "kembalian", "cashback"
        - Phrases like: "dibayar oleh", "transfer dari", "kiriman dari", "diberi", "dikasih"

        EXPENSE indicators (set transaction_type to "expense"):
        - Words about spending: "beli", "bayar", "belanja", "pengeluaran", "keluar", "dibayar"
        - Purchase verbs: "membeli", "memesan", "berlangganan", "sewa", "booking"
        - Expense categories: "makanan", "transportasi", "bensin", "pulsa", "tagihan", "biaya", "iuran"
        - Phrases like: "dibayarkan untuk", "transfer ke", "kirim ke"

        If the text doesn't clearly indicate transaction type, look at the context:
        - If it mentions purchasing an item or service, it's likely an expense
        - If it mentions receiving money or payment, it's likely income

        If still unclear, default to "expense".

        For category, try to identify specific categories like:
        - Income categories: "Gaji", "Bonus", "Investasi", "Hadiah", "Penjualan", "Bisnis"
        - Expense categories: "Makanan", "Transportasi", "Belanja", "Hiburan", "Tagihan", "Kesehatan", "Pendidikan"

        If any field is unclear, set it to null.
        """

        # Use retry logic for Gemini API call
        response = await call_gemini_with_retry(
            lambda: model.generate_content(prompt),
            max_retries=2,
            base_delay=2
        )

        try:
            # Extract JSON from response
            response_text = response.text
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].strip()
            else:
                json_str = response_text.strip()

            data = json.loads(json_str)

            # Process the date field - if Gemini couldn't determine it, try to parse it ourselves
            if not data.get('date') and data.get('time_context'):
                time_context = data.get('time_context').lower()

                # Handle common time expressions
                if any(word in time_context for word in ["kemarin", "yesterday"]):
                    data['date'] = (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
                elif any(word in time_context for word in ["besok", "tomorrow"]):
                    data['date'] = (current_date + timedelta(days=1)).strftime("%Y-%m-%d")
                elif any(word in time_context for word in ["lusa", "day after tomorrow"]):
                    data['date'] = (current_date + timedelta(days=2)).strftime("%Y-%m-%d")
                elif "hari yang lalu" in time_context or "days ago" in time_context:
                    try:
                        days_ago = int(re.search(r'(\d+)', time_context).group(1))
                        data['date'] = (current_date - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                    except:
                        pass
                elif "minggu lalu" in time_context or "last week" in time_context:
                    data['date'] = (current_date - timedelta(days=7)).strftime("%Y-%m-%d")

                # Handle day names
                day_names = {
                    "senin": 0, "monday": 0,
                    "selasa": 1, "tuesday": 1,
                    "rabu": 2, "wednesday": 2,
                    "kamis": 3, "thursday": 3,
                    "jumat": 4, "friday": 4,
                    "sabtu": 5, "saturday": 5,
                    "minggu": 6, "sunday": 6
                }

                for day_name, day_num in day_names.items():
                    if day_name in time_context:
                        days_diff = (current_date.weekday() - day_num) % 7
                        if days_diff == 0:
                            if "lalu" in time_context or "last" in time_context:
                                days_diff = 7

                        if "depan" in time_context or "next" in time_context:
                            days_diff = (day_num - current_date.weekday()) % 7
                            if days_diff == 0:
                                days_diff = 7
                            data['date'] = (current_date + timedelta(days=days_diff)).strftime("%Y-%m-%d")
                        else:
                            data['date'] = (current_date - timedelta(days=days_diff)).strftime("%Y-%m-%d")

                        break

            # If still no date, use today's date
            if not data.get('date'):
                data['date'] = current_date.strftime("%Y-%m-%d")

            # Additional processing for amount and transaction type
            if data.get('amount') is not None:
                amount = abs(float(data.get('amount')))
                if data.get('transaction_type') == 'expense':
                    amount = -amount
                data['amount'] = amount
            elif local_result.get('amount'):
                # If Gemini couldn't parse amount but local parser did, use local result
                data['amount'] = local_result['amount']
                if not data.get('transaction_type'):
                    data['transaction_type'] = local_result['transaction_type']

            # Remove time_context from final data
            data.pop('time_context', None)

            # If description is missing, use the original text
            if not data.get('description'):
                data['description'] = local_result.get('description', text)

            return data

        except json.JSONDecodeError as e:
            logger.error(f"Error parsing Gemini JSON response: {e}")
            # Fall through to local parser

    except Exception as e:
        error_str = str(e).lower()
        logger.warning(f"Gemini API failed, using local fallback: {e}")

        # Check if it's a rate limit error
        if '429' in error_str or 'quota' in error_str or 'exceeded' in error_str:
            logger.warning("Rate limit hit, using local parser as fallback")

    # FALLBACK: Use local parser if Gemini fails
    logger.info(f"Using local parser fallback for: {text}")
    return local_result

def parse_date_from_text(text):
    """Attempt to extract a date from text using various methods."""
    from datetime import datetime, timedelta
    import re
    
    # Current date for reference
    current_date = datetime.now()
    
    # Try to find date patterns in the text
    text = text.lower()
    
    # Check for "yesterday", "today", "tomorrow"
    if "kemarin" in text or "yesterday" in text:
        return (current_date - timedelta(days=1)).strftime("%Y-%m-%d")
    elif "hari ini" in text or "today" in text:
        return current_date.strftime("%Y-%m-%d")
    elif "besok" in text or "tomorrow" in text:
        return (current_date + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "lusa" in text or "day after tomorrow" in text:
        return (current_date + timedelta(days=2)).strftime("%Y-%m-%d")
    
    # Check for "X days ago"
    days_ago_match = re.search(r'(\d+)\s+hari\s+(?:yang\s+)?lalu', text) or re.search(r'(\d+)\s+days\s+ago', text)
    if days_ago_match:
        days = int(days_ago_match.group(1))
        return (current_date - timedelta(days=days)).strftime("%Y-%m-%d")
    
    # Check for date formats like DD/MM/YYYY or DD-MM-YYYY
    date_patterns = [
        r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})',  # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
        r'(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})'   # YYYY/MM/DD or YYYY-MM-DD or YYYY.MM.DD
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups[0]) == 4:  # YYYY/MM/DD format
                year, month, day = groups
            else:  # DD/MM/YYYY format
                day, month, year = groups
            
            try:
                # Validate and format the date
                date_obj = datetime(int(year), int(month), int(day))
                return date_obj.strftime("%Y-%m-%d")
            except ValueError:
                # Invalid date, continue to next pattern
                continue
    
    # If no date found, return today's date
    return current_date.strftime("%Y-%m-%d")
    
# Function to parse multiple transactions from multi-line input
async def parse_multiple_transactions(text):
    """Parse multiple transactions from text separated by newlines."""
    # Split the text by newlines and filter out empty lines
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    print(f"Parsing {len(lines)} lines")
    
    if not lines:
        return []
    
    # Process each line as a separate transaction
    transactions = []
    for i, line in enumerate(lines):
        try:
            print(f"Parsing line {i+1}: {line}")
            transaction_data = await parse_financial_data(line)
            print(f"Parsed data: {transaction_data}")
            
            # Only include transactions where an amount could be determined
            if transaction_data.get('amount') is not None:
                transactions.append(transaction_data)
                print(f"Added transaction {i+1}")
            else:
                print(f"Skipping line {i+1} - no amount detected")
        except Exception as e:
            print(f"Error parsing line {i+1}: {e}")
            logger.error(f"Error parsing transaction line '{line}': {e}", exc_info=True)
            # Continue with other lines even if one fails
            continue
    
    print(f"Returning {len(transactions)} parsed transactions")
    return transactions

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return
    
    # Original handler code
    await update.message.reply_text(
        "👋 Selamat datang di Bot Pencatatan Keuangan!\n\n"
        "Gunakan tombol di bawah ini untuk mengakses fitur utama tanpa perlu mengetik perintah manual.\n\n"
        "📸 *FITUR BARU: Scan Struk Otomatis!*\n"
        "Kirim foto struk belanja untuk otomatis mencatat transaksi.\n\n"
        "Perintah manual masih tersedia bila dibutuhkan:\n"
        "/catat - Catat transaksi baru\n"
        "/laporan - Lihat laporan keuangan\n"
        "/sheet - Dapatkan link Google Sheet\n"
        "/hapus - Hapus data keuangan\n"
        "/menu - Tampilkan menu tombol\n"
        "/help - Panduan lengkap\n\n"
        "Atau cukup kirim pesan seperti:\n"
        "• 'Beli makan siang 50000' (pengeluaran)\n"
        "• 'Terima gaji bulan ini 5000000' (pemasukan)\n"
        "• 📸 Kirim foto struk untuk scan otomatis\n\n"
        "Bot akan otomatis mendeteksi apakah itu pemasukan atau pengeluaran.",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

def get_main_keyboard():
    """Create persistent keyboard for main commands"""
    keyboard = [
        [
            KeyboardButton("📝 Catat"),
            KeyboardButton("📊 Laporan")
        ],
        [
            KeyboardButton("📋 Sheet"),
            KeyboardButton("🗑️ Hapus")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu with persistent keyboard"""
    user_id = update.effective_user.id

    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return

    menu_text = (
        "📋 *Menu Utama Bot Keuangan*\n\n"
        "Pilih salah satu opsi di bawah ini dengan menekan tombol:"
    )

    await update.message.reply_text(
        menu_text,
        parse_mode='Markdown',
        reply_markup=get_main_keyboard()
    )

async def keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle keyboard button presses"""
    text = update.message.text
    user_id = update.effective_user.id

    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return

    # Map keyboard buttons to functions
    if text == "📝 Catat":
        await record_command(update, context)
    elif text == "📊 Laporan":
        await report(update, context)
    elif text == "📋 Sheet":
        await sheet_link(update, context)
    elif text == "🗑️ Hapus":
        await delete_data(update, context)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages (receipts)"""
    user_id = update.effective_user.id

    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return

    # Send processing message
    processing_msg = await update.message.reply_text(
        "🔍 Sedang menganalisis struk/foto...\n"
        "Mohon tunggu sebentar..."
    )

    try:
        # Get the largest photo
        photo_file = await update.message.photo[-1].get_file()

        # Download photo to bytes
        photo_bytes = await photo_file.download_as_bytearray()

        # Convert to PIL Image for Gemini
        image = Image.open(io.BytesIO(photo_bytes))

        # Analyze the receipt
        receipt_data = await analyze_receipt_image(image)

        # Check for errors in analysis
        if receipt_data.get('error'):
            await processing_msg.edit_text(
                f"❌ Gagal menganalisis struk:\n{receipt_data.get('error')}\n\n"
                "Tips: Pastikan foto struk jelas dan tidak buram."
            )
            return

        # Process based on receipt data
        if receipt_data.get('items') and len(receipt_data['items']) > 0:
            # Multiple items detected - ask for confirmation
            await process_receipt_items(update, context, receipt_data, processing_msg)
        elif receipt_data.get('total_amount'):
            # Only total amount detected
            await process_receipt_total(update, context, receipt_data, processing_msg)
        else:
            await processing_msg.edit_text(
                "❌ Tidak dapat mendeteksi informasi transaksi dari foto.\n\n"
                "Tips:\n"
                "• Pastikan foto struk terlihat jelas\n"
                "• Foto tidak buram atau terpotong\n"
                "• Pencahayaan cukup terang"
            )

    except Exception as e:
        logger.error(f"Error processing photo: {e}", exc_info=True)
        await processing_msg.edit_text(
            "❌ Terjadi kesalahan saat memproses foto.\n"
            "Silakan coba lagi atau ketik transaksi secara manual."
        )

async def process_receipt_items(update: Update, context: ContextTypes.DEFAULT_TYPE, receipt_data, processing_msg):
    """Process receipt with multiple items"""
    user_id = update.effective_user.id

    # Create summary message
    store_name = receipt_data.get('store_name', 'Toko')
    receipt_date = receipt_data.get('receipt_date', datetime.now().strftime("%Y-%m-%d"))
    total_amount = receipt_data.get('total_amount', 0)

    # Format date for display
    try:
        display_date = datetime.strptime(receipt_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except:
        display_date = receipt_date

    confirmation_message = f"🧾 *Struk Terdeteksi dari {store_name}*\n"
    confirmation_message += f"📅 Tanggal: {display_date}\n"
    confirmation_message += f"💰 Total: Rp {abs(total_amount):,.0f}\n\n"

    confirmation_message += "*Detail Barang:*\n"
    for i, item in enumerate(receipt_data['items'][:10], 1):  # Limit to 10 items for display
        item_desc = item.get('description', 'Item')
        item_qty = item.get('quantity', 1)
        item_amount = float(item.get('amount', 0))
        confirmation_message += f"{i}. {item_desc}"
        if item_qty > 1:
            confirmation_message += f" (x{item_qty})"
        confirmation_message += f": Rp {abs(item_amount):,.0f}\n"

    if len(receipt_data['items']) > 10:
        confirmation_message += f"... dan {len(receipt_data['items']) - 10} item lainnya\n"

    # Add tax and discount if present
    if receipt_data.get('tax'):
        confirmation_message += f"\n💸 Pajak: Rp {float(receipt_data.get('tax')):,.0f}"
    if receipt_data.get('discount'):
        confirmation_message += f"\n🎁 Diskon: Rp {float(receipt_data.get('discount')):,.0f}"

    confirmation_message += "\n\nPilih cara pencatatan:"

    # Store receipt data in context
    context.user_data['pending_receipt'] = receipt_data

    # Create options
    keyboard = [
        [InlineKeyboardButton("💵 Catat Total Saja", callback_data="receipt_total")],
        [InlineKeyboardButton("📝 Catat Per Item", callback_data="receipt_items")],
        [InlineKeyboardButton("🏷️ Catat Per Kategori", callback_data="receipt_categories")],
        [InlineKeyboardButton("❌ Batal", callback_data="receipt_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await processing_msg.edit_text(
        confirmation_message,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def process_receipt_total(update: Update, context: ContextTypes.DEFAULT_TYPE, receipt_data, processing_msg):
    """Process receipt with only total amount"""
    user_id = update.effective_user.id

    # Prepare transaction data
    total_amount = -abs(float(receipt_data.get('total_amount', 0)))  # Negative for expense
    store_name = receipt_data.get('store_name', 'Toko')
    receipt_date = receipt_data.get('receipt_date', datetime.now().strftime("%Y-%m-%d"))
    description = receipt_data.get('suggested_description', f'Belanja di {store_name}')

    # Format date for display
    try:
        display_date = datetime.strptime(receipt_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except:
        display_date = receipt_date

    confirmation_message = f"📝 *Detail Transaksi dari Struk*\n\n"
    confirmation_message += f"Tanggal: {display_date}\n"
    confirmation_message += f"Toko: {store_name}\n"
    confirmation_message += f"Jenis: Pengeluaran\n"
    confirmation_message += f"Jumlah: Rp {abs(total_amount):,.0f}\n"
    confirmation_message += f"Kategori: Belanja\n"
    confirmation_message += f"Deskripsi: {description}\n\n"
    confirmation_message += "Apakah data ini benar?"

    # Save data temporarily
    context.user_data['pending_transaction'] = {
        'date': receipt_date,
        'amount': total_amount,
        'category': 'Belanja',
        'description': description
    }

    # Create confirmation buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Ya, Benar", callback_data="confirm_yes"),
            InlineKeyboardButton("✏️ Input Ulang", callback_data="confirm_edit")
        ],
        [
            InlineKeyboardButton("🚫 Batal", callback_data="confirm_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await processing_msg.edit_text(
        confirmation_message,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt processing callbacks"""
    query = update.callback_query
    user_id = update.effective_user.id

    # Check authorization
    if not is_authorized(user_id):
        await query.answer("Anda tidak memiliki akses untuk menggunakan bot ini.", show_alert=True)
        return

    await query.answer()
    action = query.data.split("_")[1]

    if action == "cancel":
        await query.edit_message_text("❌ Pencatatan struk dibatalkan.")
        context.user_data.pop('pending_receipt', None)
        return

    receipt_data = context.user_data.get('pending_receipt', {})

    if not receipt_data:
        await query.edit_message_text("❌ Data struk tidak ditemukan. Silakan foto ulang.")
        return

    if action == "total":
        # Record only the total amount
        processing_msg = await query.edit_message_text("⏳ Mencatat transaksi...")

        # Check if Google Sheets is available
        if not sheet or not USE_GOOGLE_SHEETS:
            await processing_msg.edit_text(
                "❌ Google Sheets tidak terhubung.\n"
                "Silakan hubungi administrator untuk mengaktifkan integrasi Google Sheets."
            )
            logger.error("Google Sheets not available - cannot record receipt")
            return

        try:
            total_amount = -abs(float(receipt_data.get('total_amount', 0)))
            store_name = receipt_data.get('store_name', 'Toko')
            receipt_date = receipt_data.get('receipt_date', datetime.now().strftime("%Y-%m-%d"))
            description = receipt_data.get('suggested_description', f'Belanja di {store_name}')

            # Prepare row data
            row_data = [
                receipt_date,
                total_amount,
                'Belanja',
                description,
                user_id,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ]

            # Append to Google Sheet
            sheet.append_row(row_data)

            # Build basic confirmation message
            confirmation_message = (
                f"✅ Transaksi dari struk berhasil dicatat!\n\n"
                f"Total: Rp {abs(total_amount):,.0f}\n"
                f"Toko: {store_name}\n"
                f"Tanggal: {receipt_date}"
            )

            # Get recent transactions for category summary
            try:
                all_records = sheet.get_all_records()
                # Filter today's transactions for this user
                today_transactions = []
                for record in all_records:
                    if (record.get('Date') == receipt_date and
                        str(record.get('User ID', '')).strip() == str(user_id)):

                        # Convert amount and add to transactions
                        try:
                            record_amount = abs(float(record.get('Amount', 0)))
                            if record_amount > 0:  # Only include valid amounts
                                today_transactions.append({
                                    'category': record.get('Category', 'Lainnya'),
                                    'amount': record_amount,
                                    'description': record.get('Description', 'Item')
                                })
                        except (ValueError, TypeError):
                            continue

                # Add category summary if we have transactions
                if today_transactions:
                    category_summary = generate_category_summary(today_transactions, "📋 RINGKASAN HARI INI")
                    confirmation_message += category_summary
                    confirmation_message += "\n\n💡 Gunakan /laporan untuk detail lengkap."

            except Exception as e:
                logger.error(f"Error generating category summary: {e}", exc_info=True)

            await processing_msg.edit_text(confirmation_message, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error recording receipt total: {e}", exc_info=True)
            await processing_msg.edit_text("❌ Gagal mencatat transaksi. Silakan coba lagi.")

    elif action == "items":
        # Record each item separately
        processing_msg = await query.edit_message_text("⏳ Mencatat setiap item...")

        # Check if Google Sheets is available
        if not sheet or not USE_GOOGLE_SHEETS:
            await processing_msg.edit_text(
                "❌ Google Sheets tidak terhubung.\n"
                "Silakan hubungi administrator untuk mengaktifkan integrasi Google Sheets."
            )
            logger.error("Google Sheets not available - cannot record receipt items")
            return

        try:
            items = receipt_data.get('items', [])
            receipt_date = receipt_data.get('receipt_date', datetime.now().strftime("%Y-%m-%d"))
            store_name = receipt_data.get('store_name', 'Toko')

            success_count = 0
            for item in items:
                try:
                    item_amount = -abs(float(item.get('amount', 0)))
                    item_desc = item.get('description', 'Item')
                    item_category = item.get('category', 'Belanja')
                    item_qty = item.get('quantity', 1)

                    if item_qty > 1:
                        full_desc = f"{item_desc} (x{item_qty}) di {store_name}"
                    else:
                        full_desc = f"{item_desc} di {store_name}"

                    # Prepare row data
                    row_data = [
                        receipt_date,
                        item_amount,
                        item_category,
                        full_desc,
                        user_id,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ]

                    # Append to Google Sheet
                    sheet.append_row(row_data)
                    success_count += 1
                    await asyncio.sleep(0.3)  # Small delay between inserts

                except Exception as e:
                    logger.error(f"Error recording item: {e}", exc_info=True)

            # Generate category summary for the recorded items
            recorded_transactions = []
            for item in items[:success_count]:  # Only include successfully recorded items
                recorded_transactions.append({
                    'category': item.get('category', 'Belanja'),
                    'amount': abs(float(item.get('amount', 0))),
                    'description': item.get('description', 'Item')
                })

            # Create completion message with summary
            completion_message = f"✅ Berhasil mencatat {success_count} dari {len(items)} item!\n\n"
            completion_message += f"🏪 Toko: {store_name}\n"
            completion_message += f"📅 Tanggal: {receipt_date}"

            # Add category summary
            if recorded_transactions:
                category_summary = generate_category_summary(recorded_transactions, "📋 RINGKASAN PER KATEGORI")
                completion_message += category_summary

            completion_message += f"\n\n💡 Gunakan /laporan untuk melihat detail lengkap."

            await processing_msg.edit_text(completion_message, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error recording receipt items: {e}", exc_info=True)
            await processing_msg.edit_text("❌ Gagal mencatat item. Silakan coba lagi.")

    elif action == "categories":
        # Group items by category and record
        processing_msg = await query.edit_message_text("⏳ Mengelompokkan per kategori...")

        # Check if Google Sheets is available
        if not sheet or not USE_GOOGLE_SHEETS:
            await processing_msg.edit_text(
                "❌ Google Sheets tidak terhubung.\n"
                "Silakan hubungi administrator untuk mengaktifkan integrasi Google Sheets."
            )
            logger.error("Google Sheets not available - cannot record receipt by categories")
            return

        try:
            items = receipt_data.get('items', [])
            receipt_date = receipt_data.get('receipt_date', datetime.now().strftime("%Y-%m-%d"))
            store_name = receipt_data.get('store_name', 'Toko')

            # Group by category
            category_totals = {}
            for item in items:
                category = item.get('category', 'Belanja')
                amount = abs(float(item.get('amount', 0)))

                if category in category_totals:
                    category_totals[category] += amount
                else:
                    category_totals[category] = amount

            # Record each category
            success_count = 0
            for category, total in category_totals.items():
                try:
                    # Prepare row data
                    row_data = [
                        receipt_date,
                        -total,  # Negative for expense
                        category,
                        f"Belanja {category} di {store_name}",
                        user_id,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ]

                    # Append to Google Sheet
                    sheet.append_row(row_data)
                    success_count += 1
                    await asyncio.sleep(0.3)

                except Exception as e:
                    logger.error(f"Error recording category: {e}", exc_info=True)

            # Generate category summary for the recorded items
            recorded_transactions = []
            for category, total in category_totals.items():
                recorded_transactions.append({
                    'category': category,
                    'amount': total,
                    'description': f"Belanja {category}"
                })

            # Create completion message with enhanced summary
            completion_message = f"✅ Berhasil mencatat {success_count} kategori!\n\n"
            completion_message += f"🏪 Toko: {store_name}\n"
            completion_message += f"📅 Tanggal: {receipt_date}"

            # Add beautiful category summary
            if recorded_transactions:
                category_summary = generate_category_summary(recorded_transactions, "📋 RINGKASAN PER KATEGORI")
                completion_message += category_summary

            completion_message += f"\n\n💡 Gunakan /laporan untuk melihat detail lengkap."

            await processing_msg.edit_text(completion_message, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Error recording by categories: {e}", exc_info=True)
            await processing_msg.edit_text("❌ Gagal mencatat kategori. Silakan coba lagi.")

    # Clear pending receipt data
    context.user_data.pop('pending_receipt', None)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return

    # Check if we're in delete state or processing a financial message
    if 'delete_state' in context.user_data:
        # Check if the message is a command (starts with /)
        message_text = update.message.text
        if message_text and message_text.startswith('/'):
            # Clear delete state when user sends a command
            context.user_data.pop('delete_state', None)
            context.user_data.pop('start_date', None)
            context.user_data.pop('records_to_delete', None)
            # Let the command handler process this command
            return
        else:
            await handle_date_input(update, context)
    else:
        message_text = update.message.text
        print(f"Received message: {message_text}")

        # Split by newlines and filter out empty lines
        lines = [line.strip() for line in message_text.split('\n') if line.strip()]
        print(f"Detected {len(lines)} lines")

        # If we have multiple lines, process as multiple transactions
        if len(lines) > 1:
            transactions = await parse_multiple_transactions(message_text)
            print(f"Parsed {len(transactions)} transactions")

            if not transactions:
                await update.message.reply_text(
                    "❌ Saya tidak dapat mengenali transaksi dari pesan Anda.\n"
                    "Pastikan setiap baris berisi informasi transaksi yang lengkap."
                )
                return

            # Process multiple transactions
            await process_multiple_transactions(update, context, transactions)
        else:
            # Single transaction processing
            await process_financial_message(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🔍 *Cara Menggunakan Bot Keuangan*\n\n"
        "*📝 Mencatat Transaksi:*\n"
        "Cukup kirim pesan yang menjelaskan transaksi Anda. Bot akan otomatis mendeteksi apakah itu pemasukan atau pengeluaran.\n\n"
        "*Contoh Pemasukan:*\n"
        "• Terima gaji bulan ini 5000000\n"
        "• Dapat bonus kerja 1500000\n"
        "• Penjualan barang 250000\n"
        "• Kiriman dari ibu 500000\n\n"
        "*Contoh Pengeluaran:*\n"
        "• Beli makan siang 50000\n"
        "• Bayar tagihan listrik 350000\n"
        "• Belanja bulanan di supermarket 750000\n"
        "• Isi bensin motor 25000\n\n"
        "*📸 Scan Struk (BARU!):*\n"
        "Kirim foto struk belanja untuk otomatis mencatat transaksi!\n"
        "• Bot akan membaca total belanja\n"
        "• Mendeteksi nama toko dan tanggal\n"
        "• Bisa catat per item atau per kategori\n"
        "• Support struk Indomaret, Alfamart, dll\n\n"
        "*📋 Input Multi-Transaksi:*\n"
        "Anda dapat mencatat beberapa transaksi sekaligus dengan mengirimkan pesan dengan format:\n\n"
        "Transaksi 1\n"
        "Transaksi 2\n"
        "Transaksi 3\n\n"
        "Contoh:\n"
        "Beli makan siang kemarin 50000\n"
        "Bayar listrik hari ini 350000\n"
        "Terima gaji 5000000\n\n"
        "Bot akan menganalisis setiap baris sebagai transaksi terpisah.\n\n"
        "*⚙️ Perintah Lain:*\n"
        "/catat - Mulai mencatat transaksi baru\n"
        "/laporan - Lihat laporan keuangan lengkap\n"
        "/sheet - Dapatkan link Google Sheet\n"
        "/hapus - Hapus transaksi\n"
        "/hapuspesan - Aktifkan/nonaktifkan penghapusan pesan otomatis\n"
        "/help - Tampilkan bantuan ini\n\n"
        "*💡 Tips:*\n"
        "• Foto struk harus jelas dan terang\n"
        "• Bot bisa deteksi tanggal dari struk\n"
        "• Semua data otomatis tersimpan di Google Sheets"
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def record_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Silakan kirim detail transaksi Anda.\n"
        "Format: [deskripsi] [jumlah]\n"
        "Contoh: 'Beli makan siang 50000' atau 'Gaji bulan ini 5000000'"
    )

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Check authorization
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Maaf, Anda tidak memiliki akses untuk menggunakan bot ini.")
        return

    # Check if Google Sheets is available
    if not sheet or not USE_GOOGLE_SHEETS:
        await update.message.reply_text(
            "❌ *Fitur Google Sheets Tidak Aktif*\n\n"
            "Bot berjalan dalam mode terbatas karena:\n"
            "• Kredensial Google Sheets tidak ditemukan\n"
            "• File service account tidak tersedia\n\n"
            "📞 Silakan hubungi administrator untuk setup Google Sheets.\n\n"
            "💡 *Sementara waktu:*\n"
            "Bot masih dapat menjawab pertanyaan keuangan umum dengan Gemini AI.",
            parse_mode='Markdown'
        )
        logger.error(f"Google Sheets not available - cannot generate report (USE_GOOGLE_SHEETS={USE_GOOGLE_SHEETS}, sheet={sheet is not None})")
        return

    await update.message.reply_text("📊 Mengambil data laporan keuangan Anda...")

    try:
        # Get all records directly from the sheet
        all_records = sheet.get_all_records()

        # Filter records for this user
        user_records = [record for record in all_records if str(record.get('User ID')) == str(user_id)]

        if not user_records:
            await update.message.reply_text("❌ Anda belum memiliki catatan keuangan.")
            return

        # Calculate summary
        total_income = sum(float(record['Amount']) for record in user_records if float(record['Amount']) > 0)
        total_expense = sum(abs(float(record['Amount'])) for record in user_records if float(record['Amount']) < 0)
        balance = total_income - total_expense

        # Calculate period statistics
        from datetime import datetime, timedelta
        current_date = datetime.now()
        current_month = current_date.month
        current_year = current_date.year

        # This month's statistics
        month_income = 0
        month_expense = 0

        # Today's statistics
        today_income = 0
        today_expense = 0
        today_str = current_date.strftime("%Y-%m-%d")

        # Last 7 days statistics
        week_income = 0
        week_expense = 0
        week_start = (current_date - timedelta(days=7)).strftime("%Y-%m-%d")

        # Calculate statistics per period
        for record in user_records:
            amount = float(record['Amount'])
            record_date = record.get('Date', '')

            # Check if date is in current month
            if record_date.startswith(f"{current_year:04d}-{current_month:02d}"):
                if amount > 0:
                    month_income += amount
                else:
                    month_expense += abs(amount)

            # Check if date is today
            if record_date == today_str:
                if amount > 0:
                    today_income += amount
                else:
                    today_expense += abs(amount)

            # Check if date is in last 7 days
            if record_date >= week_start:
                if amount > 0:
                    week_income += amount
                else:
                    week_expense += abs(amount)

        # Calculate average transaction
        total_transactions = len(user_records)
        avg_expense = total_expense / total_transactions if total_transactions > 0 else 0
        avg_income = total_income / sum(1 for r in user_records if float(r['Amount']) > 0) if any(float(r['Amount']) > 0 for r in user_records) else 0

        # Calculate highest and lowest transactions
        expense_amounts = [abs(float(r['Amount'])) for r in user_records if float(r['Amount']) < 0]
        income_amounts = [float(r['Amount']) for r in user_records if float(r['Amount']) > 0]

        highest_expense = max(expense_amounts) if expense_amounts else 0
        highest_income = max(income_amounts) if income_amounts else 0

        # Find most frequent category for expenses
        expense_by_category = {}
        income_by_category = {}

        for record in user_records:
            amount = float(record['Amount'])
            category = record.get('Category', 'Lainnya')

            if amount < 0:  # Expense
                if category in expense_by_category:
                    expense_by_category[category] += abs(amount)
                else:
                    expense_by_category[category] = abs(amount)
            else:  # Income
                if category in income_by_category:
                    income_by_category[category] += amount
                else:
                    income_by_category[category] = amount

        # Create enhanced report message
        report_message = f"📊 *LAPORAN KEUANGAN LENGKAP*\n"
        report_message += f"_Per tanggal {current_date.strftime('%d/%m/%Y')}_\n"
        report_message += "=" * 30 + "\n\n"

        # Overall summary with balance indicator
        report_message += f"💰 *RINGKASAN TOTAL*\n"
        report_message += f"├ Total Pemasukan: Rp {total_income:,.0f}\n"
        report_message += f"├ Total Pengeluaran: Rp {total_expense:,.0f}\n"

        # Balance with emoji indicator
        balance_emoji = "🟢" if balance >= 0 else "🔴"
        report_message += f"└ Saldo: {balance_emoji} Rp {balance:,.0f}\n\n"

        # Period insights
        report_message += f"📅 *INSIGHTS PERIODE*\n\n"

        # This month
        report_message += f"*Bulan Ini ({current_date.strftime('%B %Y')}):*\n"
        report_message += f"├ Pemasukan: Rp {month_income:,.0f}\n"
        report_message += f"├ Pengeluaran: Rp {month_expense:,.0f}\n"
        month_balance = month_income - month_expense
        report_message += f"└ Selisih: {'➕' if month_balance >= 0 else '➖'} Rp {abs(month_balance):,.0f}\n\n"

        # Last 7 days
        report_message += f"*7 Hari Terakhir:*\n"
        report_message += f"├ Pemasukan: Rp {week_income:,.0f}\n"
        report_message += f"├ Pengeluaran: Rp {week_expense:,.0f}\n"
        week_balance = week_income - week_expense
        report_message += f"└ Selisih: {'➕' if week_balance >= 0 else '➖'} Rp {abs(week_balance):,.0f}\n\n"

        # Today's transactions
        if today_income > 0 or today_expense > 0:
            report_message += f"*Hari Ini:*\n"
            report_message += f"├ Pemasukan: Rp {today_income:,.0f}\n"
            report_message += f"├ Pengeluaran: Rp {today_expense:,.0f}\n"
            today_balance = today_income - today_expense
            report_message += f"└ Selisih: {'➕' if today_balance >= 0 else '➖'} Rp {abs(today_balance):,.0f}\n\n"

        # Statistics and Analysis
        report_message += f"📈 *ANALISIS & STATISTIK*\n\n"

        # Transaction count
        income_count = sum(1 for r in user_records if float(r['Amount']) > 0)
        expense_count = sum(1 for r in user_records if float(r['Amount']) < 0)
        report_message += f"*Jumlah Transaksi:*\n"
        report_message += f"├ Total: {total_transactions} transaksi\n"
        report_message += f"├ Pemasukan: {income_count} transaksi\n"
        report_message += f"└ Pengeluaran: {expense_count} transaksi\n\n"

        # Average transactions
        report_message += f"*Rata-rata per Transaksi:*\n"
        if income_count > 0:
            report_message += f"├ Pemasukan: Rp {avg_income:,.0f}\n"
        if expense_count > 0:
            report_message += f"└ Pengeluaran: Rp {total_expense/expense_count:,.0f}\n\n"

        # Highest transactions
        if highest_income > 0 or highest_expense > 0:
            report_message += f"*Transaksi Terbesar:*\n"
            if highest_income > 0:
                report_message += f"├ Pemasukan: Rp {highest_income:,.0f}\n"
            if highest_expense > 0:
                report_message += f"└ Pengeluaran: Rp {highest_expense:,.0f}\n\n"

        # Category breakdown - Expenses
        if expense_by_category:
            report_message += f"🏷️ *PENGELUARAN PER KATEGORI*\n"

            # Find the top spending category
            top_expense_cat = max(expense_by_category.items(), key=lambda x: x[1])

            for category, amount in sorted(expense_by_category.items(), key=lambda x: x[1], reverse=True):
                percentage = (amount / total_expense) * 100 if total_expense > 0 else 0
                # Add emoji for top category
                emoji = "🔥" if category == top_expense_cat[0] else "•"
                report_message += f"{emoji} {category}: Rp {amount:,.0f} ({percentage:.1f}%)\n"
            report_message += "\n"

        # Category breakdown - Income
        if income_by_category:
            report_message += f"💵 *PEMASUKAN PER KATEGORI*\n"
            for category, amount in sorted(income_by_category.items(), key=lambda x: x[1], reverse=True):
                percentage = (amount / total_income) * 100 if total_income > 0 else 0
                report_message += f"• {category}: Rp {amount:,.0f} ({percentage:.1f}%)\n"
            report_message += "\n"

        # Financial health indicator
        report_message += f"🏥 *INDIKATOR KESEHATAN KEUANGAN*\n"

        # Savings rate
        if total_income > 0:
            savings_rate = ((total_income - total_expense) / total_income) * 100
            if savings_rate >= 20:
                savings_emoji = "🟢 Sangat Baik"
            elif savings_rate >= 10:
                savings_emoji = "🟡 Baik"
            elif savings_rate >= 0:
                savings_emoji = "🟠 Cukup"
            else:
                savings_emoji = "🔴 Perlu Perbaikan"

            report_message += f"├ Tingkat Tabungan: {savings_rate:.1f}% {savings_emoji}\n"

        # Expense to income ratio
        if total_income > 0:
            expense_ratio = (total_expense / total_income) * 100
            if expense_ratio <= 70:
                ratio_emoji = "🟢"
            elif expense_ratio <= 90:
                ratio_emoji = "🟡"
            else:
                ratio_emoji = "🔴"

            report_message += f"└ Rasio Pengeluaran: {expense_ratio:.1f}% {ratio_emoji}\n\n"

        # Recent transactions (last 5)
        report_message += f"📝 *5 TRANSAKSI TERAKHIR*\n"

        # Sort transactions by date (newest first)
        sorted_records = sorted(user_records, key=lambda x: x.get('Timestamp', ''), reverse=True)
        recent_transactions = sorted_records[:5]

        for i, record in enumerate(recent_transactions, 1):
            try:
                amount = float(record['Amount'])
                symbol = "➕" if amount >= 0 else "➖"
                date = record.get('Date', '')
                category = record.get('Category', 'Lainnya')
                description = record.get('Description', '')

                # Format date to DD/MM
                try:
                    date_obj = datetime.strptime(date, "%Y-%m-%d")
                    formatted_date = date_obj.strftime("%d/%m")
                except:
                    formatted_date = date[:5]

                # Truncate description if too long
                if len(description) > 25:
                    description = description[:22] + "..."

                report_message += f"{i}. {formatted_date} {symbol} Rp {abs(amount):,.0f}\n"
                report_message += f"   {category}: {description}\n"
            except Exception as e:
                continue

        # Footer with tips
        report_message += "\n" + "=" * 30 + "\n"
        report_message += "💡 *TIPS:* "

        # Generate contextual tip based on financial state
        if balance < 0:
            report_message += "Pengeluaran melebihi pemasukan. Pertimbangkan untuk mengurangi pengeluaran tidak penting."
        elif savings_rate < 10 if total_income > 0 else True:
            report_message += "Tingkatkan tabungan Anda hingga minimal 10-20% dari pemasukan."
        elif expense_by_category and top_expense_cat[1] > total_expense * 0.4:
            report_message += f"Kategori {top_expense_cat[0]} menghabiskan {(top_expense_cat[1]/total_expense*100):.0f}% pengeluaran. Pertimbangkan untuk mengontrol kategori ini."
        else:
            report_message += "Keuangan Anda terlihat sehat! Pertahankan pola ini."

        # Send the report
        await update.message.reply_text(report_message, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error generating report: {e}", exc_info=True)
        error_type = type(e).__name__
        await update.message.reply_text(
            f"❌ Terjadi kesalahan saat mengambil laporan keuangan Anda.\n\n"
            f"Error: {error_type}\n"
            f"Detail: {str(e)[:100]}\n\n"
            f"Silakan hubungi administrator untuk bantuan."
        )

# Fallback function to detect transaction type from text
def detect_transaction_type(text):
    text = text.lower()
    
    # Income indicators
    income_words = [
        "terima", "dapat", "pemasukan", "masuk", "diterima", 
        "gaji", "bonus", "komisi", "dividen", "bunga", "hadiah", 
        "warisan", "penjualan", "refund", "kembalian", "cashback",
        "dibayar oleh", "transfer dari", "kiriman dari", "diberi", "dikasih"
    ]
    
    # Expense indicators
    expense_words = [
        "beli", "bayar", "belanja", "pengeluaran", "keluar", "dibayar",
        "membeli", "memesan", "berlangganan", "sewa", "booking",
        "makanan", "transportasi", "bensin", "pulsa", "tagihan", "biaya", "iuran",
        "dibayarkan untuk", "transfer ke", "kirim ke"
    ]
    
    # Count matches
    income_score = sum(1 for word in income_words if word in text)
    expense_score = sum(1 for word in expense_words if word in text)
    
    # Determine type based on score
    if income_score > expense_score:
        return "income"
    else:
        return "expense"  # Default to expense if tied or no matches

# Message handler for financial data with improved detection
async def process_financial_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Store the user's message ID for later deletion
    if 'messages_to_delete' not in context.user_data:
        context.user_data['messages_to_delete'] = []

    # Add the user's message ID to the list
    context.user_data['messages_to_delete'].append(update.message.message_id)

    # Authorization is already checked in the message_handler

    message_text = update.message.text

    # ============================================================
    # CHECK IF WE'RE WAITING FOR AMOUNT INPUT
    # ============================================================
    if context.user_data.get('conversation_state') == STATE_WAITING_AMOUNT:
        # User is providing amount for a previous transaction
        amount = parse_indonesian_amount(message_text)

        if amount is not None:
            # Get stored transaction details
            transaction_type = context.user_data.get('transaction_type', 'expense')
            description = context.user_data.get('description', '')
            detected_date = context.user_data.get('date', datetime.now().strftime("%Y-%m-%d"))
            category = context.user_data.get('pending_category', 'Lainnya')

            # Apply sign based on transaction type
            if transaction_type == 'expense':
                amount = -abs(amount)
            else:
                amount = abs(amount)

            # Clear the waiting state
            context.user_data['conversation_state'] = None

            # Format the date for display
            try:
                display_date = datetime.strptime(detected_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            except:
                display_date = detected_date

            # Create confirmation message
            type_display = "Pemasukan" if amount > 0 else "Pengeluaran"
            confirmation_message = f"📝 *Detail Transaksi*\n\n"
            confirmation_message += f"Tanggal: {display_date}\n"
            confirmation_message += f"Jenis: {type_display}\n"
            confirmation_message += f"Jumlah: Rp {abs(amount):,.0f}\n"
            confirmation_message += f"Kategori: {category}\n"
            confirmation_message += f"Deskripsi: {description}\n\n"
            confirmation_message += "Apakah data ini benar?"

            # Save data temporarily
            context.user_data['pending_transaction'] = {
                'date': detected_date,
                'amount': amount,
                'category': category,
                'description': description
            }

            # Create confirmation buttons
            keyboard = [
                [
                    InlineKeyboardButton("✅ Ya, Benar", callback_data="confirm_yes"),
                    InlineKeyboardButton("✏️ Input Ulang", callback_data="confirm_edit")
                ],
                [
                    InlineKeyboardButton("🚫 Batal", callback_data="confirm_cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(confirmation_message, reply_markup=reply_markup, parse_mode='Markdown')
            return
        else:
            # Couldn't parse amount from input
            await update.message.reply_text(
                "❌ Format jumlah tidak valid.\n\n"
                "Contoh format yang benar:\n"
                "• 50000\n"
                "• 50k atau 50rb (untuk 50.000)\n"
                "• 1jt atau 1juta (untuk 1.000.000)\n"
                "• 1.500.000\n\n"
                "Silakan masukkan jumlah lagi:"
            )
            return

    # ============================================================
    # NORMAL TRANSACTION PROCESSING
    # ============================================================

    # Split by newlines and filter out empty lines
    lines = [line.strip() for line in message_text.split('\n') if line.strip()]

    # If we have multiple lines, process as multiple transactions
    if len(lines) > 1:
        transactions = await parse_multiple_transactions(message_text)

        if not transactions:
            error_message = await update.message.reply_text(
                "❌ Saya tidak dapat mengenali transaksi dari pesan Anda.\n"
                "Pastikan setiap baris berisi informasi transaksi yang lengkap."
            )
            context.user_data['messages_to_delete'].append(error_message.message_id)
            return

        # Process multiple transactions
        await process_multiple_transactions(update, context, transactions)
        return

    # Single transaction processing
    parsed_data = await parse_financial_data(message_text)

    # If Gemini couldn't determine a date, try our fallback parser
    if not parsed_data.get('date'):
        parsed_data['date'] = parse_date_from_text(message_text)

    # If parsing failed or incomplete, ask for clarification
    if not parsed_data.get('amount'):
        keyboard = [
            [InlineKeyboardButton("Pemasukan", callback_data="type_income"),
             InlineKeyboardButton("Pengeluaran", callback_data="type_expense")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.user_data['pending_message'] = message_text
        # Store the detected date for later use
        context.user_data['detected_date'] = parsed_data.get('date')
        # Store category if detected
        context.user_data['pending_category'] = parsed_data.get('category', 'Lainnya')

        await update.message.reply_text(
            "Saya tidak dapat menentukan jumlah transaksi. Apakah ini pemasukan atau pengeluaran?",
            reply_markup=reply_markup
        )
        return
    
    # Create confirmation message with parsed data
    amount = parsed_data.get('amount', 0)
    transaction_type = "Pemasukan" if amount > 0 else "Pengeluaran"
    category = parsed_data.get('category', 'Lainnya')
    description = parsed_data.get('description', message_text)
    date = parsed_data.get('date')
    
    # Format the date for display (YYYY-MM-DD to DD/MM/YYYY)
    try:
        from datetime import datetime
        display_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except:
        display_date = date
    
    confirmation_message = f"📝 *Detail Transaksi*\n\n"
    confirmation_message += f"Tanggal: {display_date}\n"
    confirmation_message += f"Jenis: {transaction_type}\n"
    confirmation_message += f"Jumlah: Rp {abs(amount):,.0f}\n"
    confirmation_message += f"Kategori: {category}\n"
    confirmation_message += f"Deskripsi: {description}\n\n"
    confirmation_message += "Apakah data ini benar?"
    
    # Save data temporarily
    context.user_data['pending_message'] = message_text
    context.user_data['detected_date'] = date
    context.user_data['pending_transaction'] = {
        'date': date,
        'amount': amount,
        'category': category,
        'description': description
    }
    
    # Create confirmation buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Ya, Benar", callback_data="confirm_yes"),
            InlineKeyboardButton("✏️ Input Ulang", callback_data="confirm_edit")
        ],
        [
            InlineKeyboardButton("🚫 Batal", callback_data="confirm_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(confirmation_message, reply_markup=reply_markup, parse_mode='Markdown')

# Callback query handler
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Check authorization
    if not is_authorized(user_id):
        await query.answer("Anda tidak memiliki akses untuk menggunakan bot ini.", show_alert=True)
        return
    
    
    if query.data.startswith("type_"):
        await query.answer()
        transaction_type = query.data.split("_")[1]
        message_text = context.user_data.get('pending_message', '')

        # Get the detected date if available, otherwise use today's date
        detected_date = context.user_data.get('detected_date', datetime.now().strftime("%Y-%m-%d"))

        # Store transaction details and set conversation state
        context.user_data['transaction_type'] = transaction_type
        context.user_data['description'] = message_text
        context.user_data['date'] = detected_date
        context.user_data['conversation_state'] = STATE_WAITING_AMOUNT  # SET STATE

        # Format the date for display
        try:
            display_date = datetime.strptime(detected_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except:
            display_date = detected_date

        await query.edit_message_text(
            f"📅 Tanggal: {display_date}\n"
            f"📝 Deskripsi: {message_text}\n"
            f"📊 Jenis: {'Pemasukan' if transaction_type == 'income' else 'Pengeluaran'}\n\n"
            f"💰 Berapa jumlahnya?\n\n"
            f"_Contoh: 50000, 50k, 50rb, 1jt_",
            parse_mode='Markdown'
        )
        return
    
    if query.data.startswith("confirm_"):
        action = query.data.split("_", 1)[1]
        
        if action == "yes":
            # Get transaction data
            transaction = context.user_data.get('pending_transaction', {})

            # Check if Google Sheets is available
            if not sheet or not USE_GOOGLE_SHEETS:
                await query.edit_message_text(
                    "❌ Google Sheets tidak terhubung.\n"
                    "Silakan hubungi administrator untuk mengaktifkan integrasi Google Sheets."
                )
                logger.error("Google Sheets not available - cannot save transaction")
                return

            # Prepare row data
            row_data = [
                transaction.get('date', datetime.now().strftime("%Y-%m-%d")),  # Use the date from parsed data
                transaction.get('amount', 0),
                transaction.get('category', 'Lainnya'),
                transaction.get('description', ''),
                user_id,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ]

            # Append to Google Sheet
            sheet.append_row(row_data)

            # Wait for Google Sheets to process the new row
            await asyncio.sleep(3)

            # Determine transaction type for display
            amount = transaction.get('amount', 0)
            transaction_type = "Pemasukan" if amount > 0 else "Pengeluaran"

            # Build basic confirmation message
            confirmation_message_text = (
                "✅ Transaksi berhasil dicatat!\n\n"
                f"Tanggal: {transaction.get('date', datetime.now().strftime('%Y-%m-%d'))}\n"
                f"Jenis: {transaction_type}\n"
                f"Jumlah: Rp {format_rupiah(abs(float(amount)))}\n"
                f"Kategori: {transaction.get('category', 'Lainnya')}\n"
                f"Deskripsi: {transaction.get('description', '')}"
            )

            # Get recent transactions for category summary
            summary_added = False
            try:
                today = transaction.get('date', datetime.now().strftime('%Y-%m-%d'))
                logger.info(f"🔍 Fetching transactions for user {user_id} on {today}")

                all_records = sheet.get_all_records()
                logger.info(f"📊 Retrieved {len(all_records)} total records from Google Sheets")

                # Filter today's transactions for this user
                today_transactions = []
                found_today_count = 0

                for record in all_records:
                    record_date = record.get('Date')
                    record_user_id = str(record.get('User ID', '')).strip()

                    if record_date == today:
                        found_today_count += 1
                        logger.info(f"📅 Today record #{found_today_count}: user={record_user_id}, amount={record.get('Amount')}")

                    if (record.get('Date') == today and
                        str(record.get('User ID', '')).strip() == str(user_id)):

                        # Convert amount and add to transactions
                        try:
                            record_amount = abs(float(record.get('Amount', 0)))
                            if record_amount > 0:  # Only include valid amounts
                                today_transactions.append({
                                    'category': record.get('Category', 'Lainnya'),
                                    'amount': record_amount,
                                    'description': record.get('Description', 'Item')
                                })
                                logger.info(f"✅ Added transaction: {today_transactions[-1]}")
                        except (ValueError, TypeError) as e:
                            logger.error(f"❌ Error processing amount: {e}")
                            continue

                logger.info(f"🎯 Found {len(today_transactions)} matching transactions for user {user_id}")

                # Add category summary if we have transactions
                if today_transactions:
                    logger.info("🏗️ Generating category summary...")
                    category_summary = generate_category_summary(today_transactions, "📋 RINGKASAN HARI INI")
                    confirmation_message_text += category_summary
                    confirmation_message_text += "\n\n💡 Gunakan /laporan untuk detail lengkap."
                    summary_added = True
                    logger.info("✅ Category summary added successfully!")
                else:
                    logger.warning(f"⚠️ No transactions found for user {user_id} on {today}")

            except Exception as e:
                logger.error(f"❌ Error generating category summary: {e}")
                logger.error(f"📋 Traceback: {traceback.format_exc()}")

            # Send message with proper error handling for Markdown parsing
            try:
                confirmation_message = await query.edit_message_text(confirmation_message_text, parse_mode='Markdown')
                logger.info("✅ Message sent successfully with Markdown")
            except Exception as markdown_error:
                logger.error(f"❌ Markdown parsing failed: {markdown_error}")
                try:
                    # Fallback: Try without Markdown
                    confirmation_message = await query.edit_message_text(confirmation_message_text)
                    logger.info("✅ Message sent successfully without Markdown (fallback)")
                except Exception as fallback_error:
                    logger.error(f"❌ Even fallback message failed: {fallback_error}")
                    # Last resort: Send basic message
                    basic_message = (
                        "✅ Transaksi berhasil dicatat!\n\n"
                        f"Jenis: {transaction_type}\n"
                        f"Jumlah: Rp {format_rupiah(abs(float(amount)))}\n"
                        f"Kategori: {transaction.get('category', 'Lainnya')}\n"
                        f"Deskripsi: {transaction.get('description', '')}\n\n"
                        "⚠️ Summary tidak dapat ditampilkan (error dalam format)"
                    )
                    try:
                        confirmation_message = await query.edit_message_text(basic_message)
                        logger.info("✅ Basic message sent as last resort")
                    except Exception as final_error:
                        logger.error(f"❌ Complete message failure: {final_error}")

            # DO NOT auto-delete the message so user can see the category summary
            # Clear all pending data including conversation state
            for key in ['pending_transaction', 'pending_message', 'transaction_type', 'amount', 'description', 'detected_date', 'pending_receipt', 'conversation_state', 'pending_category', 'date']:
                context.user_data.pop(key, None)
            return
        
        elif action in ("no", "edit"):
            # Clear pending transaction data and conversation state so user can input again
            context.user_data.pop('pending_transaction', None)
            context.user_data.pop('conversation_state', None)

            pending_message = context.user_data.get('pending_message')
            if pending_message:
                keyboard = [
                    [InlineKeyboardButton("Pemasukan", callback_data="type_income"),
                     InlineKeyboardButton("Pengeluaran", callback_data="type_expense")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    "Silakan pilih jenis transaksi:",
                    reply_markup=reply_markup
                )
            else:
                # Likely came from receipt flow — ask user to resend manually
                for key in ['pending_receipt', 'transaction_type', 'amount', 'description', 'detected_date', 'conversation_state', 'pending_category', 'date']:
                    context.user_data.pop(key, None)

                await query.edit_message_text(
                    "✏️ Pencatatan dibatalkan. Silakan kirim ulang detail transaksi atau foto struk baru."
                )
            return

        elif action == "cancel":
            keys_to_clear = [
                'pending_transaction',
                'pending_message',
                'transaction_type',
                'amount',
                'description',
                'detected_date',
                'pending_receipt',
                'conversation_state',
                'pending_category',
                'date'
            ]
            for key in keys_to_clear:
                context.user_data.pop(key, None)

            await query.edit_message_text("✅ Pencatatan dibatalkan. Tidak ada data yang disimpan.")
            return

        else:
            # Unknown confirm action, ignore safely
            await query.answer()
            return

# Handle amount input after transaction type selection
async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'transaction_type' not in context.user_data:
        return
    
    try:
        # Parse amount from message
        amount_text = update.message.text.replace(',', '').replace('.', '')
        amount = float(amount_text)
        
        # Adjust sign based on transaction type
        if context.user_data['transaction_type'] == 'expense':
            amount = -abs(amount)  # Make negative for expenses
        else:
            amount = abs(amount)   # Make positive for income
        
        description = context.user_data.get('description', '')
        
        # Ask for category
        context.user_data['amount'] = amount
        
        # Suggest categories based on transaction type
        if context.user_data['transaction_type'] == 'income':
            categories = ["Gaji", "Bonus", "Investasi", "Hadiah", "Lainnya"]
        else:
            categories = ["Makanan", "Transportasi", "Belanja", "Hiburan", "Tagihan", "Lainnya"]
        
        keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in categories]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Pilih kategori untuk {'pemasukan' if amount > 0 else 'pengeluaran'} ini:",
            reply_markup=reply_markup
        )
    except ValueError:
        await update.message.reply_text("Mohon masukkan jumlah yang valid (angka saja).")

# Handle category selection
async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("cat_"):
        category = query.data.split("_")[1]
        user_id = update.effective_user.id

        # Check if Google Sheets is available
        if not sheet or not USE_GOOGLE_SHEETS:
            await query.edit_message_text(
                "❌ Google Sheets tidak terhubung.\n"
                "Silakan hubungi administrator untuk mengaktifkan integrasi Google Sheets."
            )
            logger.error("Google Sheets not available - cannot save transaction with category")
            return

        # Get transaction data
        amount = context.user_data.get('amount', 0)
        description = context.user_data.get('description', '')

        # Prepare row data
        today = datetime.now().strftime("%Y-%m-%d")
        row_data = [
            today,
            amount,  # Already has correct sign (positive for income, negative for expense)
            category,
            description,
            user_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ]

        # Append to Google Sheet
        sheet.append_row(row_data)

        # Increased delay to ensure Google Sheets has processed the new row (especially on Railway)
        await asyncio.sleep(3)

        # Determine transaction type for display
        transaction_type = "Pemasukan" if amount > 0 else "Pengeluaran"

        # Build basic confirmation message
        confirmation_message = (
            "✅ Transaksi berhasil dicatat!\n\n"
            f"Jenis: {transaction_type}\n"
            f"Jumlah: Rp {format_rupiah(abs(float(amount)))}\n"
            f"Kategori: {category}\n"
            f"Deskripsi: {description}"
        )

        # Get recent transactions from today for summary
        summary_added = False
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            logger.info(f"🔍 Fetching transactions for user {user_id} on {today}")

            all_records = sheet.get_all_records()
            logger.info(f"📊 Retrieved {len(all_records)} total records from Google Sheets")

            # Filter today's transactions for this user
            today_transactions = []
            found_today_count = 0

            for record in all_records:
                record_date = record.get('Date')
                record_user_id = str(record.get('User ID', '')).strip()

                if record_date == today:
                    found_today_count += 1
                    logger.info(f"📅 Today record #{found_today_count}: user={record_user_id}, amount={record.get('Amount')}, category={record.get('Category')}")

                if (record.get('Date') == today and
                    str(record.get('User ID', '')).strip() == str(user_id)):

                    # Convert amount and add to transactions
                    try:
                        record_amount = abs(float(record.get('Amount', 0)))
                        if record_amount > 0:  # Only include valid amounts
                            today_transactions.append({
                                'category': record.get('Category', 'Lainnya'),
                                'amount': record_amount,
                                'description': record.get('Description', 'Item')
                            })
                            logger.info(f"✅ Added transaction: {today_transactions[-1]}")
                        else:
                            logger.warning(f"⚠️ Skipped zero amount: {record_amount}")
                    except (ValueError, TypeError) as e:
                        logger.error(f"❌ Error processing amount: {e}")
                        continue

            logger.info(f"🎯 Found {len(today_transactions)} matching transactions for user {user_id}")

            # Add category summary if we have transactions
            if today_transactions:
                logger.info("🏗️ Generating category summary...")
                category_summary = generate_category_summary(today_transactions, "📋 RINGKASAN HARI INI")
                confirmation_message += category_summary
                confirmation_message += "\n\n💡 Gunakan /laporan untuk detail lengkap."
                summary_added = True
                logger.info("✅ Category summary added successfully!")
            else:
                logger.warning(f"⚠️ No transactions found for user {user_id} on {today} - summary will not be shown")
                logger.warning(f"Total today records found: {found_today_count}")

        except Exception as e:
            logger.error(f"❌ Error generating category summary: {e}")
            logger.error(f"📋 Traceback: {traceback.format_exc()}")
            # Continue with basic confirmation even if summary fails

        # Force add debug info to message if summary wasn't added (for testing)
        if not summary_added:
            confirmation_message += f"\n\n🔧 Debug: No summary generated (check logs for details)"

        # Send message with proper error handling for Markdown parsing
        try:
            await query.edit_message_text(confirmation_message, parse_mode='Markdown')
            logger.info("✅ Message sent successfully with Markdown")
        except Exception as markdown_error:
            logger.error(f"❌ Markdown parsing failed: {markdown_error}")
            try:
                # Fallback: Try without Markdown
                await query.edit_message_text(confirmation_message)
                logger.info("✅ Message sent successfully without Markdown (fallback)")
            except Exception as fallback_error:
                logger.error(f"❌ Even fallback message failed: {fallback_error}")
                # Last resort: Send basic message
                basic_message = (
                    "✅ Transaksi berhasil dicatat!\n\n"
                    f"Jenis: {transaction_type}\n"
                    f"Jumlah: Rp {format_rupiah(abs(float(amount)))}\n"
                    f"Kategori: {category}\n"
                    f"Deskripsi: {description}\n\n"
                    "⚠️ Summary tidak dapat ditampilkan (error dalam format)"
                )
                try:
                    await query.edit_message_text(basic_message)
                    logger.info("✅ Basic message sent as last resort")
                except Exception as final_error:
                    logger.error(f"❌ Complete message failure: {final_error}")
        
        # Clear user data
        context.user_data.clear()

def main():
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Create persistence object with writable path
    persistence = PicklePersistence(filepath="/app/data/bot_data.pickle")
    
    # Create application with persistence
    application = Application.builder().token(TELEGRAM_TOKEN).persistence(persistence).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("catat", record_command))
    application.add_handler(CommandHandler("laporan", report))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("sheet", sheet_link))
    application.add_handler(CommandHandler("hapus", delete_data))
    application.add_handler(CommandHandler("hapuspesan", toggle_delete_messages))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(multiple_transactions_callback, pattern="^confirm_all_"))
    application.add_handler(CallbackQueryHandler(delete_callback, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(delete_specific_callback, pattern="^del_specific_"))
    application.add_handler(CallbackQueryHandler(confirm_delete_callback, pattern="^confirm_delete_"))
    application.add_handler(CallbackQueryHandler(receipt_callback, pattern="^receipt_"))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(confirm_|type_)"))
    application.add_handler(CallbackQueryHandler(category_callback, pattern="^cat_"))

    # Add photo handler for receipt scanning
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        photo_handler
    ))

    # Add keyboard button handler (BEFORE general message handler)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex("^(📝 Catat|📊 Laporan|📋 Sheet|🗑️ Hapus)$") & filters.ChatType.PRIVATE,
        keyboard_handler
    ))

    # Add general message handler (LAST for TEXT messages)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        message_handler
    ))
    
    # Command handler for /me
    async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        await update.message.reply_text(f"Your Telegram user ID is: {user_id}")
    
    # Add the handler to the application
    application.add_handler(CommandHandler('me', cmd_me))

    # Add error handlers
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log errors caused by Updates."""
        logger.error("Exception while handling an update:", exc_info=context.error)

        # Handle 409 Conflict specifically
        if isinstance(context.error, telegram.error.Conflict):
            logger.error("🔴 Bot conflict detected - another instance is already running!")
            logger.error("💡 This usually means the bot is running on Railway/Heroku or another local instance")
            logger.error("💡 Stop the other instance or use the production bot directly")
            return

        # Handle network errors
        if isinstance(context.error, telegram.error.NetworkError):
            logger.error("🌐 Network error occurred - this is usually temporary")
            return

        # Handle other telegram errors
        if isinstance(context.error, telegram.error.TelegramError):
            logger.error(f"🤖 Telegram API error: {context.error}")
            return

    # Register error handler
    application.add_error_handler(error_handler)

    # Set bot commands (menu buttons)
    async def post_init(application: Application) -> None:
        """Set bot commands after initialization."""
        bot_commands = [
            BotCommand("start", "Mulai bot dan lihat menu utama"),
            BotCommand("catat", "Catat transaksi baru"),
            BotCommand("laporan", "Lihat laporan keuangan"),
            BotCommand("sheet", "Dapatkan link Google Sheet"),
            BotCommand("hapus", "Hapus data keuangan"),
            BotCommand("menu", "Tampilkan menu utama"),
            BotCommand("help", "Panduan penggunaan bot"),
            BotCommand("hapuspesan", "Toggle auto-delete pesan"),
        ]
        await application.bot.set_my_commands(bot_commands)
        logger.info("✅ Bot commands registered successfully")

    # Register post_init
    application.post_init = post_init

    # Start the Bot with proper exception handling
    try:
        logger.info("🚀 Starting bot...")
        application.run_polling(drop_pending_updates=True)
    except telegram.error.Conflict:
        logger.error("❌ Cannot start bot - another instance is already running!")
        logger.error("💡 Check if bot is running on Railway, Heroku, or another terminal")
        logger.error("💡 Use the production bot directly or stop the other instance first")
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    main()
