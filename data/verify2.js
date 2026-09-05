// end-to-end: original ST_July_copy.xlsx  ->  live ROKUDO Data / SKUs
const SP = process.env.SP;
const X = require(SP + '/package/xlsx.js');

const src = X.readFile('/root/.claude/uploads/4070dcfc-cfbd-5af7-8efb-39ba0e83ae1b/18905f11-ST_July_copy.xlsx').Sheets['Sheet1'];
const g = ref => (src[ref] ? src[ref].v : '');

// row ranges read off the column-E merges; pattern names read off the embedded images
const GROUPS = [
  ['Qirin 990', 6, 30], ['Roadtrexx H/T', 31, 31], ['UHP1', 32, 35],
  ['Terraintrexx A/T', 36, 43], ['Mudtrexx M/T', 45, 49],
  ['Crossover', 54, 57], ['Qirin 990 EV', 64, 88],
];

const srcRows = [];
for (const [pattern, from, to] of GROUPS)
  for (let r = from; r <= to; r++) {
    const size = String(g('F' + r)).trim();
    if (size) srcRows.push({ srcRow: r, pattern, size, li: String(g('G' + r)).trim(), cost: g('J' + r), price: g('K' + r) });
  }

const live = X.utils.sheet_to_json(X.readFile(SP + '/rokudo_after.xlsx').Sheets['SKUs'], { header: 1, defval: '', blankrows: false });
const H = live[0];
const c = n => H.indexOf(n);
const newRows = live.slice(333);

let fail = 0;
console.log('ต้นฉบับ ' + srcRows.length + ' ไซซ์  vs  ในชีต ' + newRows.length + ' แถว');
if (srcRows.length !== newRows.length) { console.log('  x จำนวนไม่ตรง'); fail++; }

srcRows.forEach((s, i) => {
  const l = newRows[i]; if (!l) return;
  const wl = /\bWL\b/.test(s.size);
  const checks = [
    ['size', s.size.replace(/\s*WL$/, ''), String(l[c('size')]).trim()],
    ['loadSpeed', s.li, String(l[c('loadSpeed')]).trim()],
    ['model', s.pattern, String(l[c('model')]).trim()],
    ['pattern', s.pattern + (wl ? ' WL' : ''), String(l[c('pattern')]).trim()],
    ['wholesale(Pack 12)', String(s.cost), String(l[c('wholesale')])],
    ['retail(ราคาแนะนำขาย)', String(s.price), String(l[c('retail')])],
  ];
  for (const [f, want, got] of checks)
    if (want !== got) { if (fail < 10) console.log('  x ' + l[0] + ' (ST แถว ' + s.srcRow + ') ' + f + ': ต้นฉบับ "' + want + '" ในชีต "' + got + '"'); fail++; }
});

console.log('');
console.log(fail ? 'FAIL: ' + fail + ' ช่องไม่ตรง' : 'PASS: ทุกไซซ์ ทุกราคา ทุกรุ่น ตรงกับ ST_July ต้นฉบับ 100%');
