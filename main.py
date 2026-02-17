import sqlite3
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.ext import ApplicationHandlerStop  # <-- para parar handlers corretamente

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

def salvar_usuario_pago(user_id: int):
    cursor.execute(
        "INSERT OR IGNORE INTO usuarios_pagos (user_id) VALUES (?)",
        (user_id,)
    )
    conn.commit()


def usuario_tem_acesso(user_id: int) -> bool:
    cursor.execute(
        "SELECT user_id FROM usuarios_pagos WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchone() is not None


# === BLOQUEIO GLOBAL (SÓ COMANDOS) === #

async def bloquear_nao_pagantes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Só processa mensagens com texto
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id

    # Admin sempre liberado
    if user_id == ADMIN_ID:
        return

    # Comando (sem parâmetros)
    comando = update.message.text.split()[0].replace("/", "")

    # Comandos liberados
    if comando in COMANDOS_LIVRES:
        return

    # Bloqueia se não pagou
    if not usuario_tem_acesso(user_id):
        await update.message.reply_text(
            "🔒 Este comando é exclusivo para membros.\n\n"
            "Digite /start para adquirir acesso."
        )
        # Interrompe o processamento de handlers seguintes
        raise ApplicationHandlerStop


async def verificar_acesso(update: Update) -> bool:
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
    keyboard = [[InlineKeyboardButton("🔓 Quero Acesso", callback_data="quero_acesso")]]

    await update.message.reply_text(
        "🚀 Sistema IA Lucrativa\n\n"
        "Aprenda a gerar renda usando Inteligência Artificial.\n\n"
        "Clique abaixo para desbloquear o acesso completo.",
        reply_markup=InlineKeyboardMarkup(keyboard),
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
    user_id = update.effective_user.id
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


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Você não tem permissão.")
        return

    cursor.execute("SELECT user_id FROM usuarios_pagos")
    usuarios = cursor.fetchall()

    total = len(usuarios)
    lista_ids = "\n".join([str(u[0]) for u in usuarios]) if usuarios else "Nenhum usuário ainda."

    await update.message.reply_text(
        f"📊 PAINEL ADMIN\n\n"
        f"👥 Total pagos: {total}\n\n"
        f"📋 IDs:\n{lista_ids}"
    )


# === POST INIT (limpa webhook) === #
async def post_init(app):
    await app.bot.delete_webhook(drop_pending_updates=True)


# === INICIAR BOT === #

if __name__ == "__main__":
    print("🚀 Iniciando bot...")

    if not TOKEN:
        raise ValueError("❌ TELEGRAM_TOKEN não encontrado!")

    print("✅ Token carregado com sucesso!")

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    # bloqueio primeiro (group=0)
    app.add_handler(MessageHandler(filters.COMMAND, bloquear_nao_pagantes), group=0)

    # comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("liberar", liberar))
    app.add_handler(CommandHandler("verificar", verificar))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("admin", admin))

    # callbacks
    app.add_handler(CallbackQueryHandler(botoes))

    print("🤖 Bot rodando...")
    app.run_polling(drop_pending_updates=True)
