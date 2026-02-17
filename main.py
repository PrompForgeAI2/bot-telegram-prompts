import sqlite3
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters,
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = 5680777509  # seu ID
COMANDOS_LIVRES = ["start", "liberar", "verificar", "admin"]

# === BANCO DE DADOS === #
conn = sqlite3.connect("usuarios.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios_pagos (
    user_id INTEGER PRIMARY KEY
)
""")
conn.commit()


# === FUNÇÕES DE BANCO === #

def salvar_usuario_pago(user_id):
    cursor.execute(
        "INSERT OR IGNORE INTO usuarios_pagos (user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()


def usuario_tem_acesso(user_id):
    cursor.execute(
        "SELECT user_id FROM usuarios_pagos WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchone() is not None


# === BLOQUEIO GLOBAL === #

async def bloquear_nao_pagantes(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        return

    if update.message.text and update.message.text.startswith("/"):
        comando = update.message.text.split()[0].replace("/", "")

        if comando in COMANDOS_LIVRES:
            return

        if not usuario_tem_acesso(user_id):
            await update.message.reply_text(
                "🔒 Este comando é exclusivo para membros.\n\n"
                "Digite /start para adquirir acesso."
            )


async def verificar_acesso(update: Update):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        return True

    if usuario_tem_acesso(user_id):
        return True

    await update.message.reply_text(
        "🔒 Você ainda não tem acesso ao conteúdo.\n\n"
        "Digite /start para adquirir acesso."
    )
    return False


# === COMANDOS === #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔓 Quero Acesso", callback_data="quero_acesso")]
    ]

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
            [InlineKeyboardButton("✅ Já Paguei", callback_data="ja_paguei")]
