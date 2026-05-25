import os
import asyncio
import logging
from datetime import datetime
import aiohttp
from telegram.ext import Application, CommandHandler

TOKEN   = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
SYMBOL   = "BTCUSDT"
INTERVAL = "5m"
LIMIT    = 150

# نسب وقف الخسارة وجني الأرباح
SL_PCT = 1.5   # وقف الخسارة 1.5%
TP1_PCT = 2.0  # هدف أول 2%
TP2_PCT = 4.0  # هدف ثاني 4%
TP3_PCT = 6.0  # هدف ثالث 6%

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

def ema(prices, period):
    k = 2 / (period + 1)
    val = prices[0]
    for p in prices[1:]:
        val = p * k + val * (1 - k)
    return val

def adx(highs, lows, closes, period=14):
    n = len(closes)
    tr_list, pdm_list, mdm_list = [], [], []
    for i in range(1, n):
        h_diff = highs[i] - highs[i-1]
        l_diff = lows[i-1] - lows[i]
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        tr_list.append(tr)
        pdm_list.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        mdm_list.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)

    def wilder(arr, p):
        s = sum(arr[:p])
        res = [s]
        for v in arr[p:]:
            s = s - s/p + v
            res.append(s)
        return res

    sT  = wilder(tr_list,  period)
    sPD = wilder(pdm_list, period)
    sMD = wilder(mdm_list, period)
    di_plus, di_minus, dx_list = [], [], []
    for i in range(len(sT)):
        p = (sPD[i]/sT[i]*100) if sT[i] else 0
        m = (sMD[i]/sT[i]*100) if sT[i] else 0
        di_plus.append(p); di_minus.append(m)
        s = p + m
        dx_list.append(abs(p-m)/s*100 if s else 0)
    adx_vals = wilder(dx_list, period)
    return adx_vals[-1], di_plus[-1], di_minus[-1]

async def fetch_klines():
    urls = [
        f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}",
        f"https://api1.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}",
        f"https://api2.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}",
    ]
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        raw = await r.json()
                        return {
                            "opens":  [float(c[1]) for c in raw],
                            "highs":  [float(c[2]) for c in raw],
                            "lows":   [float(c[3]) for c in raw],
                            "closes": [float(c[4]) for c in raw],
                        }
            except Exception as e:
                log.warning(f"failed: {e}")
    raise ConnectionError("تعذّر الاتصال بـ Binance")

def calc_levels(price, signal):
    """حساب مستويات وقف الخسارة وجني الأرباح"""
    if signal == "BUY":
        sl  = price * (1 - SL_PCT  / 100)
        tp1 = price * (1 + TP1_PCT / 100)
        tp2 = price * (1 + TP2_PCT / 100)
        tp3 = price * (1 + TP3_PCT / 100)
    elif signal == "SELL":
        sl  = price * (1 + SL_PCT  / 100)
        tp1 = price * (1 - TP1_PCT / 100)
        tp2 = price * (1 - TP2_PCT / 100)
        tp3 = price * (1 - TP3_PCT / 100)
    else:
        return None
    return {"sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3}

def get_signal(data):
    closes = data["closes"]
    highs  = data["highs"]
    lows   = data["lows"]
    price  = closes[-1]
    e6  = ema(closes, 6);  e10 = ema(closes, 10)
    e21 = ema(closes, 21); e55 = ema(closes, 55)
    pe6  = ema(closes[:-1], 6)
    pe21 = ema(closes[:-1], 21)
    adx_val, di_plus, di_minus = adx(highs, lows, closes)
    bull_cross = pe6 <= pe21 and e6 > e21
    bear_cross = pe6 >= pe21 and e6 < e21
    bull_align = e6 > e10 > e21
    bear_align = e6 < e10 < e21
    adx_strong = adx_val > 20
    if (bull_cross or bull_align) and adx_strong and di_plus > di_minus:
        signal = "BUY"
    elif (bear_cross or bear_align) and adx_strong and di_minus > di_plus:
        signal = "SELL"
    else:
        signal = "WAIT"
    levels = calc_levels(price, signal)
    return {"signal": signal, "price": price,
            "ema6": e6, "ema10": e10, "ema21": e21, "ema55": e55,
            "adx": adx_val, "di_plus": di_plus, "di_minus": di_minus,
            "bull_cross": bull_cross, "bear_cross": bear_cross,
            "levels": levels}

def format_message(r, scheduled=False):
    time_str = datetime.now().strftime("%H:%M  %d/%m/%Y")
    if r["signal"] == "BUY":
        header, emoji = "إشارة شراء BUY 🟢", "🚀"
    elif r["signal"] == "SELL":
        header, emoji = "إشارة بيع SELL 🔴", "🔻"
    else:
        header, emoji = "انتظار — لا إشارة ⏳", "😴"
    cross = ""
    if r["bull_cross"]: cross = "\n📌 تقاطع EMA صاعد ✅"
    elif r["bear_cross"]: cross = "\n📌 تقاطع EMA هابط ✅"

    # قسم وقف الخسارة وجني الأرباح
    levels_text = ""
    if r["levels"]:
        lv = r["levels"]
        sl_emoji  = "🛑"
        tp_emoji  = "🎯"
        levels_text = f"""
━━━━━━━━━━━━━━━━
{sl_emoji} *وقف الخسارة:* `${lv['sl']:,.1f}` _(-{SL_PCT}%)_
{tp_emoji} *هدف 1:* `${lv['tp1']:,.1f}` _(+{TP1_PCT}%)_
{tp_emoji} *هدف 2:* `${lv['tp2']:,.1f}` _(+{TP2_PCT}%)_
{tp_emoji} *هدف 3:* `${lv['tp3']:,.1f}` _(+{TP3_PCT}%)_"""

    return f"""
{emoji} *{header}*
{'🔔 تحليل مجدول' if scheduled else '🔍 تحليل فوري'}
━━━━━━━━━━━━━━━━
💰 *السعر:* `${r['price']:,.1f}`
🕐 *الوقت:* `{time_str}`
📊 *ADX:* `{r['adx']:.1f}` {'✅ قوي' if r['adx']>20 else '⚠️ ضعيف'}
📈 *DI+:* `{r['di_plus']:.1f}`  📉 *DI-:* `{r['di_minus']:.1f}`{cross}
━━━━━━━━━━━━━━━━
EMA6: `{r['ema6']:,.0f}` | EMA10: `{r['ema10']:,.0f}`
EMA21: `{r['ema21']:,.0f}` | EMA55: `{r['ema55']:,.0f}`{levels_text}
━━━━━━━━━━━━━━━━
⚠️ _إشارة مساعدة فقط — قرارك أنت_
""".strip()

async def cmd_start(update, context):
    await update.message.reply_text(
        "👋 *مرحباً! أنا بوت إشارات BTC*\n\n"
        "/signal — إشارة فورية\n"
        "/status — حالة المؤشرات\n"
        "/help — المساعدة\n\n"
        "🔔 إشارات تلقائية كل 4 ساعات\n"
        "🛑 وقف الخسارة: 1.5%\n"
        "🎯 أهداف الربح: 2% | 4% | 6%",
        parse_mode="Markdown")

async def cmd_signal(update, context):
    msg = await update.message.reply_text("⏳ جارٍ التحليل...")
    try:
        data = await fetch_klines()
        result = get_signal(data)
        await msg.edit_text(format_message(result, False), parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

async def cmd_status(update, context):
    msg = await update.message.reply_text("⏳ جارٍ التحليل...")
    try:
        data = await fetch_klines()
        r = get_signal(data)
        await msg.edit_text(
            f"📊 *حالة المؤشرات*\n"
            f"💰 السعر: `${r['price']:,.1f}`\n"
            f"📊 ADX: `{r['adx']:.1f}` ({'قوي ✅' if r['adx']>20 else 'ضعيف ⚠️'})\n"
            f"🟢 DI+: `{r['di_plus']:.1f}` | 🔴 DI-: `{r['di_minus']:.1f}`\n"
            f"الإشارة: *{r['signal']}*",
            parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {e}")

async def cmd_help(update, context):
    await update.message.reply_text(
        "📖 *المساعدة*\n"
        "/signal — تحليل فوري مع وقف الخسارة والأهداف\n"
        "/status — قيم المؤشرات\n"
        "⏰ إشارات تلقائية كل 4 ساعات\n"
        "📊 الاستراتيجية: 4EMA + ADX | BTCUSD M5\n\n"
        "🛑 *وقف الخسارة:* 1.5% من سعر الدخول\n"
        "🎯 *الأهداف:*\n"
        "   • هدف 1: +2%\n"
        "   • هدف 2: +4%\n"
        "   • هدف 3: +6%",
        parse_mode="Markdown")

async def send_scheduled(bot):
    try:
        data = await fetch_klines()
        result = get_signal(data)
        await bot.send_message(chat_id=CHAT_ID,
            text=format_message(result, True), parse_mode="Markdown")
    except Exception as e:
        log.error(f"Scheduled error: {e}")

async def scheduled_loop(bot):
    while True:
        await send_scheduled(bot)
        await asyncio.sleep(4 * 60 * 60)

async def post_init(app):
    asyncio.create_task(scheduled_loop(app.bot))

def main():
    if not TOKEN or not CHAT_ID:
        raise ValueError("BOT_TOKEN و CHAT_ID مطلوبان")

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help",   cmd_help))

    log.info("✅ البوت شغال")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

