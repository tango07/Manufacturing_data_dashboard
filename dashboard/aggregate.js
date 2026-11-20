// Aggregation for the dashboard. It adds up the cleaned rows the pipeline exports, for whatever date range
// the user picks. Every rate is a ratio of sums (never an average of row rates), matching pipeline/kpis.py
// and pipeline/views.py. tests/pipeline/test_aggregate.py checks these totals against the pipeline's own
// results for the same windows.

function createAggregator(rows) {
  const toObjects = t => t.data.map(r => Object.fromEntries(t.columns.map((c, i) => [c, r[i]])));
  const RUNS = toObjects(rows.runs);
  const EVENTS = toObjects(rows.events);
  const MATS = toObjects(rows.materials);
  const INSP = toObjects(rows.inspections);
  const dates = RUNS.map(r => r.date).sort();
  const FIRST = dates[0];
  const LAST = dates[dates.length - 1];

  const DAY = 86400000;
  function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function daysBetween(a, b) {
    return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / DAY);
  }
  function dayList(a, b) {
    const out = [];
    for (let d = a; d <= b; d = addDays(d, 1)) out.push(d);
    return out;
  }
  function fmtDay(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {day: "2-digit", month: "short", year: "numeric", timeZone: "UTC"});
  }
  const ratio = (n, d) => (d ? n / d : null);
  const materialTypes = () => [...new Set(MATS.map(m => m.material_type))].sort();
  const inScope = (plant, shift) => r => (plant === "ALL" || r.plant === plant) && (shift === "ALL" || r.shift === shift);

  function totalsOf(runs) {
    const t = {runs: runs.length, produced: 0, planned: 0, good: 0, sched: 0, dt_min: 0, dt_unpl: 0, repair: 0, scrap: 0};
    for (const r of runs) {
      t.produced += r.produced; t.planned += r.planned; t.good += r.good; t.sched += r.sched;
      t.dt_min += r.dt_min; t.dt_unpl += r.dt_unpl; t.repair += r.dt_repair; t.scrap += r.scrap_cost;
    }
    return t;
  }

  function windowMetrics(runs, label) {
    if (!runs.length) return null;
    const t = totalsOf(runs);
    return {
      label,
      days_with_runs: new Set(runs.map(r => r.date)).size,
      runs: t.runs,
      produced_units: t.produced,
      plan_attainment: ratio(t.produced, t.planned),
      scrap_rate: ratio(t.produced - t.good, t.produced),
      unplanned_minutes: t.dt_unpl,
      repair_cost_usd: t.repair,
    };
  }

  // The window compared with the equal-length window directly before it.
  function compareWith(start, end, plant, shift) {
    const len = daysBetween(start, end) + 1;
    const prevLo = addDays(start, -len), prevHi = addDays(start, -1);
    const scope = inScope(plant, shift);
    const cur = RUNS.filter(r => r.date >= start && r.date <= end && scope(r));
    const prev = RUNS.filter(r => r.date >= prevLo && r.date <= prevHi && scope(r));
    const current = windowMetrics(cur, `${fmtDay(start)} to ${fmtDay(end)}`);
    const previous = windowMetrics(prev, `${fmtDay(prevLo)} to ${fmtDay(prevHi)}`);
    if (!current || !previous) return null;
    const diff = k => (current[k] === null || previous[k] === null ? null : current[k] - previous[k]);
    return {current, previous, change: {
      plan_attainment: diff("plan_attainment"), scrap_rate: diff("scrap_rate"),
      unplanned_minutes: diff("unplanned_minutes"), runs: diff("runs"), produced_units: diff("produced_units")}};
  }

  // Everything the charts and tiles need for one selection, shaped like the pipeline's views.
  function viewFor(start, end, plant, shift, material = "ALL") {
    const scope = inScope(plant, shift);
    const runs = RUNS.filter(r => r.date >= start && r.date <= end && scope(r));
    const ids = new Set(runs.map(r => r.run));
    const events = EVENTS.filter(e => ids.has(e.run));
    // Materials: the all-types set feeds the by-type chart; the selected material feeds the QC, moisture,
    // purity and cost figures and the supplier QC chart.
    const matsAll = MATS.filter(m => ids.has(m.run));
    const mats = material === "ALL" ? matsAll : matsAll.filter(m => m.material_type === material);
    const insps = INSP.filter(i => ids.has(i.run));
    const t = totalsOf(runs);
    const sortDesc = (arr, key) => arr.sort((a, b) => (b[key] ?? -Infinity) - (a[key] ?? -Infinity));

    const group = (list, keyFn, init, add) => {
      const out = new Map();
      for (const x of list) {
        const k = keyFn(x);
        if (!out.has(k)) out.set(k, init(k));
        add(out.get(k), x);
      }
      return [...out.values()];
    };

    const byProduct = sortDesc(group(runs, r => r.product,
      k => ({label: k, runs: 0, produced_units: 0}),
      (g, r) => { g.runs += 1; g.produced_units += r.produced; }), "runs");

    const catMinutes = group(events, e => e.category,
      k => ({label: k, minutes: 0}), (g, e) => { g.minutes += e.minutes; });
    const catTotal = catMinutes.reduce((a, g) => a + g.minutes, 0);
    const byCategory = sortDesc(catMinutes.map(g => ({label: g.label, minutes: g.minutes,
      share: ratio(g.minutes, catTotal)})), "minutes");

    const byLine = sortDesc(group(runs, r => `${r.plant} · ${r.line}`,
      k => ({label: k, produced: 0, scrap: 0, runs: 0}),
      (g, r) => { g.produced += r.produced; g.scrap += r.produced - r.good; g.runs += 1; }).map(g => ({
      label: g.label, scrap_rate: ratio(g.scrap, g.produced), runs: g.runs})), "scrap_rate");

    const costBy = (field) => sortDesc(group(runs, r => r[field],
      k => ({label: k, scrap: 0, repair: 0}),
      (g, r) => { g.scrap += r.scrap_cost; g.repair += r.dt_repair; }).map(g => ({
      label: g.label, scrap_cost_usd: g.scrap, repair_cost_usd: g.repair, total_usd: g.scrap + g.repair})), "total_usd");

    const bySupplier = group(mats, m => m.supplier,
      k => ({label: k, records: 0, fails: 0}),
      (g, m) => { g.records += 1; g.fails += m.fail ? 1 : 0; }).map(g => ({
      label: g.label, fail_rate: ratio(g.fails, g.records), records: g.records}));

    // Daily series: plan attainment and scrap rate from runs; unplanned minutes from events by event date.
    const days = dayList(start, end);
    const perDay = new Map();
    for (const r of runs) {
      const p = perDay.get(r.date) || {produced: 0, planned: 0, good: 0};
      p.produced += r.produced; p.planned += r.planned; p.good += r.good;
      perDay.set(r.date, p);
    }
    const unplanned = new Map();
    for (const e of events) if (e.unplanned) unplanned.set(e.date, (unplanned.get(e.date) || 0) + e.minutes);
    const minutes = days.map(d => unplanned.get(d) || 0);
    const daily = days.map((d, i) => {
      const p = perDay.get(d);
      const window = minutes.slice(Math.max(0, i - 6), i + 1);
      return {
        date: d,
        plan_attainment: p ? ratio(p.produced, p.planned) : null,
        scrap_rate: p ? ratio(p.produced - p.good, p.produced) : null,
        unplanned_minutes: minutes[i],
        unplanned_7day_avg: window.reduce((a, b) => a + b, 0) / window.length,
      };
    });

    // Defect types (K6) and sample defect rate (K5), from the inspections in scope.
    const defectTotal = insps.reduce((a, i) => a + i.defects, 0);
    const sampleTotal = insps.reduce((a, i) => a + i.sample, 0);
    const byDefect = sortDesc(group(insps, i => i.defect_type,
      k => ({label: k, defects: 0, sample: 0, inspections: 0}),
      (g, i) => { g.defects += i.defects; g.sample += i.sample; g.inspections += 1; }).map(g => ({
      label: g.label, defects: g.defects, rate: ratio(g.defects, g.sample), inspections: g.inspections})), "defects");

    // Materials by type: records, incoming QC fail rate, cost, and mean moisture and purity (K7, K8, K9).
    const moistureTotal = mats.reduce((a, m) => a + m.moisture, 0);
    const purityTotal = mats.reduce((a, m) => a + m.purity, 0);
    const materialCost = mats.reduce((a, m) => a + m.cost, 0);
    const byMaterial = sortDesc(group(matsAll, m => m.material_type,
      k => ({label: k, records: 0, fails: 0, cost: 0, moisture: 0, purity: 0}),
      (g, m) => { g.records += 1; g.fails += m.fail ? 1 : 0; g.cost += m.cost; g.moisture += m.moisture; g.purity += m.purity; })
      .map(g => ({label: g.label, records: g.records, fail_rate: ratio(g.fails, g.records), cost_usd: g.cost,
        moisture_mean: ratio(g.moisture, g.records), purity_mean: ratio(g.purity, g.records)})), "records");

    return {
      totals: {scrap_cost_usd: t.scrap, repair_cost_usd: t.repair},
      defect_by_type: byDefect,
      materials_by_type: byMaterial,
      daily,
      runs_by_product: byProduct,
      downtime_by_category: byCategory,
      scrap_by_line: byLine,
      loss_by_plant: costBy("plant"),
      loss_by_machine: costBy("machine"),
      qc_by_supplier: sortDesc(bySupplier, "fail_rate"),
      headline: {
        K1: {records: t.runs, numerator: t.produced, denominator: t.planned, value: ratio(t.produced, t.planned)},
        K2: {value: ratio(t.produced - t.good, t.produced)},
        K3a: {value: t.dt_unpl},
        K3b: {value: ratio(t.dt_min, t.sched)},
        K4: {value: t.repair},
        K7: {records: mats.length, numerator: mats.filter(m => m.fail).length, denominator: mats.length,
             value: ratio(mats.filter(m => m.fail).length, mats.length)},
        K5: {records: insps.length, numerator: defectTotal, denominator: sampleTotal, value: ratio(defectTotal, sampleTotal)},
        K8_moisture: {records: mats.length, value: ratio(moistureTotal, mats.length)},
        K8_purity: {records: mats.length, value: ratio(purityTotal, mats.length)},
        K9_material_cost: {records: mats.length, value: materialCost},
      },
    };
  }

  return {FIRST, LAST, addDays, daysBetween, fmtDay, viewFor, compareWith, materialTypes, runCount: RUNS.length};
}
