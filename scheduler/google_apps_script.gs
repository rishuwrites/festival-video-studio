/**
 * Daily festival video scheduler.
 *
 * Setup:
 * 1. Copy this file into a Google Apps Script project.
 * 2. In Project Settings > Script properties, add GITHUB_PAT with a token
 *    allowed to dispatch workflows in rishuwrites/festival-video-studio.
 * 3. Run setupDailyTrigger() once and authorize the requested permissions.
 *
 * The daily trigger dispatches one festival video for tomorrow and one
 * Panchang video two days ahead. A two-hour trigger retries only these videos.
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
const ACTIVE_BATCH_SLOTS = new Set([1]);
const RETRY_COOLDOWN_MS = 15 * 60 * 1000;
const RETRYABLE_BATCH_STATUSES = new Set([
  "planned", "generated", "scheduled", "failed_saved_to_drive", "skipped"
]);

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

  setupRetryTrigger();
  Logger.log("Installed daily video dispatch trigger near 02:05 IST.");
}

function setupRetryTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === "checkAndRetryFailedVideos")
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));

  ScriptApp.newTrigger("checkAndRetryFailedVideos")
    .timeBased()
    .everyHours(2)
    .create();
  Logger.log("Installed two-hour upload verification and retry trigger.");
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
        throw new Error("Too late to safely schedule the festival video for " + publishDate + " " + PUBLISH_TIME + " IST.");
      }

      const calendar = fetchJson(LEGACY_CALENDAR_URL, "festival calendar");
      if (festivalDate >= calendar.start_date && festivalDate <= calendar.end_date) {
        const entry = (calendar.entries || []).find(item => item.date === festivalDate);
        if (!entry) {
          throw new Error("No festival video brief exists for " + festivalDate + ".");
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
        properties.setProperty("LEGACY_TARGET_" + publishDate, String(Date.now()));
        Logger.log(
          "Dispatched festival video " + entry.topic + " for calendar date " + festivalDate +
          ", public release " + publishDate + " at " + PUBLISH_TIME + " IST (run " + legacyResult + ")"
        );
      } else {
        Logger.log("No legacy calendar coverage for " + festivalDate + "; skipping festival dispatch.");
        properties.setProperty(dispatchKey, "no-legacy-coverage");
      }
    } else {
      Logger.log("Festival video already handled today: " + properties.getProperty(dispatchKey));
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
    const batchRows = (batchCalendar.videos || []).filter(item => (
      item.date === batchDate && ACTIVE_BATCH_SLOTS.has(Number(item.slot))
    ));
    if (
      batchRows.length !== ACTIVE_BATCH_SLOTS.size
      || batchRows.some(item => item.status !== "planned")
    ) {
      throw new Error("The batch calendar needs its planned Panchang slot for " + batchDate + ".");
    }
    const batchResult = dispatchWorkflow(BATCH_WORKFLOW, { date: batchDate });
    properties.setProperty(batchKey, batchResult);
    properties.setProperty("BATCH_TARGET_" + batchDate, String(Date.now()));
    properties.setProperty("LAST_BATCH_DISPATCH", today + " " + batchDate + " [" + batchResult + "]");
    Logger.log("Dispatched daily batch for " + batchDate + " (run " + batchResult + ")");
  } finally {
    lock.releaseLock();
  }
}

function checkAndRetryFailedVideos() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    throw new Error("Another publishing check is already running.");
  }

  try {
    const properties = PropertiesService.getScriptProperties();
    const allProperties = properties.getProperties();
    const batchTargets = Object.keys(allProperties)
      .filter(key => key.indexOf("BATCH_TARGET_") === 0)
      .map(key => key.slice("BATCH_TARGET_".length))
      .sort();
    const legacyTargets = Object.keys(allProperties)
      .filter(key => key.indexOf("LEGACY_TARGET_") === 0)
      .map(key => key.slice("LEGACY_TARGET_".length))
      .sort();
    if (!batchTargets.length && !legacyTargets.length) {
      Logger.log("No dispatched videos are awaiting verification.");
      return;
    }

    const batchRuns = listWorkflowRuns(BATCH_WORKFLOW);
    const legacyRuns = listWorkflowRuns(LEGACY_WORKFLOW);
    if (batchRuns.some(isRunActive) || legacyRuns.some(isRunActive)) {
      Logger.log("A publishing workflow is queued or running; postponing retries.");
      return;
    }
    if (batchTargets.length) {
      retryFailedBatchDates(batchTargets, batchRuns, properties);
    }
    if (legacyTargets.length) {
      retryFailedLegacyDates(legacyTargets, legacyRuns, properties);
    }
  } finally {
    lock.releaseLock();
  }
}

function retryFailedBatchDates(targetDates, runs, properties) {
  const now = new Date();
  const calendar = fetchJson(BATCH_CALENDAR_URL, "daily batch calendar");
  targetDates.forEach(batchDate => {
    if (hasActiveRunForDate(runs, batchDate)) {
      Logger.log("Batch " + batchDate + " is queued or in progress; not retrying yet.");
      return;
    }
    if (isInRetryCooldown(properties, "BATCH_RETRY_" + batchDate)) {
      Logger.log("Batch " + batchDate + " was dispatched recently; waiting for its run to appear.");
      return;
    }

    const rows = (calendar.videos || []).filter(row => (
      row.date === batchDate && ACTIVE_BATCH_SLOTS.has(Number(row.slot))
    ));
    if (!rows.length) {
      Logger.log("No batch rows found for " + batchDate + "; cannot verify this date.");
      return;
    }
    const retryable = rows.filter(row => {
      if (row.youtube_video_id) {
        return false;
      }
      if (!RETRYABLE_BATCH_STATUSES.has(row.status)) {
        return false;
      }
      const publishAt = new Date(
        row.date + "T" + row.publish_time_ist + ":00+05:30",
      );
      return publishAt.getTime() > now.getTime() + 15 * 60 * 1000;
    });
    const expired = rows.filter(row => (
      !row.youtube_video_id
      && ACTIVE_BATCH_SLOTS.has(Number(row.slot))
      && RETRYABLE_BATCH_STATUSES.has(row.status)
      && new Date(row.date + "T" + row.publish_time_ist + ":00+05:30").getTime()
        <= now.getTime() + 15 * 60 * 1000
    ));
    if (expired.length) {
      Logger.log(
        "Cannot schedule " + expired.length + " failed slot(s) for " + batchDate +
        ": their publish times are within 15 minutes or have passed.",
      );
    }
    if (!retryable.length) {
      const activeFailure = rows.some(row => (
        !row.youtube_video_id
        && ACTIVE_BATCH_SLOTS.has(Number(row.slot))
        && RETRYABLE_BATCH_STATUSES.has(row.status)
        && new Date(row.date + "T" + row.publish_time_ist + ":00+05:30").getTime()
          > now.getTime() + 15 * 60 * 1000
      ));
      if (!activeFailure) {
        properties.deleteProperty("BATCH_TARGET_" + batchDate);
      }
      Logger.log(
        activeFailure
          ? "Batch " + batchDate + " has no retryable slots at this check."
          : "Batch " + batchDate + " is complete or past its safe retry window.",
      );
      return;
    }

    const run = dispatchWorkflow(BATCH_WORKFLOW, {
      date: batchDate,
      retry_failed: true,
    });
    properties.setProperty("BATCH_RETRY_" + batchDate, String(Date.now()));
    Logger.log(
      "Retried " + retryable.length + " unsuccessful video(s) for " + batchDate +
      " only; slots " + retryable.map(row => row.slot).join(", ") +
      " (dispatch " + run + ").",
    );
  });
}

function retryFailedLegacyDates(targetDates, runs, properties) {
  const now = new Date();
  targetDates.forEach(publishDate => {
    const publishAt = new Date(publishDate + "T" + PUBLISH_TIME + ":00+05:30");
    if (publishAt.getTime() <= now.getTime() + 15 * 60 * 1000) {
      properties.deleteProperty("LEGACY_TARGET_" + publishDate);
      Logger.log("Festival video for " + publishDate + " is past its safe retry window.");
      return;
    }
    const matching = runs.filter(run => (
      workflowRunTitle(run).indexOf("Legacy video " + publishDate) !== -1
    ));
    if (!matching.length) {
      Logger.log("No GitHub Actions run found yet for festival video " + publishDate + ".");
      return;
    }
    const latest = matching[0];
    if (isRunActive(latest)) {
      Logger.log("Festival video " + publishDate + " is queued or in progress.");
      return;
    }
    if (latest.conclusion === "success") {
      properties.deleteProperty("LEGACY_TARGET_" + publishDate);
      Logger.log("Festival video " + publishDate + " succeeded in YouTube.");
      return;
    }
    if (!["failure", "timed_out", "cancelled"].includes(latest.conclusion)) {
      Logger.log(
        "Festival video " + publishDate + " ended as " + latest.conclusion +
        "; automatic retry was not started.",
      );
      return;
    }
    if (isInRetryCooldown(properties, "LEGACY_RETRY_" + publishDate)) {
      Logger.log("Festival video " + publishDate + " was retried recently; waiting for the result.");
      return;
    }

    rerunWorkflow(latest.id);
    properties.setProperty("LEGACY_RETRY_" + publishDate, String(Date.now()));
    Logger.log(
      "Re-ran failed festival video " + publishDate + " only (Actions run " +
      latest.id + ", attempt " + (Number(latest.run_attempt || 1) + 1) + ").",
    );
  });
}

function listWorkflowRuns(workflow) {
  const url = "https://api.github.com/repos/" + OWNER + "/" + REPO +
    "/actions/workflows/" + workflow + "/runs?branch=" + BRANCH + "&per_page=100";
  const response = githubApiRequest("get", url);
  if (response.getResponseCode() !== 200) {
    throw new Error(
      "Could not read " + workflow + " runs (HTTP " + response.getResponseCode() +
      "): " + response.getContentText().slice(0, 500),
    );
  }
  const payload = JSON.parse(response.getContentText());
  return (payload.workflow_runs || []).sort((left, right) => (
    new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
  ));
}

function hasActiveRunForDate(runs, calendarDate) {
  return runs.some(run => (
    workflowRunTitle(run).indexOf(calendarDate) !== -1 && isRunActive(run)
  ));
}

function workflowRunTitle(run) {
  return String(run.display_title || run.name || "");
}

function isRunActive(run) {
  return ["queued", "in_progress", "waiting", "requested", "pending"].includes(run.status);
}

function isInRetryCooldown(properties, key) {
  const lastDispatch = Number(properties.getProperty(key) || 0);
  return lastDispatch > 0 && Date.now() - lastDispatch < RETRY_COOLDOWN_MS;
}

function rerunWorkflow(runId) {
  const url = "https://api.github.com/repos/" + OWNER + "/" + REPO +
    "/actions/runs/" + encodeURIComponent(runId) + "/rerun";
  const response = githubApiRequest("post", url);
  if (response.getResponseCode() !== 201) {
    throw new Error(
      "Could not rerun Actions run " + runId + " (HTTP " +
      response.getResponseCode() + "): " + response.getContentText().slice(0, 500),
    );
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
  const url = "https://api.github.com/repos/" + OWNER + "/" + REPO +
    "/actions/workflows/" + workflow + "/dispatches";
  const response = githubApiRequest("post", url, { ref: BRANCH, inputs: inputs });
  if (response.getResponseCode() !== 204) {
    throw new Error(
      "GitHub workflow dispatch failed (HTTP " + response.getResponseCode() + "): " +
      response.getContentText().slice(0, 500)
    );
  }
  return Utilities.formatDate(new Date(), TIME_ZONE, "yyyyMMdd'T'HHmmss");
}

function githubApiRequest(method, url, payload) {
  const token = PropertiesService.getScriptProperties().getProperty("GITHUB_PAT");
  if (!token) {
    throw new Error("Set GITHUB_PAT in Apps Script project Script properties first.");
  }

  const options = {
    method: method,
    headers: {
      Authorization: "Bearer " + token,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"
    },
    contentType: "application/json",
    muteHttpExceptions: true
  };
  if (payload) {
    options.payload = JSON.stringify(payload);
  }
  return UrlFetchApp.fetch(url, options);
}
