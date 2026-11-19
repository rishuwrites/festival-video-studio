/**
 * Daily festival video scheduler.
 *
 * Setup:
 * 1. Copy this file into a Google Apps Script project.
 * 2. In Project Settings > Script properties, add GITHUB_PAT with a token
 *    allowed to dispatch workflows in rishuwrites/festival-video-studio.
 * 3. Run setupDailyTrigger() once and authorize the requested permissions.
 *
 * The daily trigger dispatches only the daily Panchang and festival videos
 * two days ahead. A separate two-hour trigger retries those active slots only.
 */

const OWNER = "rishuwrites";
const REPO = "festival-video-studio";
const BRANCH = "main";
const BATCH_WORKFLOW = "daily-batch.yml";
const TIME_ZONE = "Asia/Kolkata";
const PUBLISH_LEAD_DAYS = 2;
const BATCH_CALENDAR_URL =
  "https://raw.githubusercontent.com/rishuwrites/festival-video-studio/main/calendar/content_calendar.json";
const ACTIVE_BATCH_SLOTS = new Set([1, 2]);
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
      throw new Error("The batch calendar needs planned Panchang and festival slots for " + batchDate + ".");
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
    if (!batchTargets.length) {
      Logger.log("No dispatched videos are awaiting verification.");
      return;
    }

    const batchRuns = listWorkflowRuns(BATCH_WORKFLOW);
    if (batchRuns.some(isRunActive)) {
      Logger.log("A publishing workflow is queued or running; postponing retries.");
      return;
    }
    if (batchTargets.length) {
      retryFailedBatchDates(batchTargets, batchRuns, properties);
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
