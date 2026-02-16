import sqlite3
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")

# === BANCO DE DADOS ===#
conn = sqlite3.connect("usuarios.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios_pagos (
    user_id INTEGER PRIMARY KEY
)
""")

conn.commit()
def salvar_usuario_pago(user_id):
    cursor.execute("INSERT OR IGNORE INTO usuarios_pagos (user_id) VALUES (?)", (user_id,))
    conn.commit()
def usuario_tem_acesso(user_id):
    cursor.execute("SELECT user_id FROM usuarios_pagos WHERE user_id = ?", (user_id,))
    resultado = cursor.fetchone()
    return resultado is not None
    
    # ===== FUNÇÕES DE TESTE (PASSO 4) =====
async def liberar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    salvar_usuario_pago(user_id)
    await update.message.reply_text("✅ Você foi salvo como pago.")

async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if usuario_tem_acesso(user_id):
        await update.message.reply_text("🔓 Você tem acesso.")
    else:
        await update.message.reply_text("❌ Você NÃO tem acesso.")
        
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot funcionando 🚀")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("liberar", liberar))
    app.add_handler(CommandHandler("verificar", verificar))

    app.run_polling()

if __name__ == "__main__":
    main()
