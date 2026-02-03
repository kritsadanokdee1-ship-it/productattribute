import { useState, useRef, useCallback } from "react";
import * as XLSX from "sheetjs";

/* ─── CONFIG ─── */
const BATCH = 50;
const WORKERS = 3;

/* ─── SYSTEM PROMPT ─── */
const SYS = `คุณเป็น product attribute extractor สำหรับ retail สินค้า
จาก Name + Category แบ่งออกเป็น 7 fields:

1. brand – แบรนด์สินค้า เช่น พาลโด นีเวีย OPPO UNO
2. product_type – ชื่อ/ประเภทสินค้า เช่น บะหมี่กึ่งแบบแห้ง เซรั่ม หูฟัง
3. flavor – รส/กลิ่น เมื่อมี เช่น รสไก่เผ็ด กลิ่นมะนาว ใส่ "-" ถ้าไม่มี
4. variant – แบบเฉพาะ เช่น เข้มข้น พลัส สูตร1 แบบแห้ง ใส่ "-" ถ้าไม่มี
5. size – ขนาด เช่น 118g 480ml 1kg 4/128 ใส่ "-" ถ้าไม่มี
6. pack – จำนวน เช่น x6 แพ็ค3 60เม็ด ใส่ "-" ถ้าไม่มี
7. color_model – สี หรือ รุ่น เช่น สีขาว Pink TWS01 ใส่ "-" ถ้าไม่มี

กฎสำคัญ:
- แบ่ง Flavor กับ Color ให้ถูก:
  - คำเรื่อง กลิ่น/รส เช่น "กลิ่นกุหลาบ" "รสมะเขือเทศ" -> Flavor
  - สีของสินค้า เช่น ผ้า ครีม เครื่องใช้ เช่น "ปรับผ้า…ฟ้า" -> Color_Model
  - Fabric softener สี เช่น "ไฮยีนปรับผ้าเข้มข้นมอร์นิ่งฮักฟ้า" -> color_model = ฟ้า
- Prefix PM_ 10_ 50_ CP2_ SWF_ KCG_ TWD_ DN_ ใม่ใช่ brand ให้ข้ามไป
- UNO เป็น prefix -> brand = UNO
- Model เช่น M-555 TWS01 HBG-404 G70 -> color_model
- Variant คือ modifier เช่น เข้มข้น พลัส จืด หวาน ไม่ใช่ flavor

ตอบเป็น JSON array เท่านั้น — keys: brand, product_type, flavor, variant, size, pack, color_model
ไม่มี markdown fence ไม่มี explanation`;

/* ─── helpers ─── */
function buildMsg(batch) {
  return (
    batch.map((it, i) => `${i}. Name: "${it.n}" | Category: ${it.c}`).join("\n") +
    "\n\nตอบเป็น JSON array เท่านั้น เรียง index เดียวกัน"
  );
}

async function callClaude(batch) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "claude-sonnet-4-20250514",
      max_tokens: 8000,
      system: SYS,
      messages: [{ role: "user", content: buildMsg(batch) }],
    }),
  });
  if (r.status === 429) throw new Error("429");
  if (!r.ok) throw new Error("HTTP" + r.status);
  const d = await r.json();
  let t = d.content[0].text.trim();
  t = t.replace(/^```json\s*/i, "").replace(/\s*```$/i, "");
  return JSON.parse(t);
}

const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));

/* ─── parse xlsx ─── */
function parseXLSX(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = (e) => {
      try {
        const wb = XLSX.read(e.target.result, { type: "array" });
        res(XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { header: 1 }));
      } catch (err) { rej(err); }
    };
    fr.onerror = rej;
    fr.readAsArrayBuffer(file);
  });
}

/* ─── export xlsx ─── */
function exportXLSX(items, results) {
  const heads = ["Product ID", "Name", "Category", "Brand", "Product_Type", "Flavor", "Variant", "Size", "Pack", "Color_Model"];
  const aoa = [heads];
  items.forEach((it, i) => {
    const e = results[i] || {};
    aoa.push([
      it.id, it.n, it.c,
      e.brand || "-", e.product_type || "-", e.flavor || "-",
      e.variant || "-", e.size || "-", e.pack || "-", e.color_model || "-",
    ]);
  });
  const ws = XLSX.utils.aoa_to_sheet(aoa);
  ws["!cols"] = [12, 48, 30, 18, 24, 18, 24, 10, 8, 20].map((w) => ({ wch: w }));
  heads.forEach((_, c) => {
    const ref = XLSX.utils.encode_cell({ c, r: 0 });
    if (ws[ref])
      ws[ref].s =
        c < 3
          ? { font: { bold: true, color: { rgb: "FFFFFF" }, sz: 110 }, fill: { fgColor: { rgb: "4A90D9" } } }
          : { font: { bold: true, color: { rgb: "FFFFFF" }, sz: 110 }, fill: { fgColor: { rgb: "27AE60" } } };
  });
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Attributes");
  XLSX.writeFile(wb, "Product_Attributes_Output.xlsx");
}

const E0 = { brand: "-", product_type: "-", flavor: "-", variant: "-", size: "-", pack: "-", color_model: "-" };

export default function App() {
  const [status, setStatus] = useState("idle");
  const [items, setItems] = useState([]);
  const [results, setResults] = useState([]);
  const [prog, setProg] = useState({ done: 0, total: 0, err: 0 });
  const [errMsg, setErrMsg] = useState("");
  const stopRef = useRef(false);
  const resRef = useRef([]);

  const onUpload = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setStatus("parsing"); setErrMsg("");
    try {
      const rows = await parseXLSX(f);
      const arr = [];
      for (let i = 1; i < rows.length; i++) {
        const id   = rows[i]?.[0] != null ? String(rows[i][0]).trim() : "";
        const name = rows[i]?.[1] != null ? String(rows[i][1]).trim() : "";
        const cat  = rows[i]?.[7] != null ? String(rows[i][7]).trim() : "";
        if (name) arr.push({ id, n: name, c: cat });
      }
      setItems(arr);
      setProg({ done: 0, total: arr.length, err: 0 });
      setResults([]);
      resRef.current = new Array(arr.length).fill(null);
      setStatus("ready");
    } catch (ex) { setErrMsg(ex.message); setStatus("error"); }
  };

  const onStart = useCallback(async () => {
    setStatus("running");
    stopRef.current = false;

    const batches = [];
    for (let i = 0; i < items.length; i += BATCH)
      batches.push({ start: i, chunk: items.slice(i, i + BATCH) });

    let done = 0, errs = 0, ptr = 0;

    const worker = async () => {
      while (ptr < batches.length && !stopRef.current) {
        const { start, chunk } = batches[ptr++];
        let tries = 4, ok = false;
        while (tries > 0 && !ok && !stopRef.current) {
          try {
            const res = await callClaude(chunk);
            chunk.forEach((_, j) => { resRef.current[start + j] = res[j] || E0; });
            ok = true;
          } catch (ex) {
            if (ex.message === "429") await sleep(33000);
            else { tries--; await sleep(3000); }
          }
        }
        if (!ok) {
          chunk.forEach((_, j) => { resRef.current[start + j] = { ...E0, brand: "ERROR" }; });
          errs += chunk.length;
        }
        done += chunk.length;
        setProg({ done, total: items.length, err: errs });
      }
    };

    await Promise.all(Array.from({ length: WORKERS }, () => worker()));
    setResults([...resRef.current]);
    if (!stopRef.current) setStatus("done");
  }, [items]);

  const pct = prog.total > 0 ? Math.round((prog.done / prog.total) * 100) : 0;
  const N = (n) => Number(n).toLocaleString();

  return (
    <div style={S.root}>
      <div style={S.wrap}>
        <div style={S.card}>
          <h1 style={S.h1}>🏷️ Product Attribute Extractor</h1>
          <p style={S.sub}>แบ่ง Name สินค้า → Brand · Type · Flavor · Variant · Size · Pack · Color/Model</p>
        </div>

        {["idle","error","parsing"].includes(status) && (
          <div style={S.card}>
            <div style={{ textAlign:"center", padding:"24px 0 8px" }}>
              <div style={{ fontSize:52 }}>📂</div>
              <p style={{ color:"#64748b", margin:"10px 0 20px", fontSize:15 }}>
                อัปโลด <b>Test_product_attribute.xlsx</b> ตรงนี้เลย
              </p>
              <label style={S.uploadBtn}>
                เลือกไฟล์ .xlsx
                <input type="file" accept=".xlsx,.xls" onChange={onUpload} style={{ display:"none" }} />
              </label>
              {status==="error"   && <p style={{ color:"#ef4444", marginTop:12, fontSize:13 }}>{errMsg}</p>}
              {status==="parsing" && <p style={{ color:"#3b82f6", marginTop:12, fontSize:13 }}>กำลัง parse…</p>}
            </div>
          </div>
        )}

        {status === "ready" && (
          <div style={S.card}>
            <div style={S.rowSB}>
              <span style={S.bigLabel}>✅ พบ <b>{N(prog.total)}</b> สินค้า</span>
              <button style={S.btnGreen} onClick={onStart}>▶ เริ่ม Extract</button>
            </div>
            <p style={S.lbl}>Preview 10 รายแรก</p>
            <div style={{ overflowX:"auto" }}>
              <table style={S.tbl}>
                <thead><tr style={{ background:"#f1f5f9" }}>
                  {["Product ID","Name","Category"].map(h => <th key={h} style={S.th}>{h}</th>)}
                </tr></thead>
                <tbody>
                  {items.slice(0,10).map((it,i) => (
                    <tr key={i} style={{ borderBottom:"1px solid #f1f5f9" }}>
                      <td style={S.td}>{it.id}</td>
                      <td style={S.td}>{it.n}</td>
                      <td style={S.td}>{it.c}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button style={{ ...S.btnGhost, marginTop:14 }} onClick={() => { setItems([]); setStatus("idle"); }}>← เปลี่ยนไฟล์</button>
          </div>
        )}

        {["running","stopped"].includes(status) && (
          <div style={S.card}>
            <div style={S.rowSB}>
              <span style={S.bigLabel}>{status==="running" ? "⚙️ กำลัง Extract…" : "⏸️ หยุดแล้ว"}</span>
              {status==="running" && <button style={S.btnRed} onClick={() => { stopRef.current = true; setStatus("stopped"); }}>⏹ หยุด</button>}
            </div>
            <div style={{ background:"#e2e8f0", borderRadius:10, height:28, overflow:"hidden", margin:"0 0 8px" }}>
              <div style={{
                background:"linear-gradient(90deg,#3b82f6,#60a5fa)", height:"100%",
                width:`${pct}%`, transition:"width 0.5s",
                display:"flex", alignItems:"center", justifyContent:"center",
                color:"#fff", fontSize:13, fontWeight:700
              }}>{pct > 5 && `${pct}%`}</div>
            </div>
            <p style={S.lbl}>
              {N(prog.done)} / {N(prog.total)} สินค้า
              {prog.err > 0 && <span style={{ color:"#ef4444" }}> · Error {prog.err}</span>}
            </p>
          </div>
        )}

        {status === "done" && (
          <div style={S.card}>
            <div style={S.rowSB}>
              <span style={{ ...S.bigLabel, color:"#16a34a" }}>🎉 เสร็จ! {N(results.length)} สินค้า</span>
              <button style={S.btnGreen} onClick={() => exportXLSX(items, results)}>⬇️ Download xlsx</button>
            </div>
            <p style={S.lbl}>Preview 20 รายแรก</p>
            <div style={{ overflowX:"auto" }}>
              <table style={S.tbl}>
                <thead><tr style={{ background:"#1e293b" }}>
                  {["Product ID","Name","Cat","Brand","Type","Flavor","Variant","Size","Pack","Color"].map(h => (
                    <th key={h} style={{ ...S.th, background:"#1e293b", color:"#fff" }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {results.slice(0,20).map((e,i) => {
                    const it = items[i]||{};
                    return (
                      <tr key={i} style={{ borderBottom:"1px solid #f1f5f9", background: i%2===0?"#fff":"#f8fafc" }}>
                        <td style={S.td}>{it.id}</td>
                        <td style={{ ...S.td, maxWidth:160, wordBreak:"break-all" }}>{it.n}</td>
                        <td style={S.td}>{it.c}</td>
                        <td style={{ ...S.td, fontWeight:600, color:"#2563eb" }}>{e.brand}</td>
                        <td style={S.td}>{e.product_type}</td>
                        <td style={{ ...S.td, color: e.flavor==="-"?"#cbd5e1":"#ca8a04" }}>{e.flavor}</td>
                        <td style={{ ...S.td, color: e.variant==="-"?"#cbd5e1":"#7c3aed" }}>{e.variant}</td>
                        <td style={{ ...S.td, color: e.size==="-"?"#cbd5e1":"#059669" }}>{e.size}</td>
                        <td style={{ ...S.td, color: e.pack==="-"?"#cbd5e1":"#dc2626" }}>{e.pack}</td>
                        <td style={{ ...S.td, color: e.color_model==="-"?"#cbd5e1":"#db2777" }}>{e.color_model}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <button style={{ ...S.btnGhost, marginTop:16 }} onClick={() => { setItems([]); setResults([]); setStatus("idle"); }}>← เริ่มใหม่</button>
          </div>
        )}

        <div style={S.info}>
          <strong>💡</strong> อัปโลด xlsx → กด เริ่ม Extract → รอ progress → กด Download<br/>
          <span style={{ color:"#1e40af" }}>สีน้ำเงิน = เดิม &nbsp;|&nbsp; สีเขียว = ใหม่</span>
        </div>
      </div>
    </div>
  );
}

const S = {
  root:     { fontFamily:"'Segoe UI',system-ui,sans-serif", minHeight:"100vh", background:"#f0f4f8", padding:20 },
  wrap:     { maxWidth:980, margin:"0 auto" },
  card:     { background:"#fff", borderRadius:14, padding:"22px 26px", marginBottom:16, boxShadow:"0 2px 10px rgba(0,0,0,0.07)" },
  h1:       { margin:0, fontSize:20, color:"#1e293b" },
  sub:      { margin:"4px 0 0", color:"#64748b", fontSize:14 },
  rowSB:    { display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 },
  bigLabel: { fontWeight:700, color:"#1e293b", fontSize:16 },
  lbl:      { color:"#64748b", fontSize:13, margin:"14px 0 8px" },
  tbl:      { borderCollapse:"collapse", fontSize:13, width:"100%" },
  th:       { textAlign:"left", padding:"7px 10px", fontWeight:600, whiteSpace:"nowrap", borderBottom:"2px solid #e2e8f0", background:"#f8fafc", fontSize:13 },
  td:       { padding:"5px 10px", whiteSpace:"nowrap" },
  uploadBtn:{ display:"inline-block", background:"#3b82f6", color:"#fff", padding:"11px 28px", borderRadius:8, cursor:"pointer", fontSize:15, fontWeight:600 },
  btnGreen: { background:"#16a34a", color:"#fff", border:"none", padding:"9px 22px", borderRadius:8, cursor:"pointer", fontSize:14, fontWeight:600 },
  btnRed:   { background:"#dc2626", color:"#fff", border:"none", padding:"8px 18px", borderRadius:8, cursor:"pointer", fontSize:13 },
  btnGhost: { background:"none", border:"1px solid #cbd5e1", color:"#64748b", padding:"5px 14px", borderRadius:6, cursor:"pointer", fontSize:13 },
  info:     { background:"#eff6ff", borderRadius:10, padding:"13px 18px", border:"1px solid #bfdbfe", color:"#1e40af", fontSize:13 },
};
