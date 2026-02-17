import os
import re
import base64
import sqlite3
import time
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ======================
# CONFIG
# ======================
TOKEN = os.getenv("TELEGRAM_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # ex: https://xxxx.up.railway.app (SEM / no final)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")  # obrigatório

ADMIN_ID = 5680777509
PRECO = 29.90

# Anti-spam e expiração
PAYMENT_TTL_SECONDS = 15 * 60     # 15 min: se não pagar, expira
CREATE_COOLDOWN_SECONDS = 60      # 60s: impede gerar pagamento sem parar
VERIFY_COOLDOWN_SECONDS = 10      # 10s: impede spam no "verificar"

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# ======================
# DB
# ======================
conn = sqlite3.connect("usuarios.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios (
    user_id INTEGER PRIMARY KEY,
    email TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios_pagos (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pagamentos (
    payment_id TEXT PRIMARY KEY,
    user_id INTEGER,
    status TEXT,
    created_at INTEGER,
    expires_at INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event TEXT,
    detail TEXT,
    ts INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS rate_limits (
    user_id INTEGER PRIMARY KEY,
    last_create_ts INTEGER DEFAULT 0,
    last_verify_ts INTEGER DEFAULT 0
)
""")

conn.commit()


def now_ts() -> int:
    return int(time.time())


def audit(user_id: int, event: str, detail: str = ""):
    cursor.execute(
        "INSERT INTO audit_log (user_id, event, detail, ts) VALUES (?, ?, ?, ?)",
        (user_id, event, detail, now_ts()),
    )
    conn.commit()


def get_email(user_id: int) -> str | None:
    cursor.execute("SELECT email FROM usuarios WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def set_email(user_id: int, email: str):
    cursor.execute("INSERT OR REPLACE INTO usuarios (user_id, email) VALUES (?, ?)", (user_id, email))
    conn.commit()
    audit(user_id, "email_saved", email)


def salvar_usuario_pago(user_id: int):
    cursor.execute("INSERT OR IGNORE INTO usuarios_pagos (user_id) VALUES (?)", (user_id,))
    conn.commit()
    audit(user_id, "access_granted", "usuario_pagos")


def usuario_tem_acesso(user_id: int) -> bool:
    cursor.execute("SELECT user_id FROM usuarios_pagos WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None


def salvar_pagamento(user_id: int, payment_id: str, status: str, created_at: int, expires_at: int):
    cursor.execute(
        "INSERT OR REPLACE INTO pagamentos (payment_id, user_id, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (payment_id, user_id, status, created_at, expires_at),
    )
    conn.commit()


def atualizar_status_pagamento(payment_id: str, status: str):
    cursor.execute(
        "UPDATE pagamentos SET status = ? WHERE payment_id = ?",
        (status, payment_id),
    )
    conn.commit()


def ultimo_pagamento_do_usuario(user_id: int):
    cursor.execute(
        "SELECT payment_id, status, created_at, expires_at FROM pagamentos WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    return cursor.fetchone()  # (payment_id, status, created_at, expires_at) ou None


def ensure_rate_row(user_id: int):
    cursor.execute("INSERT OR IGNORE INTO rate_limits (user_id) VALUES (?)", (user_id,))
    conn.commit()


def can_create_payment(user_id: int) -> tuple[bool, int]:
    ensure_rate_row(user_id)
    cursor.execute("SELECT last_create_ts FROM rate_limits WHERE user_id = ?", (user_id,))
    last = cursor.fetchone()[0] or 0
    wait = (last + CREATE_COOLDOWN_SECONDS) - now_ts()
    return (wait <= 0, max(0, wait))


def mark_created(user_id: int):
    ensure_rate_row(user_id)
    cursor.execute("UPDATE rate_limits SET last_create_ts = ? WHERE user_id = ?", (now_ts(), user_id))
    conn.commit()


def can_verify(user_id: int) -> tuple[bool, int]:
    ensure_rate_row(user_id)
    cursor.execute("SELECT last_verify_ts FROM rate_limits WHERE user_id = ?", (user_id,))
    last = cursor.fetchone()[0] or 0
    wait = (last + VERIFY_COOLDOWN_SECONDS) - now_ts()
    return (wait <= 0, max(0, wait))


def mark_verified(user_id: int):
    ensure_rate_row(user_id)
    cursor.execute("UPDATE rate_limits SET last_verify_ts = ? WHERE user_id = ?", (now_ts(), user_id))
    conn.commit()


def pagamento_ativo_ainda(last_row) -> bool:
    if not last_row:
        return False
    _pid, status, _created, expires_at = last_row
    if status in ("approved", "rejected", "cancelled", "refunded", "charged_back"):
        return False
    return now_ts() < int(expires_at or 0)


# ======================
# MERCADO PAGO
# ======================
async def criar_pagamento_pix(user_id: int, email: str):
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("MP_ACCESS_TOKEN não configurado no Railway.")

    url = "https://api.mercadopago.com/v1/payments"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}

    payload = {
        "transaction_amount": PRECO,
        "description": "Acesso Sistema IA Lucrativa",
        "payment_method_id": "pix",
        "external_reference": str(user_id),
        "payer": {"email": email},
        "notification_url": f"{PUBLIC_URL.rstrip('/')}/mp-webhook",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    payment_id = str(data["id"])
    status = data.get("status", "pending")

    created_at = now_ts()
    expires_at = created_at + PAYMENT_TTL_SECONDS
    salvar_pagamento(user_id, payment_id, status, created_at, expires_at)

    tx = data.get("point_of_interaction", {}).get("transaction_data", {})
    copia_cola = tx.get("qr_code")
    qr_b64 = tx.get("qr_code_base64")

    audit(user_id, "payment_created", f"id={payment_id} status={status}")

    return payment_id, status, copia_cola, qr_b64, expires_at


async def consultar_pagamento(payment_id: str):
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


# ======================
# BOT + FASTAPI
# ======================
api = FastAPI()
ptb_app: Application = Application.builder().token(TOKEN).build()

AGUARDANDO_EMAIL: set[int] = set()


def pagamento_texto(copia_cola: str, payment_id: str, expires_at: int) -> str:
    restante = max(0, expires_at - now_ts())
    mins = restante // 60
    secs = restante % 60
    return (
        "💎 Acesso Completo ao Sistema IA Lucrativa\n\n"
        f"Valor: R${PRECO:.2f}\n\n"
        "✅ Pague via Pix copiando e colando:\n\n"
        f"`{copia_cola}`\n\n"
        f"🧾 ID do pagamento: `{payment_id}`\n"
        f"⏳ Expira em: **{mins:02d}:{secs:02d}**\n\n"
        "Depois de pagar, clique em **Verificar pagamento**."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔓 Quero Acesso", callback_data="quero_acesso")]]
    await update.message.reply_text(
        "🚀 Sistema IA Lucrativa\n\n"
        "Aprenda a gerar renda usando Inteligência Artificial.\n\n"
        "Clique abaixo para desbloquear o acesso completo.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID and not usuario_tem_acesso(user_id):
        await update.message.reply_text("🔒 Acesso exclusivo.\n\nDigite /start para adquirir acesso.")
        return
    await update.message.reply_text("📚 Bem-vindo ao Sistema IA Lucrativa\n\nEm breve aqui estarão os módulos.")


async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if usuario_tem_acesso(update.effective_user.id):
        await update.message.reply_text("🔓 Você tem acesso.")
    else:
        await update.message.reply_text("❌ Você NÃO tem acesso.")


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Você não tem permissão.")
        return

    cursor.execute("SELECT user_id, email FROM usuarios ORDER BY user_id DESC LIMIT 200")
    todos = cursor.fetchall()

    cursor.execute("SELECT user_id FROM usuarios_pagos")
    pagos = set([r[0] for r in cursor.fetchall()])

    total_pagos = len(pagos)

    linhas = []
    for uid, em in todos:
        tag = "✅" if uid in pagos else "⏳"
        linhas.append(f"{tag} {uid} - {em or 'sem email'}")

    await update.message.reply_text(
        f"📊 PAINEL ADMIN\n\n"
        f"👥 Total pagos: {total_pagos}\n\n"
        f"📋 Usuários (últimos 200):\n" + ("\n".join(linhas) if linhas else "Nenhum usuário ainda.")
    )


async def liberar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Você não tem permissão.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Use assim:\n/liberar ID_DO_USUARIO")
        return

    try:
        user_id = int(context.args[0])
        salvar_usuario_pago(user_id)
        await update.message.reply_text(f"✅ Usuário {user_id} liberado!")

        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Pagamento confirmado!\n\nUse /menu para acessar.",
        )
    except ValueError:
        await update.message.reply_text("❌ ID inválido.")


async def capturar_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    if user_id not in AGUARDANDO_EMAIL:
        return

    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("⚠️ Email inválido. Envie novamente (ex: nome@gmail.com).")
        return

    set_email(user_id, email)
    AGUARDANDO_EMAIL.discard(user_id)

    await update.message.reply_text("✅ Email salvo! Agora clique em **Quero Acesso**.", parse_mode="Markdown")


async def botoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # ==========
    # CRIAR / MOSTRAR PIX
    # ==========
    if query.data == "quero_acesso":
        if usuario_tem_acesso(user_id):
            await query.message.reply_text("✅ Você já tem acesso. Use /menu.")
            return

        # 1) exigir email
        email = get_email(user_id)
        if not email:
            AGUARDANDO_EMAIL.add(user_id)
            await query.message.reply_text(
                "📧 Antes de gerar o Pix, me envie seu **email** (o mesmo do Mercado Pago).\n\n"
                "Exemplo: `seunome@gmail.com`",
                parse_mode="Markdown",
            )
            return

        # 2) anti-spam criação
        ok, wait = can_create_payment(user_id)
        if not ok:
            await query.message.reply_text(f"⏳ Aguarde {wait}s para gerar um novo Pix.")
            return

        # 3) se já existe um pagamento ativo recente, reaproveita (não cria outro)
        last = ultimo_pagamento_do_usuario(user_id)
        if pagamento_ativo_ainda(last):
            pid, _status, _created, expires_at = last
            await query.message.reply_text(
                "ℹ️ Você já tem um Pix ativo. Use o mesmo e depois clique em **Verificar pagamento**.\n"
                "Se expirou, aguarde e gere um novo.",
                parse_mode="Markdown",
            )
            keyboard = [[InlineKeyboardButton("🔄 Verificar pagamento", callback_data="verificar_pagamento")]]
            await query.message.reply_text(
                f"🧾 Pagamento ativo: `{pid}`\n⏳ Expira em: {max(0, int(expires_at) - now_ts())//60} min",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # 4) cria novo pix
        mark_created(user_id)
        await query.edit_message_text("⏳ Gerando seu Pix...")

        payment_id, status, copia_cola, qr_b64, expires_at = await criar_pagamento_pix(user_id, email)

        keyboard = [[InlineKeyboardButton("🔄 Verificar pagamento", callback_data="verificar_pagamento")]]

        await query.edit_message_text(
            pagamento_texto(copia_cola, payment_id, expires_at),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

        if qr_b64:
            img_bytes = base64.b64decode(qr_b64)
            await context.bot.send_photo(chat_id=user_id, photo=img_bytes, caption="📌 QR Code Pix")

    # ==========
    # VERIFICAR STATUS
    # ==========
    elif query.data == "verificar_pagamento":
        if usuario_tem_acesso(user_id):
            await query.message.reply_text("✅ Você já tem acesso. Use /menu.")
            return

        ok, wait = can_verify(user_id)
        if not ok:
            await query.message.reply_text(f"⏳ Aguarde {wait}s para verificar novamente.")
            return
        mark_verified(user_id)

        last = ultimo_pagamento_do_usuario(user_id)
        if not last:
            await query.message.reply_text("⚠️ Nenhum pagamento encontrado. Clique em **Quero Acesso**.", parse_mode="Markdown")
            return

        payment_id, status_db, created_at, expires_at = last

        # expirado localmente
        if now_ts() >= int(expires_at):
            atualizar_status_pagamento(payment_id, "expired")
            audit(user_id, "payment_expired", f"id={payment_id}")
            await query.message.reply_text("⌛ Seu Pix expirou. Clique em **Quero Acesso** para gerar outro.", parse_mode="Markdown")
            return

        # consulta MP
        info = await consultar_pagamento(payment_id)
        status = info.get("status", "unknown")
        atualizar_status_pagamento(payment_id, status)
        audit(user_id, "payment_checked", f"id={payment_id} status={status}")

        if status == "approved":
            salvar_usuario_pago(user_id)
            await query.message.reply_text("✅ Pagamento aprovado! Acesso liberado.\n\nUse /menu.")
        else:
            await query.message.reply_text(f"⏳ Status atual: **{status}**.\nTente novamente em alguns segundos.", parse_mode="Markdown")


# ======================
# FASTAPI ROUTES
# ======================
@api.on_event("startup")
async def on_startup():
    if not TOKEN or not PUBLIC_URL:
        raise RuntimeError("Configure TELEGRAM_TOKEN e PUBLIC_URL nas variáveis do Railway.")
    if not MP_ACCESS_TOKEN:
        raise RuntimeError("Configure MP_ACCESS_TOKEN nas variáveis do Railway.")

    base = PUBLIC_URL.rstrip("/")
    webhook_url = f"{base}/webhook/{WEBHOOK_SECRET}"

    await ptb_app.initialize()
    await ptb_app.start()

    await ptb_app.bot.delete_webhook(drop_pending_updates=True)
    await ptb_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)


@api.on_event("shutdown")
async def on_shutdown():
    await ptb_app.stop()
    await ptb_app.shutdown()


@api.get("/")
async def root():
    return {"ok": True}


@api.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@api.get("/webhook-info")
async def webhook_info():
    info = await ptb_app.bot.get_webhook_info()
    return {
        "url": info.url,
        "pending_update_count": info.pending_update_count,
        "last_error_date": info.last_error_date,
        "last_error_message": info.last_error_message,
        "ip_address": info.ip_address,
    }


@api.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")

    data = await request.json()
    try:
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True}


@api.post("/mp-webhook")
async def mp_webhook(request: Request):
    """
    Webhook Mercado Pago:
    - consulta o pagamento real
    - se approved: libera automaticamente
    """
    data = await request.json()

    payment_id = None
    if isinstance(data, dict):
        payment_id = (data.get("data", {}) or {}).get("id") or data.get("id")

    if not payment_id:
        return {"ok": True}

    try:
        info = await consultar_pagamento(str(payment_id))
    except Exception:
        return {"ok": True}

    status = info.get("status", "unknown")
    ext = info.get("external_reference") or "0"

    try:
        user_id = int(ext)
    except ValueError:
        user_id = 0

    if user_id:
        # atualiza status se existir registro
        atualizar_status_pagamento(str(payment_id), status)
        audit(user_id, "mp_webhook", f"id={payment_id} status={status}")

    if status == "approved" and user_id:
        salvar_usuario_pago(user_id)
        try:
            await ptb_app.bot.send_message(
                chat_id=user_id,
                text="🎉 Pagamento confirmado automaticamente!\n\nUse /menu para acessar."
            )
        except:
            pass

    return {"ok": True}


# ======================
# HANDLERS REGISTRATION
# ======================
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("menu", menu))
ptb_app.add_handler(CommandHandler("verificar", verificar))
ptb_app.add_handler(CommandHandler("admin", admin))
ptb_app.add_handler(CommandHandler("liberar", liberar))

ptb_app.add_handler(CallbackQueryHandler(botoes))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, capturar_email))
