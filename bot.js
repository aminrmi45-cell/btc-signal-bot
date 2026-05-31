const fetch = require('node-fetch');

const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;
const CHAT_ID = process.env.CHAT_ID;
const TWELVE_KEY = process.env.TWELVE_KEY;

const ema = (arr, period) => {
  const k = 2 / (period + 1);
  let val = arr[0];
  for (let i = 1; i < arr.length; i++)
    val = arr[i] * k + val * (1 - k);
  return val;
};

const rsi = (closes, period = 14) => {
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) gains += diff;
    else losses += Math.abs(diff);
  }
  const rs = gains / losses;
  return 100 - (100 / (1 + rs));
};

const calcADX = (highs, lows, closes) => {
  let trList = [], dmP = [], dmM = [];
  for (let i = 1; i < closes.length; i++) {
    trList.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i-1]),
      Math.abs(lows[i] - closes[i-1])
    ));
    dmP.push(highs[i] - highs[i-1] > lows[i-1] - lows[i] ?
      Math.max(highs[i] - highs[i-1], 0) : 0);
    dmM.push(lows[i-1] - lows[i] > highs[i] - highs[i-1] ?
      Math.max(lows[i-1] - lows[i], 0) : 0);
  }
  const atr = trList.slice(-14).reduce((a,b) => a+b, 0) / 14;
  const diP = dmP.slice(-14).reduce((a,b) => a+b, 0) / 14 / atr * 100;
  const diM = dmM.slice(-14).reduce((a,b) => a+b, 0) / 14 / atr * 100;
  return { adx: Math.abs(diP-diM) / (diP+diM) * 100 };
};

const calcSqueeze = (highs, lows, closes, period = 20) => {
  const bb_mult = 2.0, kc_mult = 1.5;
  const mean = arr => arr.reduce((a,b) => a+b, 0) / arr.length;
  const stdDev = arr => {
    const m = mean(arr);
    return Math.sqrt(arr.reduce((a,b) => a + (b-m)**2, 0) / arr.length);
  };
  const slice  = closes.slice(-period);
  const sliceH = highs.slice(-period);
  const sliceL = lows.slice(-period);
  const basis  = mean(slice);
  const dev    = stdDev(slice);
  const upperBB = basis + bb_mult * dev;
  const lowerBB = basis - bb_mult * dev;
  const trList = [];
  for (let i = closes.length - period; i < closes.length; i++) {
    trList.push(Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i-1]),
      Math.abs(lows[i] - closes[i-1])
    ));
  }
  const atr = mean(trList);
  const upperKC = basis + kc_mult * atr;
  const lowerKC = basis - kc_mult * atr;
  const sqzOn  = lowerBB > lowerKC && upperBB < upperKC;
  const highest = Math.max(...sliceH);
  const lowest  = Math.min(...sliceL);
  const delta   = closes[closes.length-1] - ((highest + lowest) / 2 + basis) / 2;
  const prevSlice  = closes.slice(-period-1, -1);
  const prevSliceH = highs.slice(-period-1, -1);
  const prevSliceL = lows.slice(-period-1, -1);
  const prevBasis  = mean(prevSlice);
  const prevHighest = Math.max(...prevSliceH);
  const prevLowest  = Math.min(...prevSliceL);
  const prevDelta  = closes[closes.length-2] -
    ((prevHighest + prevLowest) / 2 + prevBasis) / 2;
  return { sqzOn, delta, prevDelta };
};

const checkHighImpactNews = async () => {
  try {
    const now = new Date();
    const url = `https://nfs.faireconomy.media/ff_calendar_thisweek.json`;
    const res = await fetch(url);
    const data = await res.json();
    const highImpact = data.filter(event =>
      event.impact === "High" &&
      ["USD","EUR","GBP","JPY","CHF"].includes(event.currency)
    );
    for (const event of highImpact) {
      const eventTime = new Date(event.date);
      const diffMinutes = (eventTime - now) / 1000 / 60;
      if (diffMinutes > -30 && diffMinutes < 30) {
        return { hasNews: true, newsTitle: event.title, newsCurrency: event.currency };
      }
    }
    return { hasNews: false };
  } catch(e) {
    return { hasNews: false };
  }
};

const getCandles = async (symbol, interval, size = 100) => {
  const url = `https://api.twelvedata.com/time_series?symbol=${symbol}&interval=${interval}&outputsize=${size}&apikey=${TWELVE_KEY}`;
  const res  = await fetch(url);
  const data = await res.json();
  if (!data.values) return null;
  const candles = data.values.reverse();
  return {
    closes: candles.map(c => parseFloat(c.close)),
    highs:  candles.map(c => parseFloat(c.high)),
    lows:   candles.map(c => parseFloat(c.low)),
    price:  parseFloat(candles[candles.length-1].close)
  };
};

const analyzeSymbol = async (symbol, name) => {
  try {
    const h1 = await getCandles(symbol, "1h", 100);
    const h4 = await getCandles(symbol, "4h", 100);
    if (!h1 || !h4) return null;

    const price = h1.price;
    const ema20_h1  = ema(h1.closes, 20);
    const ema50_h1  = ema(h1.closes, 50);
    const ema200_h1 = ema(h1.closes, 200);
    const rsi_h1    = rsi(h1.closes);
    const { adx: adx_h1 } = calcADX(h1.highs, h1.lows, h1.closes);
    const sqz_h1    = calcSqueeze(h1.highs, h1.lows, h1.closes);

    const ema50_h4  = ema(h4.closes, 50);
    const ema200_h4 = ema(h4.closes, 200);
    const rsi_h4    = rsi(h4.closes);

    const h4NotBearish = !(ema50_h4 < ema200_h4 && rsi_h4 < 40);
    const h4NotBullish = !(ema50_h4 > ema200_h4 && rsi_h4 > 60);

    const buySignal  = ema20_h1 > ema50_h1 &&
                       rsi_h1 > 35 && rsi_h1 < 65 &&
                       adx_h1 > 20 &&
                       !sqz_h1.sqzOn && sqz_h1.delta > 0 &&
                       price > ema200_h1 &&
                       h4NotBearish;

    const sellSignal = ema20_h1 < ema50_h1 &&
                       rsi_h1 > 35 && rsi_h1 < 65 &&
                       adx_h1 > 20 &&
                       !sqz_h1.sqzOn && sqz_h1.delta < 0 &&
                       price < ema200_h1 &&
                       h4NotBullish;

    if (!buySignal && !sellSignal) return null;

    const isBuy  = buySignal;
    const action = isBuy ? "BUY 🟢" : "SELL 🔴";

    const atr = h1.highs.slice(-14).reduce((a,b) => a+b, 0) / 14
              - h1.lows.slice(-14).reduce((a,b) => a+b, 0) / 14;
    const sl  = isBuy ? price - atr * 1.5 : price + atr * 1.5;
    const tp1 = isBuy ? price + atr * 1.0 : price - atr * 1.0;
    const tp2 = isBuy ? price + atr * 2.0 : price - atr * 2.0;
    const tp3 = isBuy ? price + atr * 3.0 : price - atr * 3.0;

    const sqzStatus = sqz_h1.sqzOn ? "ضغط 🔴" :
                     sqz_h1.delta > 0 && sqz_h1.delta > sqz_h1.prevDelta ? "أخضر فاتح 🟢" :
                     sqz_h1.delta > 0 ? "أخضر داكن 🟡" :
                     sqz_h1.delta < 0 && sqz_h1.delta < sqz_h1.prevDelta ? "أحمر فاتح 🔴" : "أحمر داكن 🟠";

    const now = new Date().toLocaleTimeString('ar-SA');

    return `${action} ${name}
💰 السعر: ${price.toFixed(5)}
🎯 TP1: ${tp1.toFixed(5)}
🎯 TP2: ${tp2.toFixed(5)}
🎯 TP3: ${tp3.toFixed(5)}
❌ SL: ${sl.toFixed(5)}
📊 RSI: ${rsi_h1.toFixed(1)}
📈 ADX: ${adx_h1.toFixed(1)}
⚡ Squeeze: ${sqzStatus}
🕐 الوقت: ${now}
⏰ الإطار: H1 + H4`;

  } catch(e) {
    return null;
  }
};

const main = async () => {
  const newsCheck = await checkHighImpactNews();
  if (newsCheck.hasNews) {
    console.log(`⛔ خبر قوي: ${newsCheck.newsTitle}`);
    return;
  }

  const symbols = [
    { symbol: "BTC/USD", name: "BTCUSD" },
    { symbol: "ETH/USD", name: "ETHUSD" },
    { symbol: "EUR/USD", name: "EURUSD" },
    { symbol: "GBP/USD", name: "GBPUSD" },
    { symbol: "USD/JPY", name: "USDJPY" },
    { symbol: "USD/CHF", name: "USDCHF" },
  ];

  let messages = [];
  for (const s of symbols) {
    const msg = await analyzeSymbol(s.symbol, s.name);
    if (msg) messages.push(msg);
  }

  if (messages.length === 0) {
    console.log("لا توجد إشارة الآن ⏳");
    return;
  }

  for (const message of messages) {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: CHAT_ID, text: message })
    });
  }

  console.log(`✅ تم إرسال ${messages.length} إشارة`);
};

main();
