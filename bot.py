import os
import logging
from telegram.ext import ApplicationBuilder, CommandHandler

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# دالة الاستجابة لأمر /start
async def start(update, context):
    await update.message.reply_text('البوت يعمل الآن بشكل صحيح!')

if __name__ == '__main__':
    # الحصول على التوكن من المتغيرات البيئية
    token = os.environ.get("BOT_TOKEN")
    
    if not token:
        print("خطأ: لم يتم العثور على BOT_TOKEN")
    else:
        # بناء التطبيق بالطريقة الحديثة
        application = ApplicationBuilder().token(token).build()
        
        # إضافة المعالج
        start_handler = CommandHandler('start', start)
        application.add_handler(start_handler)
        
        # تشغيل البوت
        print("البوت يعمل...")
        application.run_polling()
