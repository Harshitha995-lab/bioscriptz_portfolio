"use strict";
// Everything that comes from Instagram, a website or a model is untrusted. Every dynamic value goes through esc() before it
// reaches innerHTML, and links are only built for instagram.com. Colours and widths are set through classes or the DOM (paint),
// because the page's security policy blocks inline style attributes and inline scripts.
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pad = (n) => String(n).padStart(2, "0");
const LINK_OK = /^https:\/\/(www\.)?instagram\.com\//;
const fmtN = (n) => (n == null ? "?" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n));
const COLORS = new Set(["pink", "orange", "yellow", "mint", "sky", "violet", "surface2", "lav"]);
const chip = (t, c) => `<span class="chip c-${COLORS.has(c) ? c : "surface2"}">${esc(t)}</span>`;
const L = (x) => `<div class="cl">${x}</div>`;
const M = (x) => `<div class="cm">${x}</div>`;
const lnk = (url, txt) => (LINK_OK.test(url || "") ? `<a class="lnk" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(txt)}</a>` : esc(txt));
const quote = (t) => `<span class="quote">“${esc(t)}”</span>`;
const none = (t) => `<span class="muted">${esc(t)}</span>`;

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

const STEPS = [
  { n: "Research", c: "sky", sheets: [0, 1, 2, 3], blurb: "Competitor and brand websites, the real customer comments, and the viral outliers." },
  { n: "Audience avatar", c: "pink", sheets: [4, 5], blurb: "Five awareness stages, sorted from real comments." },
  { n: "Ideation", c: "yellow", sheets: [6], blurb: "Winning structures paired with new angles. You approve before scripting." },
  { n: "Script", c: "mint", sheets: [7], blurb: "Shoot-ready scripts with the full storyboard." },
  { n: "Presentation", c: "orange", sheets: [8], blurb: "One pack for review, with what you still need to bring." },
];
const SHEETS = ["Competitor Research", "Brand & Product", "Market & Customer", "Outlier Data", "Awareness Map", "Audience Avatars", "Ideation SOP", "Script & Storyboard", "Presentation Pack"];
const stepOf = (i) => STEPS.findIndex((s) => s.sheets.includes(i));
const SUBS = [
  ["Reading competitor and brand websites", "Finding and decoding outlier Reels", "Collecting real customer comments"],
  ["Sorting comments by awareness stage", "Writing avatars from those comments"],
  ["Pairing winning formats with new angles", "Waiting for your approval"],
  ["Writing scripts for approved ideas", "Planning shots and storyboard"],
  ["Assembling the workbook", "Listing what you still need to bring"],
];
const STAGE_DO = [
  "Make the problem visible with a moment of recognition. No pitch yet.",
  "Name the problem in their words, validate it, and show it is solvable.",
  "Show why your approach is different and teach them what to look for.",
  "Handle price and trust objections with proof and side-by-side comparisons.",
  "Nudge to action. Reward loyalty and make reordering effortless.",
];
const STAGE_COLOR = ["pink", "orange", "yellow", "mint", "sky"];

const S = { state: {}, view: "start", wb: null, sheet: 0, otab: "4B", script: 0, fs: 3, job: null, approved: new Set(), plan: null, vault: null, remix: {},
  form: { brand: "", category: "", website: "", watch: "", competitor_sites: "", days: "30" }, error: "" };

/* ---------- styles applied through the DOM (the page's security policy blocks style attributes) ---------- */
function paint(root = document) {
  root.querySelectorAll("[data-w]").forEach((e) => { e.style.width = e.dataset.w + "%"; });
  root.querySelectorAll("[data-h]").forEach((e) => { e.style.height = e.dataset.h + "px"; });
  root.querySelectorAll("[data-flex]").forEach((e) => { e.style.flex = e.dataset.flex; });
}
const setApp = (html) => { $("#app").innerHTML = html; paint($("#app")); };

/* ---------- header ---------- */
function renderTop() {
  const sample = S.state.sample;
  $("#topbar").innerHTML = `<button class="logo" data-act="nav" data-v="start" aria-label="Bioscriptz home"><span class="mark">B</span>Bioscriptz</button>
 <span class="pill ${sample ? "sample" : ""}">${sample ? "Sample data · AI: stand-in" : "Live · AI: " + esc(S.state.ai || "?")}${sample ? "" : ` · Apify spent $${esc(S.state.month_spent ?? 0)} of $${esc(S.state.free_credit ?? 5)}`}</span>
 <nav class="nav"><button class="btn sm" data-act="brand" aria-haspopup="dialog">Brand colors</button>
 <button class="btn sm ${S.view === "start" ? "on" : ""}" data-act="nav" data-v="start">New run</button>
 <button class="btn sm ${S.view === "book" ? "on" : ""}" data-act="nav" data-v="book" ${S.wb ? "" : "disabled"}>Workbook</button>
 <button class="btn sm" data-act="vault" ${S.wb ? "" : "disabled"}>Content vault</button>
 <a class="btn sm" href="/classic">Classic view</a></nav>`;
}

/* ---------- start ---------- */
function renderStart() {
  const f = S.form, rec = S.state.workbooks || [];
  setApp(`<section class="hero">
 <span class="pill mint-pill fit">5 steps · 9 sheets · 1 workbook</span>
 <h1>Type a brand. Get the <span class="hl bg-pink">whole</span> <span class="hl bg-yellow">strategy.</span></h1>
 <p>Research, audience avatars, ideas and shoot-ready scripts. Built from what is already winning on Instagram and what real people wrote, not guesswork.</p>
 <form id="startForm" class="formgrid" autocomplete="off">
  <div class="fld"><label for="f-brand">Brand name</label><input id="f-brand" maxlength="40" placeholder="e.g. Minimalist" value="${esc(f.brand)}"></div>
  <div class="fld"><label for="f-category">Category</label><input id="f-category" maxlength="40" placeholder="e.g. skincare" value="${esc(f.category)}"></div>
  <div class="fld"><label for="f-website">Brand website (optional)</label><input id="f-website" maxlength="200" placeholder="https://…" value="${esc(f.website)}"></div>
  <div class="fld"><label for="f-days">Look back</label><select id="f-days">${[7, 14, 30].map((d) => `<option value="${d}" ${String(d) === f.days ? "selected" : ""}>Last ${d} days</option>`).join("")}</select></div>
  <div class="fld"><label for="f-watch">Instagram creators and competitors to watch (optional, up to 30 handles)</label><textarea id="f-watch" maxlength="900" placeholder="@handle1, @handle2 …">${esc(f.watch)}</textarea></div>
  <div class="fld"><label for="f-comp">Competitor websites (optional, one per line, as <b>Name | https://…</b>)</label><textarea id="f-comp" maxlength="900" placeholder="Acme | https://acme.com">${esc(f.competitor_sites)}</textarea></div>
  <div class="row cols"><button class="btn pri" type="submit">Run the strategy</button><span class="muted">You see the cost and confirm before anything is spent.</span></div>
 </form>
 <div id="planBox"></div><div id="startErr" class="err"></div>
 </section>
 <section class="sec"><h2>What happens when you hit run</h2><div class="five">${STEPS.map((s, i) => `<div class="card tint c-${s.c}"><span class="num c-${s.c}">${i + 1}</span><h3>${esc(s.n)}</h3><p>${esc(s.blurb)}</p></div>`).join("")}</div></section>
 <section class="sec"><h2>Your workbook, sheet by sheet</h2><div class="tiles">${SHEETS.map((n, i) => `<div class="tile tint c-${STEPS[stepOf(i)].c}"><b>${i + 1}</b>${esc(n)}</div>`).join("")}</div></section>
 <section class="sec"><h2>Recent runs</h2><div class="recent">${rec.length ? rec.map((r) => `<div class="rrow"><div class="grow"><b>${esc(r.brand)}</b> <span class="muted">· ${esc(r.category)} · ${esc(String(r.at).slice(0, 10))}${r.sample ? " · sample" : ""}</span></div>
  ${chip(r.ideas + " ideas", "yellow")}${chip(r.scripts + " scripts", "mint")}<button class="btn sm" data-act="open-recent" data-id="${esc(r.id)}">Open workbook</button></div>`).join("") : `<div class="empty">No runs yet.</div>`}</div></section>`);
  $("#startForm").addEventListener("submit", (e) => { e.preventDefault(); readForm(); planRun(); });
}
function readForm() {
  S.form = { brand: $("#f-brand").value.trim(), category: $("#f-category").value.trim(), website: $("#f-website").value.trim(), watch: $("#f-watch").value,
    competitor_sites: $("#f-comp").value, days: $("#f-days").value };
}
const payload = (extra) => ({ brand: S.form.brand, category: S.form.category, website: S.form.website, watch: S.form.watch, competitor_sites: S.form.competitor_sites,
  days: Number(S.form.days), ...extra });
async function planRun() {
  $("#startErr").textContent = ""; $("#planBox").innerHTML = "";
  try {
    const plan = await api("/api/wb/plan", payload());
    S.plan = plan;
    if (plan.sample) return startRun(false, false);
    $("#planBox").innerHTML = `<div class="card gate"><h3>Plan for “${esc(plan.topic)}”</h3><p class="m0">${esc(plan.message)}</p>
      <p class="muted small m0">${esc(plan.note)} Estimated Apify cost $${esc((plan.est_cost ?? 0).toFixed(2))} (month so far $${esc((plan.month_spent ?? 0).toFixed(2))} of $5.00).</p>
      ${plan.cached ? `<p class="small m0">You have ${esc(plan.cached.reels)} saved Reels for this brand (${esc(plan.cached.hours_ago)} hours old).</p>` : ""}
      <div class="row"><button class="btn go" data-act="confirm-run" ${plan.ok ? "" : "disabled"}>Run for about $${esc((plan.est_cost ?? 0).toFixed(2))}</button>
      ${plan.cached ? `<button class="btn" data-act="reuse-run">Re-use saved Reels (no Apify cost)</button>` : ""}<button class="btn sm" data-act="cancel-plan">Cancel</button></div></div>`;
  } catch (err) { $("#startErr").textContent = err.message; }
}
async function startRun(confirm, reuse) {
  try {
    const { job } = await api("/api/wb/start", payload({ confirm, reuse }));
    S.job = { id: job, status: "running", messages: [], step: 0 }; S.view = "run"; S.wb = null; S.approved = new Set(); render();
    track(job);
  } catch (err) { const e = $("#startErr"); if (e) e.textContent = err.message; else toast(err.message); }
}

/* ---------- run ---------- */
async function track(jobId) {
  for (;;) {
    await sleep(1200);
    let j;
    try { j = await api("/api/job/" + jobId); } catch (err) { S.job = { ...S.job, status: "error", error: err.message }; break; }
    S.job = j;
    if (S.view === "run") renderRun();
    if (j.status === "error") break;
    if (j.status === "gate") { S.wb = await api("/api/wb?id=" + encodeURIComponent(j.wb_id)); S.approved = new Set(S.wb.ideas.map((_, i) => i)); renderTop(); renderRun(); return; }
    if (j.status === "done") {
      S.wb = await api("/api/wb?id=" + encodeURIComponent(j.wb_id)); S.state = await api("/api/state");
      S.view = "book"; S.sheet = 0; render(); toast("Workbook ready"); return;
    }
  }
  if (S.view === "run") renderRun();
}
function renderRun() {
  if (S.view !== "run") return;
  const j = S.job, step = j.step || 0, gate = j.status === "gate", err = j.status === "error";
  const cards = STEPS.map((st, i) => {
    const done = i < step || j.status === "done", running = i === step && !done && !gate && !err, needs = gate && i === 2;
    const status = done ? chip("Done", "mint") : needs ? chip("Needs you", "pink") : running ? chip("Working", "yellow") : chip("Queued", "surface2");
    return `<div class="card stepc ${!done && !running && !needs ? "queued" : ""}"><div class="hd"><span class="num c-${st.c}">${i + 1}</span><h3>${esc(st.n)}</h3><span class="push">${status}</span></div>
    <ul class="subs">${SUBS[i].map((t) => `<li><span class="dot ${done ? "d" : running ? "r" : ""}">${done ? "✓" : ""}</span><span class="${done || running ? "" : "muted"}">${esc(t)}</span></li>`).join("")}</ul></div>`;
  }).join("");
  const wb = S.wb;
  const gateHtml = gate && wb ? `<div class="card gate cols"><div><h3>Your turn: approve the ideas you would shoot</h3><p class="muted mt4">Scripts are only written for approved ideas. ${wb.ideas.length ? "" : "No ideas could be built from this research."}</p></div>
    <div class="ideas">${wb.ideas.map((x, i) => ideaRow(x, i)).join("")}</div>
    <div class="row"><button class="btn go" data-act="approve-go" ${S.approved.size ? "" : "disabled"}>Approve ${S.approved.size} and write scripts</button><button class="btn sm" data-act="gate-all">Select all</button><button class="btn sm" data-act="gate-none">Clear</button></div></div>` : "";
  const errHtml = err ? `<div class="card warnbox cols"><b>This run stopped.</b><p class="m0">${esc(j.error)}</p><p class="m0 muted">Nothing is lost: saved Reels can be re-used on the next run at no Apify cost.</p></div>` : "";
  setApp(`<div class="runlay"><div class="steps"><div class="card tint c-violet"><div class="row"><h2 class="h2s">Running for ${esc(S.form.brand || (S.wb && S.wb.brand) || "your brand")}</h2>${chip(S.form.category || "", "pink")}</div>
   <p class="muted mt4">${S.state.sample ? "Sample mode: synthetic data, nothing is spent." : "Live run."}</p></div>${cards}</div>
   <div class="stack"><div class="term" aria-live="polite">${(j.messages || []).slice(-13).map((m) => `<div>${esc(m)}</div>`).join("")}${gate || err || j.status === "done" ? "" : `<div class="t">▌</div>`}</div></div>${gateHtml}${errHtml}</div>`);
}
const ideaRow = (x, i) => `<label class="idea"><input type="checkbox" data-act="toggle-idea" data-i="${i}" ${S.approved.has(i) ? "checked" : ""}><span class="g"><b>${esc(x.hook)}</b>
  <span class="row">${chip(x.format, "sky")}${chip(x.angle, "pink")}${x.avatar ? chip(x.avatar, "yellow") : ""}</span></span></label>`;
async function approve() {
  const ids = [...S.approved].sort((a, b) => a - b);
  try {
    const { job } = await api("/api/wb/approve", { id: S.wb.id, approved: ids });
    S.job = { id: job, status: "running", messages: [], step: 3 }; S.view = "run"; render(); track(job);
  } catch (err) { toast(err.message); }
}

/* ---------- workbook ---------- */
function renderBook() {
  const wb = S.wb, st = stepOf(S.sheet);
  setApp(`<div class="bookhd"><div class="grow"><h2>${esc(wb.brand)}</h2><span class="muted">${esc(wb.category)} · ${wb.approved.length} approved ideas · ${esc(String(wb.updated_at).slice(0, 16).replace("T", " "))}${wb.sample ? " · SAMPLE DATA" : ""}</span></div>
 <a class="btn go" href="/api/wb/export?id=${encodeURIComponent(wb.id)}">Export .xlsx</a></div>
 <div class="strip">${STEPS.map((s, i) => `<button class="sp c-${s.c}" data-act="step" data-i="${i}" aria-current="${i === st}"><small>STEP ${i + 1}</small><b>${esc(s.n)}</b></button>`).join("")}</div>
 <div class="sheet st-${STEPS[st].c}">${[sheet1, sheet2, sheet3, sheet4, sheet5, sheet6, sheet7, sheet8, sheet9][S.sheet]()}</div>
 <div class="tabs"><div class="tabsin" role="tablist">${SHEETS.map((n, i) => `<button class="tab c-${STEPS[stepOf(i)].c}" role="tab" data-act="sheet" data-i="${i}" aria-selected="${i === S.sheet}"><i></i>${i + 1} · ${esc(n)}</button>`).join("")}</div></div>`);
}
const tbl = (cols, rows, rowAttr) => `<div class="tw"><table><thead><tr><th class="rn"></th>${cols.map((c) => (typeof c === "string" ? `<th>${esc(c)}</th>` : `<th class="${esc(c.cls)}">${esc(c.t)}</th>`)).join("")}</tr></thead>
 <tbody>${rows.map((r, i) => `<tr ${rowAttr ? rowAttr(i) : ""}><td class="rn">${i + 1}</td>${r.map((x) => `<td>${x}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
const head = (n, sub) => `<div class="shd"><h3>Sheet ${n + 1} · ${esc(SHEETS[n])}</h3>${chip("Step " + (stepOf(n) + 1) + " · " + STEPS[stepOf(n)].n, STEPS[stepOf(n)].c)}<span class="grow muted right">${esc(sub)}</span></div>`;
const empty = (msg) => `<div class="empty">${msg}</div>`;

function siteRows(list) {
  return list.map((c) => [`<b>${esc(c.who)}</b>`, c.url ? lnkAny(c.url) : "", M(esc(c.positioning || "")), M(esc(c.hero_product || "")), esc(c.price || ""),
    L(esc((c.claims || []).join("; "))), M(esc(c.tone || "")), c.error ? M(`<span class="err">${esc(c.error)}</span>`) : M(none("From the page text; unverified facts are dropped"))]);
}
const lnkAny = (url) => (/^https?:\/\//.test(url) ? `<a class="lnk" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url.replace(/^https?:\/\//, "").slice(0, 40))}</a>` : esc(url));
const SITE_COLS = ["Business", "Website", "Positioning", "Hero product", "Price (as written)", "Claims on the page", "Tone", "Note"];

function sheet1() {
  const c = (S.wb.sites || {}).competitors || [];
  return head(0, "What each competitor says on its own site") + (c.length ? tbl(SITE_COLS, siteRows(c)) + `<p class="muted small">Only facts whose quote is really on the fetched page are kept. Ad hooks, reviews and complaints are not collected yet, so there are no columns for them.</p>`
    : empty("<b>No competitor websites were given.</b><br>Add them on the start screen, one per line (Name | https://…)."));
}
function sheet2() {
  const b = (S.wb.sites || {}).brand;
  return head(1, `What ${S.wb.brand} says about itself`) + (b ? tbl(SITE_COLS, siteRows([b])) : empty("<b>No brand website was given.</b><br>Add it on the start screen to fill this sheet."));
}
function sheet3() {
  const a = (S.wb.research || {}).audience, v = a && a.voice;
  if (!v || !v.comments) return head(2, "Real customer language") + empty("<b>No comments came back for these Reels.</b><br>This sheet only shows real comments, so it stays empty rather than inventing any.");
  const rows = [];
  for (const t of v.themes.filter((x) => x.count)) for (const ex of t.examples.slice(0, 2)) rows.push([chip(t.theme, "sky"), `${t.count} (${Math.round(t.share * 100)}%)`, L(quote(ex.text)), M(none("Instagram comment"))]);
  return head(2, "Real customer language, grouped by theme") + `<p class="muted m0">${esc(v.comments)} comments from ${esc(a.reels)} Reels (${esc(v.sorted)} sorted, ${esc(v.reactions)} too short to sort). ${esc(v.caveat)}</p>` + tbl(["Theme", "Count (share)", "Exact customer words", "Source"], rows);
}

const tally = (cards, get) => { const m = {}; cards.forEach((c) => { const k = get(c); if (k) m[k] = (m[k] || 0) + 1; }); return Object.entries(m).sort((a, b) => b[1] - a[1]); };
const scoreChip = (x) => chip(x.toFixed(1) + "x", x >= 8 ? "pink" : x >= 5 ? "orange" : "yellow");
const hookText = (c) => (c.hook && ((c.hook.audio && c.hook.audio.text) || (c.hook.text && c.hook.text.text))) || "";
function sheet4() {
  const r = S.wb.research || {}, all = (r.cards || []), cards = all.filter((c) => !c.error), tb = S.otab;
  const avg = cards.length ? cards.reduce((a, c) => a + (c.ratio || 0), 0) / cards.length : 0;
  const bars = (arr, c) => arr.slice(0, 4).map(([k, n]) => `<div class="meter"><span>${esc(k)}</span><div class="bar"><span class="fillbar c-${c}" data-w="${(n / cards.length) * 100}"></span></div><b>${n}</b></div>`).join("");
  const summary = cards.length ? `<div class="panel"><div class="card tint c-yellow"><h4>Winning patterns</h4><div class="big">${avg.toFixed(1)}x</div>
    <span>Average gain over each creator's usual plays, across ${cards.length} outliers.</span><span>${esc(r.summary && r.summary.note ? r.summary.note : "")}</span></div>
    <div class="card"><h4>Content angles</h4>${bars(tally(cards, (c) => c.content_angle), "pink")}</div>
    <div class="card"><h4>Formats</h4>${bars(tally(cards, (c) => c.format), "sky")}</div></div>` : "";
  const tabs = `<div class="subtabs">${[["4A", "1 · Watchlist & feed"], ["4B", "2 · Viral outliers"], ["4C", "3 · Hooks & structure"], ["4D", "4 · Remix a script"], ["4E", "5 · Content vault"]]
    .map((t) => `<button class="btn sm ${tb === t[0] ? "on" : ""}" data-act="otab" data-v="${t[0]}">${esc(t[1])}</button>`).join("")}</div>`;
  let body = "";
  if (tb === "4A") {
    body = `<p class="muted m0">Recent Reels from the creators you named and from the creators behind the outliers.</p>` + ((S.wb.feed || []).length
      ? tbl(["Creator", "Followers", "Caption", "Reel link", "Date", "Plays", "Likes", "Comments"], S.wb.feed.map((f) => [esc(f.creator), esc(fmtN(f.followers)), L(esc(f.caption)), M(lnk(f.link, "Open reel ↗")),
        esc((f.posted_at || "").slice(0, 10)), `<b>${esc(fmtN(f.plays))}</b>`, esc(fmtN(f.likes)), esc(fmtN(f.comments))])) : empty("No recent posts from the watched creators were saved."));
  }
  if (tb === "4B") {
    const list = cards.filter((c) => (c.ratio || 0) >= S.fs).sort((a, b) => b.ratio - a.ratio);
    body = `<div class="filters"><label>Min score <select id="fScore">${[3, 5, 8].map((x) => `<option value="${x}" ${S.fs === x ? "selected" : ""}>${x}x</option>`).join("")}</select></label>
      <span class="muted">Outlier score = plays ÷ the creator's usual (median) plays. Click a row for the full breakdown and transcript. ${all.length - cards.length ? `${all.length - cards.length} Reel(s) could not be decoded.` : ""}</span></div>` +
      (list.length ? tbl(["Video", "Link", "Creator", "Plays", "Creator's usual", "Outlier score", "Grade", "Format", "Angle"], list.map((c) => [L(esc(hookText(c)) || none("(no hook text)")),
        M(lnk(c.link, "Open reel ↗")), esc("@" + c.creator), `<b>${esc(fmtN(c.plays))}</b>`, esc(c.usual ? fmtN(c.usual) : "no baseline"), scoreChip(c.ratio || 0), chip(c.grade || "", c.grade === "winning" ? "pink" : "yellow"),
        M(esc(c.format || "")), M(esc(c.content_angle || ""))]), (i) => `data-act="row" data-v="${all.indexOf(list[i])}"`) : empty("No Reels match this score. Lower the minimum."));
  }
  if (tb === "4C") {
    body = `<p class="muted m0">Each outlier broken into hook, angle, structure and call to action, from its transcript and on-screen frames. Click a row for the transcript.</p>` + (cards.length
      ? tbl(["Video", "Spoken hook", "On-screen hook", "Visual", "Angle", "Structure", "Rate of revelation", "Super hook", "CTA"], cards.map((c) => [`#${all.indexOf(c) + 1} · ${esc("@" + c.creator)}<br>${lnk(c.link, "Open reel ↗")}`,
        L(c.hook && c.hook.audio && c.hook.audio.analysed ? `${chip(c.hook.audio.type, "pink")} ${quote(c.hook.audio.text || "")}` : none("no transcript")),
        L(c.hook && c.hook.text && c.hook.text.analysed ? `${chip(c.hook.text.type, "pink")} ${quote(c.hook.text.text || "")}` : none("not analysed (needs frames)")),
        M(c.hook && c.hook.video && c.hook.video.analysed ? esc(c.hook.video.type) : none("not analysed")), M(esc(c.content_angle || "")),
        M(`<span class="mono small">${esc((c.structure || []).join(" → "))}</span>`),
        M(esc(c.rate_of_revelation && c.rate_of_revelation.per_10s != null ? `${c.rate_of_revelation.per_10s} per 10s (${c.rate_of_revelation.pace})` : "unknown")),
        M(esc(c.super_hook ? c.super_hook.value : "")), M(esc(c.cta && c.cta.type !== "none" ? c.cta.type : "none"))]), (i) => `data-act="row" data-v="${all.indexOf(cards[i])}"`) : empty("No decoded outliers yet."));
  }
  if (tb === "4D") {
    const done = Object.entries(S.remix);
    body = `<p class="muted m0">Structure and pacing are kept from the winner. The wording is always new. Open an outlier (click a row in tab 2 or 3) and press “Write a script like this”.</p>` +
      (done.length ? done.map(([k, v]) => `<div class="card"><h4>From outlier #${esc(k)}</h4><pre class="pre" data-pre="${esc(k)}"></pre></div>`).join("") : empty("No remixed scripts yet."));
  }
  if (tb === "4E") {
    body = `<div class="filters"><span class="muted">Every script saved to your vault, from the workbook and from the remix button.</span></div>` + (S.vault === null ? empty("Loading…") : S.vault.length
      ? tbl(["Item", "Niche", "Status", "Saved"], S.vault.map((r) => [`<b>${esc(r.title)}</b>`, M(esc(r.niche)), chip(r.status, "mint"), esc(String(r.created_at).slice(0, 10))])) : empty("Nothing saved yet."));
  }
  return head(3, "What is winning on Instagram right now") + summary + tabs + body;
}

function sheet5() {
  const a = S.wb.awareness || { stages: [] }, placed = a.placed || 0;
  if (!placed) return head(4, "Where the audience sits") + empty("<b>Not enough real comments to map awareness.</b><br>This sheet is counted from comments, so it stays empty rather than guessing.");
  const spec = `<div class="card"><div class="row"><h4 class="h4s">Where the commenters sit</h4>${chip("Counted from real comments", "mint")}</div>
   <div class="spec" role="img" aria-label="Awareness spread">${a.stages.map((s) => `<div class="c-${STAGE_COLOR[s.stage]} bg-c" data-flex="${Math.max(s.share, 0.02)}">${Math.round(s.share * 100)}%</div>`).join("")}</div>
   <div class="speclg">${a.stages.map((s) => `<div><i class="bg-c c-${STAGE_COLOR[s.stage]}"></i><b>${Math.round(s.share * 100)}%</b> ${esc(s.name)}</div>`).join("")}</div>
   <p class="muted small m0">${esc(placed)} of ${esc(a.comments)} comments were sorted into a stage by the AI; ${esc(a.off_topic)} were off-topic. ${esc(a.caveat)}</p></div>`;
  return head(4, "One row per stage, with the commenters' own words") + spec + tbl(["Awareness stage", "Share", "What the creative must do", "A real comment"], a.stages.map((s) => [`<span class="stage c-${STAGE_COLOR[s.stage]}">${esc(s.name)}</span>`,
    `<div class="cs"><b class="num2">${Math.round(s.share * 100)}%</b> <span class="muted">(${s.count} of ${placed})</span><div class="mini"><span class="fillbar c-${STAGE_COLOR[s.stage]}" data-w="${s.share * 100}"></span></div></div>`,
    L(esc(STAGE_DO[s.stage])), L(s.examples[0] ? quote(s.examples[0].text) : none("none"))]));
}
function sheet6() {
  const av = (S.wb.avatars || {}).avatars || [];
  if (!av.length) return head(5, "Who is in each stage") + empty(`<b>No avatars could be written.</b><br>${esc(((S.wb.avatars || {}).skipped || [])[0] || "Not enough comments.")}`);
  return head(5, "Who is in each stage, with their own words") + `<p class="muted m0">${esc(S.wb.avatars.note)}</p>` + tbl(["Segment", "Awareness stage", "Share", "The problem they face", "What they think", "Main doubt", "Exact words (verbatim)", "Best formats"],
    av.map((a) => [`<b>${esc(a.name)}</b>`, `<span class="stage c-${STAGE_COLOR[a.stage]}">${esc(a.stage_name)}</span>`, `<b>${Math.round(a.share * 100)}%</b>`, M(esc(a.problem)), M(esc(a.belief)), M(esc(a.objection)),
      L(quote(a.words)), M(esc(a.formats.join(" · ")))])) + ((S.wb.avatars.skipped || []).length ? `<p class="muted small">${esc(S.wb.avatars.skipped.join(" · "))}</p>` : "");
}
function sheet7() {
  const ideas = S.wb.ideas || [];
  if (!ideas.length) return head(6, "Approve a row and it gets scripted") + empty(`<b>No ideas could be built.</b><br>${esc(S.wb.ideas_note || "")}`);
  return head(6, "Approve a row and it gets scripted") + `<p class="muted m0">${esc(S.wb.ideas_note)} The “proof” column says what you must bring or show. It is never a claim.</p>` +
    tbl(["Format", "Angle", "Hook", "Key message", "Proof you must bring", "Call to action", "Visual direction", "Segment", "Goal", "Source outlier", "Approved"],
      ideas.map((x, i) => [M(`<b>${esc(x.format)}</b>`), M(chip(x.angle, "pink")), L(esc(x.hook)), L(esc(x.message)), M(esc(x.proof)), M(esc(x.cta)), M(esc(x.visual)), M(esc(x.avatar)), chip(x.goal, "sky"),
        lnk(x.source_link, "@" + (x.source_creator || "source")),
        `<label class="chk"><input type="checkbox" data-act="toggle-idea" data-i="${i}" ${S.approved.has(i) ? "checked" : ""}>${S.approved.has(i) ? chip("Approved", "mint") : chip("Pending", "yellow")}</label>`])) +
    `<div class="row mt12"><button class="btn go" data-act="approve-go" ${S.approved.size ? "" : "disabled"}>Write scripts for ${S.approved.size} approved</button><span class="muted">Scripts already written are kept.</span></div>`;
}
function sheet8() {
  const list = S.wb.scripts || [];
  if (!list.length) return head(7, "Scripts for approved ideas") + empty(`<b>No scripts yet.</b><br>Approve ideas in Sheet 7 and press “Write scripts”.<div class="mt12"><button class="btn on" data-act="sheet" data-i="6">Go to Sheet 7</button></div>`);
  S.script = Math.min(S.script, list.length - 1);
  const s = list[S.script], idea = S.wb.ideas[s.idea] || {};
  return `<div class="shd"><div class="sheettitle">shoot flows</div>${chip("Step 4 · Script", "mint")}</div>
  <div class="subtabs">${list.map((y, i) => `<button class="btn sm ${i === S.script ? "on" : ""}" data-act="script" data-i="${i}">${esc(y.id)} · ${esc((S.wb.ideas[y.idea] || {}).angle || "")}</button>`).join("")}</div>
  <div class="hdrgrid">${[["Script ID", s.id], ["Format", idea.format], ["Hook", s.hook], ["Key message", idea.message], ["Proof you must bring", idea.proof], ["Call to action", idea.cta], ["Storyline", s.storyline], ["Tone", s.tone],
    ["Segment and goal", `${idea.avatar || "any"} · ${idea.goal || ""}`]].map((a) => `<div class="kv"><small>${esc(a[0])}</small><div>${esc(a[1])}</div></div>`).join("")}</div>
  ${(s.needs_from_you || []).length ? `<div class="card warnbox"><b>You still need to bring</b><ul>${s.needs_from_you.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
  <div class="tw"><table><thead><tr><th class="shot-th-seq">shot</th><th>script (line by line)</th><th>shot type</th><th>angle</th><th>action</th><th>location</th><th>prop</th><th>equipment</th><th>cut</th><th>on-screen text</th><th>sound</th></tr></thead><tbody>
  ${s.shots.map((r) => `<tr><td>${chip(String(r.seq), "sky")}</td><td>${L(esc(r.line))}</td><td>${esc(r.shot_type)}</td><td>${esc(r.angle)}</td><td>${M(esc(r.action))}</td><td>${M(esc(r.location))}</td><td>${esc(r.prop)}</td><td>${M(esc(r.equipment))}</td><td>${esc(r.cut)}</td><td>${M(esc(r.on_screen_text))}</td><td>${esc(r.sound)}</td></tr>`).join("")}</tbody></table></div>`;
}
function sheet9() {
  const wb = S.wb, ideas = wb.ideas || [], list = wb.scripts || [], aw = wb.awareness || { stages: [] };
  const top = tally((wb.research.cards || []).filter((c) => !c.error), (c) => c.content_angle)[0];
  const sum = [["Brand", wb.brand], ["Category", wb.category], ["Comments sorted", String(aw.placed || 0)], ["Avatars", String(((wb.avatars || {}).avatars || []).length)], ["Approved ideas", String(wb.approved.length)],
    ["Scripts ready", String(list.length)], ["Most common winning angle", top ? `${top[0]} (${top[1]})` : "n/a"]];
  const refs = [...new Set(list.map((s) => (ideas[s.idea] || {}).source_link).filter(Boolean))];
  return head(8, "The sheet you hand over") + `<div class="hdrgrid">${sum.map((a) => `<div class="kv"><small>${esc(a[0])}</small><div><b>${esc(a[1])}</b></div></div>`).join("")}</div>` +
    (list.length ? `<h3 class="h3s">Approved ideas and scripts</h3>` + tbl(["Script", "Format", "Angle", "Hook", "CTA", "Still needed from you"], list.map((s) => { const x = ideas[s.idea] || {};
      return [esc(s.id), M(esc(x.format)), chip(x.angle || "", "pink"), L(esc(x.hook)), M(esc(x.cta)), L(esc((s.needs_from_you || []).join("; ")))]; })) +
      `<h3 class="h3s">Editing notes</h3>` + tbl(["Script", "Shot", "Cut", "On-screen text", "Sound"], list.flatMap((s) => s.shots.map((r) => [esc(s.id), chip(String(r.seq), "sky"), esc(r.cut), M(esc(r.on_screen_text)), esc(r.sound)]))) +
      `<h3 class="h3s">References</h3>` + tbl(["Source outlier", "Link"], refs.map((u) => [esc(u), lnk(u, "Open reel ↗")])) : empty("<b>Nothing to present yet.</b><br>Approve ideas in Sheet 7 first."));
}

/* ---------- drawer ---------- */
function openDrawer(i) {
  const c = S.wb.research.cards[i];
  if (!c) return;
  const h = c.hook || {}, rr = c.rate_of_revelation || {};
  $("#drawer").innerHTML = `<div class="row"><h3 class="h3d">Video #${i + 1} breakdown</h3><button class="btn sm" data-act="close-drawer" aria-label="Close">Close</button></div>
  <div class="row">${scoreChip(c.ratio || 0)}${chip("@" + c.creator, "surface2")}${chip(fmtN(c.plays) + " plays", "surface2")}${c.followers ? chip(fmtN(c.followers) + " followers", "surface2") : ""}${c.grade ? chip(c.grade, c.grade === "winning" ? "pink" : "yellow") : ""}</div>
  <div class="kv"><small>Exact video</small><div>${lnk(c.link, "Open reel on Instagram ↗")}<div class="muted mt4">${esc(c.basis || "")}</div></div></div>
  ${c.error ? `<div class="kv"><small>Breakdown</small><div class="err">${esc(c.error)}</div></div>` : `
  <div class="card tint c-yellow"><div class="muted mono small">CONTENT ANGLE</div><b class="h4s">${esc(c.content_angle)}</b></div>
  <div class="row">${chip(c.format || "format unknown", "sky")}${c.story_loop && c.story_loop !== "none" ? chip("loop: " + c.story_loop, "orange") : ""}${chip("CTA: " + (c.cta && c.cta.type), "mint")}</div>
  <div class="kv"><small>Hooks</small><div>Spoken: ${h.audio && h.audio.analysed ? esc(h.audio.type) + " " + quote(h.audio.text || "") : "no transcript"}<br>On-screen: ${h.text && h.text.analysed ? esc(h.text.type) + " " + quote(h.text.text || "") : "not analysed"}<br>Visual: ${h.video && h.video.analysed ? esc(h.video.type + " — " + (h.video.description || "")) : "not analysed"}</div></div>
  <div class="kv"><small>Structure</small><div class="mono small">${esc((c.structure || []).join(" → "))}</div></div>
  <div class="kv"><small>Rate of revelation</small><div>${esc(rr.per_10s != null ? `${rr.per_10s} reveals per 10s (${rr.pace}), ${rr.reveals} beats over ~${rr.seconds}s, ${rr.basis}` : "unknown (no video length or transcript)")}</div></div>
  <div class="kv"><small>Super hook</small><div>${esc(c.super_hook ? c.super_hook.value + " — " + c.super_hook.why : "")}</div></div>
  <div class="kv"><small>Contrarian take</small><div>${c.contrarian && c.contrarian.value ? esc("Yes — " + c.contrarian.why.join("; ")) : "No"}</div></div>
  <div class="kv"><small>Transcript</small><div>${c.transcript ? esc(c.transcript) : none("No transcript was made for this Reel.")}</div></div>`}
  <button class="btn hot" data-act="remix" data-i="${i}">Write a script like this</button><div id="remixOut"></div>`;
  $("#drawer").classList.add("open"); $("#drawer .btn").focus();
}
const closeDrawer = () => $("#drawer").classList.remove("open");
async function remix(i) {
  const c = S.wb.research.cards[i], out = $("#remixOut");
  out.textContent = "Writing…";
  try {
    const r = await api("/api/script", { topic: S.wb.topic, reel_id: c.reel_id, my_topic: `${S.wb.brand} ${S.wb.category}`.slice(0, 60) });
    S.remix[i + 1] = r.markdown; out.textContent = `Saved to your vault as script #${r.id}.`;
    const pre = document.createElement("pre"); pre.className = "pre"; pre.textContent = r.markdown; out.append(pre);
    S.vault = null;
  } catch (err) { out.textContent = err.message; }
}

/* ---------- misc ---------- */
let tt;
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); clearTimeout(tt); tt = setTimeout(() => t.classList.remove("show"), 3200); }
function render() {
  renderTop(); closeDrawer();
  if (S.view === "start") renderStart(); else if (S.view === "run") renderRun(); else renderBook();
  fillRemix(); window.scrollTo({ top: 0 });
}
function fillRemix() { document.querySelectorAll("[data-pre]").forEach((p) => { p.textContent = S.remix[p.dataset.pre] || ""; }); }
function keepScroll(fn) { const y = window.scrollY; fn(); fillRemix(); window.scrollTo({ top: y }); }
async function loadVault() { try { S.vault = await api("/api/wb/vault"); } catch (e) { S.vault = []; } if (S.view === "book" && S.sheet === 3 && S.otab === "4E") keepScroll(renderBook); }

document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-act]");
  if (!t) return;
  const a = t.dataset.act;
  if (a === "nav") { if (t.dataset.v === "start") { if (S.view === "start") return; S.view = "start"; } else if (S.wb) S.view = "book"; render(); }
  else if (a === "confirm-run") startRun(true, false);
  else if (a === "reuse-run") startRun(false, true);
  else if (a === "cancel-plan") $("#planBox").innerHTML = "";
  else if (a === "open-recent") { try { S.wb = await api("/api/wb?id=" + encodeURIComponent(t.dataset.id)); S.approved = new Set(S.wb.approved); S.view = "book"; S.sheet = 0; render(); } catch (err) { toast(err.message); } }
  else if (a === "step") { S.sheet = STEPS[+t.dataset.i].sheets[0]; render(); }
  else if (a === "sheet") { S.sheet = +t.dataset.i; render(); }
  else if (a === "vault") { S.sheet = 3; S.otab = "4E"; S.view = "book"; render(); loadVault(); }
  else if (a === "otab") { S.otab = t.dataset.v; keepScroll(renderBook); if (S.otab === "4E") loadVault(); }
  else if (a === "toggle-idea") { const i = +t.dataset.i; t.checked ? S.approved.add(i) : S.approved.delete(i); keepScroll(() => (S.view === "run" ? renderRun() : renderBook())); }
  else if (a === "gate-all") { S.wb.ideas.forEach((_, i) => S.approved.add(i)); renderRun(); }
  else if (a === "gate-none") { S.approved.clear(); renderRun(); }
  else if (a === "approve-go") approve();
  else if (a === "row") openDrawer(+t.dataset.v);
  else if (a === "close-drawer") closeDrawer();
  else if (a === "script") { S.script = +t.dataset.i; keepScroll(renderBook); }
  else if (a === "remix") remix(+t.dataset.i);
  else if (a === "brand") toggleBrand();
  else if (a === "brand-reset") { Object.assign(BR, BR0); applyBrand(); saveBrand(); fillBrand(); }
});
document.addEventListener("change", (e) => { if (e.target.id === "fScore") { S.fs = +e.target.value; keepScroll(renderBook); } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

/* ---------- brand colours (kept in this browser only) ---------- */
const BR0 = { violet: "#8057FF", pink: "#FF5FA8", yellow: "#FFD93D" }, BR = { ...BR0 };
const lum = (h) => { const n = parseInt(h.slice(1), 16); return (0.299 * (n >> 16 & 255) + 0.587 * (n >> 8 & 255) + 0.114 * (n & 255)) / 255; };
function applyBrand() { const s = document.documentElement.style; for (const k in BR) s.setProperty("--" + k, BR[k]); s.setProperty("--on-pri", lum(BR.violet) > 0.6 ? "#17132E" : "#FFFFFF"); }
function saveBrand() { try { localStorage.setItem("bioscriptz-brand", JSON.stringify(BR)); } catch (e) { /* storage blocked: colours just are not remembered */ } }
function loadBrand() { try { const j = JSON.parse(localStorage.getItem("bioscriptz-brand") || "null"); if (j) for (const k in BR) if (/^#[0-9a-f]{6}$/i.test(j[k] || "")) BR[k] = j[k]; } catch (e) { /* ignore */ } }
function fillBrand() { for (const k in BR) { $("#bc-" + k).value = BR[k]; $("#bt-" + k).value = BR[k]; } }
function toggleBrand() { const p = $("#brandpanel"); p.hidden = !p.hidden; fillBrand(); }
document.addEventListener("input", (e) => {
  const t = e.target, k = t.dataset.brand || t.dataset.brandtext;
  if (!k) return;
  let v = t.value.trim();
  if (t.dataset.brandtext && v[0] !== "#") v = "#" + v;
  if (!/^#[0-9a-f]{6}$/i.test(v)) return;
  BR[k] = v.toLowerCase(); applyBrand(); saveBrand();
  if (t.dataset.brand) $("#bt-" + k).value = BR[k]; else $("#bc-" + k).value = BR[k];
});

(async function init() {
  loadBrand(); applyBrand(); fillBrand();
  try { S.state = await api("/api/state"); } catch (e) { S.state = {}; }
  render();
})();
