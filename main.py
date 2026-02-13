import os
import mercadopago
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")

sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("💳 Comprar acesso - R$5,90", callback_data="comprar")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Acesso aos prompts premium por apenas R$5,90.\nClique abaixo para pagar:",
        reply_markup=reply_markup
    )

async def comprar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    payment_data = {
        "transaction_amount": 5.90,
        "description": "Acesso Prompts Premium",
        "payment_method_id": "pix",
        "payer": {
            "email": "comprador@email.com"
        }
    }

    payment = sdk.payment().create(payment_data)

    pix_code = payment["response"]["point_of_interaction"]["transaction_data"]["qr_code"]

    await query.message.reply_text(
        f"Copie o código PIX abaixo e pague:\n\n{pix_code}"
    )

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(comprar, pattern="comprar"))

    print("Bot rodando...")
    app.run_polling()

if __name__ == "__main__":
    main()
