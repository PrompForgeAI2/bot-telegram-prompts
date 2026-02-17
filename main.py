import sqlite3
import os
from telegram.ext import MessageHandler, filters
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler


TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = 5680777509  # coloque seu ID real aqui
COMANDOS_LIVRES = ["start", "liberar", "verificar"]



# === BANCO DE DADOS === #
conn = sqlite3.connect("usuarios.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios_pagos (
    user_id INTEGER PRIMARY KEY
)
""")

conn.commit()
async def bloquear_nao_pagantes(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Se não for mensagem de texto, ignora
    if not update.message:
        return

    user_id = update.effective_user.id

    # Admin sempre liberado
    if user_id == ADMIN_ID:
        return

    # Pega o comando digitado
    if update.message.text.startswith("/"):
        comando = update.message.text.split()[0].replace("/", "")

        if comando in COMANDOS_LIVRES:
            return

        if not usuario_tem_acesso(user_id):
            await update.message.reply_text(
                "🔒 Este comando é exclusivo para membros.\n\n"
                "Digite /start para adquirir acesso."
            )
            return

async def verificar_acesso(update: Update):
    user_id = update.effective_user.id

    # Admin sempre tem acesso
    if user_id == ADMIN_ID:
        return True

    if usuario_tem_acesso(user_id):
        return True

    await update.message.reply_text(
        "🔒 Você ainda não tem acesso ao conteúdo.\n\n"
        "Digite /start para adquirir acesso."
    )

    return False

def salvar_usuario_pago(user_id):
    cursor.execute("INSERT OR IGNORE INTO usuarios_pagos (user_id) VALUES (?)", (user_id,))
    conn.commit()


def usuario_tem_acesso(user_id):
    cursor.execute("SELECT user_id FROM usuarios_pagos WHERE user_id = ?", (user_id,))
    resultado = cursor.fetchone()
    return resultado is not None


# ===== FUNÇÕES =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔓 Quero Acesso", callback_data="quero_acesso")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🚀 Sistema IA Lucrativa\n\n"
        "Aprenda a gerar renda usando Inteligência Artificial.\n\n"
        "Clique abaixo para desbloquear o acesso completo.",
        reply_markup=reply_markup
    )
async def botoes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chave_pix = "c5073f6f-214d-4db1-8323-472b64bd9be3"

    if query.data == "quero_acesso":
        keyboard = [
            [InlineKeyboardButton("📋 Copiar Chave Pix", callback_data="copiar_pix")],
            [InlineKeyboardButton("✅ Já Paguei", callback_data="ja_paguei")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "💎 Acesso Completo ao Sistema IA Lucrativa\n\n"
            "Valor: R$29,90\n\n"
            "Clique abaixo para copiar sua chave Pix:",
            reply_markup=reply_markup
        )

    elif query.data == "copiar_pix":
        await query.message.reply_text(
            f"📋 Toque e segure para copiar:\n\n`{chave_pix}`",
            parse_mode="Markdown"
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
            )
        )

        await query.edit_message_text(
            "📩 Recebemos sua solicitação!\n\n"
            "Seu pagamento será verificado.\n"
            "Assim que confirmado, você receberá acesso."
        )

async def liberar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Verifica se é o admin
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Você não tem permissão para usar este comando.")
        return

    # Verifica se foi enviado um ID
    if not context.args:
        await update.message.reply_text("⚠️ Use assim:\n/liberar ID_DO_USUARIO")
        return

    try:
        user_id = int(context.args[0])
        salvar_usuario_pago(user_id)

        await update.message.reply_text(f"✅ Usuário {user_id} liberado com sucesso!")

        # Notifica o usuário liberado
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Seu pagamento foi confirmado!\n\nAgora você já pode acessar o sistema usando /menu"
        )

    except:
        await update.message.reply_text("❌ ID inválido.")



async def verificar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if usuario_tem_acesso(user_id):
        await update.message.reply_text("🔓 Você tem acesso.")
    else:
        await update.message.reply_text("❌ Você NÃO tem acesso.")


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await verificar_acesso(update):
        return

    await update.message.reply_text(
        "📚 Bem-vindo ao Sistema IA Lucrativa\n\n"
        "Em breve aqui estarão os módulos."
    )



# ===== INICIAR BOT =====

print("🚀 Iniciando bot...")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.ALL, bloquear_nao_pagantes), group=0)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("liberar", liberar))
app.add_handler(CommandHandler("verificar", verificar))
app.add_handler(CommandHandler("menu", menu))
app.add_handler(CallbackQueryHandler(botoes))


app.run_polling()
