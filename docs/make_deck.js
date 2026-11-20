const pptxgen = require("pptxgenjs");

const NAVY = "1F2A37", TEAL = "0E9F8E", RED = "C2412D";
const LIGHT = "F3F5F7", MUTED = "5B6675", WHITE = "FFFFFF", INK = "1F2937";
const HEAD = "Cambria", BODY = "Calibri";

const outFile = process.argv[2];
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625 in
pres.title = "Axiom Operations Dashboard";
pres.author = "Vinithkumar Butta, Jayanth Konareddy, Akshay Hariwal";

function footer(slide, text, dark = false) {
  slide.addText(text, {x: 0.5, y: 5.2, w: 9, h: 0.25, fontFace: BODY, fontSize: 9,
    color: dark ? "A9B4C2" : MUTED, margin: 0, isTextBox: true});
}

function title(slide, text) {
  slide.addText(text, {x: 0.5, y: 0.35, w: 9, h: 0.7, fontFace: HEAD, fontSize: 30, bold: true,
    color: NAVY, margin: 0, isTextBox: true});
}

const bulletRuns = (items) => items.map((t, i) => ({text: t,
  options: {bullet: true, breakLine: i < items.length - 1, paraSpaceAfter: 6}}));

// ---- 1. Title and team ----------------------------------------------------------------
{
  const s = pres.addSlide();
  s.background = {color: NAVY};
  s.addText("Axiom Operations Dashboard", {x: 0.6, y: 1.2, w: 8.8, h: 1.0, fontFace: HEAD, fontSize: 40,
    bold: true, color: WHITE, margin: 0, isTextBox: true});
  s.addText("Manufacturing data intelligence for plant, machine and supplier performance", {x: 0.6, y: 2.2,
    w: 8.8, h: 0.5, fontFace: BODY, fontSize: 18, color: "8FE3D6", margin: 0, isTextBox: true});
  s.addText("EPAM Generative AI Kata · Axiom Auto Components", {x: 0.6, y: 2.7, w: 8.8, h: 0.4, fontFace: BODY,
    fontSize: 14, color: "A9B4C2", margin: 0, isTextBox: true});
  s.addText("Team", {x: 0.6, y: 3.7, w: 4, h: 0.3, fontFace: BODY, fontSize: 12, bold: true,
    color: "A9B4C2", margin: 0, isTextBox: true});
  ["Vinithkumar Butta", "Jayanth Konareddy", "Akshay Hariwal"].forEach((m, i) => {
    s.addText(m, {x: 0.6 + i * 3.0, y: 4.0, w: 2.8, h: 0.4, fontFace: BODY, fontSize: 16, bold: true,
      color: WHITE, margin: 0, isTextBox: true});
  });
}

// ---- 2. Why a dashboard was needed -----------------------------------------------------
{
  const s = pres.addSlide();
  s.background = {color: WHITE};
  title(s, "Why we needed a dashboard");
  s.addText("Leaders saw inconsistent reports while losses grew. Four departments exported four separate spreadsheets.",
    {x: 0.5, y: 1.05, w: 9, h: 0.5, fontFace: BODY, fontSize: 14, color: MUTED, margin: 0, isTextBox: true});

  const cards = [
    ["Reports disagreed", "Production, maintenance, quality and purchasing each exported their own data, so totals did not reconcile."],
    ["Output looked healthy", "Plan attainment hid rising scrap and downtime, so the cost of rejects and stoppages went unseen."],
    ["No defensible cause", "The COO needed a root-cause view and a ranked action plan that can be traced back to source rows."],
  ];
  cards.forEach((c, i) => {
    const x = 0.5 + i * 3.08;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {x, y: 1.75, w: 2.85, h: 1.95, fill: {color: LIGHT},
      line: {color: LIGHT}, rectRadius: 0.08});
    s.addShape(pres.shapes.OVAL, {x: x + 0.2, y: 1.95, w: 0.45, h: 0.45, fill: {color: TEAL}, line: {color: TEAL}});
    s.addText(String(i + 1), {x: x + 0.2, y: 1.95, w: 0.45, h: 0.45, fontFace: BODY, fontSize: 14, bold: true,
      color: WHITE, align: "center", valign: "middle", margin: 0, isTextBox: true});
    s.addText(c[0], {x: x + 0.2, y: 2.5, w: 2.5, h: 0.35, fontFace: BODY, fontSize: 15, bold: true,
      color: NAVY, margin: 0, isTextBox: true});
    s.addText(c[1], {x: x + 0.2, y: 2.85, w: 2.5, h: 0.8, fontFace: BODY, fontSize: 12, color: INK,
      margin: 0, valign: "top", isTextBox: true});
  });

  [["975", "clean production runs (of 1,000)"], ["17,695", "unplanned downtime minutes"],
   ["$1.21M", "repair and scrap cost"], ["13.9%", "incoming QC fail rate"]].forEach((st, i) => {
    const x = 0.5 + i * 2.27;
    s.addText(st[0], {x, y: 3.95, w: 2.1, h: 0.6, fontFace: HEAD, fontSize: 30, bold: true, color: RED, margin: 0,
      isTextBox: true});
    s.addText(st[1], {x, y: 4.55, w: 2.1, h: 0.5, fontFace: BODY, fontSize: 12, color: MUTED, margin: 0, valign: "top",
      isTextBox: true});
  });
  footer(s, "Source: full Excel export, production runs 1 Jul to 22 Sep 2026.");
}

// ---- 3. Architecture and tables -----------------------------------------------------------
{
  const s = pres.addSlide();
  s.background = {color: WHITE};
  title(s, "Architecture and tables (high-level design)");

  const flow = [
    ["Excel exports", "4 files, 1,000 rows each"],
    ["Ingest", "raw_* tables + source row"],
    ["Clean and join", "clean_*, quarantine_*"],
    ["KPIs and leadership", "run_fact, kpi_snapshot"],
    ["Dashboard", "HTML page + aggregate.js"],
    ["Chat server", "streams replies from the LLM"],
  ];
  const bw = 1.4, gap = 0.22, y = 1.3;
  flow.forEach((f, i) => {
    const x = 0.3 + i * (bw + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {x, y, w: bw, h: 1.1, fill: {color: i >= 4 ? TEAL : NAVY},
      line: {color: i >= 4 ? TEAL : NAVY}, rectRadius: 0.06});
    s.addText([{text: f[0], options: {bold: true, breakLine: true, fontSize: 12}}, {text: f[1], options: {fontSize: 10}}],
      {x: x + 0.07, y: y + 0.1, w: bw - 0.14, h: 0.9, fontFace: BODY, color: WHITE, align: "center", valign: "middle",
       margin: 0, isTextBox: true});
    if (i < flow.length - 1) {
      s.addText("→", {x: x + bw, y: y + 0.3, w: gap, h: 0.4, fontFace: BODY, fontSize: 16, bold: true, color: MUTED,
        align: "center", margin: 0, isTextBox: true});
    }
  });

  const hdr = (t) => ({text: t, options: {bold: true, color: WHITE, fill: {color: NAVY}}});
  const rows = [
    [hdr("Layer"), hdr("Tables in data/db/axiom.db"), hdr("What it holds")],
    ["Raw", "raw_production_runs, raw_machine_downtime, raw_quality_inspections, raw_material_batches",
      "Rows as received, with file name and Excel row number"],
    ["Clean", "clean_production_runs, clean_machine_downtime, clean_quality_inspections, clean_material_batches",
      "Typed rows that passed the quality rules"],
    ["Quarantine", "quarantine_* (four tables), dq_exceptions",
      "Rejected rows with reason, and one log line per rule failure"],
    ["Derived", "run_fact, kpi_snapshot, ingest_log; exported rows (runs, events, inspections, materials)",
      "Run-level totals, KPI output, file hashes, and the cleaned rows the date filters add up"],
  ];
  s.addTable(rows, {x: 0.3, y: 2.75, w: 9.4, colW: [1.3, 4.9, 3.2], fontFace: BODY, fontSize: 11, color: INK,
    border: {type: "solid", color: "D5DBE3", pt: 0.75}, rowH: 0.45, valign: "middle", margin: 0.05});
  footer(s, "Joins are on Run_ID: child records are totalled per run, then left-joined onto production runs.");
}

// ---- 4. Prompt techniques and tech stack -----------------------------------------------------
{
  const s = pres.addSlide();
  s.background = {color: WHITE};
  title(s, "Prompt techniques and tech stack");

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {x: 0.4, y: 1.25, w: 4.5, h: 4.0, fill: {color: LIGHT}, line: {color: LIGHT},
    rectRadius: 0.08});
  s.addText("Prompt techniques", {x: 0.65, y: 1.4, w: 4.1, h: 0.4, fontFace: HEAD, fontSize: 18, bold: true, color: NAVY,
    margin: 0, isTextBox: true});
  s.addText(bulletRuns([
    "Role prompt: operations analyst for the COO, with company context",
    "XML-tagged prompt: <role>, <rules>, <answer_format>, <data_context>",
    "Turns tagged: questions in <question>, replies in <answer>",
    "Grounding: figures come only from the pipeline; the model never calculates",
    "Scope rules: flag missing data and out-of-scope questions",
    "Prompt caching: the data context is a cached system block",
    "Constrained output: plain prose, KPI IDs cited, about 200 words",
    "Memory: last 12 messages sent with each question",
  ]), {x: 0.65, y: 1.9, w: 4.1, h: 3.0, fontFace: BODY, fontSize: 11.5, color: INK, valign: "top", margin: 0,
    isTextBox: true});

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {x: 5.1, y: 1.25, w: 4.5, h: 4.0, fill: {color: LIGHT}, line: {color: LIGHT},
    rectRadius: 0.08});
  s.addText("Tech stack", {x: 5.35, y: 1.4, w: 4.1, h: 0.4, fontFace: HEAD, fontSize: 18, bold: true, color: NAVY,
    margin: 0, isTextBox: true});
  s.addText(bulletRuns([
    "Python 3.10: pandas and openpyxl for ingest and calculation",
    "SQLite: one local database file, rebuilt on each run",
    "Data quality rules DQ-01 to DQ-08, with quarantine and an exception log",
    "Dashboard: HTML, CSS, JavaScript and Chart.js 4.5",
    "Chat server: Python standard library, streaming over server-sent events",
    "LLM: Anthropic Messages API, key kept on the server in .env",
    "Tests: pytest (94 tests), including a Node check of the dashboard totals",
  ]), {x: 5.35, y: 1.9, w: 4.1, h: 3.0, fontFace: BODY, fontSize: 12, color: INK, valign: "top", margin: 0,
    isTextBox: true});
}

// ---- 5. Dashboard metrics -----------------------------------------------------------------
{
  const s = pres.addSlide();
  s.background = {color: WHITE};
  title(s, "Dashboard metrics");

  const hdr = (t) => ({text: t, options: {bold: true, color: WHITE, fill: {color: NAVY}}});
  const rows = [
    [hdr("Metric"), hdr("Definition"), hdr("Full data")],
    ["Plan attainment", "Units produced ÷ units planned", "95.8%"],
    ["Scrap rate", "(Produced − good) ÷ produced", "3.8%"],
    ["Unplanned downtime", "Minutes on unplanned events; rate is ÷ scheduled minutes", "17,695 min (9.0%)"],
    ["Repair + scrap cost", "Repair cost plus scrap units × unit cost (USD)", "$1.21M"],
    ["Sample defect rate", "Defects ÷ inspected sample", "4.5%"],
    ["Incoming QC fail rate", "Failed material records ÷ material records", "13.9%"],
  ];
  s.addTable(rows, {x: 0.4, y: 1.2, w: 5.6, colW: [1.55, 2.75, 1.3], fontFace: BODY, fontSize: 11, color: INK,
    border: {type: "solid", color: "D5DBE3", pt: 0.75}, rowH: 0.48, valign: "middle", margin: 0.05});

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {x: 6.25, y: 1.2, w: 3.35, h: 3.75, fill: {color: LIGHT},
    line: {color: LIGHT}, rectRadius: 0.08});
  s.addText("What the page shows", {x: 6.45, y: 1.35, w: 3.0, h: 0.35, fontFace: HEAD, fontSize: 15, bold: true,
    color: NAVY, margin: 0, isTextBox: true});
  s.addText(bulletRuns([
    "Tiles, and change against an equal-length window before",
    "Downtime by failure category (pie)",
    "Loss by plant and by machine (bars)",
    "Runs by product (pie); scrap rate by line (bars)",
    "Daily trends (lines), with a 7-day average for downtime",
    "Defects by type and materials by type (bars)",
    "Quality tiles: defect rate, QC fail rate, moisture, purity, cost",
    "Filters: calendar dates, plant, shift and material type",
  ]), {x: 6.45, y: 1.8, w: 3.0, h: 3.0, fontFace: BODY, fontSize: 10.5, color: INK, valign: "top", margin: 0,
    paraSpaceAfter: 5, isTextBox: true});
  footer(s, "Figures: full export, 975 clean production runs. Scrap cost uses Unit_Cost_USD per unit (assumption A-01).");
}

// ---- 6. Materials and defect metrics ----------------------------------------------------------
{
  const s = pres.addSlide();
  s.background = {color: WHITE};
  title(s, "Materials and defect metrics");

  const hdr = (t, right) => ({text: t, options: {bold: true, color: WHITE, fill: {color: NAVY}, align: right ? "right" : "left"}});
  const num = (t) => ({text: t, options: {align: "right"}});

  s.addText("Defects by type", {x: 0.4, y: 1.1, w: 4.4, h: 0.35, fontFace: HEAD, fontSize: 15, bold: true, color: NAVY,
    margin: 0, isTextBox: true});
  const defectRows = [
    [hdr("Defect type"), hdr("Defects", true), hdr("Defect rate", true), hdr("Inspections", true)],
    ["Porosity", num("803"), num("5.3%"), num("232")],
    ["Dimensional", num("663"), num("4.1%"), num("251")],
    ["Surface finish", num("628"), num("4.3%"), num("216")],
    ["Crack", num("379"), num("4.5%"), num("129")],
    ["Other", num("300"), num("4.0%"), num("115")],
    [{text: "All types", options: {bold: true}}, num("2,773"), num("4.5%"), num("943")],
  ];
  s.addTable(defectRows, {x: 0.4, y: 1.5, w: 4.4, colW: [1.5, 0.9, 1.0, 1.0], fontFace: BODY, fontSize: 10.5, color: INK,
    border: {type: "solid", color: "D5DBE3", pt: 0.75}, rowH: 0.33, valign: "middle", margin: 0.04});

  s.addText("Materials by type", {x: 5.0, y: 1.1, w: 4.6, h: 0.35, fontFace: HEAD, fontSize: 15, bold: true, color: NAVY,
    margin: 0, isTextBox: true});
  const matRows = [
    [hdr("Material"), hdr("Records", true), hdr("QC fail", true), hdr("Cost", true), hdr("Moist.", true), hdr("Purity", true)],
    ["Alloy steel", num("334"), num("13.5%"), num("$1.50M"), num("0.246%"), num("98.87%")],
    ["Aluminum", num("302"), num("14.9%"), num("$1.40M"), num("0.244%"), num("98.90%")],
    ["Cast iron", num("302"), num("13.2%"), num("$1.38M"), num("0.251%"), num("98.88%")],
  ];
  s.addTable(matRows, {x: 5.0, y: 1.5, w: 4.6, colW: [1.0, 0.7, 0.7, 0.8, 0.7, 0.7], fontFace: BODY, fontSize: 10,
    color: INK, border: {type: "solid", color: "D5DBE3", pt: 0.75}, rowH: 0.33, valign: "middle", margin: 0.04});

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {x: 0.4, y: 4.2, w: 9.2, h: 0.85, fill: {color: LIGHT}, line: {color: LIGHT},
    rectRadius: 0.08});
  s.addText([
    {text: "Reading the figures: ", options: {bold: true}},
    {text: "porosity is the largest defect type. QC fail rates are similar across material types (13% to 15%), so the QC "
      + "failures are concentrated by supplier rather than by material. Material cost is the total over all records."},
  ], {x: 0.6, y: 4.25, w: 8.8, h: 0.75, fontFace: BODY, fontSize: 12, color: INK, valign: "middle", margin: 0,
    isTextBox: true});
  footer(s, "Defect rate = defects ÷ sampled units. QC fail rate = failed records ÷ material records. Full export, 975 clean runs.");
}

pres.writeFile({fileName: outFile}).then(f => console.log("wrote", f));
