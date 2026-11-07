/**
 * AutoHunter → Google Sheets. Paste into the sheet's Extensions → Apps Script, then
 * Deploy → New deployment → Web app (Execute as: Me, Who has access: Anyone).
 * Requests need TOKEN, so the URL alone isn't enough to write to your sheet.
 * `main.py sheets setup` fills TOKEN in for you.
 */
const TOKEN = "__TOKEN__";
const SHEET = "已投递";
const HEADERS = ["投递日期", "公司", "职位", "状态", "跟进日期", "简历改动", "Cover letter 要点",
                 "简历", "链接", "平台", "来源", "联系人", "备注", "key"];
// Columns you edit in the sheet. AutoHunter fills them once and never overwrites your edits.
const OWNED = ["状态", "跟进日期", "联系人", "备注"];
const STATUSES = ["Applied", "OA", "Interview", "Offer", "Rejected", "Withdrawn", "Ghosted"];
const DRIVE_FOLDER = "AutoHunter 简历";

function doPost(e) {
  let req;
  try { req = JSON.parse(e.postData.contents); } catch (err) { return out_({ok: false, error: "bad json"}); }
  if (req.token !== TOKEN) return out_({ok: false, error: "bad token"});
  if (req.action === "ping") return out_({ok: true, sheet: SpreadsheetApp.getActive().getName(), mail: MAIL_VERSION});
  if (req.action === "verification") return out_(verification_(req));
  if (req.action !== "upsert") return out_({ok: false, error: "unknown action"});
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = sheet_();
    const done = (req.rows || []).map(r => upsert_(sh, r));
    return out_({ok: true, rows: done.length});
  } finally {
    lock.releaseLock();
  }
}

// Workday account verification: read-only search of recent verification emails. Returns only the
// verification links / codes found, never other mail. Gmail access is used for nothing else.
const MAIL_VERSION = 1;
const MAIL_QUERY = 'newer_than:1d (from:myworkday.com OR from:workday.com OR from:myworkdayjobs.com ' +
                   'OR subject:(verify OR verification OR "confirm your" OR activate OR "security code"))';

function verification_(req) {
  const since = req.since ? new Date(req.since) : new Date(Date.now() - 30 * 60 * 1000);
  const hint = String(req.hint || "").toLowerCase();
  const hits = [];
  GmailApp.search(MAIL_QUERY, 0, 15).forEach(t => t.getMessages().forEach(m => {
    if (m.getDate() < since) return;
    const html = m.getBody(), text = m.getPlainBody();
    const hay = (m.getFrom() + " " + m.getSubject() + " " + text).toLowerCase();
    if (hint && !hay.includes(hint)) return;
    const links = [...html.matchAll(/href="([^"]+)"/g)].map(x => x[1].replace(/&amp;/g, "&"))
      .filter(u => /verif|activat|confirm|validate/i.test(u)).slice(0, 3);
    const codes = [...new Set([...text.matchAll(/\b(\d{6})\b/g)].map(x => x[1]))].slice(0, 3);
    if (links.length || codes.length)
      hits.push({date: m.getDate().toISOString(), from: m.getFrom(), subject: m.getSubject(), links, codes});
  }));
  hits.sort((a, b) => b.date.localeCompare(a.date));
  return {ok: true, messages: hits.slice(0, 5)};
}

/** Run this once from the editor (select "authorize" → ▶ Run) to grant the Gmail + Drive +
 *  Sheets permissions. Redeploying alone doesn't ask for newly added permissions. */
function authorize() {
  GmailApp.search(MAIL_QUERY, 0, 1);
  folder_();
  sheet_();
  Logger.log("AutoHunter: permissions OK");
}

function doGet(e) {
  if ((e.parameter || {}).token !== TOKEN) return out_({ok: false, error: "bad token"});
  const values = sheet_().getDataRange().getDisplayValues();
  const head = values.shift();
  return out_({ok: true, rows: values.map(r => Object.fromEntries(head.map((k, i) => [k, r[i]])))});
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function sheet_() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(SHEET);
  if (!sh) {
    sh = ss.insertSheet(SHEET, 0);
    setup_(sh);
  }
  return sh;
}

function col_(name) { return HEADERS.indexOf(name) + 1; }
function letter_(n) { return String.fromCharCode(64 + n); }

function setup_(sh) {
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS])
    .setFontWeight("bold").setBackground("#f1f3f4");
  sh.setFrozenRows(1);
  sh.hideColumns(col_("key"));
  const st = col_("状态");
  sh.getRange(2, st, 1000).setDataValidation(
    SpreadsheetApp.newDataValidation().requireValueInList(STATUSES, true).setAllowInvalid(true).build());
  const body = sh.getRange(2, 1, 1000, HEADERS.length - 1);
  const L = letter_(st);
  const colors = [["OA", "#e8f0fe"], ["Interview", "#d4edda"], ["Offer", "#b7e1cd"],
                  ["Rejected", "#f4c7c3"], ["Withdrawn", "#eeeeee"], ["Ghosted", "#eeeeee"]];
  sh.setConditionalFormatRules(colors.map(([v, c]) => SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied(`=$${L}2="${v}"`).setBackground(c).setRanges([body]).build()));
  const widths = {"投递日期": 95, "公司": 130, "职位": 260, "状态": 95, "跟进日期": 95, "简历改动": 340,
                  "Cover letter 要点": 260, "简历": 60, "链接": 60, "平台": 85, "来源": 90, "联系人": 140, "备注": 240};
  Object.entries(widths).forEach(([k, w]) => sh.setColumnWidth(col_(k), w));
  sh.getRange(2, col_("简历改动"), 1000, 2).setWrap(true);
}

function folder_() {
  const it = DriveApp.getFoldersByName(DRIVE_FOLDER);
  return it.hasNext() ? it.next() : DriveApp.createFolder(DRIVE_FOLDER);
}

function saveResume_(r) {
  const name = `${r["投递日期"] || ""} ${r["公司"] || ""} - ${r.resume_name || "CV.pdf"}`.trim();
  const blob = Utilities.newBlob(Utilities.base64Decode(r.resume_pdf_b64), MimeType.PDF, name);
  const folder = folder_();
  const old = folder.getFilesByName(name);
  while (old.hasNext()) old.next().setTrashed(true);
  return folder.createFile(blob).getUrl();
}

function upsert_(sh, r) {
  if (r.resume_pdf_b64) r["简历"] = `=HYPERLINK("${saveResume_(r)}","PDF")`;
  if (r["链接"] && !String(r["链接"]).startsWith("=")) r["链接"] = `=HYPERLINK("${r["链接"]}","打开")`;
  const values = sh.getDataRange().getValues();
  const keyIdx = col_("key") - 1;
  const at = values.findIndex((row, i) => i > 0 && row[keyIdx] === r.key);
  if (at < 0) {
    sh.appendRow(HEADERS.map(h => r[h] ?? ""));
    return "added";
  }
  const current = values[at];
  const merged = HEADERS.map((h, i) => {
    if (OWNED.includes(h) && current[i] !== "" && current[i] !== null) return current[i];
    if ((h === "简历" || h === "链接") && !r[h]) return sh.getRange(at + 1, i + 1).getFormula() || current[i];
    return r[h] ?? current[i];
  });
  sh.getRange(at + 1, 1, 1, HEADERS.length).setValues([merged]);
  return "updated";
}
