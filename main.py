import os
import sqlite3
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
PUBLIC_URL = os.getenv("PUBLIC_URL")  # ex: https://xxxx.up.railway.app (SEM / no final)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")

ADMIN_ID = 5680777509
COMANDOS_LIVRES = ["start", "liberar", "verificar", "admin"]

# === DB ===
conn = sqlite3.connect("usuarios.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios_pagos (
    user_id INTEGER PRIMARY KEY
)
""")
conn.commit()

def salvar_usuario_pago(user_id: int):
    cursor.execute("INSERT OR IGNORE INTO usuarios_pagos (user_id) VALUES (?)", (user_id,))
    conn.commit()

def usuario_tem_acesso(user_id: int) -> bool:
    cursor.execute("SELECT user_id FROM usuarios_pagos WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None


# === BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔓 Quero Acesso", callback_data="quero_acesso")]]
    await update.message.reply_text(
        "🚀 Sistema IA Lucrativa\n\n"
        "Aprenda a gerar renda usando Inteligência Artificial.\n\n"
        "Clique abaixo para desbloquear o acesso completo.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def botoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chave_pix = "c5073f6f-214d-4db1-8323-472b64bd9be3"

    if query.data == "quero_acesso":
        keyboard = [
            [InlineKeyboardButton("📋 Copiar Chave Pix", callback_data="copiar_pix")],
            [InlineKeyboardButton("✅ Já Paguei", callback_data="ja_paguei")],
        ]
        await query.edit_message_text(
            "💎 Acesso Completo ao Sistema IA Lucrativa\n\n"
            "Valor: R$29,90\n\n"
            "Clique abaixo para copiar sua chave Pix:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "copiar_pix":
        await query.message.reply_text(
            f"📋 Toque e segure para copiar:\n\n`{chave_pix}`",
            parse_mode="Markdown",
        )

    elif query.data == "ja_paguei":
        user = query.from_user
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🚨 Novo pedido de verificação de pagamento!\n\n"
                f"👤 Nome: {user.full_name}\n"
                f"🆔 ID: {user.id}\n"
                f"📎 Username: @{user.username if user.username else 'Não possui'}"
            ),
        )
        await query.edit_message_text(
            "📩 Recebemos sua solicitação!\n\n"
            "Seu pagamento será verificado.\n"
            "Assim que confirmado, você receberá acesso."
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

async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if usuario_tem_acesso(update.effective_user.id):
        await update.message.reply_text("🔓 Você tem acesso.")
    else:
        await update.message.reply_text("❌ Você NÃO tem acesso.")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID and not usuario_tem_acesso(user_id):
        await update.message.reply_text("🔒 Acesso exclusivo.\n\nDigite /start para adquirir acesso.")
        return
    await update.message.reply_text("📚 Bem-vindo ao Sistema IA Lucrativa\n\nEm breve aqui estarão os módulos.")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Você não tem permissão.")
        return
    cursor.execute("SELECT user_id FROM usuarios_pagos")
    usuarios = cursor.fetchall()
    total = len(usuarios)
    lista_ids = "\n".join([str(u[0]) for u in usuarios]) if usuarios else "Nenhum usuário ainda."
    await update.message.reply_text(
        f"📊 PAINEL ADMIN\n\n👥 Total pagos: {total}\n\n📋 IDs:\n{lista_ids}"
    )


# === FASTAPI + APP ===
api = FastAPI()
ptb_app: Application = Application.builder().token(TOKEN).build()

ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("liberar", liberar))
ptb_app.add_handler(CommandHandler("verificar", verificar))
ptb_app.add_handler(CommandHandler("menu", menu))
ptb_app.add_handler(CommandHandler("admin", admin))
ptb_app.add_handler(CallbackQueryHandler(botoes))


@api.on_event("startup")
async def on_startup():
    if not TOKEN or not PUBLIC_URL:
        raise RuntimeError("Configure TELEGRAM_TOKEN e PUBLIC_URL nas variáveis do Railway.")

    # normaliza URL (remove / final)
    base = PUBLIC_URL.rstrip("/")
    webhook_url = f"{base}/webhook/{WEBHOOK_SECRET}"

    await ptb_app.initialize()
    await ptb_app.start()

    # limpa webhook antigo e seta o novo
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
    # útil pra você checar se o Telegram gravou a URL do webhook
    info = await ptb_app.bot.get_webhook_info()
    return {
        "url": info.url,
        "has_custom_certificate": info.has_custom_certificate,
        "pending_update_count": info.pending_update_count,
        "last_error_date": info.last_error_date,
        "last_error_message": info.last_error_message,
        "max_connections": info.max_connections,
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
        # não deixa o Telegram "re-tentar" por erro do seu app
        return {"ok": False, "error": str(e)}

    return {"ok": True}
