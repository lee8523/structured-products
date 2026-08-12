// ============================================================
// utils.js — 工具函数 / 计算引擎
// ============================================================

// ============================================================
// 格式化
// ============================================================
function typeLabel(t) { return {'single_shark':'单鲨','three_element':'三元'}[t]||t; }
function retClass(v) { return v>0?'ret-pos':v<0?'ret-neg':'ret-zero'; }
function fmtRet(v) { return (v>0?'+':'')+v.toFixed(2)+'%'; }
function fmtPrice(v) { return (!v||v<=0)?'--':(v>=10000?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):v.toFixed(2)); }
function fmtMoney(v) { return v>=1e8?(v/1e8).toFixed(2)+'亿':v>=1e4?(v/1e4).toFixed(2)+'万':v.toLocaleString('zh-CN',{maximumFractionDigits:2}); }
function esc(s) { if(!s)return''; const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
function showToast(msg) { const el=document.getElementById('toast'); el.textContent=msg; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),3000); }

// ============================================================
// 日期
// ============================================================
function daysBetween(d1, d2) {
    try { return Math.max(0, Math.round((new Date(d2) - new Date(d1)) / 86400000)); } catch(e) { return 365; }
}

function parseDate(val) {
    if (!val) return '';
    if (typeof val === 'number') {
        try {
            const d = XLSX.SSF.parse_date_code(val);
            if (d) return `${d.y}-${String(d.m).padStart(2,'0')}-${String(d.d).padStart(2,'0')}`;
        } catch(e) {}
    }
    const s = String(val).trim();
    for (const fmt of [/(\d{4})-(\d{1,2})-(\d{1,2})/, /(\d{4})\/(\d{1,2})\/(\d{1,2})/, /(\d{4})\.(\d{1,2})\.(\d{1,2})/]) {
        const m = s.match(fmt);
        if (m) return `${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
    }
    return s;
}

// ============================================================
// 定价引擎
// ============================================================
function getInitialPrice(p) {
    if (typeof initialPrices !== 'undefined' && initialPrices[p.product_code] && initialPrices[p.product_code] > 0)
        return initialPrices[p.product_code];
    if (p.initial_price && p.initial_price > 0) return p.initial_price;
    if (typeof priceCache !== 'undefined') {
        const cached = priceCache[p.underlying_code];
        if (cached && cached.price > 0) return cached.price;
    }
    return 0;
}

function emptyResult(p, price) {
    return { ...p, current_price: price||0, nav:0, estimated_return:0, estimated_value:0,
        days_to_maturity:0, progress:0, status:'待输入价格', barrier_status:null, details:{} };
}

function calcSingleShark(p, price) {
    const initial = getInitialPrice(p);
    if (!price || price <= 0 || !initial) return emptyResult(p, price);

    const strikePct = p.strike_pct || 1;
    const strike = initial * strikePct;
    const upBarrier = initial * (p.up_barrier_pct || 0);
    const partRate = p.participation_rate || 0;
    const nonExRate = p.non_exercise_rate || 0;
    const koRate = p.knock_out_rate || 0;
    const notional = p.notional || 10000000;
    const today = new Date().toISOString().slice(0, 10);
    const totalDays = daysBetween(p.start_date, p.maturity_date);
    const elapsed = daysBetween(p.start_date, today);
    const remaining = daysBetween(today, p.maturity_date);
    const progress = totalDays > 0 ? Math.min(elapsed / totalDays, 1) : 0;
    const matured = remaining <= 0;

    let nav, ret, statusText, barrierState;

    if (upBarrier > 0 && price >= upBarrier) {
        ret = koRate;
        nav = 1 + ret;
        statusText = matured ? '已到期(触及障碍)' : '基准情景(触及障碍)';
        barrierState = 'up_barrier_hit';
    } else if (price >= strike) {
        ret = nonExRate + partRate * (price / initial - strikePct);
        nav = 1 + ret;
        statusText = matured ? '已到期(行权价之上)' : '基准情景(行权价之上)';
        barrierState = matured ? 'matured' : 'normal';
    } else {
        ret = nonExRate;
        nav = 1 + ret;
        statusText = matured ? '已到期(行权价之下)' : '基准情景(行权价之下)';
        barrierState = matured ? 'matured' : 'normal';
    }

    const distUp = upBarrier > 0 ? (upBarrier - price) / price * 100 : null;

    return {
        ...p, current_price: price, initial_price_display: initial,
        nav: +nav.toFixed(6), estimated_return: +(ret * 100).toFixed(2),
        estimated_value: +(notional * nav).toFixed(2),
        days_to_maturity: remaining, progress: +(progress * 100).toFixed(1),
        status: statusText,
        barrier_status: {
            state: barrierState, strike, up_barrier: upBarrier,
            dist_up: distUp !== null ? +distUp.toFixed(1) : null,
            current_price: price, initial_price: initial
        },
        details: {
            '行权价': strike.toFixed(2) + ` (${(strikePct*100).toFixed(0)}%)`,
            '上涨障碍': upBarrier > 0 ? upBarrier.toFixed(2) + ` (${(p.up_barrier_pct*100).toFixed(0)}%)` : '无',
            '上涨参与率': (partRate * 100).toFixed(2) + '%',
            '未行权基准': (nonExRate * 100).toFixed(2) + '%',
            '敲出基准': (koRate * 100).toFixed(2) + '%',
            '距上涨障碍': distUp !== null ? distUp.toFixed(1) + '%' : 'N/A',
            '距行权价': ((strike - price) / price * 100).toFixed(1) + '%'
        }
    };
}

function calcThreeElement(p, price) {
    const initial = getInitialPrice(p);
    if (!price || price <= 0 || !initial) return emptyResult(p, price);

    const strike = initial;
    const upBarrier = initial * (p.up_barrier_pct || 1);
    const downBarrier = initial * (p.down_barrier_pct || 0.8);
    const nonExRate = p.non_exercise_rate || 0;
    const koRate = p.knock_out_rate || 0;
    const notional = p.notional || 10000000;
    const today = new Date().toISOString().slice(0, 10);
    const totalDays = daysBetween(p.start_date, p.maturity_date);
    const elapsed = daysBetween(p.start_date, today);
    const remaining = daysBetween(today, p.maturity_date);
    const progress = totalDays > 0 ? Math.min(elapsed / totalDays, 1) : 0;
    const matured = remaining <= 0;

    let nav, ret, statusText, barrierState;

    if (price >= upBarrier) {
        const holdingYears = Math.max(elapsed, 1) / 365;
        ret = koRate * holdingYears;
        nav = 1 + ret;
        statusText = matured ? '已到期(已敲出)' : '已敲出';
        barrierState = 'knock_out';
    } else if (price <= downBarrier) {
        ret = price / initial - 1;
        nav = 1 + ret;
        statusText = matured ? '已到期(已敲入)' : '已敲入';
        barrierState = 'knock_in';
    } else if (matured) {
        if (price >= initial) {
            ret = nonExRate;
            statusText = '已到期(期初价之上)';
        } else {
            ret = 0;
            statusText = '已到期(期初价之下)';
        }
        nav = 1 + ret;
        barrierState = 'matured';
    } else {
        ret = koRate;
        nav = 1 + ret;
        statusText = '基准情景(敲出基准)';
        barrierState = 'normal';
    }

    const distUp = (upBarrier - price) / price * 100;
    const distDown = (price - downBarrier) / price * 100;

    return {
        ...p, current_price: price, initial_price_display: initial,
        nav: +nav.toFixed(6), estimated_return: +(ret * 100).toFixed(2),
        estimated_value: +(notional * nav).toFixed(2),
        days_to_maturity: remaining, progress: +(progress * 100).toFixed(1),
        status: statusText,
        barrier_status: {
            state: barrierState, strike, up_barrier: upBarrier, down_barrier: downBarrier,
            dist_up: +distUp.toFixed(1), dist_down: +distDown.toFixed(1),
            current_price: price, initial_price: initial
        },
        details: {
            '敲出价(100%)': upBarrier.toFixed(2),
            '敲入价(80%)': downBarrier.toFixed(2),
            '期初价': initial.toFixed(2),
            '未行权基准': (nonExRate * 100).toFixed(2) + '%',
            '敲出基准(年化)': (koRate * 100).toFixed(2) + '%/年',
            '距敲出': distUp.toFixed(1) + '%',
            '距敲入': distDown.toFixed(1) + '%'
        }
    };
}

function calculate(p, price) {
    try {
        if (p.product_type === 'three_element') return calcThreeElement(p, price);
        return calcSingleShark(p, price);
    } catch(e) { return emptyResult(p, price); }
}

// ============================================================
// 行情抓取
// ============================================================
function buildSinaUrl(code, market) {
    if (market === 'cn_index') {
        const prefix = code.startsWith('399') ? 'sz' : 'sh';
        return `https://hq.sinajs.cn/list=s_${prefix}${code}`;
    }
    if (market === 'sge') {
        return `https://hq.sinajs.cn/list=hf_GC`;
    }
    if (market === 'futures_shfe') {
        const base = code.replace(/\d+$/, '');
        return `https://hq.sinajs.cn/list=nf_${base.toLowerCase()}0`;
    }
    if (market === 'futures_gfex') {
        const base = code.replace(/\d+$/, '');
        return `https://hq.sinajs.cn/list=nf_${base.toLowerCase()}0`;
    }
    return null;
}

function parseSinaResponse(text, market) {
    const match = text.match(/"([^"]+)"/);
    if (!match) return null;
    const fields = match[1].split(',');
    if (fields.length < 2) return null;
    if (market === 'cn_index') return parseFloat(fields[1]) || null;
    for (const f of fields) { const v = parseFloat(f); if (v > 0) return v; }
    return null;
}

async function fetchPrice(code, market) {
    const url = buildSinaUrl(code, market);
    if (!url) return null;
    const proxies = [
        u => `https://api.allorigins.win/raw?url=${encodeURIComponent(u)}`,
        u => `https://cors.app/run?${encodeURIComponent(u)}`
    ];
    for (const proxy of proxies) {
        try {
            const resp = await fetch(proxy(url), { signal: AbortSignal.timeout(8000) });
            if (!resp.ok) continue;
            const text = await resp.text();
            const price = parseSinaResponse(text, market);
            if (price && price > 0) return price;
        } catch(e) { continue; }
    }
    return null;
}

// ============================================================
// Excel 导入解析
// ============================================================
function parsePctStr(val) {
    if (!val || val === '/' || val === '') return 0;
    let s = String(val).replace('%', '').replace('/年', '').trim();
    let v = parseFloat(s);
    if (isNaN(v)) return 0;
    if (String(val).includes('%')) return v / 100;
    if (v > 10) return v / 100;
    return v;
}

function parsePctLevel(val) {
    if (!val || val === '/' || val === '') return 0;
    let s = String(val).replace('%', '').trim();
    let v = parseFloat(s);
    if (isNaN(v)) return 0;
    return v / 100;
}

function extractUnderlyingCode(name) {
    if (!name) return '';
    let m = name.match(/AU(\d+)/i);
    if (m) return 'AU' + m[1];
    if (name.includes('中证1000')) return '000852';
    if (name.includes('中证500')) return '000905';
    if (name.includes('沪深300')) return '000300';
    m = name.match(/碳酸锂.*?(\d{4})/);
    if (m) return 'LC' + m[1];
    m = name.match(/沪铜.*?(\d{4})/);
    if (m) return 'CU' + m[1];
    return '';
}

function inferMarket(code, name) {
    if (code.startsWith('AU')) return 'sge';
    if (code.startsWith('000') || code.startsWith('399')) return 'cn_index';
    if (code.startsWith('LC')) return 'futures_gfex';
    if (code.startsWith('CU') || code.startsWith('AG') || code.startsWith('AU')) return 'futures_shfe';
    return 'cn_index';
}
