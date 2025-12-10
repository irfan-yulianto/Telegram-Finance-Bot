# Telegram Finance Bot

🤖 Bot Telegram untuk pencatatan keuangan pribadi dengan AI-powered receipt scanning, integrasi Google Sheets, dan dukungan bahasa Indonesia.


## Fitur Utama

- **Pencatatan Natural Language** - Catat transaksi dengan bahasa sehari-hari: "Makan siang 50rb", "Gaji masuk 5jt"
- **AI Receipt Scanning** - Upload foto struk, AI akan mengekstrak data otomatis (powered by Google Gemini)
- **Google Sheets Integration** - Data tersimpan otomatis ke Google Sheets untuk analisis lebih lanjut
- **Format Indonesia** - Support format angka Indonesia (50rb, 1jt, 500k)
- **Laporan Otomatis** - Lihat ringkasan harian, mingguan, dan bulanan
- **Multi-user Support** - Bisa digunakan untuk beberapa user sekaligus
- **Rate Limit Handling** - Built-in retry logic dengan exponential backoff
- **Local Fallback** - Parsing lokal jika API tidak tersedia

## Tech Stack

- Python 3.10+
- python-telegram-bot
- Google Gemini API (gemini-2.0-flash-lite)
- Google Sheets API
- Docker & Docker Compose

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/telegram-finance-bot.git
cd telegram-finance-bot
```

### 2. Setup Environment Variables

Copy `.env.example` ke `.env` dan isi dengan kredensial Anda:

```bash
cp .env.example .env
```

Edit file `.env`:

```env
# Telegram Bot Token (dari @BotFather)
TELEGRAM_TOKEN=your_telegram_bot_token_here

# Google Gemini API Key (dari https://aistudio.google.com/apikey)
GEMINI_API_KEY=your_gemini_api_key_here

# ID user Telegram yang diizinkan (pisahkan dengan koma untuk multi-user)
AUTHORIZED_USER_ID=123456789,987654321

# Google Sheets ID (dari URL spreadsheet)
SPREADSHEET_ID=your_google_sheets_id_here

# Google Sheets Service Account Credentials (JSON string)
GOOGLE_SHEETS_CREDENTIALS_JSON={"type":"service_account","project_id":"your-project",...}
```

### 3. Setup Google Sheets (Optional tapi Recommended)

1. Buka [Google Cloud Console](https://console.cloud.google.com/)
2. Buat project baru atau gunakan yang ada
3. Enable **Google Sheets API**
4. Buat **Service Account** dan download JSON key
5. Share spreadsheet Anda ke email service account
6. Copy isi JSON key ke `GOOGLE_SHEETS_CREDENTIALS_JSON`

### 4. Jalankan Bot

**Option A: Docker (Recommended)**

```bash
docker-compose up -d
```

**Option B: Local Python**

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Cara Penggunaan

### Commands

| Command | Deskripsi |
|---------|-----------|
| `/start` | Mulai bot dan lihat menu |
| `/catat` | Mulai pencatatan manual |
| `/laporan` | Lihat laporan keuangan |
| `/sheet` | Cek status Google Sheets |
| `/hapus` | Hapus transaksi terakhir |
| `/help` | Bantuan penggunaan |

### Contoh Pencatatan

**Manual Input:**
```
Makan siang 35rb
Bensin motor 50k
Gaji masuk 5jt
Bayar listrik 250000
```

**Upload Struk:**
1. Kirim foto struk ke bot
2. Pilih mode pencatatan:
   - Total saja
   - Per item
   - Per kategori
3. Konfirmasi data yang diekstrak

## Deployment Options

### Docker Compose (VPS/Cloud VM)

```bash
# Clone dan setup
git clone https://github.com/YOUR_USERNAME/telegram-finance-bot.git
cd telegram-finance-bot
cp .env.example .env
nano .env  # Edit credentials

# Run
docker-compose up -d

# Check logs
docker-compose logs -f
```

### GCP Free Tier (e2-micro)

1. Buat VM instance e2-micro (free tier)
2. SSH ke VM
3. Install Docker:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose
   sudo usermod -aG docker $USER
   ```
4. Clone repo dan setup `.env`
5. Jalankan `docker-compose up -d`

### Railway

1. Fork repository ini
2. Connect ke Railway
3. Set environment variables di Railway dashboard
4. Deploy otomatis

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token dari @BotFather |
| `GEMINI_API_KEY` | Yes | API key dari Google AI Studio |
| `AUTHORIZED_USER_ID` | Yes | Telegram user ID yang diizinkan |
| `SPREADSHEET_ID` | No | Google Sheets ID untuk penyimpanan |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` | No | Service account JSON credentials |

### Gemini Model

Bot menggunakan `gemini-2.0-flash-lite` yang cost-efficient:
- Input: $0.075 / 1M tokens
- Output: $0.30 / 1M tokens

Untuk ~1000 struk/bulan, estimasi biaya < $0.50

## Project Structure

```
telegram-finance-bot/
├── main.py              # Main bot application
├── requirements.txt     # Python dependencies
├── Dockerfile          # Docker image definition
├── docker-compose.yml  # Docker Compose configuration
├── .env.example        # Environment variables template
├── .gitignore          # Git ignore rules
└── README.md           # This file
```

## Troubleshooting

### Bot tidak merespons
- Cek `TELEGRAM_TOKEN` sudah benar
- Pastikan bot sudah di-start dengan `/start`
- Cek `AUTHORIZED_USER_ID` sudah include ID Anda

### Rate limit error (429)
- Bot sudah punya retry logic built-in
- Jika sering terjadi, pertimbangkan upgrade ke paid tier Gemini

### Google Sheets tidak tersinkron
- Pastikan `SPREADSHEET_ID` benar
- Pastikan service account sudah di-share ke spreadsheet
- Cek `GOOGLE_SHEETS_CREDENTIALS_JSON` formatnya valid JSON

### Cara cek Telegram User ID
Kirim pesan ke [@userinfobot](https://t.me/userinfobot) untuk mendapatkan ID Anda.

## Contributing

Pull requests are welcome! Untuk perubahan besar, silakan buka issue terlebih dahulu.

1. Fork repository
2. Buat feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

## License

MIT License

Copyright (c) 2025 Irfan Yulianto

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

## Acknowledgments

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [Google Gemini API](https://ai.google.dev/)
- [gspread](https://github.com/burnash/gspread)
