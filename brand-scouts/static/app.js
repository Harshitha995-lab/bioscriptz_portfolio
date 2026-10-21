"use strict";
// Scraped captions, transcripts and handles are untrusted: everything is inserted with textContent, never as HTML.
const $ = (id) => document.getElementById(id);
const LINK_OK = /^https:\/\/(www\.)?instagram\.com\//;

function el(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v; else if (k === "onclick") n.onclick = v; else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k)));
  return n;
}
async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const fmt = (n) => (n == null ? "?" : Number(n).toLocaleString());
const yn = (v) => (v === true ? "Yes" : v === false ? "No" : String(v));

let state = {};
async function init() {
  state = await api("/api/state");
  const b = $("banner");
  if (state.sample) { b.hidden = false; b.className = "note"; b.textContent = "SAMPLE MODE: synthetic Reels about personal branding are shown whatever topic you type. Nothing is scraped and nothing is spent."; }
  else if (state.setup_issue) { b.hidden = false; b.className = "note"; b.textContent = "Setup needed before a live run: " + state.setup_issue; }
  else { b.hidden = false; b.className = "note"; b.textContent = `Live mode. AI: ${state.ai}. Recorded Apify spend this month: $${state.month_spent.toFixed(2)} of $${state.free_credit.toFixed(2)} free credit.`; }
  const chips = $("recent"); chips.replaceChildren();
  for (const t of state.topics || []) chips.append(el("button", { type: "button", text: t.topic, onclick: () => { $("topic").value = t.topic; loadSaved(t.topic); } }));
}

async function loadSaved(topic) {
  try { render(await api("/api/result?topic=" + encodeURIComponent(topic)), topic); } catch (e) { $("results").replaceChildren(el("p", { class: "small", text: "No saved result for that topic yet." })); }
}

const mode = () => document.querySelector('input[name="mode"]:checked').value;
const isCreators = () => mode() === "creators";
function brandPayload() {
  if (mode() !== "brand") return null;
  return { brand: $("brand").value.trim(), category: $("category").value.trim(), own: $("own").value.trim(),
           competitors: $("competitors").value.split(",").map((s) => s.trim()).filter(Boolean) };
}
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", () => {
  const b = mode() === "brand";
  $("go").textContent = isCreators() ? "Find creators" : "Find outliers";
  $("brandFields").hidden = !b; $("topic").hidden = b; $("topicLabel").hidden = b; $("topic").required = !b;
  $("topic").closest(".row").hidden = b;
}));

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const brand = brandPayload();
  const topic = brand ? `${brand.brand} ${brand.category}` : $("topic").value.trim(), days = Number($("days").value);
  $("results").replaceChildren(); $("progress").hidden = true;
  try {
    const plan = await api("/api/plan", { topic, brand, creators: isCreators() });
    if (plan.sample) return run(topic, days, false, brand);
    const box = $("plan"); box.hidden = false; box.replaceChildren();
    const inner = el("div", { class: "box" },
      el("b", { text: `Plan for “${plan.topic}”` }),
      el("p", { text: plan.message }),
      el("p", { class: "small", text: (plan.creators ? `${plan.keywords.length} creator searches × up to ${plan.per_keyword} creators, each with their latest Reels. ` : `${plan.keywords.length} search terms × ${plan.per_keyword} + ${plan.baseline_creators} creators × ${plan.per_creator} Reels. `) +
        `Estimated cost $${plan.est_cost.toFixed(2)} at $${plan.price.toFixed(2)} per 1,000 results${plan.price_assumed ? " (ASSUMED price)" : ""}. Month so far $${plan.month_spent.toFixed(2)} of $5.00.` }));
    const go = el("button", { type: "button", text: `Run for about $${plan.est_cost.toFixed(2)}`, onclick: () => { box.hidden = true; run(topic, days, true, brand); } });
    if (!plan.ok) go.disabled = true;
    if (plan.cached && !plan.setup_blocked) {
      inner.append(el("p", { class: "small", text: `You already have ${plan.cached.reels} saved Reels for this topic (${plan.cached.hours_ago} hours old).` }),
        el("button", { type: "button", text: "Re-use saved Reels (no Apify cost)", onclick: () => { box.hidden = true; run(topic, days, false, brand, true); } }), " ");
    }
    inner.append(go, " ", el("button", { type: "button", class: "ghost", text: "Cancel", onclick: () => { box.hidden = true; } }));
    box.append(inner);
  } catch (err) { showError(err.message); }
});

function showError(msg) { $("progress").hidden = false; $("progress").replaceChildren(el("p", { class: "err", text: msg })); }

async function run(topic, days, confirm, brand, reuse) {
  $("go").disabled = true;
  const prog = $("progress"); prog.hidden = false; prog.replaceChildren(el("p", { text: "Starting…" }));
  try {
    const { job } = await api("/api/research", { topic, days, confirm, brand, reuse: reuse === true, creators: isCreators() });
    for (;;) {
      await new Promise((r) => setTimeout(r, 1200));
      const j = await api("/api/job/" + job);
      prog.replaceChildren(...j.messages.map((m) => el("p", { class: "small", text: m })), j.status === "running" ? el("p", { text: "Working…" }) : "");
      if (j.status === "error") throw new Error(j.error);
      if (j.status === "done") { prog.hidden = true; render(j.result, topic); init(); break; }
    }
  } catch (err) { showError(err.message); } finally { $("go").disabled = false; }
}

function row(k, v) { return [el("dt", { text: k }), el("dd", {}, v)]; }

function hookRows(h) {
  const out = [];
  out.push(el("div", {}, el("b", { text: "Spoken: " }), h.audio.analysed ? [h.audio.type + (h.audio.text ? ": " : ""), h.audio.text ? el("q", { text: h.audio.text }) : "", h.audio.verified_quote ? "" : (h.audio.text ? " (quote not found in transcript)" : "")] : "no transcript"));
  out.push(el("div", {}, el("b", { text: "On-screen text: " }), h.text.analysed ? [h.text.type + (h.text.text ? ": " : ""), h.text.text ? el("q", { text: h.text.text }) : ""] : "not analysed (needs video frames)"));
  out.push(el("div", {}, el("b", { text: "Visual: " }), h.video.analysed ? [h.video.type, h.video.description ? ` — ${h.video.description}` : ""] : "not analysed (needs video frames)"));
  return out;
}

function card(c, i, topic) {
  const head = el("h3", {}, `${i}. @${c.creator}`, el("span", { class: "tag " + (c.strong ? "strong" : ""), text: c.strong ? "strong outlier" : "weak basis" }));
  const meta = el("div", { class: "meta", text: `${fmt(c.plays)} plays · ${c.basis}${c.followers ? ` · ${fmt(c.followers)} followers` : ""}` });
  if (c.error) return el("div", { class: "card" }, head, meta, el("p", { class: "err", text: "Breakdown unavailable: " + c.error }), linkRow(c));
  const rr = c.rate_of_revelation;
  const rate = rr.per_10s == null ? "unknown (no video length or transcript)" : `${rr.per_10s} reveals per 10s (${rr.pace}) — ${rr.reveals} new-information beats over ~${rr.seconds}s, ${rr.basis}`;
  const dl = el("dl", {},
    row("Hook", hookRows(c.hook)),
    row("Content angle", c.content_angle),
    row("Creator", `@${c.creator}`),
    row("Rate of revelation", rate),
    row("Super hook", `${c.super_hook.value === "yes" ? "Yes" : c.super_hook.value === "no" ? "No" : "Unknown"} — ${c.super_hook.why}`),
    row("Contrarian take", c.contrarian.value ? [`Yes — ${c.contrarian.why.join("; ")}` + (c.contrarian.quote ? ": " : ""), c.contrarian.quote ? el("q", { text: c.contrarian.quote }) : ""] : "No"),
    row("Call to action", c.cta.type === "none" ? "None" : [c.cta.type + (c.cta.text ? ": " : ""), c.cta.text ? el("q", { text: c.cta.text }) : ""]),
    row("Structure", c.structure.join(" → ") + (c.story_loop && c.story_loop !== "none" ? ` · loop: ${c.story_loop}` : "")),
    row("Link", linkNode(c)));
  const box = el("div", { class: "card" }, head, meta, dl, scriptBox(c, topic));
  return box;
}
function linkNode(c) { return LINK_OK.test(c.link) ? el("a", { href: c.link, target: "_blank", rel: "noopener noreferrer", text: c.link }) : "(link unavailable)"; }
function linkRow(c) { return el("p", {}, linkNode(c)); }

function scriptBox(c, topic) {
  const out = el("div", {});
  const input = el("input", { placeholder: "Your topic for a script with this Reel's structure", maxlength: "60" });
  const btn = el("button", { type: "button", class: "ghost", text: "Write a script like this" });
  btn.onclick = async () => {
    if (!input.value.trim()) return input.focus();
    btn.disabled = true; out.replaceChildren(el("p", { class: "small", text: "Writing…" }));
    try { const r = await api("/api/script", { topic, reel_id: c.reel_id, my_topic: input.value.trim() }); out.replaceChildren(el("p", { class: "small", text: `Saved to your vault as script #${r.id}.` }), el("pre", { text: r.markdown })); }
    catch (e) { out.replaceChildren(el("p", { class: "err", text: e.message })); } finally { btn.disabled = false; }
  };
  return el("details", { class: "small" }, el("summary", { text: "Turn this into your own script" }), el("div", { class: "row" }, input, btn), out);
}

function render(res, topic) {
  const r = $("results"); r.replaceChildren();
  const s = res.summary;
  if (res.creator_board) r.append(creatorBoard(res.creator_board));
  r.append(el("h2", { text: `Top outliers for “${res.topic}” — last ${res.days} days` }));
  if (res.sample) r.append(el("div", { class: "note", text: "SAMPLE: synthetic data and a rule-based stand-in analyst. This shows the layout, not real findings." }));
  if (res.warning) r.append(el("div", { class: "note", text: res.warning }));
  if (res.undated) r.append(el("div", { class: "note", text: `${res.undated} Reel(s) had no posting date, so the time window could not be checked for them.` }));
  const st = res.stats;
  r.append(el("p", { class: "small", text: `${st.considered} Reels in the window, ${st.outliers} outliers (${st.strong} strong). Strong = beat that creator's own median by 3× or more (needs 5 of that creator's Reels from the last 180 days). ${st.creators_with_a_usual} creator(s) in the saved data have that baseline. Weak = no baseline, so small accounts can spike for reasons unrelated to the content.` }));
  if (!res.cards.length) { r.append(el("p", { text: "No outliers found. Try a wider window, a broader topic, or harvest more." })); return; }
  if (s.n) {
    r.append(el("div", { class: "box" }, el("b", { text: "What the top Reels have in common" }),
      el("div", { class: "summary" },
        el("div", {}, el("b", { text: s.angles[0] ? s.angles[0][0] : "-" }), el("span", { text: `most common angle (${s.angles[0] ? s.angles[0][1] : 0} of ${s.n})` })),
        el("div", {}, el("b", { text: `${s.contrarian} of ${s.n}` }), el("span", { text: "take a contrarian stance" })),
        el("div", {}, el("b", { text: s.super_hook_known ? `${s.super_hook_yes} of ${s.super_hook_known}` : "n/a" }), el("span", { text: "have a super hook" })),
        el("div", {}, el("b", { text: `${s.with_cta} of ${s.n}` }), el("span", { text: "end with a CTA" })),
        el("div", {}, el("b", { text: s.median_rate == null ? "?" : String(s.median_rate) }), el("span", { text: "median reveals / 10s" }))),
      el("p", { class: "small", text: s.note })));
  }
  res.cards.forEach((c, i) => r.append(card(c, i + 1, res.topic)));
  if (res.audience) r.append(audience(res.audience));
}

function creatorBoard(b) {
  const box = el("div", { class: "box" }, el("h2", { text: "Top creators" }));
  if (!b.creators.length) return el("div", { class: "box" }, el("h2", { text: "Top creators" }), el("p", { class: "small", text: "No creator had 3 or more recent Reels." }));
  box.append(el("p", { class: "small", text: `${b.found} creators had enough Reels (micro ${b.tiers.micro}, small ${b.tiers.small}, big ${b.tiers.big}). Micro under 10k followers, small under 100k, big above.` }));
  const tbl = el("table", {}, el("tr", {}, ...["Creator", "Size", "Followers", "Usual plays", "Best Reel", "Plays per follower"].map((h) => el("th", { text: h }))));
  for (const c of b.creators) {
    tbl.append(el("tr", {}, el("td", { text: "@" + c.username }), el("td", { text: c.tier }), el("td", { text: c.followers ? fmt(c.followers) : "?" }),
      el("td", { text: fmt(c.median_plays) }), el("td", {}, LINK_OK.test(c.best_link) ? el("a", { href: c.best_link, target: "_blank", rel: "noopener noreferrer", text: fmt(c.best_plays) + " plays" }) : fmt(c.best_plays)),
      el("td", { text: c.reach == null ? "?" : c.reach + "×" })));
  }
  box.append(tbl, el("p", { class: "small", text: b.note }));
  return box;
}

function audience(a) {
  const box = el("div", { class: "box" }, el("h2", { text: "What the audience says" }));
  const v = a.voice;
  if (!v.comments) { box.append(el("p", { class: "small", text: "No comments were returned for these Reels, so there is nothing to summarise." })); }
  else {
    box.append(el("p", { class: "small", text: `${v.comments} comments from ${a.reels} Reels (${v.sorted} sorted, ${v.reactions} too short to sort, like emoji).` }));
    for (const t of v.themes.filter((x) => x.count)) {
      const w = Math.max(4, Math.round(t.share * 200));
      const fill = el("span", { class: "f" }); fill.style.width = w + "px";      // set through the DOM: the page's CSP blocks style attributes
      box.append(el("div", { class: "bar" }, el("b", { text: t.theme }), fill, el("span", { text: `${t.count} (${Math.round(t.share * 100)}%)` })));
      for (const ex of t.examples.slice(0, 2)) box.append(el("div", { class: "small" }, el("q", { text: ex.text })));
    }
    if (v.errors && v.errors.length) box.append(el("p", { class: "err small", text: "Some comments could not be sorted: " + v.errors[0] }));
    box.append(el("p", { class: "small", text: v.caveat }));
  }
  const s = a.signals;
  if (s.accounts.length || s.hashtags.length) {
    box.append(el("h3", { text: "Mentioned alongside" }));
    const tbl = el("table", {}, el("tr", {}, el("th", { text: "Accounts tagged or mentioned" }), el("th", { text: "Hashtags" })));
    for (let i = 0; i < Math.max(s.accounts.length, s.hashtags.length); i++) {
      const ac = s.accounts[i], hs = s.hashtags[i];
      tbl.append(el("tr", {}, el("td", { text: ac ? `@${ac[0]} (${ac[1]} Reels)` : "" }), el("td", { text: hs ? `#${hs[0]} (${hs[1]})` : "" })));
    }
    box.append(tbl);
  }
  return box;
}

init();
