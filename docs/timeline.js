// Draw a witness session, from the data `src/checker/timeline.py` generates.
//
// The page supplies the prose; everything here is driven by window.ANCHOR_TIMELINE. Shared rather
// than copied into each page because a second copy of a drawing drifts from the first exactly the
// way a second copy of a model does, and this repo already refuses that trade elsewhere.
//
// Elements are filled if present, so a page includes only the panels it wants:
//   #content #missing #subtitle #timeline #chart-panel #chart-heading #chart
//   #why-rule #why-consequence #provenance
(function () {
  const DATA = window.ANCHOR_TIMELINE;
  if (!DATA) return;

  const show = (id, on) => { const e = document.getElementById(id); if (e) e.hidden = !on; };
  show("missing", false);
  show("content", true);

  // Dogwood's complete decision-event vocabulary. Listing it is a fact about the LANGUAGE, not a
  // claim about any policy: showing every kind is what lets a reader see that the one meaning
  // "the action actually completed" never occurs, without the page asserting what was intended.
  const KINDS = ["request", "response", "error"];
  const KIND_COLOR = { request: "var(--request)", response: "var(--response)", error: "var(--error)" };

  const NS = "http://www.w3.org/2000/svg";
  const el = (n, a = {}) => {
    const e = document.createElementNS(NS, n);
    for (const k in a) e.setAttribute(k, a[k]);
    return e;
  };
  const MONO = { "font-family": "ui-monospace, monospace" };
  const text = (svg, a, content) => {
    const t = el("text", a); t.textContent = content; svg.appendChild(t); return t;
  };
  const money = n => "$" + Number(n).toLocaleString("en-US");

  // Trace timestamps are seconds, and a gap stated as a bare number invites the reader to compare
  // it against a window they are also reading as a bare number. Both are durations; say so.
  const dur = s =>
    (s >= 3600 && s % 3600 === 0) ? (s / 3600) + "h" :
    (s >= 60 && s % 60 === 0) ? (s / 60) + "m" : s + "s";
  const set = (id, html) => { const e = document.getElementById(id); if (e) e.innerHTML = html; };

  const EVENTS = DATA.events;
  const CHART = DATA.chart;
  const ruleAt = Object.fromEntries(DATA.rules.map(r => [r.index, r]));
  const decisions = EVENTS.filter(e => e.verdict);
  const deciding = CHART ? ruleAt[CHART.rule] : null;
  const ruleName = () => deciding && deciding.label ? deciding.label : (CHART && CHART.action) || "";

  // The window a predicate rule looks back over, anchored at the decision it was evaluated for.
  const decisionAt = decisions.length ? decisions[decisions.length - 1].at : null;
  const band = (CHART && CHART.kind === "predicate" && CHART.requires && decisionAt !== null)
    ? { from: decisionAt - CHART.requires.window, to: decisionAt }
    : null;

  function readField(ev) {
    const [side, name] = ((CHART && CHART.field) || "input.amount").split(".");
    return (ev[side] || {})[name];
  }

  function note(ev) {
    if (ev.kind === "error") return "refused, nothing happened";
    if (ev.kind === "request") {
      return readField(ev) != null ? "attempt " + money(readField(ev)) : "attempt";
    }
    if (ev.kind === "response") return "completed";
    return ev.kind;
  }

  // --- subtitle -------------------------------------------------------------
  set("subtitle",
    `<code>${DATA.source.witness}/${DATA.policy}</code> &mdash; ${EVENTS.length} events, ` +
    `${decisions.length} decision${decisions.length === 1 ? "" : "s"}, ` +
    `claim <code>${DATA.claim}</code>.`);

  // --- the timeline ---------------------------------------------------------
  (function timeline() {
    const svg = document.getElementById("timeline");
    if (!svg) return;
    const L = 70, R = 790, axisY = 130;

    // POSITION BY TIMESTAMP, NOT BY INDEX. For a session whose events are one tick apart the two
    // are the same, but a rule about a window is a claim ABOUT the gap: drawing `@1` and `@961`
    // the same distance apart as `@1` and `@2` hides the only thing under test. Even spacing is
    // kept as a fallback for a degenerate span, and for one so lopsided that markers would
    // collide, and the page says which it used rather than leaving the reader to assume.
    const ats = EVENTS.map(e => e.at);
    const lo = Math.min(...ats, band ? band.from : Infinity);
    const hi = Math.max(...ats);
    const span = hi - lo;
    let proportional = span > 0;
    const byTime = at => L + ((at - lo) / span) * (R - L);
    if (proportional) {
      const xs = ats.map(byTime).sort((a, b) => a - b);
      const tightest = Math.min(...xs.slice(1).map((x, i) => x - xs[i]));
      if (xs.length > 1 && tightest < 64) proportional = false;   // would overlap; be readable
    }
    const step = (R - L) / Math.max(EVENTS.length - 1, 1);
    const xOf = (ev, i) => proportional ? byTime(ev.at) : L + i * step;

    svg.setAttribute("aria-label",
      `Session of ${EVENTS.length} events; ` +
      decisions.map(d => `@${d.at} ${d.verdict}`).join(", ") + ".");

    // the window band, drawn first so markers sit on top of it
    if (band && proportional) {
      const x1 = byTime(Math.max(band.from, lo)), x2 = byTime(band.to);
      svg.appendChild(el("rect", { x: x1, y: axisY - 26, width: Math.max(x2 - x1, 1), height: 52,
                                   fill: "var(--window)", opacity: 0.16 }));
      svg.appendChild(el("line", { x1: x1, y1: axisY - 26, x2: x1, y2: axisY + 26,
                                   stroke: "var(--window)", "stroke-width": 1.5,
                                   "stroke-dasharray": "4 3" }));
      text(svg, { x: (x1 + x2) / 2, y: axisY - 34, "text-anchor": "middle",
                  fill: "var(--window)", "font-size": 12, "font-weight": 600 },
           `${CHART.requires.windowText} window`);
    }

    svg.appendChild(el("line", { x1: L - 26, y1: axisY, x2: R + 30, y2: axisY,
                                 stroke: "var(--rule)", "stroke-width": 2 }));

    EVENTS.forEach((ev, i) => {
      const x = xOf(ev, i), color = KIND_COLOR[ev.kind] || "var(--ink-faint)";
      svg.appendChild(el("line", { x1: x, y1: axisY - 26, x2: x, y2: axisY,
                                   stroke: color, "stroke-width": 2, opacity: 0.45 }));
      // A refusal is a square, so it reads differently from an attempt at a glance.
      svg.appendChild(ev.kind === "error"
        ? el("rect", { x: x - 8, y: axisY - 8, width: 16, height: 16, fill: color, rx: 2 })
        : el("circle", { cx: x, cy: axisY, r: 8, fill: color }));

      text(svg, { x, y: axisY + 26, "text-anchor": "middle", fill: "var(--ink-faint)",
                  "font-size": 13, ...MONO }, "@" + ev.at);
      text(svg, { x, y: axisY - 40, "text-anchor": "middle", fill: "var(--ink)",
                  "font-size": 12.5, ...MONO }, ev.action + "::" + ev.kind);
      text(svg, { x, y: axisY - 56, "text-anchor": "middle", fill: "var(--ink-faint)",
                  "font-size": 12 }, note(ev));

      if (ev.verdict) {
        const bad = ev.verdict === "DENY" ? "var(--deny)" : "var(--allow)";
        svg.appendChild(el("rect", { x: x - 48, y: axisY + 44, width: 96, height: 42, rx: 6,
                                     fill: "none", stroke: bad, "stroke-width": 1.5 }));
        text(svg, { x, y: axisY + 62, "text-anchor": "middle", fill: bad,
                    "font-size": 14, "font-weight": 700, ...MONO }, ev.verdict);
        // No rule means the deny was by default, which is a different fact worth saying.
        text(svg, { x, y: axisY + 78, "text-anchor": "middle", fill: "var(--ink-faint)",
                    "font-size": 11.5 },
             ev.rules.length ? "rule " + ev.rules.join(", ") : "by default");
      }
    });

    text(svg, { x: L - 26, y: axisY + 112, fill: "var(--ink-faint)", "font-size": 11.5 },
         proportional ? "Events are placed by timestamp."
                      : "Events are evenly spaced; timestamps would overlap at this scale.");
  })();

  // --- the aggregate chart: one bar per event kind --------------------------
  // The rule names ONE kind. Summing the same field over each kind and letting the reader compare
  // is mechanical; saying which kind the requirement meant would not be.
  if (CHART && CHART.kind === "aggregate" && document.getElementById("chart")) {
    const svg = document.getElementById("chart");
    set("chart-heading",
        `what rule ${CHART.rule} sums, by event kind, within ${CHART.windowText}`);

    const L = 250, R = 790;
    const rows = KINDS.map(k => ({
      kind: k,
      value: EVENTS.filter(e => e.action === CHART.action && e.kind === k)
                   .reduce((s, e) => s + (readField(e) ?? 0), 0)
    }));
    const max = Math.max(...rows.map(r => r.value), CHART.threshold) * 1.15;
    const x = v => L + (v / max) * (R - L);
    svg.setAttribute("aria-label", rows.map(r => `${r.kind} ${money(r.value)}`).join("; "));

    rows.forEach((row, i) => {
      const y = 42 + i * 56;
      const counted = row.kind === CHART.eventKind;
      const color = counted ? "var(--counted)" : "var(--quiet)";
      text(svg, { x: L - 16, y: y + 14, "text-anchor": "end", fill: "var(--ink)",
                  "font-size": 14, "font-weight": 600, ...MONO }, "::" + row.kind);
      if (counted) {
        text(svg, { x: L - 16, y: y + 31, "text-anchor": "end", fill: "var(--counted)",
                    "font-size": 11.5, "font-weight": 600 }, `counted by rule ${CHART.rule}`);
      }
      svg.appendChild(el("rect", { x: L, y, width: R - L, height: 24, rx: 4,
                                   fill: "var(--rule)", opacity: 0.4 }));
      // Give zero a sliver, so it reads as measured rather than missing.
      const w = Math.max(x(row.value) - L, row.value === 0 ? 3 : 0);
      svg.appendChild(el("rect", { x: L, y, width: w, height: 24, rx: 4, fill: color,
                                   opacity: counted ? 1 : 0.55 }));
      text(svg, { x: L + w + 12, y: y + 17, fill: color, "font-size": 14,
                  "font-weight": 700, ...MONO }, money(row.value));
    });

    const cx = x(CHART.threshold);
    svg.appendChild(el("line", { x1: cx, y1: 22, x2: cx, y2: 42 + rows.length * 56 - 14,
                                 stroke: "var(--cap)", "stroke-width": 1.5,
                                 "stroke-dasharray": "5 4" }));
    text(svg, { x: cx, y: 14, "text-anchor": "middle", fill: "var(--cap)", "font-size": 12,
                "font-weight": 600, ...MONO },
         `forbids ${CHART.cmp} ${money(CHART.threshold)}`);
    text(svg, { x: L, y: 42 + rows.length * 56 + 14, fill: "var(--ink-soft)", "font-size": 13 },
         "Same session, same field. Only ::response means it completed.");
  } else {
    show("chart-panel", false);
  }

  // --- the prose, named from the data --------------------------------------
  if (CHART && CHART.kind === "aggregate") {
    set("why-rule",
      `Rule&nbsp;${CHART.rule} &mdash; <i>${ruleName()}</i> &mdash; takes the ` +
      `<code>${CHART.aggregate}</code> of <code>${CHART.field}</code> over ` +
      `<code>${CHART.action}::${CHART.eventKind}</code> within <code>${CHART.windowText}</code>, ` +
      `and forbids when that total is <code>${CHART.cmp} ${money(CHART.threshold)}</code>.`);
  } else if (CHART && CHART.kind === "predicate" && CHART.requires) {
    const r = CHART.requires;
    const gap = (decisionAt !== null && EVENTS.length)
      ? decisionAt - EVENTS[0].at : null;
    const inside = gap !== null && gap <= r.window;
    set("why-rule",
      `Rule&nbsp;${CHART.rule} &mdash; <i>${ruleName()}</i> &mdash; is a ` +
      `<code>${CHART.effect}</code> on <code>${(CHART.actions || []).join(", ")}</code> gated ` +
      `<b>${CHART.negated ? "unless" : "when"}</b> ` +
      `<code>${r.action}::${r.eventKind}</code> occurred within ` +
      `<code>${r.windowText}</code>.`);
    set("why-consequence",
      gap === null ? "" :
      `Here the gap is <code>${dur(gap)}</code> against a window of <code>${r.windowText}</code>, so the ` +
      `condition is <b>${inside ? "true" : "false"}</b> &mdash; and because the rule is gated ` +
      `<b>${CHART.negated ? "unless" : "when"}</b>, that makes the ${CHART.effect} ` +
      `<b>${(CHART.negated ? !inside : inside) ? "fire" : "stay shut"}</b>.`);
  }

  // --- provenance -----------------------------------------------------------
  set("provenance",
    `Trace generated by <code>src/checker/witness.py</code> from the TLC counterexample to ` +
    `<code>${DATA.claim}</code>; this page's data by <code>${DATA.generatedBy}</code>, which ` +
    `reads the rule out of the policy rather than restating it. Verdicts are the reference ` +
    `engine's, not ours:<br><code>${DATA.source.replay}</code><br>&rarr; ` +
    decisions.map(d => `<code>@${d.at}: ${d.verdict}` +
      `${d.rules.length ? " [rules: " + d.rules.join(", ") + "]" : ""}</code>`).join(" &middot; "));
})();
