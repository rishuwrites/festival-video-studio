/**
 * Daily festival video scheduler.
 *
 * Setup:
 * 1. Copy this file into a Google Apps Script project.
 * 2. In Project Settings > Script properties, add GITHUB_PAT with a token
 *    allowed to dispatch workflows in rishuwrites/festival-video-studio.
 * 3. Run setupDailyTrigger() once and authorize the requested permissions.
 *
 * The trigger runs near 02:05 Asia/Kolkata. It prepares the calendar topic
 * three days ahead and schedules public release at 09:00 IST, one day ahead.
 * YouTube requires future-scheduled uploads to be private until publishAt;
 * YouTube makes them public at that time.
 */

const OWNER = "rishuwrites";
const REPO = "festival-video-studio";
const BRANCH = "main";
const LEGACY_WORKFLOW = "festival-video.yml";
const BATCH_WORKFLOW = "daily-batch.yml";
const TIME_ZONE = "Asia/Kolkata";
const PUBLISH_TIME = "09:00";
const GENERATION_LEAD_DAYS = 3;
const PUBLISH_LEAD_DAYS = 2;
const LEGACY_CALENDAR_URL =
  "https://raw.githubusercontent.com/rishuwrites/festival-video-studio/main/data/india-festival-video-calendar-2026.json";
const BATCH_CALENDAR_URL =
  "https://raw.githubusercontent.com/rishuwrites/festival-video-studio/main/calendar/content_calendar.json";

function setupDailyTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === "dispatchTodaysFestivalVideo")
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));

  ScriptApp.newTrigger("dispatchTodaysFestivalVideo")
    .timeBased()
    .atHour(2)
    .nearMinute(5)
    .everyDays(1)
    .inTimezone(TIME_ZONE)
    .create();

  Logger.log("Installed daily video dispatch trigger near 02:05 IST.");
}

function dispatchTodaysFestivalVideo() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error("Another daily video dispatch is already running.");
  }

  try {
    const now = new Date();
    const today = Utilities.formatDate(now, TIME_ZONE, "yyyy-MM-dd");
    const properties = PropertiesService.getScriptProperties();
    const dispatchKey = "DISPATCHED_" + today;
    if (!properties.getProperty(dispatchKey)) {
      const publishDate = shiftDate(today, GENERATION_LEAD_DAYS - PUBLISH_LEAD_DAYS);
      const festivalDate = shiftDate(today, GENERATION_LEAD_DAYS);
      const publishAt = new Date(publishDate + "T" + PUBLISH_TIME + ":00+05:30");
      if (publishAt.getTime() <= now.getTime() + 15 * 60 * 1000) {
        throw new Error("Too late to safely schedule the video for " + publishDate + " " + PUBLISH_TIME + " IST.");
      }

      const calendar = fetchJson(LEGACY_CALENDAR_URL, "festival calendar");
      if (festivalDate >= calendar.start_date && festivalDate <= calendar.end_date) {
        const entry = (calendar.entries || []).find(item => item.date === festivalDate);
        if (!entry) {
          throw new Error("No video brief exists for " + festivalDate + " in the festival calendar.");
        }
        const monthSource = festivalDate.slice(5, 7) === "11" ? "drik_november" : "drik_december";
        const sourceIds = Array.from(new Set([...(entry.source_ids || []), monthSource]));
        const sources = sourceIds
          .map(sourceId => calendar.sources && calendar.sources[sourceId])
          .filter(source => source && source.title && source.url);
        if (!entry.topic || !entry.research_notes || !Array.isArray(entry.panchang_events) || sources.length < 2) {
          throw new Error("The " + festivalDate + " calendar brief needs a topic, notes, event list, and at least two sources.");
        }

        const legacyResult = dispatchWorkflow(LEGACY_WORKFLOW, {
          topic: entry.topic,
          date: festivalDate,
          scope: entry.scope || calendar.default_scope,
          publish_date: publishDate,
          publish_time: PUBLISH_TIME,
          research_context: JSON.stringify({
            notes: [
              entry.festival
                ? "Scheduled observance: " + entry.festival
                : "Evergreen calendar topic: " + entry.topic,
              "Calendar target date: " + festivalDate + "; planned public release: " + publishDate + " (two days before the target date).",
              entry.date_confidence ? "Date confidence: " + entry.date_confidence : "",
              entry.panchang_events.length
                ? "Other observances on this date in the monthly Panchang listing (keep distinct and identify regional scope): " + entry.panchang_events.join("; ")
                : "",
              entry.research_notes
            ].filter(Boolean).join("\n"),
            sources: sources,
            search_queries: entry.search_queries || []
          }),
          upload: "true",
          facebook_upload: "true"
        });
        properties.setProperty(dispatchKey, legacyResult);
        Logger.log(
          "Dispatched legacy video " + entry.topic + " for calendar date " + festivalDate +
          ", public release " + publishDate + " at " + PUBLISH_TIME + " IST (run " + legacyResult + ")"
        );
      } else {
        Logger.log("No legacy calendar coverage for " + festivalDate + "; skipping legacy dispatch.");
        properties.setProperty(dispatchKey, "no-legacy-coverage");
      }
    } else {
      Logger.log("Legacy video already handled today: " + properties.getProperty(dispatchKey));
    }

    const batchKey = "BATCH_DISPATCHED_" + today;
    if (properties.getProperty(batchKey)) {
      Logger.log("Daily batch already dispatched today: " + properties.getProperty(batchKey));
      return;
    }

    const batchDate = shiftDate(today, PUBLISH_LEAD_DAYS);
    const batchCalendar = fetchJson(BATCH_CALENDAR_URL, "daily batch calendar");
    if (batchDate < batchCalendar.start_date || batchDate > batchCalendar.end_date) {
      Logger.log("No batch calendar coverage for " + batchDate + "; skipping batch dispatch.");
      properties.setProperty(batchKey, "no-batch-coverage");
      return;
    }
    const batchRows = (batchCalendar.videos || []).filter(item => item.date === batchDate);
    if (batchRows.length !== 10 || !batchRows.some(item => item.status === "planned")) {
      throw new Error("The batch calendar needs ten slots and at least one planned video for " + batchDate + ".");
    }
    const batchResult = dispatchWorkflow(BATCH_WORKFLOW, { date: batchDate });
    properties.setProperty(batchKey, batchResult);
    properties.setProperty("LAST_BATCH_DISPATCH", today + " " + batchDate + " [" + batchResult + "]");
    Logger.log("Dispatched daily batch for " + batchDate + " (run " + batchResult + ")");
  } finally {
    lock.releaseLock();
  }
}

function fetchJson(url, label) {
  const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (response.getResponseCode() !== 200) {
    throw new Error("Could not read " + label + " (HTTP " + response.getResponseCode() + ").");
  }
  return JSON.parse(response.getContentText());
}

function shiftDate(isoDate, days) {
  const date = new Date(isoDate + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + days);
  return Utilities.formatDate(date, "UTC", "yyyy-MM-dd");
}

function dispatchWorkflow(workflow, inputs) {
  const token = PropertiesService.getScriptProperties().getProperty("GITHUB_PAT");
  if (!token) {
    throw new Error("Set GITHUB_PAT in Apps Script project Script properties first.");
  }

  const url = "https://api.github.com/repos/" + OWNER + "/" + REPO +
    "/actions/workflows/" + workflow + "/dispatches";
  const response = UrlFetchApp.fetch(url, {
    method: "post",
    headers: {
      Authorization: "Bearer " + token,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"
    },
    contentType: "application/json",
    payload: JSON.stringify({ ref: BRANCH, inputs: inputs }),
    muteHttpExceptions: true
  });
  if (response.getResponseCode() !== 204) {
    throw new Error(
      "GitHub workflow dispatch failed (HTTP " + response.getResponseCode() + "): " +
      response.getContentText().slice(0, 500)
    );
  }
  return Utilities.formatDate(new Date(), TIME_ZONE, "yyyyMMdd'T'HHmmss");
}
