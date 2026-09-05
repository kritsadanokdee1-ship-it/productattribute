const SP = process.env.SP;
const X = require(SP + '/package/xlsx.js');
const fs = require('fs');

const A = X.readFile(SP + '/rokudo_after.xlsx').Sheets['SKUs'];
const now = X.utils.sheet_to_json(A, { header: 1, defval: '', blankrows: false });
const before = JSON.parse(fs.readFileSync(SP + '/existing.json')); // snapshot from before the paste
const H = now[0];
const norm = r => r.map(v => String(v ?? '').trim()).join('');

let fail = 0;
const bad = m => { console.log('  x ' + m); fail++; };

console.log('1) แถวเดิม 1-333 ไม่ถูกแตะ');
if (before.length !== 333) bad('snapshot length ' + before.length);
let changed = 0;
for (let i = 0; i < before.length; i++) if (norm(before[i]) !== norm(now[i])) { if (changed < 5) bad('row ' + (i + 1) + ' changed'); changed++; }
if (!changed) console.log('  ok เหมือนเดิมทุกช่อง (หัวตาราง + 332 แถว)');

console.log('2) 72 แถวใหม่ตรงกับต้นฉบับ');
const want = fs.readFileSync('/home/user/productattribute/data/rokudo_rows_paste.tsv', 'utf8').trim().split('\n').map(l => l.split('\t'));
const got = now.slice(333);
if (got.length !== 72) bad('got ' + got.length + ' rows, want 72');
let diffs = 0;
want.forEach((w, i) => {
  const g = got[i] || [];
  for (let c = 0; c < 26; c++) {
    const a = String(w[c] ?? '').trim(), b = String(g[c] ?? '').trim();
    if (a !== b) { if (diffs < 8) bad(w[0] + ' col ' + (H[c] || c) + ': want "' + a + '" got "' + b + '"'); diffs++; }
  }
});
if (!diffs) console.log('  ok ตรงทุกช่อง 72 x 26 = 1,872 ช่อง');

console.log('3) id ไม่ซ้ำทั้งแท็บ');
const ids = now.slice(1).map(r => String(r[0]).trim()).filter(Boolean);
const dup = [...new Set(ids.filter((v, i) => ids.indexOf(v) !== i))];
dup.length ? bad('ซ้ำ: ' + dup.join(', ')) : console.log('  ok ' + ids.length + ' id ไม่ซ้ำเลย');

console.log('4) wholesale / retail / stock เป็นตัวเลขจริง ไม่ใช่ text');
let txt = 0;
for (let r = 334; r <= 405; r++) for (const c of ['I', 'J', 'K']) {
  const cell = A[c + r];
  if (!cell || cell.t !== 'n') { if (txt < 4) bad(c + r + ' type=' + (cell ? cell.t : 'empty')); txt++; }
}
if (!txt) console.log('  ok ตัวเลขครบ 216 ช่อง');

console.log('5) ราคาขาย > ราคาทุน ทุกแถว');
const cw = H.indexOf('wholesale'), cr = H.indexOf('retail');
const neg = got.filter(r => !(Number(r[cr]) > Number(r[cw])));
neg.length ? bad(neg.length + ' แถวขายต่ำกว่าทุน') : console.log('  ok กำไรเป็นบวกทั้ง 72 แถว');

console.log('6) สรุปยอดในแท็บ');
const tires = now.slice(1).filter(r => r[H.indexOf('category')] === 'tire');
const sentury = tires.filter(r => r[H.indexOf('แบรนด์')] === 'SENTURY');
console.log('  ทั้งแท็บ ' + (now.length - 1) + ' แถว | ยาง ' + tires.length + ' | Sentury ' + sentury.length);

console.log('');
console.log(fail ? 'FAIL: พบปัญหา ' + fail + ' จุด' : 'PASS: ผ่านทุกข้อ');
